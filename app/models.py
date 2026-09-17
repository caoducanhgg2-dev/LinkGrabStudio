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
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def unique_key(self) -> str:
        source = (self.extractor or self.platform or "unknown").lower()
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

