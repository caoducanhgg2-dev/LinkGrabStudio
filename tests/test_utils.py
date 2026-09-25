from app.utils import (
    detect_platform,
    extract_urls,
    format_duration,
    normalize_url,
    supports_keyword_search,
)


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
    assert detect_platform("https://fb.watch/abc123/") == "Facebook"
    assert detect_platform("https://m.facebook.com/reel/123") == "Facebook"
    assert detect_platform("https://www.instagram.com/reel/ABC123/") == "Instagram"
    assert detect_platform("https://instagr.am/p/ABC123/") == "Instagram"


def test_normalize_social_urls_removes_tracking_but_keeps_video_id() -> None:
    assert normalize_url(
        "https://www.facebook.com/watch/?v=12345&mibextid=tracking"
    ) == "https://www.facebook.com/watch?v=12345"
    assert normalize_url(
        "https://www.instagram.com/reel/ABC123/?igsh=tracking"
    ) == "https://www.instagram.com/reel/ABC123"


def test_format_duration() -> None:
    assert format_duration(65) == "01:05"
    assert format_duration(3661) == "01:01:01"
    assert format_duration(None) == "—"


def test_keyword_search_platform_support_is_explicit() -> None:
    assert supports_keyword_search("YouTube")
    assert supports_keyword_search("Douyin")
    assert not supports_keyword_search("TikTok")
    assert not supports_keyword_search("Facebook")
    assert not supports_keyword_search("Instagram")
