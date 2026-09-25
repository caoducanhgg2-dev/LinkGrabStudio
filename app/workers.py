from __future__ import annotations

from collections import deque
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .database import HistoryDatabase
from .auth import BrowserAuthError
from .downloader import DownloaderEngine, DownloaderError
from .models import DownloadJob, DownloadOptions, DownloadStatus, PreviewOptions, VideoInfo
from .updater import EngineUpdater
from .utils import detect_platform


class BrowserAuthSignals(QObject):
    finished = Signal(object)
    error = Signal(object)


class BrowserAuthWorker(QRunnable):
    def __init__(self, manager, browser: str) -> None:
        super().__init__()
        self.manager = manager
        self.browser = browser
        self.signals = BrowserAuthSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.manager.refresh(self.browser))
        except BrowserAuthError as exc:
            self.signals.error.emit(exc)
        except Exception as exc:
            self.signals.error.emit(
                BrowserAuthError(
                    f"Không thể đọc đăng nhập trình duyệt: {exc}",
                    code="unexpected",
                )
            )


class PreviewSignals(QObject):
    item = Signal(object)
    error = Signal(str, str)
    finished = Signal()


class PreviewWorker(QRunnable):
    def __init__(self, engine: DownloaderEngine, urls: list[str], options: PreviewOptions, cookie_files) -> None:
        super().__init__()
        self.engine = engine
        self.urls = urls
        self.options = options
        self.cookie_files = cookie_files
        self.signals = PreviewSignals()

    def _cookies_for(self, url: str):
        platform = self.options.search_platform if self.options.keyword_search else detect_platform(url)
        return self.cookie_files.get(platform) or self.cookie_files.get("default")

    @Slot()
    def run(self) -> None:
        for url in self.urls:
            try:
                cookies_file = self._cookies_for(url)
                if self.options.keyword_search:
                    videos = self.engine.preview_search(
                        [url], self.options, cookies_file=cookies_file
                    )
                elif self.options.channel:
                    videos = self.engine.preview_channel([url], self.options, cookies_file=cookies_file)
                else:
                    videos = self.engine.preview(
                        [url], playlist=self.options.playlist, cookies_file=cookies_file
                    )
                for video in videos:
                    self.signals.item.emit(video)
            except DownloaderError as exc:
                self.signals.error.emit(url, str(exc))
            except Exception as exc:  # keep one failed link from stopping the batch
                self.signals.error.emit(url, f"Lỗi không mong đợi: {exc}")
        self.signals.finished.emit()


class DownloadSignals(QObject):
    started = Signal(object)
    progress = Signal(str, float, str, str)
    log = Signal(str, str)
    finished = Signal(object)


class DownloadWorker(QRunnable):
    def __init__(self, engine: DownloaderEngine, database: HistoryDatabase, job: DownloadJob) -> None:
        super().__init__()
        self.engine = engine
        self.database = database
        self.job = job
        self.signals = DownloadSignals()

    @Slot()
    def run(self) -> None:
        self.job.status = DownloadStatus.PREPARING
        self.signals.started.emit(self.job)
        try:
            result = self.engine.download(
                self.job,
                on_progress=lambda p, s, e: self.signals.progress.emit(self.job.job_id, p, s, e),
                on_log=lambda line: self.signals.log.emit(self.job.job_id, line),
            )
        except DownloaderError as exc:
            self.job.status = DownloadStatus.FAILED
            self.job.error = str(exc)
            result = self.job
        except Exception as exc:
            self.job.status = DownloadStatus.FAILED
            self.job.error = f"Lỗi không mong đợi: {exc}"
            result = self.job
        self.database.record_job(result)
        self.signals.finished.emit(result)


class QueueController(QObject):
    job_added = Signal(object)
    job_started = Signal(object)
    job_progress = Signal(str, float, str, str)
    job_log = Signal(str, str)
    job_finished = Signal(object)
    queue_counts = Signal(int, int, int, int)

    def __init__(self, engine: DownloaderEngine, database: HistoryDatabase, concurrency: int = 2) -> None:
        super().__init__()
        self.engine = engine
        self.database = database
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, min(4, concurrency)))
        self.pending: deque[DownloadJob] = deque()
        self.jobs: dict[str, DownloadJob] = {}
        self.running: set[str] = set()
        self.done = 0
        self.failed = 0

    def set_concurrency(self, value: int) -> None:
        self.pool.setMaxThreadCount(max(1, min(4, value)))
        self._pump()

    def add_videos(
        self,
        videos: list[VideoInfo],
        options: DownloadOptions,
        *,
        skip_duplicates: bool = True,
    ) -> tuple[int, list[VideoInfo]]:
        completed_keys = self.database.completed_keys(videos) if skip_duplicates else set()
        active_keys = {job.video.unique_key for job in self.jobs.values() if job.status not in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}}
        added = 0
        duplicates: list[VideoInfo] = []
        for video in videos:
            if video.unique_key in completed_keys or video.unique_key in active_keys:
                duplicates.append(video)
                continue
            job = DownloadJob(job_id=uuid4().hex, video=video, options=options)
            self.jobs[job.job_id] = job
            self.pending.append(job)
            active_keys.add(video.unique_key)
            added += 1
            self.job_added.emit(job)
        self._emit_counts()
        self._pump()
        return added, duplicates

    def cancel_all(self) -> None:
        self.engine.cancel_all()
        while self.pending:
            job = self.pending.popleft()
            job.status = DownloadStatus.CANCELLED
            self.database.record_job(job)
            self.job_finished.emit(job)
        self._emit_counts()

    def _pump(self) -> None:
        while self.pending and len(self.running) < self.pool.maxThreadCount():
            job = self.pending.popleft()
            self.running.add(job.job_id)
            worker = DownloadWorker(self.engine, self.database, job)
            worker.signals.started.connect(self.job_started)
            worker.signals.progress.connect(self.job_progress)
            worker.signals.log.connect(self.job_log)
            worker.signals.finished.connect(self._on_finished)
            self.pool.start(worker)
        self._emit_counts()

    @Slot(object)
    def _on_finished(self, job: DownloadJob) -> None:
        self.running.discard(job.job_id)
        if job.status == DownloadStatus.COMPLETED:
            self.done += 1
        elif job.status == DownloadStatus.FAILED:
            self.failed += 1
        self.job_finished.emit(job)
        self._emit_counts()
        self._pump()

    def _emit_counts(self) -> None:
        self.queue_counts.emit(len(self.running), len(self.pending), self.done, self.failed)


class UpdateSignals(QObject):
    status = Signal(str)
    finished = Signal(str)
    error = Signal(str)


class EngineUpdateWorker(QRunnable):
    def __init__(self, updater: EngineUpdater) -> None:
        super().__init__()
        self.updater = updater
        self.signals = UpdateSignals()

    @Slot()
    def run(self) -> None:
        try:
            version = self.updater.update(on_status=self.signals.status.emit)
            self.signals.finished.emit(version)
        except Exception as exc:
            self.signals.error.emit(str(exc))
