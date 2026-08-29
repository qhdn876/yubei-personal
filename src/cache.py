"""
本地缓存模块 - SQLite
对应原项目的远程缓存(47.108.138.185:5001), 本地化实现
功能:
  1. 视频解析结果缓存(避免重复解析)
  2. 已发布视频记录(避免重复发布)
  3. 采集历史记录
"""
import sqlite3
import hashlib
import time
from pathlib import Path
from config import load_config
from logger import get_logger

log = get_logger()

class CacheManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.cfg = load_config()
        cache_cfg = self.cfg.get("cache", {})
        self.enabled = cache_cfg.get("enabled", True)
        if not self.enabled:
            log.info("缓存功能已禁用")
            return
        db_path = cache_cfg.get("db_path", "./data/cache.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()
        log.info(f"缓存模块已初始化: {db_path}")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        c = conn.cursor()
        # 视频解析缓存表
        c.execute("""
            CREATE TABLE IF NOT EXISTS video_parse_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT UNIQUE NOT NULL,
                url_hash TEXT NOT NULL,
                direct_url TEXT NOT NULL,
                title TEXT,
                duration INTEGER DEFAULT 0,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                source TEXT,
                strategy TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_parse_hash ON video_parse_cache(url_hash)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_parse_created ON video_parse_cache(created_at)")

        # 已发布视频记录表
        c.execute("""
            CREATE TABLE IF NOT EXISTS published_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                title TEXT,
                source_url TEXT,
                platform TEXT DEFAULT 'toutiao',
                published_at REAL NOT NULL,
                status TEXT DEFAULT 'success'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_published_hash ON published_history(file_hash)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_published_at ON published_history(published_at)")

        # 采集历史记录表
        c.execute("""
            CREATE TABLE IF NOT EXISTS collection_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT UNIQUE NOT NULL,
                title TEXT,
                source TEXT,
                collected_at REAL NOT NULL,
                downloaded INTEGER DEFAULT 0,
                published INTEGER DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_collection_url ON collection_history(source_url)")

        conn.commit()
        conn.close()

    # ==================== 视频解析缓存 ====================

    def get_parse_cache(self, source_url: str) -> dict:
        """获取视频解析缓存, 过期返回None"""
        if not self.enabled:
            return None
        url_hash = hashlib.md5(source_url.encode()).hexdigest()
        ttl_hours = self.cfg.get("cache", {}).get("video_parse_cache", {}).get("ttl_hours", 168)
        expire_time = time.time() - ttl_hours * 3600

        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM video_parse_cache WHERE url_hash = ? AND created_at > ?",
            (url_hash, expire_time)
        )
        row = c.fetchone()
        conn.close()

        if row:
            log.debug(f"解析缓存命中: {source_url[:50]}")
            return dict(row)
        return None

    def set_parse_cache(self, source_url: str, direct_url: str, meta: dict = None, strategy: str = ""):
        """保存视频解析缓存"""
        if not self.enabled:
            return
        meta = meta or {}
        url_hash = hashlib.md5(source_url.encode()).hexdigest()
        now = time.time()

        conn = self._get_conn()
        c = conn.cursor()
        try:
            c.execute("""
                INSERT OR REPLACE INTO video_parse_cache
                (source_url, url_hash, direct_url, title, duration, width, height, source, strategy, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_url, url_hash, direct_url,
                meta.get("title", ""), meta.get("duration", 0),
                meta.get("width", 0), meta.get("height", 0),
                meta.get("source", ""), strategy, now, now
            ))
            conn.commit()
            log.debug(f"解析缓存已保存: {source_url[:50]}")
        except Exception as e:
            log.error(f"保存解析缓存失败: {e}")
        finally:
            conn.close()

    def cleanup_expired_cache(self):
        """清理过期缓存"""
        if not self.enabled:
            return
        ttl_hours = self.cfg.get("cache", {}).get("video_parse_cache", {}).get("ttl_hours", 168)
        expire_time = time.time() - ttl_hours * 3600
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM video_parse_cache WHERE created_at < ?", (expire_time,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            log.info(f"清理过期解析缓存: {deleted} 条")

    # ==================== 已发布视频记录 ====================

    def is_published(self, filepath: str) -> bool:
        """检查视频是否已发布(基于文件内容哈希)"""
        if not self.enabled:
            return False
        file_hash = self._file_hash(filepath)
        if not file_hash:
            return False
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM published_history WHERE file_hash = ?", (file_hash,))
        row = c.fetchone()
        conn.close()
        return row is not None

    def record_published(self, filepath: str, title: str = "", source_url: str = "", platform: str = "toutiao"):
        """记录已发布视频"""
        if not self.enabled:
            return
        file_hash = self._file_hash(filepath)
        if not file_hash:
            return
        filename = Path(filepath).name
        now = time.time()
        conn = self._get_conn()
        c = conn.cursor()
        try:
            c.execute("""
                INSERT OR IGNORE INTO published_history
                (file_hash, filename, title, source_url, platform, published_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'success')
            """, (file_hash, filename, title, source_url, platform, now))
            conn.commit()
            log.debug(f"发布记录已保存: {filename}")
        except Exception as e:
            log.error(f"保存发布记录失败: {e}")
        finally:
            conn.close()

    def cleanup_old_published(self):
        """清理过期发布记录"""
        if not self.enabled:
            return
        retain_days = self.cfg.get("cache", {}).get("published_history", {}).get("retain_days", 90)
        expire_time = time.time() - retain_days * 86400
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM published_history WHERE published_at < ?", (expire_time,))
        conn.commit()
        conn.close()

    # ==================== 采集历史记录 ====================

    def is_collected(self, source_url: str) -> bool:
        """检查素材是否已采集过"""
        if not self.enabled:
            return False
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM collection_history WHERE source_url = ?", (source_url,))
        row = c.fetchone()
        conn.close()
        return row is not None

    def record_collected(self, source_url: str, title: str = "", source: str = ""):
        """记录采集的素材"""
        if not self.enabled:
            return
        now = time.time()
        conn = self._get_conn()
        c = conn.cursor()
        try:
            c.execute("""
                INSERT OR IGNORE INTO collection_history
                (source_url, title, source, collected_at, downloaded, published)
                VALUES (?, ?, ?, ?, 0, 0)
            """, (source_url, title, source, now))
            conn.commit()
        except Exception as e:
            log.debug(f"保存采集记录失败: {e}")
        finally:
            conn.close()

    def mark_downloaded(self, source_url: str):
        """标记为已下载"""
        if not self.enabled:
            return
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("UPDATE collection_history SET downloaded = 1 WHERE source_url = ?", (source_url,))
        conn.commit()
        conn.close()

    # ==================== 工具方法 ====================

    def _file_hash(self, filepath: str) -> str:
        """计算文件内容哈希(前1MB+文件大小, 快速哈希)"""
        try:
            path = Path(filepath)
            if not path.exists():
                return ""
            size = path.stat().st_size
            with open(filepath, 'rb') as f:
                # 读取前1MB和后1MB做哈希, 大文件也快
                head = f.read(1024 * 1024)
                if size > 2 * 1024 * 1024:
                    f.seek(-1024 * 1024, 2)
                    tail = f.read(1024 * 1024)
                else:
                    tail = b''
            return hashlib.md5(head + tail + str(size).encode()).hexdigest()
        except Exception as e:
            log.debug(f"计算文件哈希失败: {e}")
            return ""

    def get_stats(self) -> dict:
        """获取缓存统计"""
        if not self.enabled:
            return {"enabled": False}
        conn = self._get_conn()
        c = conn.cursor()
        stats = {}
        for table in ["video_parse_cache", "published_history", "collection_history"]:
            c.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = c.fetchone()[0]
        conn.close()
        return stats

def get_cache():
    return CacheManager()
