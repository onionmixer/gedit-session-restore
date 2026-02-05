import os
import json


class Settings:
    """플러그인 설정 로드/저장. JSON 파일 기반."""

    BASE_DIR = os.path.expanduser("~/.config/gedit/tmp")
    SETTINGS_FILE = os.path.join(BASE_DIR, "sessionrestore_settings.json")

    DEFAULTS = {
        "preserve_modifications": False,
        "auto_snapshot_enabled": False,
        "auto_snapshot_idle_seconds": 2.0,
    }

    def __init__(self):
        self._data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        """설정 파일을 읽어 _data에 반영한다. 파일이 없거나 손상되면 기본값 유지."""
        if not os.path.isfile(self.SETTINGS_FILE):
            return
        try:
            with open(self.SETTINGS_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            for key in self.DEFAULTS:
                if key in stored:
                    self._data[key] = stored[key]
        except (json.JSONDecodeError, OSError):
            pass

    def save(self):
        """현재 설정을 파일에 기록한다."""
        os.makedirs(self.BASE_DIR, exist_ok=True)
        tmp_path = self.SETTINGS_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.SETTINGS_FILE)

    def get(self, key):
        return self._data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self._data[key] = value
        self.save()
