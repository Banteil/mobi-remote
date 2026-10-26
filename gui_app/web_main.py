"""웹 화면판 진입점: 하나만 띄우기 · 트레이 · 창 닫기(트레이로 숨기기 또는 정리 후 종료)."""
import logging
import sys

from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from mabi import paths as mpaths
from mabi.runner import setup_logging

from .api import APP_NAME, Api
from .web_shell import WEB, WebWindow

log = logging.getLogger("mabi")
SINGLE = "MobiRemote-single"
# 이미 떠 있는 리모콘에 보내는 명령 (gui.py --resume / --halt). 키보드를 못 만질 때 원격으로 이어 하기·멈추기
COMMANDS = {"--resume": b"resume", "--halt": b"halt"}


def _command(argv: list[str]) -> bytes:
    """이미 떠 있는 리모콘에 보낼 명령. 사람이 컴퓨터를 못 만질 때 밖에서 부린다:
      --halt 일시정지 · --resume 이어 하기 · --daily 슬롯,슬롯 [숙제,숙제] 일일 숙제 카드를 넣고 시작"""
    if "--daily" in argv:
        i = argv.index("--daily")
        rest = [a for a in argv[i + 1:i + 3] if not a.startswith("--")]
        return ("daily:" + ":".join(rest)).encode()
    return next((m for a, m in COMMANDS.items() if a in argv), b"show")


def _on_message(win: "MainWindow", conn) -> None:
    msg = bytes(conn.readAll()).strip()
    q = win.api.queue
    if msg == b"resume":
        log.info("명령 → 이어 하기")
        q.resume_top()
    elif msg == b"halt":
        log.info("명령 → 작업 큐 일시정지")
        win.api.queue_halt()
    elif msg.startswith(b"daily:"):
        parts = msg.decode().split(":")[1:]
        slots = [int(x) for x in (parts[0] if parts else "").split(",") if x.strip().isdigit()]
        only = [x for x in (parts[1] if len(parts) > 1 else "").split(",") if x] or None
        if not slots or q.running:
            log.warning(f"명령 → 일일 숙제: 넣지 않음 ({'슬롯 없음' if not slots else '다른 작업이 도는 중'})")
            return
        log.info(f"명령 → 일일 숙제 시작 (슬롯 {slots}, 숙제 {only or '전체'})")
        win.api.queue_add({"kind": "daily", "label": "일일 숙제", "chars": slots, "only": only, "force": False, "fit": False}, "end")
        q.tick()
    else:
        win.show_window()


class MainWindow(WebWindow):
    def __init__(self, api: Api):
        super().__init__(api, api.initial())
        self.api = api
        self._quitting = False
        self.tray = QSystemTrayIcon(QIcon(str(WEB / "tray.png")), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction(QAction("창 열기", menu, triggered=self.show_window))
        menu.addAction(QAction("종료", menu, triggered=self.quit_app))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
                                    and self.show_window())
        self.tray.show()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, e):  # noqa: N802
        if self.api.settings.get("closeToTray") and not self._quitting:
            e.ignore()
            self.hide()
            return
        self.api.close()
        t = self.api._daily_thread
        if t and t.is_alive():
            t.join(8)
        self.tray.hide()
        super().closeEvent(e)
        QApplication.quit()


def main() -> int:
    paths = mpaths.load()
    setup_logging(paths, console=False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(WEB / "icon.png")))
    app.setQuitOnLastWindowClosed(False)  # 트레이로 숨겨도 꺼지지 않게 (종료는 closeEvent 에서)
    # 하나만 띄운다. 이미 떠 있으면 그 창을 앞으로 부르고 끝낸다
    sock = QLocalSocket()
    sock.connectToServer(SINGLE)
    if sock.waitForConnected(300):
        sock.write(_command(sys.argv))
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SINGLE)
    server = QLocalServer()
    server.listen(SINGLE)
    win = MainWindow(Api(paths))

    def on_connect():
        conn = server.nextPendingConnection()
        conn.readyRead.connect(lambda: _on_message(win, conn))

    server.newConnection.connect(on_connect)
    win.show()
    log.info(f"{APP_NAME} 시작")
    return app.exec()
