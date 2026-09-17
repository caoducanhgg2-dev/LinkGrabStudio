from app.utils import detect_platform, extract_urls, format_duration, normalize_url


def test_extract_urls_deduplicates_and_removes_tracking() -> None:
    text = """
    https://www.youtube.com/watch?v=abc123&utm_source=test
    https://www.youtube.com/watch?v=abc123&utm_source=other
    https://vm.tiktok.com/XYZ/?share_app_id=1
    """
    assert extract_urls(text) == [
        "https://www.youtube.com/watch?v=abc123",
        "https://vm.tiktok.com/XYZ",
    ]


def test_normalize_rejects_non_http() -> None:
    assert normalize_url("not-a-link") == ""
    assert normalize_url("file:///secret") == ""


def test_detect_platform() -> None:
    assert detect_platform("https://youtu.be/abc") == "YouTube"
    assert detect_platform("https://www.tiktok.com/@a/video/1") == "TikTok"
    assert detect_platform("https://v.douyin.com/a") == "Douyin"


def test_format_duration() -> None:
    assert format_duration(65) == "01:05"
    assert format_duration(3661) == "01:01:01"
    assert format_duration(None) == "—"

