from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import app_data_dir
from .models import DownloadJob, DownloadStatus, VideoInfo


class HistoryDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "history.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    unique_key TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    output_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_downloads_unique_key
                    ON downloads(unique_key);
                CREATE INDEX IF NOT EXISTS idx_downloads_created_at
                    ON downloads(created_at DESC);
                """
            )

    def has_completed(self, unique_key: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM downloads WHERE unique_key=? AND status=? LIMIT 1",
                (unique_key, DownloadStatus.COMPLETED.value),
            ).fetchone()
            return row is not None

    def completed_record(self, unique_key: str) -> dict[str, str] | None:
        """Return the newest completed record used for duplicate notices."""
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT title, source_url, output_path, completed_at, created_at
                FROM downloads
                WHERE unique_key=? AND status=?
                ORDER BY id DESC LIMIT 1
                """,
                (unique_key, DownloadStatus.COMPLETED.value),
            ).fetchone()
        return dict(row) if row is not None else None

    def record_job(self, job: DownloadJob) -> None:
        now = datetime.now(timezone.utc).isoformat()
        completed = now if job.status == DownloadStatus.COMPLETED else None
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO downloads (
                    unique_key, video_id, platform, title, source_url,
                    output_path, status, error, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.video.unique_key,
                    job.video.video_id,
                    job.video.platform,
                    job.video.title,
                    job.video.webpage_url or job.video.url,
                    job.output_path,
                    job.status.value,
                    job.error,
                    now,
                    completed,
                ),
            )

    def recent(self, limit: int = 250) -> list[dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT platform, title, source_url, output_path, status,
                       error, created_at, completed_at
                FROM downloads ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def completed_keys(self, videos: Iterable[VideoInfo]) -> set[str]:
        keys = {video.unique_key for video in videos}
        if not keys:
            return set()
        placeholders = ",".join("?" for _ in keys)
        params = [*keys, DownloadStatus.COMPLETED.value]
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT unique_key FROM downloads WHERE unique_key IN ({placeholders}) AND status=?",
                params,
            ).fetchall()
        return {str(row[0]) for row in rows}
