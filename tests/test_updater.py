import hashlib
from pathlib import Path

import pytest

from app.downloader import DownloaderError
from app.updater import EngineUpdater


def test_parse_official_checksum() -> None:
    digest = "a" * 64
    text = f"{digest}  yt-dlp.exe\n{'b' * 64}  yt-dlp"
    assert EngineUpdater._parse_checksum(text, "yt-dlp.exe") == digest


def test_checksum_requires_valid_digest() -> None:
    with pytest.raises(DownloaderError):
        EngineUpdater._parse_checksum("not-a-hash  yt-dlp.exe", "yt-dlp.exe")


def test_sha256(tmp_path: Path) -> None:
    path = tmp_path / "engine.bin"
    path.write_bytes(b"linkgrab")
    assert EngineUpdater._sha256(path) == hashlib.sha256(b"linkgrab").hexdigest()

