from __future__ import annotations

import os
import shutil
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from .config import app_data_dir


class DouyinAuthError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DouyinAuthStatus:
    code: str
    message: str
    cookie_file: Path | None = None


class DouyinAuthManager:
    """Import and validate Douyin login cookies without asking for a password."""

    AUTH_COOKIE_NAMES = {
        "sessionid",
        "sessionid_ss",
        "sid_guard",
        "sid_tt",
    }

    def __init__(self, engine) -> None:
        self.engine = engine

    @property
    def cookie_file(self) -> Path:
        return app_data_dir() / "douyin_browser_cookies.txt"

    def status(self, cookie_file: Path | None = None) -> DouyinAuthStatus:
        path = cookie_file or self.cookie_file
        if not path.is_file():
            return DouyinAuthStatus("missing", "Chưa lấy đăng nhập Douyin từ trình duyệt.")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return DouyinAuthStatus("error", f"Không đọc được cookies: {exc}", path)

        now = int(time.time())
        found_douyin = False
        found_expired_auth = False
        for raw_line in lines:
            line = raw_line.strip()
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            elif not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7 or "douyin.com" not in fields[0].lower():
                continue
            found_douyin = True
            name = fields[5].strip().lower()
            if name not in self.AUTH_COOKIE_NAMES:
                continue
            try:
                expires = int(fields[4] or "0")
            except ValueError:
                expires = 0
            if expires and expires <= now:
                found_expired_auth = True
                continue
            if fields[6]:
                return DouyinAuthStatus(
                    "logged_in",
                    "Đã đăng nhập Douyin — cookies đang hoạt động.",
                    path,
                )

        if found_expired_auth:
            return DouyinAuthStatus(
                "expired",
                "Cookies hết hạn — hãy đăng nhập lại rồi bấm Làm mới cookies.",
                path,
            )
        if found_douyin:
            return DouyinAuthStatus(
                "not_logged_in",
                "Có cookies Douyin nhưng chưa thấy phiên đăng nhập.",
                path,
            )
        return DouyinAuthStatus(
            "not_logged_in",
            "Trình duyệt chưa có phiên đăng nhập Douyin.",
            path,
        )

    def refresh(self, browser: str) -> DouyinAuthStatus:
        browser = browser.lower().strip()
        if browser not in {"chrome", "edge"}:
            raise DouyinAuthError("Chỉ hỗ trợ Google Chrome hoặc Microsoft Edge.")

        target = self.cookie_file
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp.txt")
        try:
            temp.unlink(missing_ok=True)
        except OSError as exc:
            raise DouyinAuthError(f"Không thể chuẩn bị tệp cookies tạm: {exc}") from exc

        try:
            urls = self.engine._discover_douyin_urls("热门", 1)
        except Exception:
            urls = []
        check_url = urls[0] if urls else "https://www.douyin.com/"
        command = [
            str(self.engine.ytdlp),
            "--ignore-config",
            "--cookies-from-browser",
            browser,
            "--cookies",
            str(temp),
            "--skip-download",
            "--no-warnings",
            check_url,
        ]
        try:
            result = self.engine._run_capture(command, timeout=120)
        except FileNotFoundError as exc:
            raise DouyinAuthError("Không tìm thấy yt-dlp trong gói ứng dụng.") from exc
        except subprocess.TimeoutExpired as exc:
            raise DouyinAuthError("Quá thời gian đọc đăng nhập từ trình duyệt.") from exc

        imported = self.status(temp)
        if imported.code == "logged_in":
            try:
                temp.replace(target)
            except OSError as exc:
                raise DouyinAuthError(f"Không thể lưu phiên đăng nhập Douyin: {exc}") from exc
            return self.status(target)

        temp.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout or "").strip()
        lowered = detail.lower()
        if "could not copy chrome cookie database" in lowered or "database is locked" in lowered:
            detail = "Hãy đóng hoàn toàn trình duyệt rồi thử lại."
        elif "decrypt" in lowered or "dpapi" in lowered:
            detail = (
                "Windows không giải mã được cookies của trình duyệt này. "
                "Hãy thử Microsoft Edge hoặc cập nhật yt-dlp."
            )
        elif imported.code == "expired":
            detail = imported.message
        else:
            detail = "Hãy đăng nhập Douyin trong trình duyệt đã chọn rồi thử lại."
        raise DouyinAuthError(detail)

    @staticmethod
    def open_login(browser: str) -> None:
        url = "https://www.douyin.com/"
        candidates: list[Path] = []
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        if browser == "edge":
            candidates.extend(
                Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                for base in (program_files, program_files_x86, local)
                if base
            )
            command_name = "msedge"
        else:
            candidates.extend(
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                for base in (local, program_files, program_files_x86)
                if base
            )
            command_name = "chrome"
        executable = next((path for path in candidates if path.is_file()), None)
        executable = executable or (Path(found) if (found := shutil.which(command_name)) else None)
        if executable:
            subprocess.Popen([str(executable), url])
        else:
            webbrowser.open(url)
