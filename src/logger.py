"""
日志模块
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

class Logger:
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
        self._setup()

    def _setup(self):
        from config import load_config
        cfg = load_config()
        log_cfg = cfg.get("logging", {})

        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
        log_file = log_cfg.get("file", "./logs/yubei.log")
        max_size = log_cfg.get("max_size_mb", 50) * 1024 * 1024
        backup_count = log_cfg.get("backup_count", 5)

        # 确保日志目录存在
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("yubei")
        self.logger.setLevel(level)
        self.logger.handlers.clear()

        # 控制台输出
        console = logging.StreamHandler()
        console.setLevel(level)
        console_fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )
        console.setFormatter(console_fmt)
        self.logger.addHandler(console)

        # 文件输出
        if log_file:
            file_handler = RotatingFileHandler(
                log_file, maxBytes=max_size, backupCount=backup_count, encoding="utf-8"
            )
            file_handler.setLevel(level)
            file_fmt = logging.Formatter(
                "[%(asctime)s] %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_fmt)
            self.logger.addHandler(file_handler)

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self.logger.exception(msg, *args, **kwargs)

def get_logger():
    return Logger()
