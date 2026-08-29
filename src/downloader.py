"""
视频下载模块
四重策略自动降级: Playwright DOM → API解析 → 备用API
"""
import os
import re
import time
import random
import hashlib
import requests
from pathlib import Path
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import load_config
from logger import get_logger
from collector import VideoItem
from cache import get_cache

log = get_logger()

class VideoDownloader:
    """视频下载器"""
    def __init__(self):
        self.cfg = load_config()
        self.dl_cfg = self.cfg.get("downloader", {})
        self.output_dir = Path(self.dl_cfg.get("output_dir", "./videos/raw"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.concurrency = self.dl_cfg.get("concurrency", 3)
        self.timeout = self.dl_cfg.get("timeout", 60)
        self.rest_every = self.dl_cfg.get("rest_every", 20)
        self.rest_seconds = self.dl_cfg.get("rest_seconds", 15)
        self.strategies = self.dl_cfg.get("extract_strategies", ["playwright_dom", "api_bugpk"])
        self.api_endpoints = self.dl_cfg.get("api_endpoints", {})
        self.use_cache = self.dl_cfg.get("use_cache", True)
        self.cache = get_cache() if self.use_cache else None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self._empty_count = 0
        self._downloaded_count = 0
        self._cache_hit = 0
        self._cache_miss = 0

    def download_batch(self, items: list) -> list:
        """批量下载视频, 返回下载成功的本地文件路径列表"""
        if not items:
            log.info("没有需要下载的素材")
            return []

        log.info(f"开始批量下载: {len(items)} 条, 并发={self.concurrency}")
        results = []
        self._downloaded_count = 0

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = {executor.submit(self._download_single, item, idx): idx for idx, item in enumerate(items)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                        self._downloaded_count += 1
                    # 每N条休息
                    if self._downloaded_count > 0 and self._downloaded_count % self.rest_every == 0:
                        log.info(f"已下载 {self._downloaded_count} 条, 休息 {self.rest_seconds} 秒...")
                        time.sleep(self.rest_seconds)
                except Exception as e:
                    log.error(f"下载任务异常 [{idx}]: {e}")

        log.info(f"批量下载完成: 成功 {len(results)}/{len(items)}")
        return results

    def _download_single(self, item: VideoItem, idx: int) -> Optional[dict]:
        """下载单个视频, 尝试多种提取策略"""
        log.info(f"[{idx+1}] 处理: {item.title[:40]}...")

        # 1. 提取视频直链 (多策略降级)
        direct_url, meta = self._extract_direct_url(item)
        if not direct_url:
            log.warning(f"[{idx+1}] 无法提取视频直链: {item.url}")
            self._empty_count += 1
            if self._empty_count >= 10:
                pause = self.dl_cfg.get("empty_response_pause", 300)
                log.warning(f"连续空响应 {self._empty_count} 次, 暂停 {pause} 秒")
                time.sleep(pause)
                self._empty_count = 0
            return None

        self._empty_count = 0

        # 2. 生成文件名并下载
        filename = self._make_filename(item, idx)
        filepath = self.output_dir / filename

        try:
            success = self._download_file(direct_url, filepath)
            if success and filepath.exists() and filepath.stat().st_size > 1024:
                log.info(f"[{idx+1}] 下载成功: {filename} ({filepath.stat().st_size // 1024}KB)")
                return {
                    "filepath": str(filepath),
                    "title": item.title,
                    "source_url": item.url,
                    "duration": item.duration,
                    "category": item.category,
                    "meta": meta,
                }
            else:
                log.warning(f"[{idx+1}] 下载文件过小或失败")
                if filepath.exists():
                    filepath.unlink()
                return None
        except Exception as e:
            log.error(f"[{idx+1}] 下载异常: {e}")
            if filepath.exists():
                filepath.unlink()
            return None

    def _extract_direct_url(self, item: VideoItem) -> Tuple[Optional[str], dict]:
        """多策略提取视频直链, 自动降级, 带本地缓存(对应原项目远程缓存)"""
        meta = {}
        # 1. 先查本地缓存
        if self.cache:
            cached = self.cache.get_parse_cache(item.url)
            if cached and cached.get("direct_url"):
                self._cache_hit += 1
                log.debug(f"缓存命中: {item.url[:50]}")
                meta = {
                    "title": cached.get("title", ""),
                    "duration": cached.get("duration", 0),
                    "width": cached.get("width", 0),
                    "height": cached.get("height", 0),
                    "source": cached.get("source", ""),
                    "strategy": cached.get("strategy", "cache"),
                    "from_cache": True,
                }
                return cached["direct_url"], meta
            self._cache_miss += 1

        # 2. 缓存未命中, 多策略解析
        for strategy in self.strategies:
            try:
                log.debug(f"尝试策略: {strategy}")
                if strategy == "playwright_dom":
                    url, m = self._extract_by_playwright(item)
                elif strategy == "api_bugpk":
                    url, m = self._extract_by_api(item, "bugpk")
                elif strategy == "api_jumengfang":
                    url, m = self._extract_by_api(item, "jumengfang")
                elif strategy == "api_iiilab":
                    url, m = self._extract_by_api(item, "iiilab")
                else:
                    continue

                if url:
                    meta.update(m or {})
                    log.debug(f"策略 {strategy} 成功")
                    # 3. 保存到缓存
                    if self.cache:
                        self.cache.set_parse_cache(
                            item.url, url,
                            meta={"title": item.title, "duration": item.duration, **meta},
                            strategy=strategy
                        )
                    return url, meta
                else:
                    log.debug(f"策略 {strategy} 返回空, 降级")
            except Exception as e:
                log.debug(f"策略 {strategy} 异常: {e}, 降级")
                continue

        return None, meta

    def _extract_by_playwright(self, item: VideoItem) -> Tuple[Optional[str], dict]:
        """通过Playwright浏览器DOM解析提取视频直链 (元数据最完整)"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.debug("Playwright未安装, 跳过DOM策略")
            return None, {}

        meta = {}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()
                page.goto(item.url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)  # 等待视频加载

                # 尝试从video标签获取
                video_url = page.evaluate("""() => {
                    const v = document.querySelector('video');
                    if (v && v.src) return v.src;
                    const sources = document.querySelectorAll('video source');
                    for (const s of sources) { if (s.src) return s.src; }
                    return null;
                }""")

                # 尝试从页面JSON数据中提取
                if not video_url:
                    video_url = page.evaluate("""() => {
                        const scripts = document.querySelectorAll('script');
                        for (const s of scripts) {
                            const m = s.textContent.match(/["']?video(?:_url)?["']?\s*[:=]\s*["']([^"']+\.mp4[^"']*)/i);
                            if (m) return m[1];
                        }
                        return null;
                    }""")

                # 提取元数据
                duration = page.evaluate("() => { const v = document.querySelector('video'); return v ? v.duration : 0; }")
                if duration:
                    meta["duration"] = int(duration)

                browser.close()
                return video_url, meta
        except Exception as e:
            log.debug(f"Playwright解析失败: {e}")
            return None, {}

    def _extract_by_api(self, item: VideoItem, api_name: str) -> Tuple[Optional[str], dict]:
        """通过第三方解析API提取视频直链"""
        endpoint = self.api_endpoints.get(api_name, "")
        if not endpoint:
            return None, {}

        try:
            if api_name == "bugpk":
                url = f"{endpoint}{item.url}"
                resp = self.session.get(url, timeout=15)
                data = resp.json()
                video_url = data.get("data", {}).get("url") or data.get("url") or data.get("video_url")
            elif api_name == "jumengfang":
                resp = self.session.post(endpoint, json={"url": item.url}, timeout=15)
                data = resp.json()
                video_url = data.get("data", {}).get("video_url") or data.get("url")
            elif api_name == "iiilab":
                url = f"{endpoint}?url={item.url}"
                resp = self.session.get(url, timeout=15)
                data = resp.json()
                video_url = data.get("video_url") or data.get("url")
            else:
                video_url = None

            return video_url, {}
        except Exception as e:
            log.debug(f"API解析失败 [{api_name}]: {e}")
            return None, {}

    def _download_file(self, url: str, filepath: Path) -> bool:
        """下载文件到本地"""
        try:
            with self.session.get(url, stream=True, timeout=self.timeout) as resp:
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception as e:
            log.error(f"文件下载失败: {e}")
            return False

    def _make_filename(self, item: VideoItem, idx: int) -> str:
        """生成本地文件名"""
        # 标题清洗
        title = re.sub(r'[\\/:*?"<>|\s]+', '_', item.title)[:50]
        if not title:
            title = f"video_{idx}"
        # 用URL哈希避免重复
        url_hash = hashlib.md5(item.url.encode()).hexdigest()[:8]
        return f"{idx:04d}_{title}_{url_hash}.mp4"
