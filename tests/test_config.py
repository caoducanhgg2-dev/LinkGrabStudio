from pathlib import Path

from app.config import AppSettings


def test_platform_cookie_selection_uses_specific_then_fallback(tmp_path: Path) -> None:
    fallback = tmp_path / "all.txt"
    youtube = tmp_path / "youtube.txt"
    tiktok = tmp_path / "tiktok.txt"
    douyin = tmp_path / "douyin.txt"
    facebook = tmp_path / "facebook.txt"
    instagram = tmp_path / "instagram.txt"
    settings = AppSettings(
        cookies_file=str(fallback),
        youtube_cookies_file=str(youtube),
        tiktok_cookies_file=str(tiktok),
        douyin_cookies_file=str(douyin),
        facebook_cookies_file=str(facebook),
        instagram_cookies_file=str(instagram),
    )
    assert settings.cookies_for_platform("YouTube") == youtube
    assert settings.cookies_for_platform("TikTok") == tiktok
    assert settings.cookies_for_platform("Douyin") == douyin
    assert settings.cookies_for_platform("Facebook") == facebook
    assert settings.cookies_for_platform("Instagram") == instagram


def test_platform_cookie_selection_is_backward_compatible(tmp_path: Path) -> None:
    old_cookie = tmp_path / "cookies.txt"
    settings = AppSettings(cookies_file=str(old_cookie))
    assert settings.cookies_for_platform("Douyin") == old_cookie
    assert settings.cookies_for_platform("Facebook") == old_cookie


def test_browser_login_routes_all_platforms_to_managed_file(tmp_path: Path) -> None:
    managed = tmp_path / "browser_login_cookies.txt"
    settings = AppSettings()

    settings.use_browser_login(managed, "edge")

    for platform in ("YouTube", "TikTok", "Douyin", "Facebook", "Instagram"):
        assert settings.cookies_for_platform(platform) == managed
    assert settings.login_browser == "edge"
