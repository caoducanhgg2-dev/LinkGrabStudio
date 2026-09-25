from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "LinkGrab Studio"
APP_VERSION = "1.5.2"
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
    youtube_cookies_file: str = ""
    tiktok_cookies_file: str = ""
    douyin_cookies_file: str = ""
    facebook_cookies_file: str = ""
    instagram_cookies_file: str = ""
    login_browser: str = "firefox"
    douyin_browser: str = "firefox"
    auto_clipboard: bool = True
    skip_duplicates: bool = True

    @classmethod
    def load(cls) -> "AppSettings":
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls(output_dir=str(default_download_dir()))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "login_browser" not in data and "douyin_browser" in data:
                data["login_browser"] = data["douyin_browser"]
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

    def cookies_for_platform(self, platform: str) -> Path | None:
        specific = {
            "youtube": self.youtube_cookies_file,
            "tiktok": self.tiktok_cookies_file,
            "douyin": self.douyin_cookies_file,
            "facebook": self.facebook_cookies_file,
            "instagram": self.instagram_cookies_file,
        }.get(platform.strip().lower(), "")
        selected = specific or self.cookies_file
        return Path(selected) if selected else None

    def use_browser_login(self, cookie_file: Path, browser: str) -> None:
        """Route every platform through the managed browser-login session."""
        value = str(cookie_file)
        self.cookies_file = value
        self.youtube_cookies_file = value
        self.tiktok_cookies_file = value
        self.douyin_cookies_file = value
        self.facebook_cookies_file = value
        self.instagram_cookies_file = value
        self.login_browser = browser
        self.douyin_browser = browser
