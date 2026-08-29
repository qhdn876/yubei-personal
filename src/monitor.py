"""
目录监控模块 - 对应原项目的目录监控+闲置自动触发
功能:
  1. 监控视频目录数量
  2. 低于阈值时自动触发采集下载流程
  3. 下载完成后自动触发发布
"""
import os
import time
import threading
from pathlib import Path
from config import load_config
from logger import get_logger

log = get_logger()

class DirectoryMonitor:
    """目录监控器"""
    def __init__(self, on_threshold_triggered=None):
        self.cfg = load_config()
        monitor_cfg = self.cfg.get("monitor", {})
        self.enabled = monitor_cfg.get("enabled", True)
        self.watch_dir = Path(monitor_cfg.get("watch_dir", "./videos/processed"))
        self.min_threshold = monitor_cfg.get("min_video_threshold", 20)
        self.check_interval = monitor_cfg.get("check_interval", 300)
        self.publish_delay = monitor_cfg.get("publish_delay", 60)
        self._running = False
        self._thread = None
        self._last_trigger_time = 0
        self._min_trigger_interval = 1800  # 两次触发最小间隔30分钟
        self._on_triggered = on_threshold_triggered
        self.watch_dir.mkdir(parents=True, exist_ok=True)

    def count_videos(self) -> int:
        """统计目录中的视频数量"""
        if not self.watch_dir.exists():
            return 0
        exts = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}
        count = 0
        for f in self.watch_dir.iterdir():
            if f.is_file() and f.suffix.lower() in exts:
                count += 1
        return count

    def check_and_trigger(self) -> bool:
        """检查目录数量, 低于阈值则触发"""
        if not self.enabled:
            return False
        count = self.count_videos()
        log.info(f"[目录监控] 当前视频数: {count}, 阈值: {self.min_threshold}")

        if count < self.min_threshold:
            now = time.time()
            if now - self._last_trigger_time < self._min_trigger_interval:
                log.info(f"[目录监控] 距上次触发不足{self._min_trigger_interval//60}分钟, 跳过")
                return False
            log.info(f"[目录监控] 视频数低于阈值, 触发采集下载流程!")
            self._last_trigger_time = now
            if self._on_triggered:
                try:
                    self._on_triggered()
                except Exception as e:
                    log.error(f"[目录监控] 触发回调异常: {e}")
            return True
        return False

    def start(self):
        """启动后台监控线程"""
        if not self.enabled:
            log.info("目录监控已禁用")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log.info(f"[目录监控] 已启动, 监控目录: {self.watch_dir}, 阈值: {self.min_threshold}, 间隔: {self.check_interval}秒")

    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        log.info("[目录监控] 已停止")

    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                self.check_and_trigger()
            except Exception as e:
                log.error(f"[目录监控] 检查异常: {e}")
            # 分段sleep, 便于快速停止
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

def get_monitor(on_triggered=None):
    return DirectoryMonitor(on_triggered)
