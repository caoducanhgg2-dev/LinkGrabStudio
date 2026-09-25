import subprocess
import time
from pathlib import Path

import pytest

from app import auth
from app.auth import BrowserAuthError, BrowserAuthManager


def cookie_line(domain: str, name: str, value: str, expires: int) -> str:
    return f".{domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}\n"


class FakeEngine:
    ytdlp = Path("yt-dlp.exe")

    def __init__(self, cookie_text: str) -> None:
        self.cookie_text = cookie_text
        self.commands: list[list[str]] = []

    def _run_capture(self, command: list[str], timeout: int):
        self.commands.append(command)
        cookie_path = Path(command[command.index("--cookies") + 1])
        cookie_path.write_text(
            "# Netscape HTTP Cookie File\n" + self.cookie_text,
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")


def test_status_reports_each_supported_platform(tmp_path: Path) -> None:
    expires = int(time.time()) + 3600
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        cookie_line("youtube.com", "SAPISID", "youtube", expires)
        + cookie_line("tiktok.com", "sessionid", "tiktok", expires)
        + cookie_line("douyin.com", "sessionid_ss", "douyin", expires)
        + cookie_line("facebook.com", "c_user", "facebook", expires)
        + cookie_line("instagram.com", "sessionid", "instagram", expires),
        encoding="utf-8",
    )
    manager = BrowserAuthManager(FakeEngine(""))

    statuses = manager.statuses(cookie_file)

    assert set(statuses) == {"YouTube", "TikTok", "Douyin", "Facebook", "Instagram"}
    assert all(status.code == "logged_in" for status in statuses.values())


def test_status_reports_expired_cookie(tmp_path: Path) -> None:
    manager = BrowserAuthManager(FakeEngine(""))
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        cookie_line("douyin.com", "sessionid", "expired", int(time.time()) - 3600),
        encoding="utf-8",
    )

    status = manager.status("Douyin", cookie_file)

    assert status.code == "expired"
    assert "hết hạn" in status.message


def test_refresh_imports_browser_sessions_once(monkeypatch, tmp_path: Path) -> None:
    expires = int(time.time()) + 3600
    engine = FakeEngine(
        cookie_line("douyin.com", "sessionid_ss", "active", expires)
        + cookie_line("facebook.com", "c_user", "123", expires)
    )
    manager = BrowserAuthManager(engine)
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)

    statuses = manager.refresh("chrome")

    assert statuses["Douyin"].code == "logged_in"
    assert statuses["Facebook"].code == "logged_in"
    assert manager.cookie_file == tmp_path / "browser_login_cookies.txt"
    assert manager.cookie_file.is_file()
    assert "--cookies-from-browser" in engine.commands[0]
    assert engine.commands[0][engine.commands[0].index("--cookies-from-browser") + 1] == "chrome"


def test_refresh_rejects_browser_without_login(monkeypatch, tmp_path: Path) -> None:
    engine = FakeEngine(cookie_line("douyin.com", "ttwid", "anonymous", int(time.time()) + 3600))
    manager = BrowserAuthManager(engine)
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)

    with pytest.raises(BrowserAuthError, match="Không tìm thấy tài khoản"):
        manager.refresh("edge")
    assert not manager.cookie_file.exists()


def test_refresh_marks_locked_browser_for_ui_retry(monkeypatch, tmp_path: Path) -> None:
    class LockedEngine(FakeEngine):
        def _run_capture(self, command: list[str], timeout: int):
            self.commands.append(command)
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "ERROR: Could not copy Chrome cookie database. Database is locked",
            )

    manager = BrowserAuthManager(LockedEngine(""))
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)

    with pytest.raises(BrowserAuthError) as captured:
        manager.refresh("chrome")
    assert captured.value.code == "browser_locked"
    assert "chạy nền" in str(captured.value)


def test_clear_platform_only_removes_its_cookie_lines(monkeypatch, tmp_path: Path) -> None:
    expires = int(time.time()) + 3600
    manager = BrowserAuthManager(FakeEngine(""))
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)
    manager.cookie_file.write_text(
        cookie_line("facebook.com", "c_user", "123", expires)
        + cookie_line("instagram.com", "sessionid", "abc", expires),
        encoding="utf-8",
    )

    status = manager.clear_platform("Facebook")

    assert status.code == "missing"
    assert manager.status("Instagram").code == "logged_in"
