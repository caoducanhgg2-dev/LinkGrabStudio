import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.downloader import DownloaderEngine
from app.models import DownloadOptions, PreviewOptions


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


def test_channel_preview_filters_period_and_sorts_by_views(monkeypatch) -> None:
    engine = DownloaderEngine()
    now = datetime.now(timezone.utc)
    payload = {
        "title": "Test channel",
        "entries": [
            {
                "id": "recent-low",
                "title": "Recent low",
                "webpage_url": "https://youtube.com/watch?v=recent-low",
                "extractor_key": "Youtube",
                "timestamp": int((now - timedelta(days=2)).timestamp()),
                "view_count": 100,
            },
            {
                "id": "recent-high",
                "title": "Recent high",
                "webpage_url": "https://youtube.com/watch?v=recent-high",
                "extractor_key": "Youtube",
                "timestamp": int((now - timedelta(days=4)).timestamp()),
                "view_count": 900,
            },
            {
                "id": "old",
                "title": "Old popular",
                "webpage_url": "https://youtube.com/watch?v=old",
                "extractor_key": "Youtube",
                "timestamp": int((now - timedelta(days=30)).timestamp()),
                "view_count": 999999,
            },
        ],
    }

    def fake_run(command, timeout):
        assert "--flat-playlist" in command
        assert "--extract-flat" not in command
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(engine, "_run_capture", fake_run)
    videos = engine.preview_channel(
        ["https://youtube.com/@test/videos"],
        PreviewOptions(channel=True, channel_limit=10, since_days=7, sort_by="views"),
    )
    assert [video.video_id for video in videos] == ["recent-high", "recent-low"]


def test_channel_preview_limits_results_and_sorts_newest(monkeypatch) -> None:
    engine = DownloaderEngine()
    now = datetime.now(timezone.utc)
    payload = {
        "entries": [
            {
                "id": str(index),
                "title": str(index),
                "webpage_url": f"https://youtube.com/watch?v={index}",
                "extractor_key": "Youtube",
                "timestamp": int((now - timedelta(days=index)).timestamp()),
                "view_count": index * 100,
            }
            for index in range(1, 6)
        ]
    }
    monkeypatch.setattr(
        engine,
        "_run_capture",
        lambda command, timeout: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )
    videos = engine.preview_channel(
        ["https://youtube.com/@test/videos"],
        PreviewOptions(channel=True, channel_limit=2, since_days=365, sort_by="newest"),
    )
    assert [video.video_id for video in videos] == ["1", "2"]


def test_channel_preview_retries_without_flat_option(monkeypatch) -> None:
    engine = DownloaderEngine()
    commands: list[list[str]] = []
    payload = {
        "entries": [
            {
                "id": "fallback",
                "title": "Fallback works",
                "webpage_url": "https://youtube.com/watch?v=fallback",
                "extractor_key": "Youtube",
                "timestamp": int(datetime.now(timezone.utc).timestamp()),
            }
        ]
    }

    def fake_run(command, timeout):
        commands.append(list(command))
        if "--flat-playlist" in command:
            return subprocess.CompletedProcess(command, 2, "", "no such option: --flat-playlist")
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(engine, "_run_capture", fake_run)
    videos = engine.preview_channel(
        ["https://youtube.com/@test/videos"],
        PreviewOptions(channel=True, channel_limit=10, since_days=365, sort_by="newest"),
    )
    assert [video.video_id for video in videos] == ["fallback"]
    assert len(commands) == 2
    assert "--flat-playlist" in commands[0]
    assert "--flat-playlist" not in commands[1]


def test_channel_url_is_normalized_to_videos_tab() -> None:
    assert (
        DownloaderEngine._normalize_channel_url("https://www.youtube.com/@example")
        == "https://www.youtube.com/@example/videos"
    )
    existing = "https://www.youtube.com/@example/shorts"
    assert DownloaderEngine._normalize_channel_url(existing) == existing


def test_keyword_search_uses_ytsearch_and_sorts_best_views(monkeypatch) -> None:
    engine = DownloaderEngine()
    now = datetime.now(timezone.utc)
    payload = {
        "title": "mukbang",
        "entries": [
            {
                "id": "low",
                "title": "Low views",
                "url": "low",
                "extractor_key": "Youtube",
                "timestamp": int((now - timedelta(days=1)).timestamp()),
                "view_count": 100,
            },
            {
                "id": "best",
                "title": "Best views",
                "url": "best",
                "extractor_key": "Youtube",
                "timestamp": int((now - timedelta(days=2)).timestamp()),
                "view_count": 5000,
            },
        ],
    }

    def fake_run(command, timeout):
        assert "--flat-playlist" in command
        assert command[-1] == "ytsearch50:mukbang"
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(engine, "_run_capture", fake_run)
    videos = engine.preview_search(
        ["mukbang"],
        PreviewOptions(
            keyword_search=True,
            search_limit=10,
            search_scan_limit=50,
            since_days=0,
            sort_by="views",
        ),
    )
    assert [video.video_id for video in videos] == ["best", "low"]
    assert videos[0].webpage_url == "https://www.youtube.com/watch?v=best"


def test_keyword_search_filters_time_and_normalizes_duplicate_key(monkeypatch) -> None:
    engine = DownloaderEngine()
    now = datetime.now(timezone.utc)
    payload = {
        "entries": [
            {
                "id": "recent",
                "title": "Recent",
                "url": "recent",
                "extractor_key": "YoutubeSearch",
                "timestamp": int((now - timedelta(days=2)).timestamp()),
            },
            {
                "id": "old",
                "title": "Old",
                "url": "old",
                "extractor_key": "YoutubeSearch",
                "timestamp": int((now - timedelta(days=40)).timestamp()),
            },
        ]
    }
    monkeypatch.setattr(
        engine,
        "_run_capture",
        lambda command, timeout: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )
    videos = engine.preview_search(
        ["mukbang"],
        PreviewOptions(
            keyword_search=True,
            search_limit=20,
            search_scan_limit=100,
            since_days=7,
            sort_by="newest",
        ),
    )
    assert [video.video_id for video in videos] == ["recent"]
    assert videos[0].unique_key == "youtube:recent"
