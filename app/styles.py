APP_STYLE = r"""
* {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10.5pt;
}
QMainWindow, QWidget {
    background: #0e0f1c;
    color: #f5f5fb;
}
QLabel, QCheckBox { background: transparent; }
QFrame#sidebar {
    background: #0a0b16;
    border-right: 1px solid #292a3c;
}
QLabel#brand {
    font-size: 17pt;
    font-weight: 800;
    color: white;
    padding: 12px 10px;
}
QPushButton {
    background: #171827;
    border: 1px solid #303147;
    border-radius: 9px;
    color: #f1f1f7;
    padding: 9px 13px;
    text-align: left;
}
QPushButton:hover { background: #202136; border-color: #6d4aff; }
QPushButton:checked, QPushButton#primary {
    background: #5c35db;
    border-color: #9a72ff;
    color: white;
    font-weight: 700;
}
QPushButton#primary:hover { background: #7249eb; }
QPushButton#danger { border-color: #6e3140; color: #ffabbc; }
QPushButton#danger:hover { background: #3a1721; }
QPushButton#platform {
    min-width: 120px;
    min-height: 50px;
    text-align: center;
    font-weight: 700;
}
QPushButton#platform:checked { background: #211b3f; border: 2px solid #8b5cff; }
QPushButton#mode {
    border-radius: 8px;
    padding: 8px 18px;
    text-align: center;
}
QFrame#card, QGroupBox {
    background: #171825;
    border: 1px solid #2f3042;
    border-radius: 12px;
}
QFrame#linkBar {
    background: #171825;
    border: 1px solid #34354a;
    border-radius: 9px;
}
QFrame#linkBar QLineEdit {
    color: #cbb9ff;
    background: #11121d;
    border-color: #464763;
}
QGroupBox {
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    font-weight: 700;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #232433;
    color: #f4f4f8;
    border: 1px solid #3a3b50;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #7148e8;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #8a5cff;
}
QTableWidget {
    background: #13141f;
    alternate-background-color: #191a28;
    gridline-color: #292a3b;
    border: 1px solid #303145;
    border-radius: 9px;
}
QHeaderView::section {
    background: #202131;
    color: #d9d9e6;
    padding: 8px;
    border: none;
    border-right: 1px solid #303145;
    font-weight: 700;
}
QProgressBar {
    background: #242538;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}
QProgressBar::chunk { background: #8957ff; border-radius: 5px; }
QScrollBar:vertical { background: #141520; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #3b3c51; min-height: 30px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLabel#muted { color: #9b9caf; }
QLabel#sectionTitle { font-size: 14pt; font-weight: 800; }
QLabel#countBadge { color: #cbb9ff; font-weight: 700; }
"""
