from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal, Slot
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

from .auth import DouyinAuthManager
from .config import APP_NAME, APP_VERSION, AppSettings, app_data_dir
from .database import HistoryDatabase
from .downloader import DownloaderEngine
from .models import DownloadJob, DownloadOptions, DownloadStatus, PreviewOptions, VideoInfo
from .styles import APP_STYLE
from .updater import EngineUpdater
from .utils import detect_platform, extract_urls, format_duration
from .workers import DouyinAuthWorker, EngineUpdateWorker, PreviewWorker, QueueController


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
        self._preview_errors: list[str] = []
        self._logged_translations: set[tuple[str, str]] = set()
        self._auto_queue_after_preview = False
        self._controls_collapsed = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)

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

        self.source_controls = QWidget()
        source_layout = QVBoxLayout(self.source_controls)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(8)

        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Chọn nền tảng"))
        self.platform_group = QButtonGroup(self)
        self.platform_group.setExclusive(True)
        self.platform_buttons: dict[str, QPushButton] = {}
        for index, (label, icon) in enumerate((("YouTube", "▶"), ("TikTok", "♪"), ("Douyin", "◉"))):
            button = QPushButton(f"{icon}  {label}")
            button.setObjectName("platform")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.platform_group.addButton(button)
            self.platform_buttons[label] = button
            button.clicked.connect(self._platform_changed)
            platform_row.addWidget(button)
        more = QPushButton("＋ Nền tảng khác (sắp có)")
        more.setObjectName("platform")
        more.setEnabled(False)
        platform_row.addWidget(more)
        platform_row.addStretch()
        source_layout.addLayout(platform_row)

        body = QHBoxLayout()
        body.setSpacing(14)
        form_card = QFrame()
        form_card.setObjectName("card")
        form = QVBoxLayout(form_card)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Chế độ"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.keyword_mode = QPushButton("🔍 Từ khóa")
        self.link_mode = QPushButton("🔗 Link")
        self.playlist_mode = QPushButton("▤ Playlist/Bộ")
        for button in (self.keyword_mode, self.link_mode, self.playlist_mode):
            button.setObjectName("mode")
            button.setCheckable(True)
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        self.link_mode.setChecked(True)
        self.channel_mode = QPushButton("👤 Kênh")
        self.channel_mode.setObjectName("mode")
        self.channel_mode.setCheckable(True)
        self.mode_group.addButton(self.channel_mode)
        mode_row.addWidget(self.channel_mode)
        mode_row.addStretch()
        form.addLayout(mode_row)

        channel_hint = QLabel("Từ khóa: YouTube/Douyin • dịch tiếng Trung • tự nhận diện video trùng")
        channel_hint.setObjectName("countBadge")
        channel_hint.setWordWrap(True)
        form.addWidget(channel_hint)

        self.keyword_mode.clicked.connect(self._update_mode_ui)
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
        self.url_input.setMinimumHeight(62)
        self.url_input.setMaximumHeight(76)
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
        self.channel_filters.setToolTip(self.channel_duplicate_note.text())
        self.channel_filters.setVisible(False)
        form.addWidget(self.channel_filters)

        self.search_filters = QFrame()
        search_grid = QGridLayout(self.search_filters)
        search_grid.setContentsMargins(0, 6, 0, 6)
        search_grid.addWidget(QLabel("Số video"), 0, 0)
        search_grid.addWidget(QLabel("Sắp xếp"), 0, 1)
        search_grid.addWidget(QLabel("Khoảng thời gian"), 0, 2)
        search_grid.addWidget(QLabel("Ngôn ngữ"), 0, 3)
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, 300)
        self.search_limit.setValue(50)
        self.search_sort = QComboBox()
        self.search_sort.addItem("Nhiều lượt xem nhất", "views")
        self.search_sort.addItem("Mới nhất", "newest")
        self.search_sort.addItem("Liên quan nhất", "relevance")
        self.search_period = QComboBox()
        for label, days in (
            ("Không giới hạn", 0),
            ("Trong 1 tuần", 7),
            ("Trong 1 tháng", 30),
            ("Trong 3 tháng", 90),
            ("Trong 6 tháng", 180),
            ("Trong 1 năm", 365),
        ):
            self.search_period.addItem(label, days)
        self.search_language = QComboBox()
        self.search_language.addItem("Giữ nguyên", "original")
        self.search_language.addItem("Dịch sang tiếng Trung (giản thể)", "zh-cn")
        self.search_language.addItem("Dịch sang tiếng Trung (phồn thể)", "zh-tw")
        search_grid.addWidget(self.search_limit, 1, 0)
        search_grid.addWidget(self.search_sort, 1, 1)
        search_grid.addWidget(self.search_period, 1, 2)
        search_grid.addWidget(self.search_language, 1, 3)
        search_note = QLabel(
            "YouTube/Douyin sẽ tìm rộng hơn số lượng yêu cầu, sau đó app lọc và xếp hạng kết quả tốt nhất."
        )
        search_note.setObjectName("muted")
        self.search_filters.setToolTip(search_note.text())
        self.search_filters.setVisible(False)
        form.addWidget(self.search_filters)

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
        source_layout.addLayout(body)
        root.addWidget(self.source_controls)

        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("Danh sách video"))
        self.preview_count = QLabel("0 video")
        self.preview_count.setObjectName("countBadge")
        preview_header.addWidget(self.preview_count)
        preview_header.addStretch()
        self.compact_queue_button = QPushButton("▤  Thêm đã chọn")
        self.compact_queue_button.setObjectName("compact")
        self.compact_queue_button.clicked.connect(self._queue_selected)
        preview_header.addWidget(self.compact_queue_button)
        self.toggle_controls_button = QPushButton("▴  Thu gọn bộ chọn")
        self.toggle_controls_button.setObjectName("compact")
        self.toggle_controls_button.clicked.connect(self._toggle_source_controls)
        preview_header.addWidget(self.toggle_controls_button)
        root.addLayout(preview_header)

        self.preview_table = QTableWidget(0, 9)
        self.preview_table.setHorizontalHeaderLabels(
            ["Chọn", "Nền tảng", "Tiêu đề", "Kênh", "Lượt xem", "Ngày đăng", "Thời lượng", "Link nguồn", "Trạng thái"]
        )
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.preview_table.verticalHeader().setVisible(False)
        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        for column in (4, 5, 6, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        header.resizeSection(7, 230)
        self.preview_table.currentCellChanged.connect(self._preview_row_changed)
        self.preview_table.cellDoubleClicked.connect(self._preview_cell_double_clicked)
        root.addWidget(self.preview_table, 1)

        link_bar = QFrame()
        link_bar.setObjectName("linkBar")
        link_layout = QHBoxLayout(link_bar)
        link_layout.setContentsMargins(12, 8, 12, 8)
        link_layout.setSpacing(8)
        link_label = QLabel("Link nguồn đang chọn")
        link_label.setObjectName("muted")
        link_layout.addWidget(link_label)
        self.preview_link = QLineEdit()
        self.preview_link.setReadOnly(True)
        self.preview_link.setPlaceholderText("Chọn một video để xem link đầy đủ")
        self.preview_link.setClearButtonEnabled(False)
        link_layout.addWidget(self.preview_link, 1)
        self.copy_link_button = QPushButton("⧉  Sao chép")
        self.copy_link_button.setToolTip("Sao chép link nguồn đầy đủ")
        self.copy_link_button.clicked.connect(self._copy_preview_link)
        self.open_link_button = QPushButton("↗  Mở link")
        self.open_link_button.setToolTip("Mở link nguồn trong trình duyệt")
        self.open_link_button.clicked.connect(self._open_preview_link)
        for button in (self.copy_link_button, self.open_link_button):
            button.setEnabled(False)
            link_layout.addWidget(button)
        root.addWidget(link_bar)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(80)
        self.log_box.setPlaceholderText("Nhật ký hoạt động sẽ hiển thị ở đây…")
        root.addWidget(self.log_box)

    def current_urls(self) -> list[str]:
        return extract_urls(self.url_input.toPlainText())

    def current_queries(self) -> list[str]:
        return [line.strip() for line in self.url_input.toPlainText().splitlines() if line.strip()]

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
        channel_limit = self.channel_limit.value()
        search_limit = self.search_limit.value()
        is_search = self.keyword_mode.isChecked()
        return PreviewOptions(
            playlist=self.playlist_mode.isChecked(),
            channel=self.channel_mode.isChecked(),
            keyword_search=is_search,
            search_platform=self.selected_platform(),
            search_language=str(self.search_language.currentData()),
            channel_limit=channel_limit,
            channel_scan_limit=max(100, min(500, channel_limit * 5)),
            search_limit=search_limit,
            search_scan_limit=max(50, min(500, search_limit * 5)),
            sort_by=str(self.search_sort.currentData() if is_search else self.channel_sort.currentData()),
            since_days=int(
                self.search_period.currentData() if is_search else self.channel_period.currentData()
            ),
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
        self._preview_errors.clear()
        self._logged_translations.clear()
        self.preview_table.setRowCount(0)
        self.preview_count.setText("0 video")
        self.preview_link.clear()
        self.copy_link_button.setEnabled(False)
        self.open_link_button.setEnabled(False)

    def add_preview_video(self, video: VideoInfo, duplicate: dict[str, str] | None = None) -> None:
        original_query = str(video.raw.get("search_query_original") or "")
        translated_query = str(video.raw.get("search_query_translated") or "")
        translation = (original_query, translated_query)
        if original_query and translated_query and original_query != translated_query:
            if translation not in self._logged_translations:
                self._logged_translations.add(translation)
                self.append_log(f"Đã dịch từ khóa: {original_query} → {translated_query}")
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
            status = (
                f"Đã tải {downloaded_at} — tích chọn để tải lại"
                if downloaded_at else "Đã tải trước đó — tích chọn để tải lại"
            )
            self.append_log(f"Trùng lặp: {video.title} — {duplicate.get('source_url') or source_url}")
        values = [
            video.platform,
            video.title,
            video.uploader or "—",
            views,
            upload_date or "—",
            format_duration(video.duration),
            self._short_source_url(source_url),
            status,
        ]
        for column, value in enumerate(values, 1):
            item = QTableWidgetItem(value)
            if column == 7:
                item.setData(Qt.UserRole, source_url)
                item.setToolTip(source_url)
                item.setForeground(QColor("#a98bff"))
            self.preview_table.setItem(row, column, item)
        self.videos.append(video)
        if row == 0:
            self.preview_table.setCurrentCell(0, 2)
        duplicate_count = sum(
            1 for index in range(self.preview_table.rowCount())
            if self.preview_table.item(index, 0).checkState() == Qt.Unchecked
        )
        suffix = f" • {duplicate_count} trùng" if duplicate_count else ""
        self.preview_count.setText(f"{len(self.videos)} video{suffix}")

    @staticmethod
    def _short_source_url(url: str, max_length: int = 54) -> str:
        display = url.strip()
        for prefix in ("https://www.", "http://www.", "https://", "http://"):
            if display.startswith(prefix):
                display = display[len(prefix):]
                break
        if len(display) <= max_length:
            return display
        return f"{display[:max_length - 1]}…"

    def _source_url_for_row(self, row: int) -> str:
        if row < 0 or row >= len(self.videos):
            return ""
        item = self.preview_table.item(row, 7)
        if item:
            return str(item.data(Qt.UserRole) or "")
        video = self.videos[row]
        return video.webpage_url or video.url

    def _preview_row_changed(self, current_row: int, _current_column: int, _previous_row: int, _previous_column: int) -> None:
        source_url = self._source_url_for_row(current_row)
        self.preview_link.setText(source_url)
        self.preview_link.setToolTip(source_url)
        self.preview_link.setCursorPosition(0)
        self.copy_link_button.setEnabled(bool(source_url))
        self.open_link_button.setEnabled(bool(source_url))

    def _copy_preview_link(self) -> None:
        source_url = self.preview_link.text().strip()
        if not source_url:
            return
        QApplication.clipboard().setText(source_url)
        self.append_log("Đã sao chép link nguồn vào clipboard.")

    def _open_preview_link(self) -> None:
        source_url = self.preview_link.text().strip()
        if source_url:
            QDesktopServices.openUrl(QUrl(source_url))

    def _preview_cell_double_clicked(self, row: int, column: int) -> None:
        if column != 7:
            return
        self.preview_table.setCurrentCell(row, column)
        self._open_preview_link()

    def add_preview_error(self, url: str, error: str) -> None:
        self._preview_errors.append(error)
        self.append_log(f"Không thể đọc {url}: {error}")

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {message}")

    def preview_finished(self) -> None:
        self.set_busy(False)
        self.append_log(f"Đã đọc xong {len(self.videos)} video.")
        if self.videos:
            self._set_source_controls_collapsed(True)
        if not self.videos and self._preview_errors:
            QMessageBox.warning(
                self,
                "Không đọc được video",
                "Không tìm thấy video nào.\n\n" + self._preview_errors[0],
            )
        if self._auto_queue_after_preview:
            self._auto_queue_after_preview = False
            if self.videos:
                self._queue_selected()

    def _toggle_source_controls(self) -> None:
        self._set_source_controls_collapsed(not self._controls_collapsed)

    def _set_source_controls_collapsed(self, collapsed: bool) -> None:
        self._controls_collapsed = collapsed
        self.source_controls.setVisible(not collapsed)
        self.toggle_controls_button.setText(
            "▾  Hiện bộ chọn" if collapsed else "▴  Thu gọn bộ chọn"
        )

    def set_busy(self, busy: bool) -> None:
        self.preview_button.setEnabled(not busy)
        self.download_all_button.setEnabled(not busy)
        self.preview_button.setText("⏳  Đang đọc thông tin…" if busy else "👁  Xem trước && chọn")

    def _request_preview(self, auto_queue: bool) -> None:
        is_search = self.keyword_mode.isChecked()
        items = self.current_queries() if is_search else self.current_urls()
        if not items:
            message = "Hãy nhập ít nhất một từ khóa." if is_search else "Hãy dán ít nhất một link hợp lệ."
            QMessageBox.warning(self, APP_NAME, message)
            return
        self.clear_preview()
        self._auto_queue_after_preview = auto_queue
        self.set_busy(True)
        action = "Đang tìm" if is_search else "Đang kiểm tra"
        unit = "từ khóa" if is_search else "link"
        self.append_log(f"{action} {len(items)} {unit}…")
        self.preview_requested.emit(items, self.current_preview_options(), auto_queue)

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
        if self.keyword_mode.isChecked():
            queries = self.current_queries()
            self.link_summary.setText(
                f"Đã nhập {len(queries)} từ khóa {self.selected_platform()}"
                if queries else "Chưa có từ khóa"
            )
            return
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
        is_search = self.keyword_mode.isChecked()
        self.channel_filters.setVisible(is_channel)
        self.search_filters.setVisible(is_search)
        for name, button in self.platform_buttons.items():
            button.setEnabled(not is_search or name in {"YouTube", "Douyin"})
        if is_search:
            platform = self.selected_platform()
            if platform not in {"YouTube", "Douyin"}:
                self.platform_buttons["YouTube"].setChecked(True)
                platform = "YouTube"
            if platform == "Douyin" and self.search_language.currentData() == "original":
                translated_index = self.search_language.findData("zh-cn")
                if translated_index >= 0:
                    self.search_language.setCurrentIndex(translated_index)
            self.url_label.setText(f"Từ khóa {platform} — mỗi dòng một từ khóa")
            self.url_input.setPlaceholderText(
                "Nhập từ khóa cần tìm. Ví dụ:\nmukbang\nbushcraft shelter\nhouse renovation"
            )
        elif is_channel:
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
        self._update_link_summary()

    def selected_platform(self) -> str:
        for name, button in self.platform_buttons.items():
            if button.isChecked():
                return name
        return "YouTube"

    def _platform_changed(self) -> None:
        if not hasattr(self, "keyword_mode") or not self.keyword_mode.isChecked():
            return
        target = "zh-cn" if self.selected_platform() == "Douyin" else "original"
        index = self.search_language.findData(target)
        if index >= 0:
            self.search_language.setCurrentIndex(index)
        self._update_mode_ui()


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
    douyin_open_requested = Signal(str)
    douyin_check_requested = Signal()
    douyin_refresh_requested = Signal(str)

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
        grid.addWidget(QLabel("Cookies.txt thủ công (dự phòng)"), 2, 0)
        cookie_row = QHBoxLayout()
        self.cookies = QLineEdit(settings.cookies_file)
        choose = QPushButton("Chọn file")
        choose.clicked.connect(self._choose_cookie)
        cookie_row.addWidget(self.cookies)
        cookie_row.addWidget(choose)
        grid.addLayout(cookie_row, 2, 1)
        layout.addWidget(general)

        douyin_group = QGroupBox("Đăng nhập Douyin bằng trình duyệt")
        douyin_layout = QGridLayout(douyin_group)
        douyin_layout.addWidget(QLabel("Lấy đăng nhập từ"), 0, 0)
        self.douyin_browser = QComboBox()
        self.douyin_browser.addItem("Google Chrome", "chrome")
        self.douyin_browser.addItem("Microsoft Edge", "edge")
        browser_index = self.douyin_browser.findData(settings.douyin_browser)
        self.douyin_browser.setCurrentIndex(max(0, browser_index))
        douyin_layout.addWidget(self.douyin_browser, 0, 1)
        self.douyin_status = QLabel("Chưa kiểm tra đăng nhập Douyin.")
        self.douyin_status.setObjectName("muted")
        douyin_layout.addWidget(self.douyin_status, 1, 0, 1, 2)
        douyin_buttons = QHBoxLayout()
        self.open_douyin_button = QPushButton("Mở Douyin để đăng nhập")
        self.check_douyin_button = QPushButton("Kiểm tra đăng nhập")
        self.refresh_douyin_button = QPushButton("Làm mới cookies")
        self.open_douyin_button.clicked.connect(
            lambda: self.douyin_open_requested.emit(str(self.douyin_browser.currentData()))
        )
        self.check_douyin_button.clicked.connect(self.douyin_check_requested)
        self.refresh_douyin_button.clicked.connect(
            lambda: self.douyin_refresh_requested.emit(str(self.douyin_browser.currentData()))
        )
        douyin_buttons.addWidget(self.open_douyin_button)
        douyin_buttons.addWidget(self.check_douyin_button)
        douyin_buttons.addWidget(self.refresh_douyin_button)
        douyin_layout.addLayout(douyin_buttons, 2, 0, 1, 2)
        douyin_note = QLabel(
            "App không lưu mật khẩu. Hãy đăng nhập trên Chrome/Edge, sau đó bấm Làm mới cookies."
        )
        douyin_note.setObjectName("muted")
        douyin_layout.addWidget(douyin_note, 3, 0, 1, 2)
        layout.addWidget(douyin_group)
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
        self.settings.douyin_browser = str(self.douyin_browser.currentData())
        self.settings.skip_duplicates = self.skip_duplicates.isChecked()
        self.settings.save()
        self.settings_saved.emit()
        QMessageBox.information(self, APP_NAME, "Đã lưu cài đặt.")

    def set_douyin_status(self, message: str) -> None:
        self.douyin_status.setText(message)

    def set_douyin_busy(self, busy: bool) -> None:
        self.refresh_douyin_button.setEnabled(not busy)
        self.check_douyin_button.setEnabled(not busy)
        self.douyin_status.setText("Đang đọc phiên đăng nhập từ trình duyệt…" if busy else self.douyin_status.text())

    def set_managed_cookie_file(self, path: Path) -> None:
        self.cookies.setText(str(path))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.database = HistoryDatabase()
        self.engine = DownloaderEngine()
        self.douyin_auth = DouyinAuthManager(self.engine)
        self.preview_pool = QThreadPool(self)
        self.preview_pool.setMaxThreadCount(1)
        self.queue = QueueController(self.engine, self.database, self.settings.concurrency)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Đăng nhập Douyin")
        self.resize(1450, 890)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(APP_STYLE)
        self._setup_ui()
        self._connect_signals()
        QTimer.singleShot(100, self._check_engine)
        QTimer.singleShot(150, self._check_douyin_auth)

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
        version = QLabel(f"Bản {APP_VERSION}\nĐăng nhập Douyin\nWindows 10/11")
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
        self.settings_page.douyin_open_requested.connect(self._open_douyin_login)
        self.settings_page.douyin_check_requested.connect(self._check_douyin_auth)
        self.settings_page.douyin_refresh_requested.connect(self._refresh_douyin_auth)

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
        completed = [
            video for video in videos
            if self.settings.skip_duplicates and self.database.has_completed(video.unique_key)
        ]
        fresh = [video for video in videos if video not in completed]
        reload_duplicates = False
        if completed:
            message = QMessageBox(self)
            message.setIcon(QMessageBox.Warning)
            message.setWindowTitle("Phát hiện video đã tải")
            message.setText(f"Có {len(completed)} video đã được tải trước đó.")
            message.setInformativeText(
                "Chọn Bỏ qua để giữ file cũ, hoặc Tải lại để tải và ghi lại các video này."
            )
            skip_button = message.addButton("Bỏ qua video trùng", QMessageBox.RejectRole)
            reload_button = message.addButton("Tải lại video trùng", QMessageBox.AcceptRole)
            message.addButton(QMessageBox.Cancel)
            message.exec()
            clicked = message.clickedButton()
            if clicked is None or (clicked is not skip_button and clicked is not reload_button):
                self.download_page.append_log("Đã hủy thao tác thêm video trùng vào hàng đợi.")
                return
            reload_duplicates = clicked is reload_button

        added, duplicates = self.queue.add_videos(
            fresh, options, skip_duplicates=self.settings.skip_duplicates
        )
        if reload_duplicates:
            reload_options = replace(options, overwrite_existing=True)
            reloaded, active_duplicates = self.queue.add_videos(
                completed, reload_options, skip_duplicates=False
            )
            added += reloaded
            duplicates.extend(active_duplicates)
            self.download_page.append_log(
                f"Đã chọn tải lại {reloaded}/{len(completed)} video trùng."
            )
        else:
            duplicates.extend(completed)
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

    @Slot(str)
    def _open_douyin_login(self, browser: str) -> None:
        self.douyin_auth.open_login(browser)
        self.settings_page.set_douyin_status(
            "Hãy đăng nhập Douyin trong trình duyệt, rồi quay lại bấm Làm mới cookies."
        )

    def _check_douyin_auth(self) -> None:
        configured = Path(self.settings.cookies_file) if self.settings.cookies_file else None
        status = self.douyin_auth.status(configured)
        self.settings_page.set_douyin_status(status.message)

    @Slot(str)
    def _refresh_douyin_auth(self, browser: str) -> None:
        self._douyin_refresh_browser = browser
        self.settings.douyin_browser = browser
        self.settings_page.set_douyin_busy(True)
        worker = DouyinAuthWorker(self.douyin_auth, browser)
        worker.signals.finished.connect(self._douyin_auth_finished)
        worker.signals.error.connect(self._douyin_auth_failed)
        self.preview_pool.start(worker)

    @Slot(object)
    def _douyin_auth_finished(self, status) -> None:
        self.settings_page.set_douyin_busy(False)
        self.settings.cookies_file = str(status.cookie_file or self.douyin_auth.cookie_file)
        self.settings.save()
        self.settings_page.set_managed_cookie_file(Path(self.settings.cookies_file))
        self.settings_page.set_douyin_status(status.message)
        QMessageBox.information(self, "Đăng nhập Douyin", status.message)

    @Slot(object)
    def _douyin_auth_failed(self, error) -> None:
        self.settings_page.set_douyin_busy(False)
        if getattr(error, "code", "") == "browser_locked":
            browser = getattr(self, "_douyin_refresh_browser", self.settings.douyin_browser)
            browser_name = "Microsoft Edge" if browser == "edge" else "Google Chrome"
            message = QMessageBox(self)
            message.setIcon(QMessageBox.Warning)
            message.setWindowTitle("Trình duyệt đang khóa cookies")
            message.setText(f"{browser_name} vẫn còn chạy nền.")
            message.setInformativeText(
                "App có thể đóng toàn bộ cửa sổ và tiến trình của trình duyệt rồi tự thử lại. "
                "Hãy lưu công việc đang mở trong trình duyệt trước khi tiếp tục."
            )
            retry_button = message.addButton(
                f"Đóng {browser_name} và thử lại", QMessageBox.AcceptRole
            )
            message.addButton("Hủy", QMessageBox.RejectRole)
            message.exec()
            if message.clickedButton() is retry_button:
                try:
                    self.douyin_auth.close_browser(browser)
                except Exception as close_error:
                    QMessageBox.warning(self, "Đăng nhập Douyin", str(close_error))
                    return
                self.settings_page.set_douyin_status(
                    f"Đã đóng {browser_name}; đang tự động thử lại…"
                )
                QTimer.singleShot(1500, lambda: self._refresh_douyin_auth(browser))
            return
        self.settings_page.set_douyin_status("Chưa đăng nhập Douyin hoặc cookies không đọc được.")
        QMessageBox.warning(self, "Đăng nhập Douyin", str(error))

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
