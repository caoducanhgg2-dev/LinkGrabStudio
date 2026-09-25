from __future__ import annotations

import json
import html
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
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
        self._douyin_bridge_last_error = ""

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
                direct_videos, urls = self._search_douyin_authenticated(
                    translated_query,
                    scan_limit,
                    cookies_file=cookies_file,
                )
                if direct_videos:
                    for video in direct_videos:
                        video.raw["search_query_original"] = clean_query
                        video.raw["search_query_translated"] = translated_query
                    candidates.extend(direct_videos)
                    continue
                if not urls:
                    # Public search engines are only a last resort. Their Douyin
                    # indexes are incomplete and can be empty even when the user
                    # has a valid authenticated Douyin session.
                    urls = self._discover_douyin_urls(translated_query, scan_limit)
                if not urls:
                    raise DownloaderError(
                        "Douyin không trả kết quả cho từ khóa này. Phiên đăng nhập có thể vẫn hợp lệ, "
                        "nhưng Douyin đang yêu cầu xác minh tìm kiếm. Hãy mở Douyin trong trình duyệt, "
                        "tìm thử một lần rồi bấm Làm mới đăng nhập trong Cài đặt."
                    )
                # Never send an indexed Douyin URL back to yt-dlp here.  The
                # detail endpoint used by yt-dlp requires a fresh anti-bot
                # signature and was the source of the recurring “cần đăng nhập”
                # error.  Resolve the pages inside the authenticated browser
                # instead, then download their already-authorized media URLs.
                resolve_limit = max(1, min(len(urls), options.search_limit * 2))
                videos = self._resolve_douyin_urls_with_firefox(
                    urls[:resolve_limit], cookies_file=cookies_file
                )
                if not videos:
                    detail = self._douyin_bridge_last_error or (
                        "Firefox đã mở trang Douyin nhưng trang không cung cấp địa chỉ phát video."
                    )
                    raise DownloaderError(
                        "Đã tìm thấy link Douyin nhưng cầu nối trình duyệt không đọc được video. "
                        "Chi tiết: " + detail
                    )
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

    def _search_douyin_authenticated(
        self,
        query: str,
        limit: int,
        *,
        cookies_file: Path | None = None,
    ) -> tuple[list[VideoInfo], list[str]]:
        """Return rich search items and direct Douyin page URLs from one request."""
        bodies = self._fetch_douyin_search_bodies(query, limit, cookies_file=cookies_file)
        if not bodies or not any(self._extract_douyin_video_urls(body) for body in bodies):
            # Douyin signs search requests in its own JavaScript. If the plain
            # authenticated request is challenged, let the user's logged-in
            # Firefox create that signature and read the signed JSON locally.
            bodies.extend(
                self._fetch_douyin_search_with_firefox(query, cookies_file=cookies_file)
            )
        videos: list[VideoInfo] = []
        urls: list[str] = []
        seen_videos: set[str] = set()
        seen_urls: set[str] = set()
        for body in bodies:
            for video in self._extract_douyin_search_videos(body):
                if video.unique_key in seen_videos:
                    continue
                seen_videos.add(video.unique_key)
                videos.append(video)
            for url in self._extract_douyin_video_urls(body):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                urls.append(url)
        wanted = max(1, min(300, limit))
        return videos[:wanted], urls[:wanted]

    def _search_douyin_urls_authenticated(
        self,
        query: str,
        limit: int,
        *,
        cookies_file: Path | None = None,
    ) -> list[str]:
        """Search Douyin itself with the browser session saved by the app.

        Douyin changes its client-side response shape frequently.  The parser is
        deliberately tolerant: it accepts direct URLs and the stable numeric
        identifiers found in both page hydration data and JSON API responses.
        """
        _, urls = self._search_douyin_authenticated(
            query, limit, cookies_file=cookies_file
        )
        return urls

    def _fetch_douyin_search_bodies(
        self,
        query: str,
        limit: int,
        *,
        cookies_file: Path | None = None,
    ) -> list[str]:
        """Fetch the search HTML/API while keeping cookies out of logs."""
        wanted = max(1, min(300, limit))
        encoded_query = urllib.parse.quote(query, safe="")
        referer = f"https://www.douyin.com/search/{encoded_query}?type=video"
        cookie_header = self._cookie_header_for_domain(cookies_file, "douyin.com")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": "https://www.douyin.com/",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        sources = [referer]
        # The same authenticated web endpoint used by Douyin's search page.  It
        # is attempted after the HTML page because some sessions receive all
        # results in hydration data and do not need a second request.
        api_params = urllib.parse.urlencode(
            {
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "search_channel": "aweme_general",
                "keyword": query,
                "search_source": "normal_search",
                "query_correct_type": "1",
                "is_filter_search": "0",
                "offset": "0",
                "count": str(min(50, wanted)),
            }
        )
        sources.append(
            "https://www.douyin.com/aweme/v1/web/general/search/single/?" + api_params
        )

        bodies: list[str] = []
        for source in sources:
            source_headers = dict(headers)
            source_headers["Referer"] = referer
            if "/aweme/" in source:
                source_headers["Accept"] = "application/json, text/plain, */*"
            request = urllib.request.Request(source, headers=source_headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read().decode("utf-8", errors="replace")
            except (OSError, urllib.error.URLError):
                continue
            bodies.append(body)
        return bodies

    def _fetch_douyin_search_with_firefox(
        self,
        query: str,
        *,
        cookies_file: Path | None = None,
    ) -> list[str]:
        """Use Firefox WebDriver BiDi to capture Douyin's own signed search JSON."""
        self._douyin_bridge_last_error = ""
        if os.name != "nt":
            self._douyin_bridge_last_error = "Cầu nối Douyin chỉ hỗ trợ bản Windows."
            return []
        deno_path = Path(str(self.deno))
        if not deno_path.is_file():
            self._douyin_bridge_last_error = "Gói cập nhật thiếu deno.exe."
            return []
        firefox = self._find_firefox_executable()
        if not firefox:
            self._douyin_bridge_last_error = "Không tìm thấy Mozilla Firefox trên máy."
            return []
        port = self._free_local_port()
        bridge_profile = Path(tempfile.mkdtemp(prefix="LinkGrabStudio_Douyin_"))
        search_url = (
            "https://www.douyin.com/search/"
            + urllib.parse.quote(query, safe="")
            + "?type=video"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        browser_process = None
        try:
            browser_process = subprocess.Popen(
                [
                    str(firefox),
                    "-no-remote",
                    "-profile",
                    str(bridge_profile),
                    "--remote-debugging-port",
                    str(port),
                    "-new-window",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._douyin_bridge_last_error = f"Không mở được Firefox: {exc}"
            shutil.rmtree(bridge_profile, ignore_errors=True)
            return []

        cookie_path = str(cookies_file) if cookies_file and cookies_file.is_file() else ""
        script = self._douyin_bidi_script(port, search_url, cookie_path)
        command = [
            str(deno_path),
            "eval",
            f"--allow-net=127.0.0.1:{port}",
            *( [f"--allow-read={cookie_path}"] if cookie_path else [] ),
            script,
        ]
        try:
            result = self._run_capture(command, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            self._douyin_bridge_last_error = f"Cầu nối Firefox không chạy được: {exc}"
            return []
        finally:
            if browser_process and browser_process.poll() is None:
                try:
                    browser_process.terminate()
                    browser_process.wait(timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
            shutil.rmtree(bridge_profile, ignore_errors=True)
        marker = "__LINKGRAB_DOUYIN_JSON__"
        payload_line = next(
            (line[len(marker) :] for line in result.stdout.splitlines() if line.startswith(marker)),
            "",
        )
        if not payload_line:
            diagnostic = (result.stderr or result.stdout or "").strip().splitlines()
            self._douyin_bridge_last_error = (
                diagnostic[-1][:350]
                if diagnostic
                else f"Firefox không trả dữ liệu (mã {result.returncode})."
            )
            return []
        try:
            bodies = json.loads(payload_line)
        except json.JSONDecodeError:
            self._douyin_bridge_last_error = "Dữ liệu cầu nối Firefox không hợp lệ."
            return []
        parsed = [str(body) for body in bodies if isinstance(body, str) and body.strip()]
        if not parsed:
            self._douyin_bridge_last_error = (
                "Trang tìm kiếm Douyin đã mở nhưng không trả dữ liệu video; "
                "có thể đang hiện CAPTCHA/xác minh."
            )
        return parsed

    def _resolve_douyin_urls_with_firefox(
        self,
        urls: list[str],
        *,
        cookies_file: Path | None = None,
    ) -> list[VideoInfo]:
        """Resolve Douyin pages in Firefox without calling yt-dlp's detail API."""
        self._douyin_bridge_last_error = ""
        normalized = [self._normalize_douyin_video_url(url) for url in urls]
        normalized = list(dict.fromkeys(url for url in normalized if url))
        if not normalized:
            self._douyin_bridge_last_error = "Danh sách link Douyin không hợp lệ."
            return []
        if os.name != "nt":
            self._douyin_bridge_last_error = "Cầu nối Douyin chỉ hỗ trợ bản Windows."
            return []
        deno_path = Path(str(self.deno))
        if not deno_path.is_file():
            self._douyin_bridge_last_error = "Gói cập nhật thiếu deno.exe."
            return []
        firefox = self._find_firefox_executable()
        if not firefox:
            self._douyin_bridge_last_error = (
                "Không tìm thấy Mozilla Firefox. Hãy cài Firefox rồi bấm Kiểm tra lại đăng nhập."
            )
            return []

        port = self._free_local_port()
        bridge_profile = Path(tempfile.mkdtemp(prefix="LinkGrabStudio_Douyin_"))
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        browser_process = None
        try:
            browser_process = subprocess.Popen(
                [
                    str(firefox), "-no-remote", "-profile", str(bridge_profile),
                    "--remote-debugging-port", str(port), "-new-window", "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._douyin_bridge_last_error = f"Không mở được Firefox: {exc}"
            shutil.rmtree(bridge_profile, ignore_errors=True)
            return []

        cookie_path = str(cookies_file) if cookies_file and cookies_file.is_file() else ""
        script = self._douyin_resolver_bidi_script(port, normalized, cookie_path)
        command = [
            str(deno_path), "eval", f"--allow-net=127.0.0.1:{port}",
            *([f"--allow-read={cookie_path}"] if cookie_path else []), script,
        ]
        try:
            result = self._run_capture(command, timeout=max(180, len(normalized) * 25))
        except (OSError, subprocess.SubprocessError) as exc:
            self._douyin_bridge_last_error = f"Cầu nối Firefox không chạy được: {exc}"
            return []
        finally:
            if browser_process and browser_process.poll() is None:
                try:
                    browser_process.terminate()
                    browser_process.wait(timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
            shutil.rmtree(bridge_profile, ignore_errors=True)

        marker = "__LINKGRAB_DOUYIN_VIDEOS__"
        payload_line = next(
            (line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker)),
            "",
        )
        if not payload_line:
            diagnostic = (result.stderr or result.stdout or "").strip().splitlines()
            self._douyin_bridge_last_error = (
                diagnostic[-1][:350]
                if diagnostic
                else f"Firefox không trả dữ liệu (mã {result.returncode})."
            )
            return []
        try:
            payload = json.loads(payload_line)
        except json.JSONDecodeError:
            self._douyin_bridge_last_error = "Dữ liệu video từ Firefox không hợp lệ."
            return []

        items = payload.get("items", []) if isinstance(payload, dict) else []
        diagnostics = payload.get("diagnostics", []) if isinstance(payload, dict) else []
        videos: list[VideoInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source_url = self._normalize_douyin_video_url(str(item.get("url") or ""))
            match = re.search(r"/video/(\d{12,})", source_url)
            direct_url = str(item.get("direct_url") or "")
            if not match or not direct_url.startswith(("http://", "https://")):
                continue
            video_id = match.group(1)
            direct_url = direct_url.replace("http://", "https://", 1)
            title = str(item.get("title") or f"Douyin {video_id}").strip()
            raw = dict(item)
            raw["direct_url"] = direct_url
            videos.append(
                VideoInfo(
                    url=source_url,
                    video_id=video_id,
                    title=title,
                    platform="Douyin",
                    uploader=str(item.get("uploader") or ""),
                    thumbnail=str(item.get("thumbnail") or ""),
                    webpage_url=source_url,
                    extractor="DouyinBrowser",
                    raw=raw,
                )
            )
        if not videos:
            detail = next((str(value) for value in diagnostics if value), "")
            self._douyin_bridge_last_error = detail[:350] or (
                "Trang video đã mở nhưng không có luồng phát HTTP; "
                "hãy hoàn tất CAPTCHA/xác minh trong Firefox rồi thử lại."
            )
        return videos

    @staticmethod
    def _find_firefox_executable() -> Path | None:
        candidates: list[Path] = []
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(variable, "")
            if base:
                candidates.append(Path(base) / "Mozilla Firefox" / "firefox.exe")
        executable = next((path for path in candidates if path.is_file()), None)
        if executable:
            return executable
        found = shutil.which("firefox")
        return Path(found) if found else None

    @staticmethod
    def _free_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _douyin_bidi_script(port: int, search_url: str, cookie_path: str = "") -> str:
        """Return a dependency-free Deno WebDriver BiDi client."""
        return f'''
const endpoint = "ws://127.0.0.1:{port}/session";
const targetUrl = {json.dumps(search_url)};
const cookiePath = {json.dumps(cookie_path)};
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let ws;
for (let attempt = 0; attempt < 60; attempt++) {{
  try {{
    ws = new WebSocket(endpoint);
    await new Promise((resolve, reject) => {{
      const timer = setTimeout(() => reject(new Error("open timeout")), 1000);
      ws.onopen = () => {{ clearTimeout(timer); resolve(); }};
      ws.onerror = () => {{ clearTimeout(timer); reject(new Error("open failed")); }};
    }});
    break;
  }} catch (_) {{
    try {{ ws?.close(); }} catch (_) {{}}
    ws = undefined;
    await delay(500);
  }}
}}
if (!ws) Deno.exit(2);
let nextId = 0;
const waiting = new Map();
ws.onmessage = (event) => {{
  const message = JSON.parse(event.data);
  if (!message.id || !waiting.has(message.id)) return;
  const pending = waiting.get(message.id);
  waiting.delete(message.id);
  if (message.type === "error") pending.reject(new Error(message.message || message.error));
  else pending.resolve(message.result);
}};
const send = (method, params = {{}}, timeoutMs = 30000) => new Promise((resolve, reject) => {{
  const id = ++nextId;
  waiting.set(id, {{resolve, reject}});
  ws.send(JSON.stringify({{id, method, params}}));
  setTimeout(() => {{
    if (!waiting.has(id)) return;
    waiting.delete(id);
    reject(new Error(method + " timeout"));
  }}, timeoutMs);
}});
try {{
  await send("session.new", {{capabilities: {{alwaysMatch: {{acceptInsecureCerts: false}}}}}});
  if (cookiePath) {{
    try {{
      const cookieText = await Deno.readTextFile(cookiePath);
      for (const rawLine of cookieText.split(/\\r?\\n/)) {{
        let line = rawLine.trim();
        let httpOnly = false;
        if (line.startsWith("#HttpOnly_")) {{
          httpOnly = true;
          line = line.slice("#HttpOnly_".length);
        }} else if (!line || line.startsWith("#")) {{
          continue;
        }}
        const fields = line.split("\\t");
        if (fields.length < 7) continue;
        const [domain, , path, secureText, expiryText, name, value] = fields;
        if (!domain.toLowerCase().includes("douyin.com") || !name || !value) continue;
        const cookie = {{
          name,
          value: {{type: "string", value}},
          domain: domain.replace(/^\\./, ""),
          path: path || "/",
          secure: secureText.toUpperCase() === "TRUE",
          httpOnly,
        }};
        const expiry = Number(expiryText || 0);
        if (Number.isFinite(expiry) && expiry > 0) cookie.expiry = Math.floor(expiry);
        try {{ await send("storage.setCookie", {{cookie}}); }} catch (_) {{}}
      }}
    }} catch (_) {{}}
  }}
  const tree = await send("browsingContext.getTree", {{maxDepth: 0}});
  const contexts = tree.contexts || [];
  if (!contexts.length) throw new Error("no browsing context");
  const context = (contexts.find((item) => String(item.url).includes("douyin.com")) || contexts[0]).context;
  await send("browsingContext.navigate", {{context, url: targetUrl, wait: "complete"}}, 60000);
  const expression = `(async () => {{
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const searchResources = () => performance.getEntriesByType("resource")
      .map((entry) => entry.name)
      .filter((url) => url.includes("/aweme/v1/web/") && url.includes("search"));
    for (let waitRound = 0; waitRound < 40 && !searchResources().length; waitRound++) {{
      await sleep(750);
    }}
    for (let round = 0; round < 12; round++) {{
      window.scrollBy(0, Math.max(window.innerHeight, 800));
      await sleep(600);
    }}
    await sleep(1800);
    const resources = searchResources();
    const unique = [...new Set(resources)];
    const bodies = [];
    for (const url of unique) {{
      try {{
        const response = await fetch(url, {{credentials: "include"}});
        const text = await response.text();
        if (text && text.trim().startsWith("{{")) bodies.push(text);
      }} catch (_) {{}}
    }}
    if (!bodies.length) {{
      const state = [...document.scripts]
        .map((node) => node.textContent || "")
        .filter((text) => text.includes("aweme_id") && text.length > 100);
      bodies.push(...state);
    }}
    return JSON.stringify(bodies);
  }})()`;
  const evaluated = await send("script.evaluate", {{
    expression,
    target: {{context}},
    awaitPromise: true,
    resultOwnership: "none",
  }}, 70000);
  const value = evaluated?.result?.value || "[]";
  console.log("__LINKGRAB_DOUYIN_JSON__" + value);
  try {{ await send("browser.close", {{}}); }} catch (_) {{}}
  ws.close();
}} catch (error) {{
  console.error(String(error));
  try {{ ws.close(); }} catch (_) {{}}
  Deno.exit(3);
}}
'''

    @staticmethod
    def _douyin_resolver_bidi_script(
        port: int,
        urls: list[str],
        cookie_path: str = "",
    ) -> str:
        """Return a BiDi client that resolves real media URLs from video pages."""
        template = r'''
const endpoint = "ws://127.0.0.1:__PORT__/session";
const targetUrls = __URLS__;
const cookiePath = __COOKIE_PATH__;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let ws;
for (let attempt = 0; attempt < 60; attempt++) {
  try {
    ws = new WebSocket(endpoint);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("open timeout")), 1000);
      ws.onopen = () => { clearTimeout(timer); resolve(); };
      ws.onerror = () => { clearTimeout(timer); reject(new Error("open failed")); };
    });
    break;
  } catch (_) {
    try { ws?.close(); } catch (_) {}
    ws = undefined;
    await delay(500);
  }
}
if (!ws) Deno.exit(2);
let nextId = 0;
const waiting = new Map();
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !waiting.has(message.id)) return;
  const pending = waiting.get(message.id);
  waiting.delete(message.id);
  if (message.type === "error") pending.reject(new Error(message.message || message.error));
  else pending.resolve(message.result);
};
const send = (method, params = {}, timeoutMs = 30000) => new Promise((resolve, reject) => {
  const id = ++nextId;
  waiting.set(id, {resolve, reject});
  ws.send(JSON.stringify({id, method, params}));
  setTimeout(() => {
    if (!waiting.has(id)) return;
    waiting.delete(id);
    reject(new Error(method + " timeout"));
  }, timeoutMs);
});
const diagnostics = [];
const items = [];
try {
  await send("session.new", {capabilities: {alwaysMatch: {acceptInsecureCerts: false}}});
  const tree = await send("browsingContext.getTree", {maxDepth: 0});
  const contexts = tree.contexts || [];
  if (!contexts.length) throw new Error("Firefox không tạo được thẻ trình duyệt");
  const context = contexts[0].context;
  let cookieCount = 0;
  let cookieFailures = 0;
  if (cookiePath) {
    try {
      const cookieText = await Deno.readTextFile(cookiePath);
      for (const rawLine of cookieText.split(/\r?\n/)) {
        let line = rawLine.trim();
        let httpOnly = false;
        if (line.startsWith("#HttpOnly_")) {
          httpOnly = true;
          line = line.slice("#HttpOnly_".length);
        } else if (!line || line.startsWith("#")) {
          continue;
        }
        const fields = line.split("\t");
        if (fields.length < 7) continue;
        const [rawDomain, , path, secureText, expiryText, name, value] = fields;
        if (!rawDomain.toLowerCase().includes("douyin.com") || !name || !value) continue;
        const cookie = {
          name,
          value: {type: "string", value},
          domain: rawDomain.replace(/^\./, ""),
          path: path || "/",
          secure: secureText.toUpperCase() === "TRUE",
          httpOnly,
        };
        const expiry = Number(expiryText || 0);
        if (Number.isFinite(expiry) && expiry > 0) cookie.expiry = Math.floor(expiry);
        try {
          await send("storage.setCookie", {cookie});
          cookieCount++;
        } catch (_) {
          cookieFailures++;
        }
      }
    } catch (error) {
      diagnostics.push("Không đọc được tệp phiên đăng nhập: " + String(error));
    }
  }
  if (!cookieCount) diagnostics.push("Không nạp được cookie Douyin vào Firefox tạm.");
  if (cookieFailures) diagnostics.push("Có " + cookieFailures + " cookie bị Firefox từ chối.");

  for (const targetUrl of targetUrls) {
    try {
      await send(
        "browsingContext.navigate",
        {context, url: targetUrl, wait: "interactive"},
        60000,
      );
      const expression = `(async () => {
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const httpUrl = (value) => typeof value === "string" && /^https?:\\/\\//i.test(value);
        const mediaResources = () => performance.getEntriesByType("resource")
          .map((entry) => entry.name)
          .filter((url) => httpUrl(url) && (
            /\\.(?:mp4|m3u8)(?:[?#]|$)/i.test(url) ||
            /video\\/tos|douyinvod|bytevc|mime_type=video|video_id=/i.test(url)
          ));
        let challenge = false;
        for (let round = 0; round < 60; round++) {
          const video = document.querySelector("video");
          if (video) {
            try { await video.play(); } catch (_) {}
            if (httpUrl(video.currentSrc) || httpUrl(video.src) || mediaResources().length) break;
          }
          challenge = /验证码|安全验证|captcha|verify/i.test(document.body?.innerText || "");
          // A normal page should expose its player quickly.  A verification
          // page remains visible for up to one minute so the user can complete
          // it in the Firefox window instead of the app closing it immediately.
          if (round >= 12 && !challenge) break;
          window.scrollBy(0, Math.max(300, window.innerHeight / 2));
          await sleep(1000);
        }
        const video = document.querySelector("video");
        const sources = video ? [...video.querySelectorAll("source")].map((node) => node.src) : [];
        const direct = [video?.currentSrc, video?.src, ...sources, ...mediaResources()]
          .find((value) => httpUrl(value)) || "";
        const meta = (name) => document.querySelector(
          'meta[property="' + name + '"],meta[name="' + name + '"]'
        )?.content || "";
        return JSON.stringify({
          url: location.href,
          title: meta("og:title") || document.title || "",
          uploader: meta("author") || "",
          thumbnail: meta("og:image") || "",
          direct_url: direct,
          challenge,
        });
      })()`;
      const evaluated = await send("script.evaluate", {
        expression,
        target: {context},
        awaitPromise: true,
        resultOwnership: "none",
      }, 30000);
      const value = evaluated?.result?.value || "{}";
      const item = JSON.parse(value);
      if (!item.url || !String(item.url).includes("/video/")) item.url = targetUrl;
      items.push(item);
      if (!item.direct_url) {
        diagnostics.push(
          item.challenge
            ? "Douyin đang hiện CAPTCHA/xác minh cho " + targetUrl
            : "Trang không trả luồng phát cho " + targetUrl
        );
        if (item.challenge) break;
      }
    } catch (error) {
      diagnostics.push("Không mở được " + targetUrl + ": " + String(error));
    }
  }
  console.log("__LINKGRAB_DOUYIN_VIDEOS__" + JSON.stringify({items, diagnostics}));
  try { await send("browser.close", {}); } catch (_) {}
  ws.close();
} catch (error) {
  console.error("Cầu nối Douyin: " + String(error));
  try { ws.close(); } catch (_) {}
  Deno.exit(3);
}
'''
        return (
            template.replace("__PORT__", str(port))
            .replace("__URLS__", json.dumps(urls, ensure_ascii=False))
            .replace("__COOKIE_PATH__", json.dumps(cookie_path, ensure_ascii=False))
        )

    @classmethod
    def _extract_douyin_search_videos(cls, body: str) -> list[VideoInfo]:
        """Build preview rows directly from Douyin search JSON/hydration data."""
        decoded = html.unescape(urllib.parse.unquote(body))
        decoded = decoded.replace("\\u002F", "/").replace("\\/", "/")
        payloads: list[object] = []
        candidates = [decoded]
        candidates.extend(re.findall(r"<script[^>]*>(.*?)</script>", decoded, flags=re.I | re.S))
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                payloads.append(json.loads(candidate))
            except (json.JSONDecodeError, TypeError):
                continue

        videos: list[VideoInfo] = []
        seen: set[str] = set()
        for payload in payloads:
            for item in cls._walk_douyin_dicts(payload):
                video = cls._video_from_douyin_search_item(item)
                if not video or video.unique_key in seen:
                    continue
                seen.add(video.unique_key)
                videos.append(video)
        return videos

    @staticmethod
    def _walk_douyin_dicts(value) -> Iterable[dict]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from DownloaderEngine._walk_douyin_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from DownloaderEngine._walk_douyin_dicts(child)
        elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
            try:
                nested = json.loads(value)
            except json.JSONDecodeError:
                return
            yield from DownloaderEngine._walk_douyin_dicts(nested)

    @classmethod
    def _video_from_douyin_search_item(cls, item: dict) -> VideoInfo | None:
        video_id = str(
            item.get("aweme_id")
            or item.get("awemeId")
            or item.get("group_id")
            or item.get("groupId")
            or ""
        )
        if not re.fullmatch(r"\d{12,}", video_id):
            return None
        video_data = item.get("video")
        if not isinstance(video_data, dict):
            return None
        direct_url = cls._douyin_media_url(video_data)
        if not direct_url:
            return None
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        create_time = cls._optional_int(item.get("create_time") or item.get("createTime"))
        duration_ms = cls._optional_int(video_data.get("duration") or item.get("duration"))
        cover = video_data.get("cover") or video_data.get("origin_cover") or {}
        thumbnail = cls._first_url(cover)
        webpage_url = f"https://www.douyin.com/video/{video_id}"
        raw = dict(item)
        raw["direct_url"] = direct_url
        if create_time:
            raw["timestamp"] = create_time
        return VideoInfo(
            url=webpage_url,
            video_id=video_id,
            title=str(item.get("desc") or item.get("title") or f"Douyin {video_id}"),
            platform="Douyin",
            uploader=str(author.get("nickname") or author.get("unique_id") or ""),
            duration=round(duration_ms / 1000) if duration_ms else None,
            thumbnail=thumbnail,
            webpage_url=webpage_url,
            extractor="DouyinSearch",
            view_count=cls._optional_int(
                statistics.get("play_count") or statistics.get("playCount")
            ),
            upload_date=(
                datetime.fromtimestamp(create_time, tz=timezone.utc).strftime("%Y%m%d")
                if create_time
                else ""
            ),
            raw=raw,
        )

    @classmethod
    def _douyin_media_url(cls, video_data: dict) -> str:
        sources = [
            video_data.get("play_addr"),
            video_data.get("playAddr"),
            video_data.get("play_addr_h264"),
            video_data.get("download_addr"),
        ]
        bit_rates = video_data.get("bit_rate") or video_data.get("bitRate") or []
        if isinstance(bit_rates, list):
            for rate in bit_rates:
                if isinstance(rate, dict):
                    sources.append(rate.get("play_addr") or rate.get("playAddr"))
        for source in sources:
            url = cls._first_url(source)
            if url:
                return url.replace("http://", "https://", 1)
        return ""

    @staticmethod
    def _first_url(value) -> str:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if not isinstance(value, dict):
            return ""
        urls = value.get("url_list") or value.get("urlList") or []
        if isinstance(urls, list):
            return next(
                (str(url) for url in urls if str(url).startswith(("http://", "https://"))),
                "",
            )
        return ""

    @classmethod
    def _extract_douyin_video_urls(cls, body: str) -> list[str]:
        """Extract stable Douyin video IDs from HTML, escaped JSON, or API JSON."""
        decoded = html.unescape(urllib.parse.unquote(body))
        # Hydration JSON may escape slashes once or twice.
        decoded = decoded.replace("\\u002F", "/").replace("\\/", "/")
        identifiers: list[str] = []
        identifiers.extend(
            re.findall(r"(?:https?:)?//(?:www\.)?douyin\.com/video/(\d{12,})", decoded)
        )
        identifiers.extend(
            re.findall(
                r'["\'](?:aweme_id|awemeId|group_id|groupId|item_id|itemId|video_id|videoId)'
                r'["\']\s*:\s*["\']?(\d{12,})["\']?',
                decoded,
            )
        )
        found: list[str] = []
        seen: set[str] = set()
        for identifier in identifiers:
            url = cls._normalize_douyin_video_url(
                f"https://www.douyin.com/video/{identifier}"
            )
            if url and url not in seen:
                seen.add(url)
                found.append(url)
        return found

    @staticmethod
    def _cookie_header_for_domain(cookies_file: Path | None, domain: str) -> str:
        """Convert matching, unexpired Netscape cookies to an HTTP Cookie header."""
        if not cookies_file or not cookies_file.is_file():
            return ""
        now = int(datetime.now(timezone.utc).timestamp())
        cookies: dict[str, str] = {}
        try:
            lines = cookies_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        wanted_domain = domain.lower().lstrip(".")
        for raw_line in lines:
            line = raw_line.strip()
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            elif not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7:
                continue
            cookie_domain = fields[0].lower().lstrip(".")
            if not (
                cookie_domain == wanted_domain
                or cookie_domain.endswith("." + wanted_domain)
            ):
                continue
            try:
                expires = int(fields[4] or "0")
            except ValueError:
                expires = 0
            if expires and expires <= now:
                continue
            name, value = fields[5].strip(), fields[6].strip()
            if name and value:
                cookies[name] = value
        return "; ".join(f"{name}={value}" for name, value in cookies.items())

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
                "Hãy vào Cài đặt, làm mới đăng nhập từ trình duyệt rồi thử lại. Chi tiết: "
                + detail
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
        direct_url = str(job.video.raw.get("direct_url") or "")
        source_url = direct_url or job.video.webpage_url or job.video.url
        command = self.build_download_command(
            source_url,
            options,
            filename_stem=(f"{job.video.title} [{job.video.video_id}]" if direct_url else None),
        )
        if direct_url:
            command[-1:-1] = [
                "--add-header",
                "Referer:https://www.douyin.com/",
                "--add-header",
                "Origin:https://www.douyin.com",
            ]
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

    def build_download_command(
        self,
        url: str,
        options: DownloadOptions,
        *,
        filename_stem: str | None = None,
    ) -> list[str]:
        output_name = "%(title).180B [%(id)s].%(ext)s"
        if filename_stem:
            safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename_stem).strip(" .")
            output_name = f"{safe_stem[:180] or 'Douyin video'}.%(ext)s"
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
            str(options.output_dir / output_name),
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
            return "Video cần đăng nhập. Hãy làm mới đăng nhập trình duyệt trong Cài đặt."
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
