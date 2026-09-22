import subprocess
import time
from pathlib import Path

import pytest

from app import auth
from app.auth import DouyinAuthError, DouyinAuthManager


def cookie_line(name: str, value: str, expires: int) -> str:
    return f".douyin.com\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}\n"


class FakeEngine:
    ytdlp = Path("yt-dlp.exe")

    def __init__(self, cookie_text: str) -> None:
        self.cookie_text = cookie_text
        self.commands: list[list[str]] = []

    def _discover_douyin_urls(self, query: str, limit: int) -> list[str]:
        assert query == "热门"
        assert limit == 1
        return ["https://www.douyin.com/video/729001"]

    def _run_capture(self, command: list[str], timeout: int):
        self.commands.append(command)
        cookie_path = Path(command[command.index("--cookies") + 1])
        cookie_path.write_text(
            "# Netscape HTTP Cookie File\n" + self.cookie_text,
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")


def test_status_reports_logged_in_and_expired(tmp_path: Path) -> None:
    manager = DouyinAuthManager(FakeEngine(""))
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        cookie_line("sessionid", "active", int(time.time()) + 3600),
        encoding="utf-8",
    )
    assert manager.status(cookie_file).code == "logged_in"

    cookie_file.write_text(
        cookie_line("sessionid", "expired", int(time.time()) - 3600),
        encoding="utf-8",
    )
    status = manager.status(cookie_file)
    assert status.code == "expired"
    assert "Cookies hết hạn" in status.message


def test_refresh_imports_chrome_login_and_keeps_managed_file(
    monkeypatch, tmp_path: Path
) -> None:
    engine = FakeEngine(cookie_line("sessionid_ss", "active", int(time.time()) + 3600))
    manager = DouyinAuthManager(engine)
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)

    status = manager.refresh("chrome")

    assert status.code == "logged_in"
    assert status.cookie_file == tmp_path / "douyin_browser_cookies.txt"
    assert status.cookie_file.is_file()
    assert "--cookies-from-browser" in engine.commands[0]
    assert engine.commands[0][engine.commands[0].index("--cookies-from-browser") + 1] == "chrome"


def test_refresh_rejects_browser_without_login(monkeypatch, tmp_path: Path) -> None:
    engine = FakeEngine(cookie_line("ttwid", "anonymous", int(time.time()) + 3600))
    manager = DouyinAuthManager(engine)
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)

    with pytest.raises(DouyinAuthError, match="đăng nhập Douyin"):
        manager.refresh("edge")
    assert not (tmp_path / "douyin_browser_cookies.txt").exists()


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

    manager = DouyinAuthManager(LockedEngine(""))
    monkeypatch.setattr(auth, "app_data_dir", lambda: tmp_path)

    with pytest.raises(DouyinAuthError) as captured:
        manager.refresh("chrome")
    assert captured.value.code == "browser_locked"
    assert "chạy nền" in str(captured.value)
