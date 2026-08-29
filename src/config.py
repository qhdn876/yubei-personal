"""
配置加载模块
"""
import os
import yaml
from pathlib import Path

class Config:
    _instance = None
    _data = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._data is None:
            self._load()

    def _load(self):
        """加载配置文件"""
        config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)
        # 转换相对路径为绝对路径
        self._resolve_paths()

    def _resolve_paths(self):
        """将配置中的相对路径转为绝对路径(基于项目根目录)"""
        base = Path(__file__).parent.parent
        path_keys = [
            ("downloader", "output_dir"),
            ("dedup", "output_dir"),
            ("publisher", "user_data_dir"),
            ("logging", "file"),
        ]
        for section, key in path_keys:
            if section in self._data and key in self._data[section]:
                p = self._data[section][key]
                if p and not os.path.isabs(p):
                    self._data[section][key] = str(base / p)

    def get(self, section, key=None, default=None):
        """获取配置项
        兼容: cfg.get("section") / cfg.get("section","key") / cfg.get("section","key",default) / cfg.get("section",{})
        """
        if key is not None and not isinstance(key, str):
            default = key
            key = None
        if section not in self._data:
            return default
        if key is None:
            return self._data[section]
        return self._data[section].get(key, default)

    @property
    def data(self):
        return self._data

def load_config():
    return Config()
