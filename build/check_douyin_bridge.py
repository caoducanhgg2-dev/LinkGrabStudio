from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.downloader import DownloaderEngine


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    deno = root / "tools" / "deno.exe"
    if not deno.is_file():
        raise SystemExit("Deno is missing; run bootstrap_tools.ps1 first")
    sources = {
        "search": DownloaderEngine._douyin_bidi_script(
            9222,
            "https://www.douyin.com/search/test?type=video",
            r"C:\Temp\browser_login_cookies.txt",
        ),
        "resolver": DownloaderEngine._douyin_resolver_bidi_script(
            9223,
            ["https://www.douyin.com/video/7390012345678901234"],
            r"C:\Temp\browser_login_cookies.txt",
        ),
    }
    for name, source in sources.items():
        path = Path(tempfile.gettempdir()) / f"linkgrab_douyin_{name}_check.js"
        path.write_text(source, encoding="utf-8")
        try:
            subprocess.run([str(deno), "check", str(path)], check=True)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
