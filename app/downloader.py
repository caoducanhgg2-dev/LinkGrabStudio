from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from .models import DownloadJob, DownloadOptions, DownloadStatus, PreviewOptions, VideoInfo
from .utils import detect_platform


class DownloaderError(RuntimeError):
    pass


def runtime_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def find_binary(name: str) -> Path | str:
    suffix = ".exe" if os.name == "nt" and not name.endswith(".exe") else ""
    filename = f"{name}{suffix}"
    candidates = [
        runtime_root() / "tools" / filename,
        Path(sys.executable).resolve().parent / "tools" / filename,
        Path.cwd() / "tools" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return filename


class DownloaderEngine:
    PROGRESS_PREFIX = "__LINKGRAB_PROGRESS__"

    def __init__(self) -> None:
        self.ytdlp = find_binary("yt-dlp")
        self.ffmpeg = find_binary("ffmpeg")
        self.deno = find_binary("deno")
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    @property
    def is_ready(self) -> bool:
        try:
            result = self._run_capture([str(self.ytdlp), "--version"], timeout=15)
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def version(self) -> str:
        try:
            result = self._run_capture([str(self.ytdlp), "--version"], timeout=15)
            return result.stdout.strip() if result.returncode == 0 else "Không khả dụng"
        except (OSError, subprocess.SubprocessError):
            return "Không khả dụng"

    def preview(
        self,
        urls: Iterable[str],
        *,
        playlist: bool = False,
        cookies_file: Path | None = None,
    ) -> list[VideoInfo]:
        videos: list[VideoInfo] = []
        for url in urls:
            command = [
                str(self.ytdlp),
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                "--ignore-config",
                "--yes-playlist" if playlist else "--no-playlist",
            ]
            command += self._javascript_options()
            if cookies_file and cookies_file.is_file():
                command += ["--cookies", str(cookies_file)]
            command.append(url)
            try:
                result = self._run_capture(command, timeout=120)
            except FileNotFoundError as exc:
                raise DownloaderError(
                    "Không tìm thấy yt-dlp. Hãy dùng bản Setup hoặc chạy build/bootstrap_tools.ps1."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise DownloaderError("Quá thời gian lấy thông tin video.") from exc
            if result.returncode != 0:
                raise DownloaderError(self._friendly_error(result.stderr or result.stdout))
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise DownloaderError("Nền tảng trả về dữ liệu không hợp lệ.") from exc
            entries = payload.get("entries") if playlist else None
            if entries:
                for entry in entries:
                    if entry:
                        videos.append(self._video_from_json(entry, fallback_url=url, playlist=payload))
            else:
                videos.append(self._video_from_json(payload, fallback_url=url))
        return videos

    def preview_channel(
        self,
        urls: Iterable[str],
        options: PreviewOptions,
        *,
        cookies_file: Path | None = None,
    ) -> list[VideoInfo]:
        """Read a channel/profile, then filter and rank its recent videos."""
        candidates: list[VideoInfo] = []
        for url in urls:
            url = self._normalize_channel_url(url)
            command = [
                str(self.ytdlp),
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                "--ignore-config",
                "--yes-playlist",
                "--extract-flat",
                "--playlist-end",
                str(max(options.channel_limit, options.channel_scan_limit)),
            ]
            command += self._javascript_options()
            if cookies_file and cookies_file.is_file():
                command += ["--cookies", str(cookies_file)]
            command.append(url)
            try:
                result = self._run_capture(command, timeout=300)
            except FileNotFoundError as exc:
                raise DownloaderError("Không tìm thấy yt-dlp trong gói ứng dụng.") from exc
            except subprocess.TimeoutExpired as exc:
                raise DownloaderError("Quá thời gian đọc danh sách video của kênh.") from exc
            if result.returncode != 0:
                raise DownloaderError(self._friendly_error(result.stderr or result.stdout))
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise DownloaderError("Kênh trả về dữ liệu không hợp lệ.") from exc
            entries = payload.get("entries") or []
            for entry in entries:
                if entry:
                    candidates.append(self._video_from_json(entry, fallback_url=url, playlist=payload))

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, options.since_days))
        filtered = [video for video in candidates if self._is_recent(video, cutoff)]
        unique: dict[str, VideoInfo] = {}
        for video in filtered:
            unique.setdefault(video.unique_key, video)
        filtered = list(unique.values())
        if options.sort_by == "newest":
            filtered.sort(key=self._video_timestamp, reverse=True)
        else:
            filtered.sort(key=lambda video: (video.view_count or 0, self._video_timestamp(video)), reverse=True)
        return filtered[: max(1, options.channel_limit)]

    def download(
        self,
        job: DownloadJob,
        *,
        on_progress: Callable[[float, str, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> DownloadJob:
        options = job.options
        options.output_dir.mkdir(parents=True, exist_ok=True)
        command = self.build_download_command(job.video.webpage_url or job.video.url, options)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except FileNotFoundError as exc:
            job.status = DownloadStatus.FAILED
            job.error = "Không tìm thấy yt-dlp trong gói ứng dụng."
            raise DownloaderError(job.error) from exc
        with self._lock:
            self._processes[job.job_id] = process

        final_path = ""
        last_line = ""
        try:
            job.status = DownloadStatus.DOWNLOADING
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                last_line = line
                if line.startswith(self.PROGRESS_PREFIX):
                    percent, speed, eta = self._parse_progress(line)
                    job.progress, job.speed, job.eta = percent, speed, eta
                    if on_progress:
                        on_progress(percent, speed, eta)
                    continue
                if line.startswith("__LINKGRAB_FILE__"):
                    final_path = line.removeprefix("__LINKGRAB_FILE__").strip()
                    continue
                if "Merging formats" in line or "Merger" in line or "Post-process" in line:
                    job.status = DownloadStatus.MERGING
                if on_log:
                    on_log(self._clean_log_line(line))
            return_code = process.wait()
            if return_code == 0:
                job.progress = 100.0
                job.status = DownloadStatus.COMPLETED
                job.output_path = final_path
                return job
            if job.status == DownloadStatus.CANCELLED:
                return job
            job.status = DownloadStatus.FAILED
            job.error = self._friendly_error(last_line)
            return job
        finally:
            with self._lock:
                self._processes.pop(job.job_id, None)

    def build_download_command(self, url: str, options: DownloadOptions) -> list[str]:
        command = [
            str(self.ytdlp),
            "--ignore-config",
            "--newline",
            "--windows-filenames",
            "--trim-filenames",
            "180",
            "--continue",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--concurrent-fragments",
            "4",
            "--progress-template",
            f"download:{self.PROGRESS_PREFIX}%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "--print",
            "after_move:__LINKGRAB_FILE__%(filepath)s",
            "--output",
            str(options.output_dir / "%(title).180B [%(id)s].%(ext)s"),
            "--yes-playlist" if options.playlist else "--no-playlist",
        ]
        command += self._javascript_options()
        ffmpeg_path = Path(str(self.ffmpeg))
        if ffmpeg_path.is_file():
            command += ["--ffmpeg-location", str(ffmpeg_path.parent)]

        media_format = options.media_format.upper()
        if media_format in {"MP3", "M4A"}:
            command += ["--extract-audio", "--audio-format", media_format.lower(), "--audio-quality", "0"]
        else:
            height = self._quality_height(options.quality)
            selector = "bestvideo+bestaudio/best"
            if height:
                selector = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            command += ["--format", selector]
            if media_format == "MKV":
                command += ["--merge-output-format", "mkv"]
            else:
                command += ["--merge-output-format", "mp4", "--remux-video", "mp4"]

        if options.subtitles:
            command += ["--write-subs", "--write-auto-subs", "--sub-langs", "all,-live_chat"]
        if options.thumbnail:
            command += ["--write-thumbnail"]
        if options.metadata:
            command += ["--write-info-json", "--write-description"]
        if options.cookies_file and options.cookies_file.is_file():
            command += ["--cookies", str(options.cookies_file)]
        command.append(url)
        return command

    def _javascript_options(self) -> list[str]:
        deno_path = Path(str(self.deno))
        if deno_path.is_file():
            return ["--js-runtimes", f"deno:{deno_path}", "--remote-components", "ejs:github"]
        return []

    def cancel(self, job_id: str) -> None:
        with self._lock:
            process = self._processes.get(job_id)
        if process and process.poll() is None:
            process.terminate()

    def cancel_all(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            if process.poll() is None:
                process.terminate()

    @staticmethod
    def _quality_height(quality: str) -> int | None:
        match = re.search(r"(\d{3,4})", quality)
        return int(match.group(1)) if match else None

    @staticmethod
    def _video_from_json(data: dict, fallback_url: str, playlist: dict | None = None) -> VideoInfo:
        video_id = str(data.get("id") or data.get("display_id") or "unknown")
        webpage_url = str(data.get("webpage_url") or data.get("url") or fallback_url)
        extractor = str(data.get("extractor_key") or data.get("extractor") or "")
        return VideoInfo(
            url=fallback_url,
            video_id=video_id,
            title=str(data.get("title") or f"Video {video_id}"),
            platform=detect_platform(webpage_url),
            uploader=str(data.get("uploader") or data.get("channel") or ""),
            duration=int(data["duration"]) if data.get("duration") is not None else None,
            thumbnail=str(data.get("thumbnail") or ""),
            webpage_url=webpage_url,
            extractor=extractor,
            playlist_title=str((playlist or {}).get("title") or ""),
            view_count=DownloaderEngine._optional_int(data.get("view_count")),
            upload_date=str(data.get("upload_date") or data.get("release_date") or ""),
            raw=data,
        )

    @staticmethod
    def _optional_int(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _video_timestamp(video: VideoInfo) -> int:
        for key in ("timestamp", "release_timestamp"):
            value = video.raw.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                pass
        date_text = video.upload_date
        try:
            return int(datetime.strptime(date_text, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp())
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _is_recent(cls, video: VideoInfo, cutoff: datetime) -> bool:
        timestamp = cls._video_timestamp(video)
        if timestamp <= 0:
            # Some flat channel extractors do not expose dates. Keep the item so
            # a supported channel never becomes an empty list only due to sparse metadata.
            return True
        return datetime.fromtimestamp(timestamp, tz=timezone.utc) >= cutoff

    @staticmethod
    def _normalize_channel_url(url: str) -> str:
        clean = url.rstrip("/")
        lowered = clean.lower()
        if ("youtube.com/@" in lowered or "/channel/" in lowered or "/c/" in lowered) and not any(
            lowered.endswith(suffix) for suffix in ("/videos", "/shorts", "/streams")
        ):
            return f"{clean}/videos"
        return url

    @classmethod
    def _parse_progress(cls, line: str) -> tuple[float, str, str]:
        payload = line.removeprefix(cls.PROGRESS_PREFIX)
        parts = [part.strip() for part in payload.split("|", 2)]
        while len(parts) < 3:
            parts.append("—")
        match = re.search(r"([\d.]+)", parts[0])
        percent = float(match.group(1)) if match else 0.0
        return min(100.0, max(0.0, percent)), parts[1] or "—", parts[2] or "—"

    @staticmethod
    def _clean_log_line(line: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", line)

    @staticmethod
    def _friendly_error(message: str) -> str:
        text = DownloaderEngine._clean_log_line(message or "").strip()
        lowered = text.lower()
        if "private video" in lowered:
            return "Video riêng tư hoặc tài khoản chưa có quyền xem."
        if "sign in" in lowered or "cookies" in lowered:
            return "Video cần đăng nhập. Hãy thêm cookies.txt trong Cài đặt."
        if "unsupported url" in lowered:
            return "Link này chưa được hỗ trợ."
        if "video unavailable" in lowered:
            return "Video không khả dụng, đã bị xóa hoặc bị giới hạn khu vực."
        if "ffmpeg" in lowered and "not found" in lowered:
            return "Thiếu FFmpeg nên không thể ghép hình và âm thanh."
        return text[-500:] if text else "Tải video thất bại vì lỗi không xác định."

    @staticmethod
    def _run_capture(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
            check=False,
        )
