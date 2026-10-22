"""메인 창: 탭(일일 숙제 / 기록 / 설정). 기능별 탭은 각 모듈에 있다."""
import ctypes
import logging
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from mabi import paths as mpaths
from mabi.runner import setup_logging

from . import style
from .daily_tab import DailyTab
from .dashboard_tab import DashboardTab
from .items_tab import ItemsTab
from .missions_tab import MissionsTab
from .music_tab import MusicTab
from .gather_tab import GatherTab
from .craft_ui import AlterTab, CraftTab, QueuePanel
from .dye_tab import DyeTab
from .social_tab import SocialTab
from .services import Services
from .topbar import TopBar
from .history_tab import HistoryTab
from .settings_tab import SettingsTab

APP_TITLE = "마비 일일 숙제"


class LogBridge(QObject, logging.Handler):
    """mabi 로거 → Qt 시그널. 숙제는 작업 스레드에서 돌기 때문에 화면은 시그널로만 고친다."""
    line = Signal(str, str)  # (레벨, 문장)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self, logging.INFO)
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: N802 (logging.Handler 규약)
        try:
            self.line.emit(record.levelname, self.format(record))
        except RuntimeError:  # 창이 닫히는 중
            pass


class MainWindow(QMainWindow):
    def __init__(self, paths: mpaths.Paths):
        super().__init__()
        self.paths = paths
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        self.setWindowTitle(APP_TITLE + ("" if admin else "  (관리자 아님)"))
        self.resize(1180, 760)

        self.bridge = LogBridge()
        logging.getLogger("mabi").addHandler(self.bridge)

        self.svc = Services(paths)
        self.topbar = TopBar(self.svc)
        tabs = QTabWidget()
        self.dashboard = DashboardTab(self.svc)
        self.missions = MissionsTab(self.svc)
        self.items = ItemsTab(self.svc)
        self.gather = GatherTab(self.svc)
        self.queue = QueuePanel(self.svc)
        self.craft = CraftTab(self.svc, self.queue)
        self.alter = AlterTab(self.svc, self.queue)
        self.music = MusicTab(self.svc)
        self.social = SocialTab(self.svc)
        self.dye = DyeTab(self.svc)
        self.daily = DailyTab(paths, self.bridge)
        self.history = HistoryTab(paths)
        self.settings = SettingsTab(paths)
        tabs.addTab(self.dashboard, "대시보드")
        tabs.addTab(self.missions, "미션")
        tabs.addTab(self.items, "소지품")
        tabs.addTab(self.gather, "채집")
        tabs.addTab(self.craft, "제작")
        tabs.addTab(self.alter, "가공")
        tabs.addTab(self.music, "연주")
        tabs.addTab(self.social, "소셜")
        tabs.addTab(self.dye, "염색")
        tabs.addTab(self.daily, "일일 숙제")
        tabs.addTab(self.history, "기록")
        tabs.addTab(self.settings, "설정")
        tabs.currentChanged.connect(lambda i: tabs.widget(i).refresh() if hasattr(tabs.widget(i), "refresh") else None)
        self.daily.finished.connect(self.history.refresh)
        self.settings.profile_changed.connect(self.daily.refresh)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.topbar)
        from PySide6.QtWidgets import QSplitter
        split = QSplitter()
        split.addWidget(tabs)
        split.addWidget(self.queue)
        split.setSizes([1000, 320])
        lay.addWidget(split, 1)
        self.setCentralWidget(body)
        self.tabs = tabs
        # 시작: 캐시로 먼저 그리고(게임이 꺼져 있으면 연결 판정에 5초), 연결을 확인한 뒤 실제 값으로 다시
        self.topbar.refresh()
        self.dashboard.refresh()
        self._make_tray()
        # 연결이 생기면 보고 있는 화면을 실제 값으로 다시 읽는다 (그 전엔 저장된 값)
        self.svc.connection.connect(lambda st: st.get("connected") and hasattr(tabs.currentWidget(), "refresh")
                                    and tabs.currentWidget().refresh())
        self.svc.check_status(lambda st, e: self.svc.tick.emit() if st.get("connected") else None)

        # 상태바: 알림(최근 것) · 진행 중인 게임 행동 + 취소
        from PySide6.QtWidgets import QPushButton
        self.msg = QLabel("")
        self.busy = QLabel("")
        cancel = QPushButton("취소")
        cancel.setVisible(False)
        cancel.clicked.connect(self.svc.cancel)
        self.statusBar().addWidget(self.msg, 1)
        self.statusBar().addPermanentWidget(self.busy)
        self.statusBar().addPermanentWidget(cancel)
        self.svc.notice.connect(lambda kind, text: (
            self.msg.setText(text),
            self.msg.setStyleSheet(f"color: {style.STATUS_COLORS['FAIL'] if kind == 'bad' else style.STATUS_COLORS['OK'] if kind == 'ok' else style.TEXT}")))
        self.svc.action_state.connect(lambda on, what: (self.busy.setText(f"진행 중: {what}" if on else ""),
                                                         cancel.setVisible(on)))

    def _make_tray(self) -> None:
        """트레이 아이콘. 우클릭 메뉴는 열 때마다 새로 만든다 (연결 상태·날개가 바뀌므로)."""
        from PySide6.QtGui import QAction, QColor, QPainter, QPixmap
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(style.ACCENT))
        p.setPen(QColor(style.ACCENT))
        p.drawEllipse(4, 4, 56, 56)
        p.setPen(QColor("white"))
        f = p.font()
        f.setPixelSize(34)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pix.rect(), 0x84, "M")  # AlignCenter
        p.end()
        self.setWindowIcon(pix)
        self.tray = QSystemTrayIcon(pix, self)
        self.tray.setToolTip(APP_TITLE)
        menu = QMenu()

        def build():
            menu.clear()
            st = "연결됨" if self.svc.online else "연결 안 됨"
            menu.addAction(st).setEnabled(False)
            if self.topbar.wings.text():
                menu.addAction(self.topbar.wings.text()).setEnabled(False)
            menu.addSeparator()
            menu.addAction("창 열기", self.show_window)
            menu.addAction("종료", self.quit_app)
        menu.aboutToShow.connect(build)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: reason == QSystemTrayIcon.DoubleClick and self.show_window())
        self.tray.show()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, e):  # noqa: N802
        if self.svc.settings.get("close_to_tray") and not getattr(self, "_quitting", False):
            e.ignore()
            self.hide()
            return
        if self.daily.running():
            self.daily.stop()
            self.daily.wait(8000)
        self.tray.hide()
        self.dye.shutdown()
        if self.queue.queue.running:
            self.queue.queue.halt()
        super().closeEvent(e)
        QApplication.quit()


def main() -> int:
    paths = mpaths.load()
    setup_logging(paths, console=False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setQuitOnLastWindowClosed(False)  # 트레이로 숨겨도 꺼지지 않게 (종료는 closeEvent 에서)
    # 하나만 띄운다. 이미 떠 있으면 그 창을 앞으로 부르고 끝낸다
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    name = "MabiDaily-single"
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)
    style.apply(app)
    win = MainWindow(paths)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.show_window()))
    win.show()
    return app.exec()
