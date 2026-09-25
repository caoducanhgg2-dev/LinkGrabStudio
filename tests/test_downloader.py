import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.downloader import DownloaderEngine
from app.models import DownloadJob, DownloadOptions, PreviewOptions, VideoInfo


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


def test_douyin_keyword_search_uses_indexed_direct_video_urls(monkeypatch) -> None:
    engine = DownloaderEngine()
    monkeypatch.setattr(engine, "translate_keyword", lambda query, language: "吃播")
    monkeypatch.setattr(
        engine,
        "_search_douyin_authenticated",
        lambda query, limit, cookies_file=None: ([], []),
    )
    monkeypatch.setattr(
        engine,
        "_discover_douyin_urls",
        lambda query, limit: ["https://www.douyin.com/video/729001"],
    )
    monkeypatch.setattr(
        engine,
        "_preview_douyin_urls",
        lambda urls, cookies_file=None: [
            VideoInfo(
                url=urls[0],
                video_id="729001",
                title="吃播",
                platform="Douyin",
                webpage_url=urls[0],
                extractor="Douyin",
                view_count=9000,
            )
        ],
    )
    videos = engine.preview_search(
        ["mukbang"],
        PreviewOptions(
            keyword_search=True,
            search_platform="Douyin",
            search_language="zh-cn",
            search_limit=10,
            search_scan_limit=50,
            since_days=0,
            sort_by="views",
        ),
    )
    assert videos[0].platform == "Douyin"
    assert videos[0].webpage_url == "https://www.douyin.com/video/729001"
    assert videos[0].unique_key == "douyin:729001"
    assert videos[0].raw["search_query_original"] == "mukbang"
    assert videos[0].raw["search_query_translated"] == "吃播"


def test_douyin_authenticated_search_reads_hydration_and_sends_cookies(
    monkeypatch, tmp_path: Path
) -> None:
    engine = DownloaderEngine()
    cookie_file = tmp_path / "browser_login_cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\tsecret-session\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tdo-not-send\n",
        encoding="utf-8",
    )
    bodies = [
        '<script>window._SSR_DATA={"aweme_id":"7390012345678901234",'
        '"url":"https:\\/\\/www.douyin.com\\/video\\/7390098765432101234"}</script>',
        "{}",
    ]
    requests = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body.encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse(bodies.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    urls = engine._search_douyin_urls_authenticated(
        "吃播", 20, cookies_file=cookie_file
    )
    assert urls == [
        "https://www.douyin.com/video/7390098765432101234",
        "https://www.douyin.com/video/7390012345678901234",
    ]
    assert "sessionid=secret-session" in requests[0].headers["Cookie"]
    assert "do-not-send" not in requests[0].headers["Cookie"]
    assert "%E5%90%83%E6%92%AD" in requests[0].full_url


def test_douyin_keyword_search_prefers_authenticated_results(monkeypatch) -> None:
    engine = DownloaderEngine()
    monkeypatch.setattr(engine, "translate_keyword", lambda query, language: "吃播")
    monkeypatch.setattr(
        engine,
        "_search_douyin_authenticated",
        lambda query, limit, cookies_file=None: (
            [
                VideoInfo(
                    url="https://www.douyin.com/video/7390012345678901234",
                    video_id="7390012345678901234",
                    title="吃播",
                    platform="Douyin",
                    webpage_url="https://www.douyin.com/video/7390012345678901234",
                    extractor="DouyinSearch",
                    raw={"direct_url": "https://video.example.test/play.mp4"},
                )
            ],
            ["https://www.douyin.com/video/7390012345678901234"],
        ),
    )

    def fail_public_index(query, limit):
        raise AssertionError("Public search fallback must not run")

    monkeypatch.setattr(engine, "_discover_douyin_urls", fail_public_index)
    monkeypatch.setattr(
        engine,
        "_preview_douyin_urls",
        lambda urls, cookies_file=None: [
            VideoInfo(
                url=urls[0],
                video_id="7390012345678901234",
                title="吃播",
                platform="Douyin",
                webpage_url=urls[0],
                extractor="Douyin",
            )
        ],
    )
    videos = engine.preview_search(
        ["mukbang"],
        PreviewOptions(
            keyword_search=True,
            search_platform="Douyin",
            search_language="zh-cn",
            search_limit=10,
            search_scan_limit=50,
            since_days=0,
            sort_by="views",
        ),
    )
    assert [video.video_id for video in videos] == ["7390012345678901234"]


def test_douyin_search_json_provides_metadata_and_direct_media() -> None:
    engine = DownloaderEngine()
    payload = {
        "data": [
            {
                "aweme_info": {
                    "aweme_id": "7390012345678901234",
                    "desc": "Thử thách ăn ớt",
                    "create_time": 1720000000,
                    "author": {"nickname": "Food Creator"},
                    "statistics": {"play_count": 987654},
                    "video": {
                        "duration": 61234,
                        "play_addr": {
                            "url_list": ["http://video.example.test/douyin-play"]
                        },
                        "cover": {
                            "url_list": ["https://image.example.test/cover.jpeg"]
                        },
                    },
                }
            }
        ]
    }
    videos = engine._extract_douyin_search_videos(json.dumps(payload))
    assert len(videos) == 1
    assert videos[0].title == "Thử thách ăn ớt"
    assert videos[0].uploader == "Food Creator"
    assert videos[0].duration == 61
    assert videos[0].view_count == 987654
    assert videos[0].webpage_url == "https://www.douyin.com/video/7390012345678901234"
    assert videos[0].raw["direct_url"] == "https://video.example.test/douyin-play"


def test_douyin_direct_media_download_keeps_title_and_source(monkeypatch, tmp_path: Path) -> None:
    engine = DownloaderEngine()
    video = VideoInfo(
        url="https://www.douyin.com/video/7390012345678901234",
        video_id="7390012345678901234",
        title='Ăn ớt: thử thách? lớn*',
        platform="Douyin",
        webpage_url="https://www.douyin.com/video/7390012345678901234",
        extractor="DouyinSearch",
        raw={"direct_url": "https://video.example.test/douyin-play"},
    )
    job = DownloadJob(
        job_id="douyin-direct",
        video=video,
        options=DownloadOptions(output_dir=tmp_path),
    )
    captured = {}

    class FakeProcess:
        stdout = iter(["__LINKGRAB_FILE__result.mp4\n"])

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    result = engine.download(job)
    command = captured["command"]
    assert command[-1] == "https://video.example.test/douyin-play"
    assert "Referer:https://www.douyin.com/" in command
    output = command[command.index("--output") + 1]
    assert "Ăn ớt_ thử thách_ lớn_ [7390012345678901234]" in output
    assert result.output_path == "result.mp4"


def test_douyin_discovery_reads_bing_rss_and_normalizes_urls(monkeypatch) -> None:
    engine = DownloaderEngine()
    rss = """<?xml version="1.0"?><rss><channel>
    <item><link>https://www.douyin.com/video/729001?previous_page=search</link></item>
    <item><link>https://www.douyin.com/video/729002</link></item>
    </channel></rss>"""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return rss.encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    urls = engine._discover_douyin_urls("吃播", 2)
    assert urls == [
        "https://www.douyin.com/video/729001",
        "https://www.douyin.com/video/729002",
    ]


def test_douyin_direct_metadata_uses_dump_json(monkeypatch) -> None:
    engine = DownloaderEngine()
    payload = {
        "id": "729001",
        "title": "吃播",
        "webpage_url": "https://www.douyin.com/video/729001",
        "extractor_key": "Douyin",
        "view_count": 9000,
    }
    commands: list[list[str]] = []

    def fake_run(command, timeout):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) + "\n", "")

    monkeypatch.setattr(engine, "_run_capture", fake_run)
    videos = engine._preview_douyin_urls(["https://www.douyin.com/video/729001"])
    assert "--dump-json" in commands[0]
    assert "https://www.douyin.com/search/" not in " ".join(commands[0])
    assert videos[0].unique_key == "douyin:729001"


def test_force_reload_adds_force_overwrites(tmp_path: Path) -> None:
    engine = DownloaderEngine()
    engine.ytdlp = Path("yt-dlp.exe")
    engine.ffmpeg = Path("missing-ffmpeg.exe")
    engine.deno = Path("missing-deno.exe")
    options = DownloadOptions(
        output_dir=tmp_path,
        media_format="MP4",
        overwrite_existing=True,
    )
    command = engine.build_download_command("https://youtu.be/abc", options)
    assert "--force-overwrites" in command


def test_social_video_metadata_maps_platform_and_duplicate_key() -> None:
    facebook = DownloaderEngine._video_from_json(
        {
            "id": "fb-123",
            "title": "Facebook Reel",
            "webpage_url": "https://www.facebook.com/reel/123",
            "extractor_key": "Facebook",
        },
        fallback_url="https://www.facebook.com/reel/123",
    )
    instagram = DownloaderEngine._video_from_json(
        {
            "id": "ig-456",
            "title": "Instagram Reel",
            "webpage_url": "https://www.instagram.com/reel/ABC456/",
            "extractor_key": "Instagram",
        },
        fallback_url="https://www.instagram.com/reel/ABC456/",
    )
    assert facebook.platform == "Facebook"
    assert facebook.unique_key == "facebook:fb-123"
    assert instagram.platform == "Instagram"
    assert instagram.unique_key == "instagram:ig-456"


def test_social_download_uses_configured_cookies(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    engine = DownloaderEngine()
    engine.ytdlp = Path("yt-dlp.exe")
    engine.ffmpeg = Path("missing-ffmpeg.exe")
    engine.deno = Path("missing-deno.exe")
    options = DownloadOptions(output_dir=tmp_path, cookies_file=cookie_file)
    url = "https://www.instagram.com/reel/ABC456/"
    command = engine.build_download_command(url, options)
    assert command[command.index("--cookies") + 1] == str(cookie_file)
    assert command[-1] == url
