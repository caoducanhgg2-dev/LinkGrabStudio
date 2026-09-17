from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from .downloader import DownloaderError


YTDLP_RELEASE_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"


class EngineUpdater:
    def __init__(self, target: Path) -> None:
        self.target = target

    def update(self, on_status: Callable[[str], None] | None = None) -> str:
        if not self.target.is_file():
            raise DownloaderError("Không tìm thấy yt-dlp.exe trong thư mục ứng dụng.")
        self._status(on_status, "Đang lấy mã kiểm tra chính thức…")
        sums = self._download_text(f"{YTDLP_RELEASE_BASE}/SHA2-256SUMS")
        expected = self._parse_checksum(sums, "yt-dlp.exe")

        self._status(on_status, "Đang tải engine mới…")
        with tempfile.TemporaryDirectory(prefix="linkgrab-update-") as temp_dir:
            candidate = Path(temp_dir) / "yt-dlp.exe"
            self._download_file(f"{YTDLP_RELEASE_BASE}/yt-dlp.exe", candidate)
            actual = self._sha256(candidate)
            if actual.lower() != expected.lower():
                raise DownloaderError("SHA256 không khớp. Bản cập nhật đã bị hủy.")

            self._status(on_status, "Đang kiểm tra engine mới…")
            version = self._verify_binary(candidate)
            backup = self.target.with_suffix(".exe.bak")
            staged = self.target.with_suffix(".exe.new")
            shutil.copy2(candidate, staged)
            try:
                if backup.exists():
                    backup.unlink()
                os.replace(self.target, backup)
                os.replace(staged, self.target)
                installed_version = self._verify_binary(self.target)
                if installed_version != version:
                    raise DownloaderError("Engine mới không vượt qua kiểm tra sau khi thay thế.")
            except Exception:
                if self.target.exists():
                    self.target.unlink(missing_ok=True)
                if backup.exists():
                    os.replace(backup, self.target)
                staged.unlink(missing_ok=True)
                raise
            backup.unlink(missing_ok=True)
            self._status(on_status, f"Cập nhật thành công: {version}")
            return version

    @staticmethod
    def _status(callback: Callable[[str], None] | None, message: str) -> None:
        if callback:
            callback(message)

    @staticmethod
    def _request(url: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"User-Agent": "LinkGrabStudio/1.0"})

    @classmethod
    def _download_text(cls, url: str) -> str:
        try:
            with urllib.request.urlopen(cls._request(url), timeout=30) as response:
                return response.read().decode("utf-8", errors="strict")
        except Exception as exc:
            raise DownloaderError(f"Không thể tải thông tin cập nhật: {exc}") from exc

    @classmethod
    def _download_file(cls, url: str, destination: Path) -> None:
        try:
            with urllib.request.urlopen(cls._request(url), timeout=120) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
        except Exception as exc:
            raise DownloaderError(f"Không thể tải engine mới: {exc}") from exc

    @staticmethod
    def _parse_checksum(text: str, filename: str) -> str:
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
                digest = parts[0]
                if len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest):
                    return digest
        raise DownloaderError("Không tìm thấy SHA256 chính thức của yt-dlp.exe.")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _verify_binary(path: Path) -> str:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=creationflags,
                check=False,
            )
        except Exception as exc:
            raise DownloaderError(f"Engine tải xuống không thể khởi động: {exc}") from exc
        version = result.stdout.strip()
        if result.returncode != 0 or not version:
            raise DownloaderError("Engine tải xuống không vượt qua kiểm tra khởi động.")
        return version

