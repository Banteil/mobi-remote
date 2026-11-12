"""패킷 감시 본체: 캡처 스레드를 돌려 메시지를 이벤트로 풀고, 봇이 기다리고 묻는 창구(wait·find·saw …)를 준다.
상태 반영은 Events, CLI 맞추기는 CliSync, 끊김 단서 로그는 LinkWatch 에서 상속한다."""
import hashlib
import logging
import threading
import time
from collections import deque
from pathlib import Path

from .. import packet_diag
from ..spear import SpearState
from .appearing import appearing_is_mine, appearing_name
from .capture import SERVER_PORT, _Capture
from .cli_sync import CliSync
from .events import Events
from .link_watch import LinkWatch
from .state import PacketState, Seen
from .stream import Stream, parse_tcp

log = logging.getLogger("mabi")


def game_metadata() -> Path | None:
    """게임의 IL2CPP 메타데이터 (메시지 번호표의 출처). CLI 를 찾는 경로로 게임 폴더를 찾는다. 못 찾으면 None."""
    from ..connector import candidates
    for exe, _ in candidates():
        f = Path(exe).parent / "MabinogiMobile_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"
        if f.exists():
            return f
    return None


class PacketMonitor(LinkWatch, CliSync, Events):
    GAME_CHECK = 60  # 게임 파일이 바뀌었나 보는 간격 (초) — 리모콘을 켠 채 게임이 패치될 수 있다

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.status = "off"          # off / running / no_npcap / no_table / stale_table / error
        self._game_file: Path | None | bool = None  # False = 찾아봤는데 없음
        self._game_mtime = 0.0
        self._game_checked = 0.0
        self.error = ""
        self.state = PacketState()
        self.recent: deque[Seen] = deque(maxlen=500)
        # 이벤트마다 그 뒤의 상태 사본 — '이 뒤에 한 번이라도 그랬나' (saw). 로딩·이동 시작처럼 금방 지나가는 상태를
        # 지금 값만 보고 기다리면, 화면을 보는 사이에 지나가 버려 놓친다 (2026-10-28 사용자와 정한 규칙)
        self.history: deque[tuple[int, PacketState]] = deque(maxlen=3000)
        self.last_rx = 0.0           # 마지막으로 서버 패킷을 받은 때 (monotonic)
        # 서버 연결 끊김 단서 (점검 등) — 판단에 쓰기 전에 실제로 무엇이 오는지 로그로 먼저 본다 (2026-11-12 사용자)
        self._closed: tuple[float, str, str] | None = None  # 서버가 마지막으로 연결을 닫은 때 (시각, FIN·RST, 서버 주소)
        self._opened = 0.0           # 서버와 새 연결이 마지막으로 열린 때 (시각)
        self._silent = False         # 무수신 로그를 남겼다 (다시 받으면 한 줄 더 남기고 푼다)
        self._seq = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.table = None
        self.diag = None
        self.spear = SpearState()  # 흩어진 물길 투창 패턴 (그 맵에서만 쌓는다)

    # 봇이 쓰는 것 ──────────────────────────────────

    @property
    def ok(self) -> bool:
        """신호를 믿어도 되는가 (돌고 있고 최근 30초 안에 서버 패킷을 받음 — 로딩 중엔 몇 초씩 조용하다)."""
        self._check_game()
        return self.status == "running" and time.monotonic() - self.last_rx < 30

    def _check_game(self) -> None:
        """게임이 패치돼 표를 묶은 메타데이터와 달라지면 감시를 'stale_table' 로 — 봇은 CLI·화면으로 돈다.
        패치로 메시지 번호 대부분이 바뀌어(11-05: 3,213개 중 2,877개) 옛 표로는 자동 이동 시작을 못 알아보고
        '이동 안 함' 이 남아 CLI 로 넘어가지도 않았다. 다른 메시지를 상태 이벤트로 잘못 읽을 수도 있다."""
        want = (self.table.meta.get("game_metadata_sha256") if self.table else "") or ""
        now = time.monotonic()
        if self.status != "running" or not want or now - self._game_checked < self.GAME_CHECK:
            return
        self._game_checked = now
        try:
            if self._game_file is None:
                self._game_file = game_metadata() or False
            if not self._game_file:
                return
            mtime = self._game_file.stat().st_mtime
            if mtime == self._game_mtime:
                return
            self._game_mtime = mtime
            got = hashlib.sha256(self._game_file.read_bytes()).hexdigest()[:len(want)]
        except OSError:
            return
        if got != want:
            self.status = "stale_table"
            self.diag.record("table_load", "stale_table", error=f"게임 메타데이터 {got} ≠ 표 {want}")
            log.warning("게임이 업데이트돼 패킷 표가 맞지 않음 → 패킷 신호를 끄고 CLI·화면으로 판단 (새 판 리모콘 필요)")

    DYE_LIMIT = 240   # 미니게임 제한 2분 + '적용하시겠습니까?' 창 여유. 끝 신호를 놓쳐도 이만큼 지나면 닫힌 것으로

    def dye_open(self) -> bool | None:
        """염색 미니게임이 열려 있나 (패킷). 표에 염색 신호가 없거나 감시가 안 돌면 None — 부르는 쪽은 화면으로만 본다."""
        if self.status != "running" or self.table is None or self.table.by_key("dye.open") is None:
            return None
        t = self.state.dye_open_at
        if t is None and not self.state.dye_known and time.monotonic() - getattr(self, "started_at", 0) < self.DYE_LIMIT:
            # 감시를 켜기 전에 이미 열려 있었을 수 있다 (미니게임 중에 리모콘을 켬) — 열림 알림을 못 봤으니 화면으로 본다
            return None
        return t is not None and time.monotonic() - t < self.DYE_LIMIT

    def at_charselect(self) -> bool | None:
        """캐릭터 선택 화면인가 (로그아웃 뒤 아직 게임 서버에 안 들어감). 모르면 None.
        선택 화면에선 서버 패킷이 아예 안 와서 ok(최근 30초 수신)를 따지지 않는다 — 게임이 꺼졌는지는 부르는 쪽이 본다."""
        if self.status != "running" or self.state.in_game is None:
            return None
        return not self.state.in_game

    def mark(self) -> int:
        """지금까지 본 이벤트 번호. wait(after=mark()) 로 '이 뒤에 온 것만' 기다린다."""
        with self._cond:
            return self._seq

    def find(self, key: str, after: int, check=None) -> Seen | None:
        """after 뒤에 온 key 중 처음 것 (check(vals) 가 참인 것만)."""
        with self._cond:
            for s in self.recent:
                if s.seq > after and s.key == key and (check is None or check(s.vals)):
                    return s
        return None

    def last(self, key: str, after: int = 0) -> Seen | None:
        with self._cond:
            for s in reversed(self.recent):
                if s.seq <= after:
                    return None
                if s.key == key:
                    return s
        return None

    def saw(self, pred, after: int) -> bool:
        """after 뒤 어느 순간이든 상태가 pred 를 만족한 적이 있나 (지금 상태 포함)."""
        with self._cond:
            if pred(self.state):
                return True
            return any(seq > after and pred(st) for seq, st in self.history)

    def changed(self, timeout: float) -> None:
        """새 이벤트가 오거나 timeout 이 지날 때까지 잔다."""
        with self._cond:
            self._cond.wait(timeout)

    def wait(self, keys, timeout: float, after: int | None = None, check=None, stop=None) -> Seen | None:
        """keys(이벤트 이름 하나 또는 여럿) 중 하나가 after 뒤에 오면 돌려준다. check(vals) 로 값 조건.
        감시가 꺼져 있으면 바로 None — 부르는 쪽은 화면 인식으로 넘어간다. stop() 이 참이면 그만 기다린다."""
        keys = {keys} if isinstance(keys, str) else set(keys)
        if after is None:
            after = self.mark()
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                for s in self.recent:
                    if s.seq > after and s.key in keys and (check is None or check(s.vals)):
                        return s
                left = end - time.monotonic()
                if left <= 0 or self.status != "running" or (stop and stop()):
                    return None
                self._cond.wait(min(left, 0.5))

    # 켜고 끄기 ──────────────────────────────────────

    def start(self) -> "PacketMonitor":
        if self._thread and self._thread.is_alive():
            return self
        self.table, self.diag = packet_diag.open_table(self.logs_dir)
        if self.table is None:
            self.status = "no_table"
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="packet-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.diag:
            self.diag.summary()

    def _run(self):
        try:
            cap = _Capture()
        except OSError as e:
            self.status = "no_npcap" if "Npcap" in str(e) else "error"
            self.error = str(e)
            self.diag.record("capture", self.status, error=str(e))
            log.info("패킷 감시 꺼짐: %s", e)
            return
        self.status = "running"
        self.started_at = time.monotonic()
        log.info("패킷 감시 시작 (%s)", cap.device)
        self._check_game()
        streams: dict[tuple, Stream] = {}
        try:
            while not self._stop.is_set():
                frame = cap.next()
                if frame is None:
                    self._watch_silence()
                    continue
                p = parse_tcp(frame, cap.link)
                if p is None or p[1] != SERVER_PORT:
                    continue
                src, _, dport, seq, flags, payload = p
                self._link(src, flags)
                self.last_rx = time.monotonic()
                key = (src, dport)
                st = streams.get(key)
                if st is None or flags & 0x02:
                    st = streams[key] = Stream(self.table.known, lambda why, k=key: self._desync(why, k))
                for proto, flag, body in st.feed(seq, flags, payload):
                    self._handle(proto, flag, body)
                if flags & 0x05:  # FIN/RST — 다른 서버로 옮겨 감 (끊김일 수도 — _link 가 적어 둔다)
                    streams.pop(key, None)
        except OSError as e:
            self.status, self.error = "error", str(e)
            self.diag.record("capture", "error", error=str(e))
            log.warning("패킷 감시 멈춤: %s", e)
        finally:
            cap.close()
            if self.status == "running":
                self.status = "off"
            with self._cond:
                self._cond.notify_all()

    def _handle(self, proto: int, flag: int, body: bytes):
        ev = self.table.event(proto)
        if ev is None:
            self.table.decode(proto, b"")  # 처음 보는 번호면 기록만
            return
        if ev.key.startswith("system."):
            self._server_notice(ev.key, flag, body)
        if ev.key.startswith("spear.") and not self.spear.active:
            return  # 흩어진 물길 밖 — 이동 메시지 등은 풀지도 않는다
        if flag and ev.fields:  # 읽을 필드가 없으면 풀 필요도 없다
            try:
                import brotli
                body = brotli.decompress(body)
            except Exception as e:  # noqa: BLE001 — brotli.error 는 import 해야 보인다
                self.diag.record("decompress", ev.key, body, error=str(e))
                return
        _, vals = self.table.decode(proto, body)
        if ev.key.startswith("spear."):
            self._spear(ev.key, vals)
            return
        if ev.key == "char.appearing":  # 내 고유 번호 + 자기 기록 표시가 있으면 내 캐릭터 (위치는 3094~3150 으로 들쭉날쭉)
            vals["mine"] = appearing_is_mine(body, self.state.char_id)
            if vals["mine"]:
                vals["name"] = appearing_name(body)
        self.apply(ev.key, vals)

    def _spear(self, key: str, vals: dict) -> None:
        """투창 패턴 이벤트 — 알릴 일(내가 대상·파훼·끝 등)이면 남기고 기다리는 봇을 깨운다."""
        msg = self.spear.feed(key, vals, self.state.me)
        if msg:
            log.info("패킷: %s", msg)
            with self._cond:
                self._cond.notify_all()

    def _desync(self, why: str, key) -> None:
        """스트림 조각을 잃었다 — 그 사이 이벤트(맵 이동·던전 나감·이동 끝 …)를 놓쳤을 수 있다. 기록하고 놓치면 틀리는
        상태를 모름으로 돌린다 (2026-10-30: 00:05 공백 뒤 지난밤 던전 Cleared 가 아침까지 남음)."""
        self.diag.record("stream_desync", why, server=f"{key[0]}:{key[1]}")
        self.forget(f"패킷 흐름 끊김 ({why})")


_shared: PacketMonitor | None = None
_shared_lock = threading.Lock()


def current() -> PacketMonitor | None:
    """이미 켜진 공유 감시 (없으면 None — 켜지 않는다. 설정에서 패킷 감시를 끈 경우)."""
    return _shared


def shared(logs_dir: Path) -> PacketMonitor:
    """프로세스에 하나. 처음 부를 때 켠다."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PacketMonitor(logs_dir).start()
        return _shared
