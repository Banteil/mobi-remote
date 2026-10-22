"""화면들이 같이 쓰는 것: 커넥터·캐시·조회, 연결 상태, 앱 설정, 백그라운드 실행.

CLI 호출은 50ms~수 초(게임이 꺼져 있으면 5초)라 화면 스레드에서 부르면 창이 굳는다.
run_bg(fn, done) 으로 작업 스레드에서 돌리고 결과만 화면 스레드로 받는다.
"""
import json
import logging
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from mabi import paths as mpaths
from mabi.cache import QueryCache
from mabi.calllog import CallLog
from mabi.compat import Compat
from mabi.connector import Connector
from mabi import errors
from mabi.connector import parse_cost
from mabi.query import Query
from mabi.store import Favorites, Playlists

log = logging.getLogger("mabi")

DEFAULT_SETTINGS = {
    "cli_path": "",          # 비우면 자동 탐색
    "refresh_interval": 10,  # 초. 0 = 자동 갱신 끔
    "close_to_tray": False,
}


class _Relay(QObject):
    done = Signal(object, object)  # (결과, 예외)


class _Job(QRunnable):
    def __init__(self, fn, relay: _Relay):
        super().__init__()
        self.fn, self.relay = fn, relay

    def run(self) -> None:
        try:
            r, e = self.fn(), None
        except Exception as ex:  # 화면에 넘겨서 보여 준다
            log.exception("백그라운드 작업 실패")
            r, e = None, ex
        try:
            self.relay.done.emit(r, e)
        except RuntimeError:  # 창이 닫히는 중
            pass


class Services(QObject):
    connection = Signal(dict)   # {connected, reason, ...} — 바뀔 때만
    tick = Signal()             # 자동 갱신 시각 (각 화면이 보이는 것만 다시 읽는다)
    notice = Signal(str, str)   # (종류 ok|bad|info, 문장) — 상태바에 띄운다
    action_state = Signal(bool, str)  # (진행 중?, 무엇) — 취소 버튼

    def __init__(self, paths: mpaths.Paths):
        super().__init__()
        self.paths = paths
        self.settings = self._load_settings()
        self.cli = Connector(lambda: self.settings.get("cli_path") or None, log)
        self.calllog = CallLog(paths.logs)
        self.cli.on_call = self.calllog.record
        self.cache = QueryCache(self.cli, paths.data / "cache")
        self.query = Query(self.cache)
        self.compat = Compat(self.cli, paths.data / "compat.json", self._remote_seed())
        from mabi import craft
        self.cd = craft.configure(paths.data, paths.resources / "data")
        self.playlists = Playlists(paths.data / "playlists.json")
        self.favorites = Favorites(paths.data / "favorites.json")
        self.pool = QThreadPool.globalInstance()
        self._relays: set[_Relay] = set()
        self.online: bool | None = None   # None = 아직 모름
        self.reason: str | None = None
        self._status_at = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)
        self.set_interval(self.settings.get("refresh_interval", 10))

    # ---- 설정 ----
    def _load_settings(self) -> dict:
        s = dict(DEFAULT_SETTINGS)
        try:
            s.update(json.loads(self.paths.settings.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        return s

    def save_settings(self, **kw) -> None:
        self.settings.update(kw)
        self.paths.settings.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _remote_seed():
        p = mpaths.PROJECT.parent / "mobi-remote-legacy" / "compat.json"  # 개발 PC 에만 있다
        return p if p.exists() else None

    # ---- 백그라운드 ----
    def run_bg(self, fn, done=None) -> None:
        """fn() 을 작업 스레드에서, done(result, error) 를 화면 스레드에서."""
        relay = _Relay()
        self._relays.add(relay)

        def finish(r, e):
            self._relays.discard(relay)
            if done:
                done(r, e)
        relay.done.connect(finish)
        self.pool.start(_Job(fn, relay))

    # ---- 게임 행동 ----
    def action(self, command: str, body=None, done=None, label: str = "", timeout: float | None = None) -> None:
        """게임 행동 명령 하나. 진행 중 표시, 실패는 한국어로 알림, 비용이 나갔으면 남은 양까지 알린다.
        done(result) 은 화면 스레드에서 (실패여도 불린다)."""
        if self.cli.busy():
            self.notice.emit("bad", "다른 명령이 진행 중입니다")
            return
        what = label or command
        self.action_state.emit(True, what)

        def fin(r, e):
            self.action_state.emit(False, "")
            if r is None:
                self.notice.emit("bad", f"{what}: 실행 실패 ({e})")
            elif r.ok:
                cost = parse_cost((r.data or {}).get("cost") if isinstance(r.data, dict) else None)
                self.notice.emit("ok", f"{what} 완료" + (f" — {cost['currency']} {cost['spent']} 사용, {cost['left']:,} 남음" if cost else ""))
                self.cache.clear("get_currencies")
            else:
                self.notice.emit("bad", f"{what}: " + errors.line(command, r.error, r.message or "", r.data))
            if done:
                done(r)
        self.run_bg(lambda: self.cli.run(command, body, timeout=timeout), fin)

    def cancel(self) -> None:
        self.cli.cancel()

    # ---- 연결 ----
    def opts(self, **kw) -> dict:
        """조회 옵션. 연결이 확인되기 전이나 꺼져 있으면 캐시로 직행한다 (연결 실패 판정에만 5초).
        연결되면 tick 이 화면들을 다시 읽게 한다."""
        return {"offline": self.online is not True, **kw}

    def check_status(self, done=None) -> None:
        def work():
            return self.cli.status()

        def fin(st, err):
            st = st or {"connected": False, "reason": "error"}
            changed = st["connected"] != self.online or st.get("reason") != self.reason
            self.online, self.reason = st["connected"], st.get("reason")
            self._status_at = time.monotonic()
            if changed:
                self.connection.emit(st)
            if done:
                done(st, err)
        self.run_bg(work, fin)

    def set_interval(self, sec: int) -> None:
        self.settings["refresh_interval"] = sec
        if sec:
            self.timer.start(sec * 1000)
        else:
            self.timer.stop()

    def _on_timer(self) -> None:
        # 꺼져 있으면 20초에 한 번만 연결을 다시 본다
        if self.online is False and time.monotonic() - self._status_at < 20:
            return
        if self.online is not True:
            self.check_status(lambda st, e: st.get("connected") and self.tick.emit())
            return
        if not self.cli.busy():  # 게임 행동 명령이 진행 중이면 조회로 끼어들지 않는다
            self.tick.emit()
