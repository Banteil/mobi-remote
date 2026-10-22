"""웹 화면 껍데기: QWebEngineView 에 web/index.html 을 띄우고 QWebChannel 로 파이썬(Api)과 잇는다.

화면 코드(web/app.js)는 레거시 Electron 판의 것을 거의 그대로 쓴다. 그 코드가 부르던 window.mm.* 를
web/bridge.js 가 같은 모양으로 만들고, 여기서 Api 의 메서드로 보낸다 ('kn.setLevel' → Api.kn_setLevel).
호출은 작업 스레드에서 처리한다 — CLI 호출은 수십 ms~수 초라 화면 스레드에서 돌리면 창이 굳는다.

WebView2(시스템 Edge)가 아니라 QtWebEngine 을 쓰는 이유: 염색 도우미의 게임 위 표시 창(투명·클릭 통과)과
트레이·단축키가 Qt 로 되어 있어 한 프로그램 안에서 같은 이벤트 루프로 돌아야 한다. WebView2(pywebview)는
투명 창이 되지 않았다(2026-10-21 시험).
"""
import json
import logging
import traceback
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, QRunnable, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

log = logging.getLogger("mabi")
APP_NAME = "모비 커넥터 리모콘"
WEB = Path(__file__).resolve().parent.parent / "web"


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.fn()


class Backend(QObject):
    """QWebChannel 에 'backend' 로 노출되는 유일한 객체."""
    reply = Signal(int, str)
    event = Signal(str, str)

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(8)

    @Slot(int, str, str)
    def call(self, req_id: int, method: str, args_json: str) -> None:
        def work():
            try:
                args = json.loads(args_json or "[]")
                fn = getattr(self.api, method.replace(".", "_"), None)
                if fn is None:
                    raise AttributeError(f"알 수 없는 호출: {method}")
                out = fn(*args)
                text = json.dumps(out, ensure_ascii=False, default=_jsonable)
            except Exception as e:
                log.error(f"화면 호출 실패 {method}: {e}\n{traceback.format_exc()}")
                text = json.dumps({"__error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
            try:
                self.reply.emit(req_id, text)
            except RuntimeError:
                pass  # 창이 닫히는 중
        self.pool.start(_Job(work))

    def emit_event(self, channel: str, payload=None) -> None:
        """파이썬 → 화면 이벤트 (어느 스레드에서 불러도 된다 — 시그널이 화면 스레드로 옮겨 준다)."""
        try:
            self.event.emit(channel, json.dumps(payload, ensure_ascii=False, default=_jsonable))
        except RuntimeError:
            pass


def _jsonable(o):
    if hasattr(o, "__dict__"):
        return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    try:
        import numpy as np
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.generic):
            return o.item()
    except ImportError:
        pass
    return str(o)


class Page(QWebEnginePage):
    """페이지 콘솔 메시지를 로그로 (화면 쪽 오류를 놓치지 않게)."""

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if level != QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel:
            log.warning(f"[화면] {message} ({Path(source).name}:{line})")


def _qrc_text(path: str) -> str:
    f = QFile(path)
    f.open(QIODevice.ReadOnly)
    return bytes(f.readAll()).decode("utf-8")


class WebWindow(QMainWindow):
    def __init__(self, api, init: dict):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(WEB / "icon.png")))
        self.resize(1280, 860)
        self.setMinimumSize(980, 640)
        self.backend = Backend(api)
        api.attach(self)

        view = QWebEngineView(self)
        page = Page(view)
        view.setPage(page)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        # 첫 페인트 전에 필요한 값(테마 등) → qwebchannel.js → bridge.js 순으로 페이지보다 먼저 심는다
        boot = ("window.__MM_INIT__ = " + json.dumps(init, ensure_ascii=False) + ";\n"
                + _qrc_text(":/qtwebchannel/qwebchannel.js") + "\n"
                + (WEB / "bridge.js").read_text(encoding="utf-8"))
        sc = QWebEngineScript()
        sc.setName("mm-bridge")
        sc.setSourceCode(boot)
        sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
        sc.setWorldId(QWebEngineScript.MainWorld)
        sc.setRunsOnSubFrames(False)
        page.scripts().insert(sc)
        ch = QWebChannel(page)
        ch.registerObject("backend", self.backend)
        page.setWebChannel(ch)
        view.load(QUrl.fromLocalFile(str(WEB / "index.html")))
        self.view = view
        self.setCentralWidget(view)
