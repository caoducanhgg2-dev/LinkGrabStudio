from __future__ import annotations

import os
import shutil
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from .config import app_data_dir


class BrowserAuthError(RuntimeError):
    def __init__(self, message: str, *, code: str = "unknown") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PlatformAuthSpec:
    name: str
    login_url: str
    domains: tuple[str, ...]
    auth_cookie_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class BrowserAuthStatus:
    platform: str
    code: str
    message: str
    cookie_file: Path | None = None


PLATFORM_AUTH_SPECS = {
    "YouTube": PlatformAuthSpec(
        "YouTube",
        "https://accounts.google.com/ServiceLogin?service=youtube",
        ("youtube.com", "google.com"),
        frozenset(
            {
                "sid",
                "hsid",
                "ssid",
                "sapisid",
                "__secure-1papisid",
                "__secure-3papisid",
                "login_info",
            }
        ),
    ),
    "TikTok": PlatformAuthSpec(
        "TikTok",
        "https://www.tiktok.com/login",
        ("tiktok.com",),
        frozenset({"sessionid", "sessionid_ss", "sid_guard"}),
    ),
    "Douyin": PlatformAuthSpec(
        "Douyin",
        "https://www.douyin.com/",
        ("douyin.com",),
        frozenset({"sessionid", "sessionid_ss", "sid_guard", "sid_tt"}),
    ),
    "Facebook": PlatformAuthSpec(
        "Facebook",
        "https://www.facebook.com/login/",
        ("facebook.com",),
        frozenset({"c_user", "xs"}),
    ),
    "Instagram": PlatformAuthSpec(
        "Instagram",
        "https://www.instagram.com/accounts/login/",
        ("instagram.com",),
        frozenset({"sessionid", "ds_user_id"}),
    ),
}

PLATFORM_AUTH_ORDER = ("Douyin", "TikTok", "YouTube", "Facebook", "Instagram")


class BrowserAuthManager:
    """Read login sessions from Chrome/Edge without receiving user passwords."""

    def __init__(self, engine) -> None:
        self.engine = engine

    @property
    def cookie_file(self) -> Path:
        return app_data_dir() / "browser_login_cookies.txt"

    @staticmethod
    def _domain_matches(domain: str, spec: PlatformAuthSpec) -> bool:
        normalized = domain.lower().lstrip(".")
        return any(normalized == suffix or normalized.endswith(f".{suffix}") for suffix in spec.domains)

    def status(self, platform: str, cookie_file: Path | None = None) -> BrowserAuthStatus:
        spec = PLATFORM_AUTH_SPECS[platform]
        path = cookie_file or self.cookie_file
        if not path.is_file():
            return BrowserAuthStatus(platform, "missing", "Chưa đăng nhập trong app.")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return BrowserAuthStatus(platform, "error", f"Không đọc được phiên: {exc}", path)

        now = int(time.time())
        found_platform = False
        found_expired_auth = False
        for raw_line in lines:
            line = raw_line.strip()
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            elif not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7 or not self._domain_matches(fields[0], spec):
                continue
            found_platform = True
            name = fields[5].strip().lower()
            if name not in spec.auth_cookie_names:
                continue
            try:
                expires = int(fields[4] or "0")
            except ValueError:
                expires = 0
            if expires and expires <= now:
                found_expired_auth = True
                continue
            if fields[6]:
                return BrowserAuthStatus(platform, "logged_in", f"Đã đăng nhập {platform}", path)

        if found_expired_auth:
            return BrowserAuthStatus(platform, "expired", "Cookies hết hạn", path)
        if found_platform:
            return BrowserAuthStatus(platform, "not_logged_in", "Chưa có phiên đăng nhập", path)
        return BrowserAuthStatus(platform, "missing", "Chưa đăng nhập trong app.", path)

    def statuses(self, cookie_file: Path | None = None) -> dict[str, BrowserAuthStatus]:
        return {platform: self.status(platform, cookie_file) for platform in PLATFORM_AUTH_ORDER}

    def refresh(self, browser: str) -> dict[str, BrowserAuthStatus]:
        browser = browser.lower().strip()
        if browser not in {"chrome", "edge"}:
            raise BrowserAuthError(
                "Chỉ hỗ trợ Google Chrome hoặc Microsoft Edge.",
                code="invalid_browser",
            )

        target = self.cookie_file
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp.txt")
        try:
            temp.unlink(missing_ok=True)
        except OSError as exc:
            raise BrowserAuthError(f"Không thể chuẩn bị tệp phiên tạm: {exc}", code="cookie_write") from exc

        command = [
            str(self.engine.ytdlp),
            "--ignore-config",
            "--cookies-from-browser",
            browser,
            "--cookies",
            str(temp),
            "--skip-download",
            "--no-warnings",
            "https://www.youtube.com/",
        ]
        try:
            result = self.engine._run_capture(command, timeout=180)
        except FileNotFoundError as exc:
            raise BrowserAuthError("Không tìm thấy yt-dlp trong gói ứng dụng.", code="engine_missing") from exc
        except subprocess.TimeoutExpired as exc:
            raise BrowserAuthError("Quá thời gian đọc đăng nhập từ trình duyệt.", code="timeout") from exc

        detail = (result.stderr or result.stdout or "").strip()
        lowered = detail.lower()
        if not temp.is_file():
            if "could not copy" in lowered or "database is locked" in lowered:
                raise BrowserAuthError(
                    "Trình duyệt vẫn chạy nền và đang khóa dữ liệu đăng nhập.",
                    code="browser_locked",
                )
            if "decrypt" in lowered or "dpapi" in lowered:
                raise BrowserAuthError(
                    "Windows không giải mã được phiên của trình duyệt này. "
                    "Hãy thử Microsoft Edge hoặc cập nhật yt-dlp.",
                    code="decrypt_failed",
                )
            raise BrowserAuthError(
                "Không đọc được phiên đăng nhập. Hãy đăng nhập trên trình duyệt rồi thử lại.",
                code="not_logged_in",
            )

        imported = self.statuses(temp)
        if not any(status.code == "logged_in" for status in imported.values()):
            temp.unlink(missing_ok=True)
            raise BrowserAuthError(
                "Không tìm thấy tài khoản đã đăng nhập trên trình duyệt đã chọn.",
                code="not_logged_in",
            )
        try:
            temp.replace(target)
        except OSError as exc:
            raise BrowserAuthError(f"Không thể lưu phiên đăng nhập: {exc}", code="cookie_write") from exc
        return self.statuses(target)

    def clear_platform(self, platform: str) -> BrowserAuthStatus:
        spec = PLATFORM_AUTH_SPECS[platform]
        target = self.cookie_file
        if not target.is_file():
            return self.status(platform, target)
        try:
            kept: list[str] = []
            for raw_line in target.read_text(encoding="utf-8", errors="replace").splitlines():
                parse_line = raw_line
                if parse_line.startswith("#HttpOnly_"):
                    parse_line = parse_line[len("#HttpOnly_") :]
                fields = parse_line.split("\t")
                if len(fields) >= 7 and self._domain_matches(fields[0], spec):
                    continue
                kept.append(raw_line)
            temp = target.with_suffix(".clear.tmp")
            temp.write_text("\n".join(kept) + "\n", encoding="utf-8")
            temp.replace(target)
        except OSError as exc:
            raise BrowserAuthError(f"Không thể xóa phiên {platform}: {exc}", code="cookie_write") from exc
        return self.status(platform, target)

    @staticmethod
    def close_browser(browser: str) -> None:
        """Close the selected browser only after explicit confirmation in the UI."""
        if os.name != "nt":
            return
        process_name = "msedge.exe" if browser == "edge" else "chrome.exe"
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(
                ["taskkill", "/IM", process_name, "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=creation_flags,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BrowserAuthError(f"Không thể đóng {process_name}: {exc}", code="close_failed") from exc

    @staticmethod
    def open_login(platform: str, browser: str) -> None:
        spec = PLATFORM_AUTH_SPECS[platform]
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
            subprocess.Popen([str(executable), "--disable-background-mode", spec.login_url])
        else:
            webbrowser.open(spec.login_url)


# Compatibility aliases for older integrations that imported the Douyin names.
DouyinAuthError = BrowserAuthError
DouyinAuthStatus = BrowserAuthStatus
