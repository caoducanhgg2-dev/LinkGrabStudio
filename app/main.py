from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import APP_NAME, app_data_dir
from .ui import MainWindow


def _configure_logging() -> None:
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "app.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def main() -> int:
    _configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("LinkGrab")
    if getattr(sys, "frozen", False):
        icon_path = Path(sys.executable).resolve().parent / "linkgrab.png"
    else:
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "linkgrab.png"
    app.setWindowIcon(QIcon(str(icon_path)))
    try:
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:
        logging.exception("Fatal startup error")
        QMessageBox.critical(None, APP_NAME, f"Không thể khởi động ứng dụng:\n{exc}")
        return 1
