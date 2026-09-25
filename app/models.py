from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DownloadStatus(str, Enum):
    WAITING = "Đang chờ"
    PREPARING = "Đang chuẩn bị"
    DOWNLOADING = "Đang tải"
    MERGING = "Đang ghép"
    COMPLETED = "Hoàn thành"
    FAILED = "Lỗi"
    CANCELLED = "Đã hủy"
    SKIPPED = "Bỏ qua trùng"


@dataclass(slots=True)
class VideoInfo:
    url: str
    video_id: str
    title: str
    platform: str
    uploader: str = ""
    duration: int | None = None
    thumbnail: str = ""
    webpage_url: str = ""
    extractor: str = ""
    playlist_title: str = ""
    view_count: int | None = None
    upload_date: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def unique_key(self) -> str:
        source = (self.extractor or self.platform or "unknown").lower()
        if source.startswith("youtube"):
            source = "youtube"
        elif source.startswith("tiktok"):
            source = "tiktok"
        elif source.startswith("douyin"):
            source = "douyin"
        elif source.startswith("facebook"):
            source = "facebook"
        elif source.startswith("instagram"):
            source = "instagram"
        return f"{source}:{self.video_id}"


@dataclass(slots=True)
class DownloadOptions:
    output_dir: Path
    quality: str = "1080p"
    media_format: str = "MP4"
    playlist: bool = False
    subtitles: bool = False
    thumbnail: bool = False
    metadata: bool = False
    cookies_file: Path | None = None
    overwrite_existing: bool = False


@dataclass(slots=True)
class PreviewOptions:
    playlist: bool = False
    channel: bool = False
    keyword_search: bool = False
    search_platform: str = "YouTube"
    search_language: str = "original"
    channel_limit: int = 100
    channel_scan_limit: int = 500
    search_limit: int = 50
    search_scan_limit: int = 250
    sort_by: str = "views"
    since_days: int = 365
    skip_duplicates: bool = True


@dataclass(slots=True)
class DownloadJob:
    job_id: str
    video: VideoInfo
    options: DownloadOptions
    status: DownloadStatus = DownloadStatus.WAITING
    progress: float = 0.0
    speed: str = "—"
    eta: str = "—"
    output_path: str = ""
    error: str = ""
