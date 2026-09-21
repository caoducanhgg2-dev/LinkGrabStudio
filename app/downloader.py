from __future__ import annotations

import json
import html
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
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
                "--flat-playlist",
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
            if result.returncode != 0 and "no such option: --flat-playlist" in (
                (result.stderr or result.stdout or "").lower()
            ):
                # Very old or vendor-modified engines may not expose the flat
                # playlist switch. Full extraction is slower but still works.
                command.remove("--flat-playlist")
                result = self._run_capture(command, timeout=300)
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

    def preview_search(
        self,
        queries: Iterable[str],
        options: PreviewOptions,
        *,
        cookies_file: Path | None = None,
    ) -> list[VideoInfo]:
        """Search YouTube or Douyin by keyword, then filter and rank results."""
        candidates: list[VideoInfo] = []
        scan_limit = max(options.search_limit, options.search_scan_limit)
        scan_limit = max(1, min(500, scan_limit))
        for query in queries:
            clean_query = query.strip()
            if not clean_query:
                continue
            translated_query = self.translate_keyword(clean_query, options.search_language)
            if options.search_platform == "Douyin":
                urls = self._discover_douyin_urls(translated_query, scan_limit)
                if not urls:
                    raise DownloaderError(
                        "Không tìm thấy URL video Douyin trong chỉ mục tìm kiếm web. "
                        "Hãy thử từ khóa tiếng Trung khác hoặc giảm bộ lọc thời gian."
                    )
                videos = self._preview_douyin_urls(urls, cookies_file=cookies_file)
                for video in videos:
                    video.raw["search_query_original"] = clean_query
                    video.raw["search_query_translated"] = translated_query
                candidates.extend(videos)
                continue
            command = [
                str(self.ytdlp),
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                "--ignore-config",
                "--yes-playlist",
                "--flat-playlist",
            ]
            command += self._javascript_options()
            if cookies_file and cookies_file.is_file():
                command += ["--cookies", str(cookies_file)]
            command.append(f"ytsearch{scan_limit}:{translated_query}")
            try:
                result = self._run_capture(command, timeout=300)
            except FileNotFoundError as exc:
                raise DownloaderError("Không tìm thấy yt-dlp trong gói ứng dụng.") from exc
            except subprocess.TimeoutExpired as exc:
                raise DownloaderError("Quá thời gian tìm kiếm video YouTube.") from exc
            if result.returncode != 0 and "no such option: --flat-playlist" in (
                (result.stderr or result.stdout or "").lower()
            ):
                command.remove("--flat-playlist")
                result = self._run_capture(command, timeout=300)
            if result.returncode != 0:
                raise DownloaderError(self._friendly_error(result.stderr or result.stdout))
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise DownloaderError("YouTube trả về dữ liệu tìm kiếm không hợp lệ.") from exc
            for entry in payload.get("entries") or []:
                if entry:
                    entry = dict(entry)
                    entry["search_query_original"] = clean_query
                    entry["search_query_translated"] = translated_query
                    candidates.append(
                        self._video_from_json(
                            entry,
                            fallback_url=f"ytsearch:{translated_query}",
                            playlist=payload,
                        )
                    )

        filtered = candidates
        if options.since_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=options.since_days)
            filtered = [video for video in filtered if self._is_recent(video, cutoff)]
        unique: dict[str, VideoInfo] = {}
        for video in filtered:
            unique.setdefault(video.unique_key, video)
        filtered = list(unique.values())
        if options.sort_by == "newest":
            filtered.sort(key=self._video_timestamp, reverse=True)
        elif options.sort_by == "views":
            filtered.sort(
                key=lambda video: (video.view_count or 0, self._video_timestamp(video)),
                reverse=True,
            )
        return filtered[: max(1, options.search_limit)]

    def _discover_douyin_urls(self, query: str, limit: int) -> list[str]:
        """Find indexed Douyin video URLs without sending a search page to yt-dlp."""
        wanted = max(1, min(300, limit))
        found: list[str] = []
        seen: set[str] = set()
        search_text = f"site:douyin.com/video {query}"
        providers: list[str] = []
        for first in range(1, wanted + 1, 50):
            params = urllib.parse.urlencode(
                {"q": search_text, "format": "rss", "count": "50", "first": str(first)}
            )
            providers.append("https://www.bing.com/search?" + params)
        ddg_params = urllib.parse.urlencode({"q": search_text})
        providers.append("https://html.duckduckgo.com/html/?" + ddg_params)

        for url in providers:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read().decode("utf-8", errors="replace")
            except (OSError, urllib.error.URLError):
                continue

            # Bing RSS and DuckDuckGo HTML both contain the direct video URL as
            # plain text after decoding. Avoid ElementTree here: frozen Windows
            # builds may not include pyexpat, and a full XML parser is unnecessary.
            decoded = html.unescape(urllib.parse.unquote(body))
            candidates = re.findall(
                r"https?://(?:www\.)?douyin\.com/video/\d+", decoded
            )
            for candidate in candidates:
                normalized = self._normalize_douyin_video_url(candidate)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                found.append(normalized)
                if len(found) >= wanted:
                    return found
        return found

    def _preview_douyin_urls(
        self,
        urls: list[str],
        *,
        cookies_file: Path | None = None,
    ) -> list[VideoInfo]:
        """Read metadata from direct Douyin video URLs in small batches."""
        videos: list[VideoInfo] = []
        errors: list[str] = []
        for offset in range(0, len(urls), 20):
            batch = urls[offset : offset + 20]
            command = [
                str(self.ytdlp),
                "--dump-json",
                "--skip-download",
                "--no-warnings",
                "--ignore-config",
                "--no-playlist",
                "--ignore-errors",
            ]
            command += self._javascript_options()
            if cookies_file and cookies_file.is_file():
                command += ["--cookies", str(cookies_file)]
            command += batch
            try:
                result = self._run_capture(command, timeout=300)
            except FileNotFoundError as exc:
                raise DownloaderError("Không tìm thấy yt-dlp trong gói ứng dụng.") from exc
            except subprocess.TimeoutExpired:
                errors.append("Quá thời gian đọc metadata Douyin.")
                continue
            for line in result.stdout.splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("id"):
                    fallback = str(entry.get("webpage_url") or batch[0])
                    videos.append(self._video_from_json(entry, fallback_url=fallback))
            if result.returncode != 0 and result.stderr:
                errors.append(self._friendly_error(result.stderr))
        if not videos:
            detail = errors[0] if errors else "Douyin không trả về metadata video."
            raise DownloaderError(
                "Đã tìm thấy link Douyin nhưng không đọc được video. "
                "Hãy thêm cookies.txt Douyin trong Cài đặt rồi thử lại. Chi tiết: " + detail
            )
        return videos

    @staticmethod
    def _normalize_douyin_video_url(url: str) -> str:
        match = re.search(r"douyin\.com/video/(\d+)", url)
        return f"https://www.douyin.com/video/{match.group(1)}" if match else ""

    @staticmethod
    def translate_keyword(query: str, target_language: str) -> str:
        """Translate a search query without an API key, falling back to the original."""
        target = {"zh-cn": "zh-CN", "zh-tw": "zh-TW"}.get(target_language.lower())
        if not target:
            return query
        params = urllib.parse.urlencode(
            {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": query}
        )
        request = urllib.request.Request(
            "https://translate.googleapis.com/translate_a/single?" + params,
            headers={"User-Agent": "Mozilla/5.0 LinkGrabStudio/1.3"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(
                str(part[0]) for part in (payload[0] or []) if part and part[0]
            ).strip()
            return translated or query
        except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
            return query

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
        if options.overwrite_existing:
            command.append("--force-overwrites")
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
        if "youtube" in extractor.lower() and not webpage_url.startswith(("http://", "https://")):
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"
        if "douyin" in extractor.lower() and "douyin.com" not in webpage_url.lower():
            webpage_url = f"https://www.douyin.com/video/{video_id}"
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
