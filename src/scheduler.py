"""
定时调度模块 - APScheduler
每天固定时间自动执行流水线
"""
import time
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from config import load_config
from logger import get_logger
from pipeline import Pipeline

log = get_logger()

class TaskScheduler:
    """定时任务调度器"""
    def __init__(self):
        self.cfg = load_config()
        self.sched_cfg = self.cfg.get("scheduler", {})
        self.daily_times = self.sched_cfg.get("daily_times", ["08:00", "14:00", "20:00"])
        self.min_interval = self.sched_cfg.get("min_interval_minutes", 30)
        self.scheduler = BlockingScheduler(timezone="Asia/Shanghai")
        self._last_run = 0
        self._pipeline = Pipeline()

    def _run_task(self):
        """执行任务 (带最小间隔保护)"""
        now = time.time()
        if now - self._last_run < self.min_interval * 60:
            log.info(f"距上次执行不足 {self.min_interval} 分钟, 跳过")
            return
        self._last_run = now
        task_name = f"定时任务_{datetime.now().strftime('%Y%m%d_%H%M')}"
        try:
            self._pipeline.run(task_name)
        except Exception as e:
            log.exception(f"定时任务异常: {e}")

    def start(self):
        """启动定时调度"""
        if not self.sched_cfg.get("enabled", True):
            log.info("定时调度已禁用, 仅执行一次")
            self._run_task()
            return

        log.info(f"定时调度启动, 每天执行时间: {self.daily_times}")
        for t in self.daily_times:
            hour, minute = map(int, t.split(":"))
            trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai")
            self.scheduler.add_job(
                self._run_task,
                trigger=trigger,
                id=f"daily_{hour}_{minute}",
                name=f"每日{t}任务",
                misfire_grace_time=300,
            )
            log.info(f"  已注册: 每天 {t}")

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("定时调度已停止")

    def run_once(self):
        """立即执行一次"""
        log.info("手动触发一次任务")
        self._run_task()
