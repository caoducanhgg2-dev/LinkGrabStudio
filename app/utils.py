from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SUPPORTED_HOSTS = {
    "youtube.com": "YouTube",
    "www.youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "www.tiktok.com": "TikTok",
    "vm.tiktok.com": "TikTok",
    "vt.tiktok.com": "TikTok",
    "douyin.com": "Douyin",
    "www.douyin.com": "Douyin",
    "v.douyin.com": "Douyin",
    "facebook.com": "Facebook",
    "www.facebook.com": "Facebook",
    "m.facebook.com": "Facebook",
    "mbasic.facebook.com": "Facebook",
    "web.facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "instagram.com": "Instagram",
    "www.instagram.com": "Instagram",
    "m.instagram.com": "Instagram",
    "instagr.am": "Instagram",
}

KEYWORD_SEARCH_PLATFORMS = {"YouTube", "Douyin"}


def supports_keyword_search(platform: str) -> bool:
    return platform in KEYWORD_SEARCH_PLATFORMS


def extract_urls(text: str) -> list[str]:
    candidates = re.findall(r"https?://[^\s<>\"']+", text or "", flags=re.IGNORECASE)
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        cleaned = candidate.rstrip(".,;:!?)]}")
        normalized = normalize_url(cleaned)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    host = parts.netloc.lower().split(":", 1)[0]
    query = parse_qsl(parts.query, keep_blank_values=True)
    if "youtube.com" in host or host == "youtu.be":
        keep = {"v", "list", "index", "t"}
        query = [(k, v) for k, v in query if k in keep]
    elif "facebook.com" in host:
        keep = {"v", "story_fbid", "id"}
        query = [(k, v) for k, v in query if k in keep]
    elif (
        "tiktok.com" in host
        or "douyin.com" in host
        or "instagram.com" in host
        or host in {"fb.watch", "instagr.am"}
    ):
        query = []
    return urlunsplit(("https", parts.netloc, parts.path.rstrip("/"), urlencode(query), ""))


def detect_platform(url: str) -> str:
    try:
        host = urlsplit(url).netloc.lower().split(":", 1)[0]
    except ValueError:
        return "Không xác định"
    if host in SUPPORTED_HOSTS:
        return SUPPORTED_HOSTS[host]
    if host.endswith(".youtube.com"):
        return "YouTube"
    if host.endswith(".tiktok.com"):
        return "TikTok"
    if host.endswith(".douyin.com"):
        return "Douyin"
    if host.endswith(".facebook.com"):
        return "Facebook"
    if host.endswith(".instagram.com"):
        return "Instagram"
    return "Trang khác"


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
