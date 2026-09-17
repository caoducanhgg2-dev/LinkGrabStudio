from pathlib import Path

from app.database import HistoryDatabase
from app.models import DownloadJob, DownloadOptions, DownloadStatus, VideoInfo


def test_completed_video_is_detected(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path / "history.db")
    video = VideoInfo(
        url="https://youtu.be/abc",
        video_id="abc",
        title="Test",
        platform="YouTube",
        extractor="Youtube",
    )
    job = DownloadJob("job-1", video, DownloadOptions(tmp_path), status=DownloadStatus.COMPLETED)
    database.record_job(job)
    assert database.has_completed(video.unique_key)
    assert video.unique_key in database.completed_keys([video])


def test_failed_video_is_not_duplicate(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path / "history.db")
    video = VideoInfo("https://x.test/a", "a", "A", "Trang khác", extractor="Generic")
    job = DownloadJob("job-2", video, DownloadOptions(tmp_path), status=DownloadStatus.FAILED)
    database.record_job(job)
    assert not database.has_completed(video.unique_key)

