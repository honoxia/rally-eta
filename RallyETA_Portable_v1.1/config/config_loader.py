"""Configuration loader"""
import yaml
from pathlib import Path
from typing import Any


class Config:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self._config = self._load_config()

    def _load_config(self):
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def get(self, key_path: str, default: Any = None):
        """Get config value using dot notation"""
        keys = key_path.split('.')
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value


config = Config()
