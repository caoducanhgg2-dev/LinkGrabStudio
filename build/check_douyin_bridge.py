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
    source = DownloaderEngine._douyin_bidi_script(
        9222,
        "https://www.douyin.com/search/test?type=video",
        r"C:\Temp\browser_login_cookies.txt",
    )
    path = Path(tempfile.gettempdir()) / "linkgrab_douyin_bidi_check.js"
    path.write_text(source, encoding="utf-8")
    try:
        subprocess.run([str(deno), "check", str(path)], check=True)
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
