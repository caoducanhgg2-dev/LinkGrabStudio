from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "LinkGrab Studio"
APP_VERSION = "1.3.5"
APP_DIR_NAME = "LinkGrabStudio"


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_download_dir() -> Path:
    candidate = Path.home() / "Downloads" / APP_DIR_NAME
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


@dataclass(slots=True)
class AppSettings:
    output_dir: str = ""
    concurrency: int = 2
    quality: str = "1080p"
    media_format: str = "MP4"
    cookies_file: str = ""
    douyin_browser: str = "chrome"
    auto_clipboard: bool = True
    skip_duplicates: bool = True

    @classmethod
    def load(cls) -> "AppSettings":
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls(output_dir=str(default_download_dir()))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            settings = cls(**{k: data[k] for k in allowed if k in data})
            if not settings.output_dir:
                settings.output_dir = str(default_download_dir())
            settings.concurrency = min(4, max(1, int(settings.concurrency)))
            return settings
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls(output_dir=str(default_download_dir()))

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
