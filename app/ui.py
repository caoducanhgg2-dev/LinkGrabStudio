from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, APP_VERSION, AppSettings, app_data_dir
from .database import HistoryDatabase
from .downloader import DownloaderEngine
from .models import DownloadJob, DownloadOptions, DownloadStatus, PreviewOptions, VideoInfo
from .styles import APP_STYLE
from .updater import EngineUpdater
from .utils import detect_platform, extract_urls, format_duration
from .workers import EngineUpdateWorker, PreviewWorker, QueueController


def open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif os.name == "posix":
        subprocess.Popen(["xdg-open", str(path)])


class DownloadPage(QWidget):
    preview_requested = Signal(list, object, bool)
    queue_requested = Signal(list)
    stop_requested = Signal()

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.videos: list[VideoInfo] = []
        self._auto_queue_after_preview = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("Tải video ngay")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Dán link YouTube hoặc TikTok — app tự nhận diện nền tảng")
        subtitle.setObjectName("muted")
        title_row.addWidget(title)
        title_row.addSpacing(12)
        title_row.addWidget(subtitle)
        title_row.addStretch()
        self.engine_badge = QLabel("Engine: đang kiểm tra…")
        self.engine_badge.setObjectName("countBadge")
        title_row.addWidget(self.engine_badge)
        root.addLayout(title_row)

        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Chọn nền tảng"))
        self.platform_group = QButtonGroup(self)
        self.platform_group.setExclusive(True)
        for index, (label, icon) in enumerate((("YouTube", "▶"), ("TikTok", "♪"), ("Douyin", "◉"))):
            button = QPushButton(f"{icon}  {label}")
            button.setObjectName("platform")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.platform_group.addButton(button)
            platform_row.addWidget(button)
        more = QPushButton("＋ Nền tảng khác (sắp có)")
        more.setObjectName("platform")
        more.setEnabled(False)
        platform_row.addWidget(more)
        platform_row.addStretch()
        root.addLayout(platform_row)

        body = QHBoxLayout()
        body.setSpacing(14)
        form_card = QFrame()
        form_card.setObjectName("card")
        form = QVBoxLayout(form_card)
        form.setContentsMargins(16, 16, 16, 16)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Chế độ"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.link_mode = QPushButton("🔗 Theo link")
        self.playlist_mode = QPushButton("▤ Playlist/Bộ")
        for button in (self.link_mode, self.playlist_mode):
            button.setObjectName("mode")
            button.setCheckable(True)
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        self.link_mode.setChecked(True)
        self.channel_mode = QPushButton("👤 Theo kênh • MỚI")
        self.channel_mode.setObjectName("mode")
        self.channel_mode.setCheckable(True)
        self.mode_group.addButton(self.channel_mode)
        mode_row.addWidget(self.channel_mode)
        mode_row.addStretch()
        form.addLayout(mode_row)

        channel_hint = QLabel(
            "MỚI 1.1: Bấm “Theo kênh” để lọc 1–300 video theo lượt xem, "
            "ngày đăng và tự loại video đã tải."
        )
        channel_hint.setObjectName("countBadge")
        channel_hint.setWordWrap(True)
        form.addWidget(channel_hint)

        self.link_mode.clicked.connect(self._update_mode_ui)
        self.playlist_mode.clicked.connect(self._update_mode_ui)
        self.channel_mode.clicked.connect(self._update_mode_ui)

        self.url_label = QLabel("Link video — mỗi dòng một link")
        form.addWidget(self.url_label)
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "Dán link vào đây. Ví dụ:\n"
            "https://www.youtube.com/watch?v=...\n"
            "https://www.tiktok.com/@user/video/..."
        )
        self.url_input.setMinimumHeight(105)
        self.url_input.textChanged.connect(self._update_link_summary)
        form.addWidget(self.url_input)
        self.link_summary = QLabel("Chưa có link")
        self.link_summary.setObjectName("muted")
        form.addWidget(self.link_summary)

        self.channel_filters = QFrame()
        channel_grid = QGridLayout(self.channel_filters)
        channel_grid.setContentsMargins(0, 6, 0, 6)
        channel_grid.addWidget(QLabel("Số video"), 0, 0)
        channel_grid.addWidget(QLabel("Sắp xếp"), 0, 1)
        channel_grid.addWidget(QLabel("Khoảng thời gian"), 0, 2)
        self.channel_limit = QSpinBox()
        self.channel_limit.setRange(1, 300)
        self.channel_limit.setValue(100)
        self.channel_sort = QComboBox()
        self.channel_sort.addItem("Nhiều lượt xem nhất", "views")
        self.channel_sort.addItem("Mới nhất", "newest")
        self.channel_period = QComboBox()
        for label, days in (
            ("Trong 1 tuần", 7),
            ("Trong 1 tháng", 30),
            ("Trong 3 tháng", 90),
            ("Trong 6 tháng", 180),
            ("Trong 1 năm", 365),
        ):
            self.channel_period.addItem(label, days)
        self.channel_period.setCurrentIndex(4)
        channel_grid.addWidget(self.channel_limit, 1, 0)
        channel_grid.addWidget(self.channel_sort, 1, 1)
        channel_grid.addWidget(self.channel_period, 1, 2)
        self.channel_duplicate_note = QLabel(
            "Video đã tải sẽ được bỏ chọn và hiển thị ngày tải cùng link nguồn."
        )
        self.channel_duplicate_note.setObjectName("muted")
        channel_grid.addWidget(self.channel_duplicate_note, 2, 0, 1, 3)
        self.channel_filters.setVisible(False)
        form.addWidget(self.channel_filters)

        filters = QGridLayout()
        filters.addWidget(QLabel("Chất lượng"), 0, 0)
        filters.addWidget(QLabel("Định dạng"), 0, 1)
        filters.addWidget(QLabel("Thư mục lưu"), 0, 2)
        self.quality = QComboBox()
        self.quality.addItems(["Tốt nhất", "4K", "1440p", "1080p", "720p", "480p"])
        self.quality.setCurrentText(self.settings.quality)
        self.media_format = QComboBox()
        self.media_format.addItems(["MP4", "MKV", "MP3", "M4A"])
        self.media_format.setCurrentText(self.settings.media_format)
        folder_row = QHBoxLayout()
        self.output_dir = QLineEdit(self.settings.output_dir)
        self.browse_button = QPushButton("…")
        self.browse_button.setFixedWidth(42)
        self.browse_button.clicked.connect(self._browse_output)
        folder_row.addWidget(self.output_dir)
        folder_row.addWidget(self.browse_button)
        filters.addWidget(self.quality, 1, 0)
        filters.addWidget(self.media_format, 1, 1)
        filters.addLayout(folder_row, 1, 2)
        form.addLayout(filters)

        extras = QHBoxLayout()
        self.subtitles = QCheckBox("Tải phụ đề")
        self.thumbnail = QCheckBox("Tải thumbnail")
        self.metadata = QCheckBox("Lưu mô tả/metadata")
        extras.addWidget(self.subtitles)
        extras.addWidget(self.thumbnail)
        extras.addWidget(self.metadata)
        extras.addStretch()
        form.addLayout(extras)
        body.addWidget(form_card, 1)

        actions = QFrame()
        actions.setObjectName("card")
        actions.setFixedWidth(285)
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(16, 16, 16, 16)
        self.preview_button = QPushButton("👁  Xem trước && chọn")
        self.preview_button.setObjectName("primary")
        self.preview_button.clicked.connect(lambda: self._request_preview(False))
        self.download_all_button = QPushButton("🚀  Tải tất cả")
        self.download_all_button.clicked.connect(lambda: self._request_preview(True))
        self.queue_button = QPushButton("▤  Thêm mục đã chọn vào hàng đợi")
        self.queue_button.clicked.connect(self._queue_selected)
        self.stop_button = QPushButton("■  Dừng tất cả")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_requested)
        for button in (self.preview_button, self.download_all_button, self.queue_button, self.stop_button):
            action_layout.addWidget(button)
        action_layout.addStretch()
        body.addWidget(actions)
        root.addLayout(body)

        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("Danh sách video"))
        self.preview_count = QLabel("0 video")
        self.preview_count.setObjectName("countBadge")
        preview_header.addWidget(self.preview_count)
        preview_header.addStretch()
        root.addLayout(preview_header)

        self.preview_table = QTableWidget(0, 9)
        self.preview_table.setHorizontalHeaderLabels(
            ["Chọn", "Nền tảng", "Tiêu đề", "Kênh", "Lượt xem", "Ngày đăng", "Thời lượng", "Link", "Trạng thái"]
        )
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.verticalHeader().setVisible(False)
        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        for column in (4, 5, 6, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        root.addWidget(self.preview_table, 1)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(115)
        self.log_box.setPlaceholderText("Nhật ký hoạt động sẽ hiển thị ở đây…")
        root.addWidget(self.log_box)

    def current_urls(self) -> list[str]:
        return extract_urls(self.url_input.toPlainText())

    def current_options(self) -> DownloadOptions:
        cookies = Path(self.settings.cookies_file) if self.settings.cookies_file else None
        return DownloadOptions(
            output_dir=Path(self.output_dir.text().strip()),
            quality=self.quality.currentText(),
            media_format=self.media_format.currentText(),
            playlist=self.playlist_mode.isChecked(),
            subtitles=self.subtitles.isChecked(),
            thumbnail=self.thumbnail.isChecked(),
            metadata=self.metadata.isChecked(),
            cookies_file=cookies,
        )

    def current_preview_options(self) -> PreviewOptions:
        limit = self.channel_limit.value()
        return PreviewOptions(
            playlist=self.playlist_mode.isChecked(),
            channel=self.channel_mode.isChecked(),
            channel_limit=limit,
            channel_scan_limit=max(100, min(500, limit * 5)),
            sort_by=str(self.channel_sort.currentData()),
            since_days=int(self.channel_period.currentData()),
            skip_duplicates=self.settings.skip_duplicates,
        )

    def selected_videos(self) -> list[VideoInfo]:
        selected: list[VideoInfo] = []
        for row, video in enumerate(self.videos):
            item = self.preview_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                selected.append(video)
        return selected

    def clear_preview(self) -> None:
        self.videos.clear()
        self.preview_table.setRowCount(0)
        self.preview_count.setText("0 video")

    def add_preview_video(self, video: VideoInfo, duplicate: dict[str, str] | None = None) -> None:
        row = self.preview_table.rowCount()
        self.preview_table.insertRow(row)
        select_item = QTableWidgetItem()
        select_item.setCheckState(Qt.Unchecked if duplicate else Qt.Checked)
        select_item.setTextAlignment(Qt.AlignCenter)
        self.preview_table.setItem(row, 0, select_item)
        views = f"{video.view_count:,}".replace(",", ".") if video.view_count is not None else "—"
        upload_date = video.upload_date
        if len(upload_date) == 8 and upload_date.isdigit():
            upload_date = f"{upload_date[6:8]}/{upload_date[4:6]}/{upload_date[:4]}"
        elif not upload_date and video.raw.get("timestamp"):
            try:
                upload_date = datetime.fromtimestamp(int(video.raw["timestamp"])).strftime("%d/%m/%Y")
            except (TypeError, ValueError, OSError):
                upload_date = ""
        source_url = video.webpage_url or video.url
        status = "Sẵn sàng"
        if duplicate:
            downloaded_at = (duplicate.get("completed_at") or duplicate.get("created_at") or "")[:10]
            status = f"Đã tải {downloaded_at}" if downloaded_at else "Đã tải trước đó"
            self.append_log(f"Trùng lặp: {video.title} — {duplicate.get('source_url') or source_url}")
        values = [
            video.platform,
            video.title,
            video.uploader or "—",
            views,
            upload_date or "—",
            format_duration(video.duration),
            source_url,
            status,
        ]
        for column, value in enumerate(values, 1):
            self.preview_table.setItem(row, column, QTableWidgetItem(value))
        self.videos.append(video)
        duplicate_count = sum(
            1 for index in range(self.preview_table.rowCount())
            if self.preview_table.item(index, 0).checkState() == Qt.Unchecked
        )
        suffix = f" • {duplicate_count} trùng" if duplicate_count else ""
        self.preview_count.setText(f"{len(self.videos)} video{suffix}")

    def add_preview_error(self, url: str, error: str) -> None:
        self.append_log(f"Không thể đọc {url}: {error}")

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {message}")

    def preview_finished(self) -> None:
        self.set_busy(False)
        self.append_log(f"Đã đọc xong {len(self.videos)} video.")
        if self._auto_queue_after_preview:
            self._auto_queue_after_preview = False
            self._queue_selected()

    def set_busy(self, busy: bool) -> None:
        self.preview_button.setEnabled(not busy)
        self.download_all_button.setEnabled(not busy)
        self.preview_button.setText("⏳  Đang đọc thông tin…" if busy else "👁  Xem trước && chọn")

    def _request_preview(self, auto_queue: bool) -> None:
        urls = self.current_urls()
        if not urls:
            QMessageBox.warning(self, APP_NAME, "Hãy dán ít nhất một link hợp lệ.")
            return
        self.clear_preview()
        self._auto_queue_after_preview = auto_queue
        self.set_busy(True)
        self.append_log(f"Đang kiểm tra {len(urls)} link…")
        self.preview_requested.emit(urls, self.current_preview_options(), auto_queue)

    def _queue_selected(self) -> None:
        selected = self.selected_videos()
        if not selected:
            QMessageBox.information(self, APP_NAME, "Chưa có video nào được chọn.")
            return
        self.queue_requested.emit(selected)

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self.output_dir.text())
        if folder:
            self.output_dir.setText(folder)

    def _update_link_summary(self) -> None:
        urls = self.current_urls()
        counts: dict[str, int] = {}
        for url in urls:
            platform = detect_platform(url)
            counts[platform] = counts.get(platform, 0) + 1
        if not urls:
            self.link_summary.setText("Chưa có link")
            return
        detail = " • ".join(f"{name}: {count}" for name, count in counts.items())
        self.link_summary.setText(f"Đã nhận diện {len(urls)} link • {detail}")

    def _update_mode_ui(self) -> None:
        is_channel = self.channel_mode.isChecked()
        self.channel_filters.setVisible(is_channel)
        if is_channel:
            self.url_label.setText("Link kênh — mỗi dòng một kênh")
            self.url_input.setPlaceholderText(
                "Dán link kênh YouTube hoặc trang cá nhân TikTok/Douyin.\n"
                "Ví dụ: https://www.youtube.com/@tenkenh/videos"
            )
        else:
            self.url_label.setText("Link video — mỗi dòng một link")
            self.url_input.setPlaceholderText(
                "Dán link vào đây. Ví dụ:\nhttps://www.youtube.com/watch?v=...\n"
                "https://www.tiktok.com/@user/video/..."
            )


class QueuePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, int] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        header = QHBoxLayout()
        title = QLabel("Hàng đợi tải")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        self.counts = QLabel("0 đang tải • 0 chờ • 0 xong • 0 lỗi")
        self.counts.setObjectName("countBadge")
        header.addWidget(self.counts)
        layout.addLayout(header)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Nền tảng", "Tiêu đề", "Trạng thái", "Tiến trình", "Tốc độ", "Còn lại", "File"])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def add_job(self, job: DownloadJob) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.rows[job.job_id] = row
        for col, value in enumerate((job.video.platform, job.video.title, job.status.value, "0%", "—", "—", "")):
            self.table.setItem(row, col, QTableWidgetItem(value))

    def update_job(self, job: DownloadJob) -> None:
        row = self.rows.get(job.job_id)
        if row is None:
            return
        self.table.item(row, 2).setText(job.status.value)
        self.table.item(row, 3).setText(f"{job.progress:.1f}%")
        self.table.item(row, 4).setText(job.speed)
        self.table.item(row, 5).setText(job.eta)
        self.table.item(row, 6).setText(job.output_path or job.error)

    def update_progress(self, job_id: str, progress: float, speed: str, eta: str) -> None:
        row = self.rows.get(job_id)
        if row is None:
            return
        self.table.item(row, 2).setText(DownloadStatus.DOWNLOADING.value)
        self.table.item(row, 3).setText(f"{progress:.1f}%")
        self.table.item(row, 4).setText(speed)
        self.table.item(row, 5).setText(eta)

    def set_counts(self, running: int, waiting: int, done: int, failed: int) -> None:
        self.counts.setText(f"{running} đang tải • {waiting} chờ • {done} xong • {failed} lỗi")


class HistoryPage(QWidget):
    def __init__(self, database: HistoryDatabase) -> None:
        super().__init__()
        self.database = database
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        header = QHBoxLayout()
        title = QLabel("Lịch sử tải")
        title.setObjectName("sectionTitle")
        refresh = QPushButton("↻ Làm mới")
        refresh.clicked.connect(self.reload)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Thời gian", "Nền tảng", "Tiêu đề", "Link nguồn", "Trạng thái", "Đường dẫn"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.reload()

    def reload(self) -> None:
        rows = self.database.recent()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row["created_at"][:19].replace("T", " "),
                row["platform"],
                row["title"],
                row["source_url"],
                row["status"],
                row["output_path"] or row["error"],
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))


class SettingsPage(QWidget):
    settings_saved = Signal()
    update_engine_requested = Signal()

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        title = QLabel("Cài đặt")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        general = QGroupBox("Tải xuống")
        grid = QGridLayout(general)
        grid.addWidget(QLabel("Số video tải đồng thời"), 0, 0)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 4)
        self.concurrency.setValue(settings.concurrency)
        grid.addWidget(self.concurrency, 0, 1)
        self.skip_duplicates = QCheckBox("Tự động bỏ qua video đã tải")
        self.skip_duplicates.setChecked(settings.skip_duplicates)
        grid.addWidget(self.skip_duplicates, 1, 0, 1, 2)
        grid.addWidget(QLabel("Cookies.txt (không bắt buộc)"), 2, 0)
        cookie_row = QHBoxLayout()
        self.cookies = QLineEdit(settings.cookies_file)
        choose = QPushButton("Chọn file")
        choose.clicked.connect(self._choose_cookie)
        cookie_row.addWidget(self.cookies)
        cookie_row.addWidget(choose)
        grid.addLayout(cookie_row, 2, 1)
        layout.addWidget(general)
        engine_group = QGroupBox("Engine tải video")
        engine_layout = QHBoxLayout(engine_group)
        self.engine_status = QLabel("Có thể cập nhật yt-dlp riêng mà không cài lại ứng dụng.")
        self.engine_status.setObjectName("muted")
        self.update_engine_button = QPushButton("Kiểm tra && cập nhật yt-dlp")
        self.update_engine_button.clicked.connect(self.update_engine_requested)
        engine_layout.addWidget(self.engine_status, 1)
        engine_layout.addWidget(self.update_engine_button)
        layout.addWidget(engine_group)
        save = QPushButton("Lưu cài đặt")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        layout.addStretch()

    def _choose_cookie(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Chọn cookies.txt", "", "Text files (*.txt);;All files (*.*)")
        if filename:
            self.cookies.setText(filename)

    def save(self) -> None:
        self.settings.concurrency = self.concurrency.value()
        self.settings.cookies_file = self.cookies.text().strip()
        self.settings.skip_duplicates = self.skip_duplicates.isChecked()
        self.settings.save()
        self.settings_saved.emit()
        QMessageBox.information(self, APP_NAME, "Đã lưu cài đặt.")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.database = HistoryDatabase()
        self.engine = DownloaderEngine()
        self.preview_pool = QThreadPool(self)
        self.preview_pool.setMaxThreadCount(1)
        self.queue = QueueController(self.engine, self.database, self.settings.concurrency)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Kênh + chống trùng")
        self.resize(1450, 890)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(APP_STYLE)
        self._setup_ui()
        self._connect_signals()
        QTimer.singleShot(100, self._check_engine)

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        brand = QLabel("∞  LinkGrab")
        brand.setObjectName("brand")
        side_layout.addWidget(brand)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_items = [
            ("⚡  Tải ngay", 0),
            ("▤  Hàng đợi", 1),
            ("📁  File đã tải", 2),
            ("◷  Lịch sử tải", 3),
            ("⚙  Cài đặt", 4),
        ]
        for index, (label, page) in enumerate(nav_items):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("page", page)
            button.clicked.connect(lambda checked=False, p=page: self.stack.setCurrentIndex(p))
            self.nav_group.addButton(button)
            side_layout.addWidget(button)
            if index == 0:
                button.setChecked(True)
        side_layout.addStretch()
        version = QLabel(f"Bản {APP_VERSION}\nKênh + chống trùng\nWindows 10/11")
        version.setObjectName("muted")
        side_layout.addWidget(version)
        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.download_page = DownloadPage(self.settings)
        self.queue_page = QueuePage()
        files_page = QWidget()
        files_layout = QVBoxLayout(files_page)
        files_layout.setContentsMargins(22, 18, 22, 18)
        files_title = QLabel("File đã tải")
        files_title.setObjectName("sectionTitle")
        files_layout.addWidget(files_title)
        files_layout.addWidget(QLabel("Các video hoàn thành được lưu trong thư mục tải xuống đã chọn."))
        open_folder = QPushButton("📁  Mở thư mục tải xuống")
        open_folder.setObjectName("primary")
        open_folder.clicked.connect(lambda: open_path(Path(self.download_page.output_dir.text())))
        files_layout.addWidget(open_folder)
        files_layout.addStretch()
        self.history_page = HistoryPage(self.database)
        self.settings_page = SettingsPage(self.settings)
        for page in (self.download_page, self.queue_page, files_page, self.history_page, self.settings_page):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

    def _connect_signals(self) -> None:
        self.download_page.preview_requested.connect(self._start_preview)
        self.download_page.queue_requested.connect(self._add_to_queue)
        self.download_page.stop_requested.connect(self._stop_all)
        self.queue.job_added.connect(self.queue_page.add_job)
        self.queue.job_started.connect(self.queue_page.update_job)
        self.queue.job_progress.connect(self.queue_page.update_progress)
        self.queue.job_finished.connect(self._job_finished)
        self.queue.queue_counts.connect(self.queue_page.set_counts)
        self.settings_page.settings_saved.connect(self._settings_saved)
        self.settings_page.update_engine_requested.connect(self._update_engine)

    @Slot(list, object, bool)
    def _start_preview(self, urls: list[str], preview_options: PreviewOptions, _auto_queue: bool) -> None:
        cookies = Path(self.settings.cookies_file) if self.settings.cookies_file else None
        worker = PreviewWorker(self.engine, urls, preview_options, cookies)
        worker.signals.item.connect(self._add_preview_video)
        worker.signals.error.connect(self.download_page.add_preview_error)
        worker.signals.finished.connect(self.download_page.preview_finished)
        self.preview_pool.start(worker)

    @Slot(object)
    def _add_preview_video(self, video: VideoInfo) -> None:
        duplicate = self.database.completed_record(video.unique_key) if self.settings.skip_duplicates else None
        self.download_page.add_preview_video(video, duplicate)

    @Slot(list)
    def _add_to_queue(self, videos: list[VideoInfo]) -> None:
        options = self.download_page.current_options()
        self.settings.output_dir = str(options.output_dir)
        self.settings.quality = options.quality
        self.settings.media_format = options.media_format
        self.settings.save()
        added, duplicates = self.queue.add_videos(
            videos, options, skip_duplicates=self.settings.skip_duplicates
        )
        self.download_page.append_log(
            f"Đã thêm {added} video vào hàng đợi; bỏ qua {len(duplicates)} video trùng."
        )
        if duplicates:
            lines = [f"• {video.title}\n  {video.webpage_url or video.url}" for video in duplicates[:8]]
            remaining = len(duplicates) - len(lines)
            if remaining > 0:
                lines.append(f"… và {remaining} video khác")
            QMessageBox.information(
                self,
                "Phát hiện video trùng",
                "Các video sau đã tải hoặc đang nằm trong hàng đợi nên được bỏ qua:\n\n"
                + "\n".join(lines),
            )
        if added:
            self.stack.setCurrentIndex(1)

    def _stop_all(self) -> None:
        answer = QMessageBox.question(self, APP_NAME, "Dừng toàn bộ video đang tải và đang chờ?")
        if answer == QMessageBox.Yes:
            self.queue.cancel_all()
            self.download_page.append_log("Đã gửi lệnh dừng tất cả.")

    @Slot(object)
    def _job_finished(self, job: DownloadJob) -> None:
        self.queue_page.update_job(job)
        self.history_page.reload()
        if job.status == DownloadStatus.COMPLETED:
            self.download_page.append_log(f"Hoàn thành: {job.video.title}")
        else:
            self.download_page.append_log(f"Lỗi: {job.video.title} — {job.error or job.status.value}")

    def _settings_saved(self) -> None:
        self.queue.set_concurrency(self.settings.concurrency)

    def _check_engine(self) -> None:
        if self.engine.is_ready:
            self.download_page.engine_badge.setText(f"yt-dlp: {self.engine.version()}")
            self.download_page.append_log("Engine tải video đã sẵn sàng.")
        else:
            self.download_page.engine_badge.setText("yt-dlp: chưa cài")
            self.download_page.append_log("Chưa tìm thấy yt-dlp. Bản Setup chính thức sẽ tự đóng gói công cụ này.")

    def _update_engine(self) -> None:
        if self.queue.running:
            QMessageBox.warning(self, APP_NAME, "Hãy chờ các video đang tải hoàn thành trước khi cập nhật engine.")
            return
        target = Path(str(self.engine.ytdlp))
        if not target.is_file():
            QMessageBox.warning(self, APP_NAME, "Bản chạy mã nguồn chưa có yt-dlp.exe để cập nhật.")
            return
        self.settings_page.update_engine_button.setEnabled(False)
        worker = EngineUpdateWorker(EngineUpdater(target))
        worker.signals.status.connect(self.settings_page.engine_status.setText)
        worker.signals.finished.connect(self._engine_update_finished)
        worker.signals.error.connect(self._engine_update_failed)
        self.preview_pool.start(worker)

    def _engine_update_finished(self, version: str) -> None:
        self.settings_page.update_engine_button.setEnabled(True)
        self.settings_page.engine_status.setText(f"Đã cập nhật yt-dlp {version}")
        self.download_page.engine_badge.setText(f"yt-dlp: {version}")
        QMessageBox.information(self, APP_NAME, f"Cập nhật engine thành công: {version}")

    def _engine_update_failed(self, error: str) -> None:
        self.settings_page.update_engine_button.setEnabled(True)
        self.settings_page.engine_status.setText("Cập nhật thất bại; bản cũ vẫn được giữ nguyên.")
        QMessageBox.critical(self, APP_NAME, error)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.queue.running:
            answer = QMessageBox.question(self, APP_NAME, "Vẫn còn video đang tải. Bạn có muốn thoát và dừng tải?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.queue.cancel_all()
        self.settings.save()
        event.accept()
