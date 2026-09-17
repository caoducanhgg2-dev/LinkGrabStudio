from pathlib import Path

from app.downloader import DownloaderEngine
from app.models import DownloadOptions


def test_mp4_command_has_quality_and_safe_output(tmp_path: Path) -> None:
    engine = DownloaderEngine()
    engine.ytdlp = Path("yt-dlp.exe")
    engine.ffmpeg = Path("missing-ffmpeg.exe")
    engine.deno = Path("missing-deno.exe")
    options = DownloadOptions(output_dir=tmp_path, quality="1080p", media_format="MP4")
    command = engine.build_download_command("https://youtu.be/abc", options)
    joined = " ".join(map(str, command))
    assert "height<=1080" in joined
    assert "--merge-output-format mp4" in joined
    assert "--no-playlist" in command
    assert command[-1] == "https://youtu.be/abc"


def test_mp3_command(tmp_path: Path) -> None:
    engine = DownloaderEngine()
    engine.ytdlp = Path("yt-dlp.exe")
    engine.ffmpeg = Path("missing-ffmpeg.exe")
    engine.deno = Path("missing-deno.exe")
    options = DownloadOptions(output_dir=tmp_path, media_format="MP3")
    command = engine.build_download_command("https://example.test/video", options)
    assert "--extract-audio" in command
    assert command[command.index("--audio-format") + 1] == "mp3"

