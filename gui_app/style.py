"""어두운 테마. 색은 여기 상수에만 둔다 (상태 색은 표와 기록 화면이 같이 쓴다)."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#1e1f24"
PANEL = "#26282e"
EDGE = "#3a3d45"
TEXT = "#e6e6e9"
MUTED = "#9a9ca5"
ACCENT = "#5b8def"

STATUS_COLORS = {
    "OK": "#3fb27f",
    "DONE": "#2f7d5c",
    "CHECK": "#d9a441",
    "FAIL": "#e0605e",
    "ERROR": "#e0605e",
    "HEAVY": "#c77dd9",
    "SKIP": "#7a7d86",
    "STOP": "#7a7d86",
    "RUN": ACCENT,
}

STATUS_TEXT = {
    "OK": "완료", "DONE": "완료", "CHECK": "남음", "FAIL": "실패", "ERROR": "오류",
    "HEAVY": "가방 무게", "SKIP": "건너뜀", "STOP": "중단", "RUN": "진행 중",
}

QSS = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Malgun Gothic'; font-size: 10pt; }}
QTabWidget::pane {{ border: 1px solid {EDGE}; }}
QTabBar::tab {{ background: {PANEL}; padding: 7px 16px; border: 1px solid {EDGE}; border-bottom: none; }}
QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; }}
QTabBar::tab:!selected {{ color: {MUTED}; }}
QPushButton {{ background: {PANEL}; border: 1px solid {EDGE}; padding: 6px 14px; border-radius: 4px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: bold; }}
QPushButton#danger {{ background: #8a3a3a; border-color: #8a3a3a; color: white; }}
QTableWidget, QTreeWidget, QListWidget, QPlainTextEdit, QLineEdit, QSpinBox, QComboBox {{
    background: {PANEL}; border: 1px solid {EDGE}; gridline-color: {EDGE}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {EDGE}; padding: 4px; }}
QGroupBox {{ border: 1px solid {EDGE}; border-radius: 4px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {MUTED}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#title {{ font-size: 12pt; font-weight: bold; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
