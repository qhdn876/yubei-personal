"""
核心流程编排 - 采集 → 下载 → 去重 → 发布
"""
import time
from datetime import datetime
from config import load_config
from logger import get_logger
from collector import get_collector
from downloader import VideoDownloader
from dedup import VideoDeduplicator
from publisher import ToutiaoPublisher
from notifier import get_notifier

log = get_logger()

class Pipeline:
    """完整处理流水线"""
    def __init__(self):
        self.cfg = load_config()
        self.collector = get_collector()
        self.downloader = VideoDownloader()
        self.dedup = VideoDeduplicator()
        self.publisher = ToutiaoPublisher()
        self.notifier = get_notifier()

    def run(self, task_name: str = "定时任务") -> dict:
        """执行完整流水线"""
        start_time = time.time()
        log.info(f"{'='*60}")
        log.info(f"流水线启动: {task_name}")
        log.info(f"{'='*60}")
        self.notifier.task_start(task_name)

        stats = {
            "task_name": task_name,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "collected": 0,
            "downloaded": 0,
            "deduped": 0,
            "published": 0,
            "publish_failed": 0,
            "duration_seconds": 0,
            "status": "running",
        }

        try:
            # 阶段1: 采集素材
            log.info(f"\n{'─'*40}")
            log.info("阶段 1/4: 素材采集")
            log.info(f"{'─'*40}")
            items = self.collector.collect()
            stats["collected"] = len(items)
            if not items:
                log.warning("未采集到素材, 流水线结束")
                stats["status"] = "no_data"
                self._finish(stats, start_time)
                return stats

            # 阶段2: 下载视频
            log.info(f"\n{'─'*40}")
            log.info("阶段 2/4: 视频下载")
            log.info(f"{'─'*40}")
            downloaded = self.downloader.download_batch(items)
            stats["downloaded"] = len(downloaded)
            if not downloaded:
                log.warning("没有视频下载成功, 流水线结束")
                stats["status"] = "download_failed"
                self._finish(stats, start_time)
                return stats

            # 阶段3: FFmpeg去重
            log.info(f"\n{'─'*40}")
            log.info("阶段 3/4: 视频去重")
            log.info(f"{'─'*40}")
            processed = self.dedup.process_batch(downloaded)
            stats["deduped"] = len(processed)

            # 阶段4: 自动发布
            log.info(f"\n{'─'*40}")
            log.info("阶段 4/4: 头条发布")
            log.info(f"{'─'*40}")
            publish_results = self.publisher.publish_batch(processed)
            stats["published"] = sum(1 for r in publish_results if r.get("success"))
            stats["publish_failed"] = sum(1 for r in publish_results if not r.get("success"))
            stats["status"] = "completed"

        except Exception as e:
            log.exception(f"流水线异常: {e}")
            stats["status"] = "error"
            stats["error"] = str(e)
            self.notifier.task_error(task_name, str(e))

        self._finish(stats, start_time)
        return stats

    def _finish(self, stats: dict, start_time: float):
        """完成统计"""
        stats["duration_seconds"] = round(time.time() - start_time, 1)
        stats["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n{'='*60}")
        log.info(f"流水线结束: {stats['status']}")
        log.info(f"  采集: {stats['collected']} | 下载: {stats['downloaded']} | "
                 f"去重: {stats['deduped']} | 发布: {stats['published']}/{stats.get('publish_failed', 0)+stats['published']}")
        log.info(f"  耗时: {stats['duration_seconds']}秒")
        log.info(f"{'='*60}\n")
        self.notifier.task_complete(stats["task_name"], {
            "状态": stats["status"],
            "采集": stats["collected"],
            "下载": stats["downloaded"],
            "去重": stats["deduped"],
            "发布成功": stats["published"],
            "发布失败": stats.get("publish_failed", 0),
            "耗时": f"{stats['duration_seconds']}秒",
        })
