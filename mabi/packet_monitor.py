"""게임 서버 → 클라이언트 패킷을 받아 상태(맵 이동, 던전 상태 등)를 알려 준다. 화면 인식을 보조하는 신호.

받기만 한다 — Npcap(wpcap.dll)의 수신 함수만 선언하고, 보내는 함수(pcap_sendpacket 등)는 쓰지 않는다.
필터는 'tcp src port 16000' (게임 서버가 보내는 쪽). 서버 주소는 맵(필드·던전 인스턴스)마다 바뀐다.

스트림: 연결 처음에 인사 블록 'MMCG'[길이 u32][내용] 하나, 그 뒤로 [메시지 번호 u32][길이 u32][압축 u8][본문],
압축 1 = Brotli. 해석은 packet_table, 어긋남 기록은 packet_diag.
Npcap 이 없거나 표·키가 없으면 꺼진 채(status)로 있고, 봇은 화면 인식만으로 돈다 — 패킷 신호는 늘 '있으면 빠르게'.

봇은 프로세스 하나에 감시 하나를 같이 쓴다 (shared). 큐는 카드마다 Bot 을 새로 만들기 때문.
"""
import copy
import ctypes
import logging
import os
import socket
import struct
import threading
import time
from collections import deque
from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_long, c_uint, c_ubyte, c_ushort, c_void_p
from dataclasses import dataclass, field
from pathlib import Path

from . import packet_diag

log = logging.getLogger("mabi")

SERVER_PORT = 16000
NPCAP_DIR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Npcap"
HDR = 9
NO_TARGET = 0xFFFFFFFFFFFFFFFF
_WEAPON = struct.pack("<I", 12) + "Weapon".encode("utf-16le")  # 등장 캐릭터의 도구 목록 첫 항목
_ONE = bytes.fromhex("0000803f00000000")                          # 도구 목록 뒤, 이름 바로 앞 (f32 1.0 + 0)
HELLO = b"MMCG"             # 연결 첫머리 인사 블록 (메시지가 아니다)
MAX_FRAME = 8 << 20         # 맵 진입 때 오는 것 중 큰 건 0.8MB 쯤
MAX_PENDING = 512           # 순서가 뒤바뀐 조각을 이만큼까지 들고 기다린다
OPEN_MAPS = ("Field", "BattleField", "FieldBoss", "HousingInn", "ScenarioField")  # 던전이 아닌 맵 종류
# CLI 가 같은 뜻으로 알려 주는 오래 남는 상태 — CLI 를 물을 때마다 그 답으로 맞춘다 (merge_cli)
CLI_FACTS = ("dungeon_state", "field_state", "dead")
CLI_LAG = 5.0  # CLI 가 패킷보다 늦게 바뀌는 시간 (쓰러짐 약 3초, death1 실측) — 패킷이 이보다 최근에 바꿨으면 패킷을 믿는다
SYNC_FRAMES = 3             # 중간부터 받기 시작했을 때 이만큼 연달아 말이 되면 맞춘 것으로 본다


# ── Npcap (수신 함수만) ─────────────────────────────────────────────

class _SockAddr(Structure):
    _fields_ = [("family", c_ushort), ("data", c_ubyte * 14)]


class _PcapAddr(Structure):
    pass


_PcapAddr._fields_ = [("next", POINTER(_PcapAddr)), ("addr", POINTER(_SockAddr)), ("netmask", POINTER(_SockAddr)),
                      ("broadaddr", POINTER(_SockAddr)), ("dstaddr", POINTER(_SockAddr))]


class _PcapIf(Structure):
    pass


_PcapIf._fields_ = [("next", POINTER(_PcapIf)), ("name", c_char_p), ("description", c_char_p),
                    ("addresses", POINTER(_PcapAddr)), ("flags", c_uint)]


class _PktHdr(Structure):
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long), ("caplen", c_uint), ("len", c_uint)]


class _BpfProgram(Structure):
    _fields_ = [("bf_len", c_uint), ("bf_insns", c_void_p)]


def _load_wpcap():
    if not (NPCAP_DIR / "wpcap.dll").exists():
        raise OSError("Npcap 이 설치돼 있지 않음")
    os.add_dll_directory(str(NPCAP_DIR))
    lib = ctypes.CDLL(str(NPCAP_DIR / "wpcap.dll"))
    lib.pcap_findalldevs.argtypes = [POINTER(POINTER(_PcapIf)), c_char_p]
    lib.pcap_freealldevs.argtypes = [POINTER(_PcapIf)]
    lib.pcap_open_live.argtypes = [c_char_p, c_int, c_int, c_int, c_char_p]
    lib.pcap_open_live.restype = c_void_p
    lib.pcap_compile.argtypes = [c_void_p, POINTER(_BpfProgram), c_char_p, c_int, c_uint]
    lib.pcap_setfilter.argtypes = [c_void_p, POINTER(_BpfProgram)]
    lib.pcap_freecode.argtypes = [POINTER(_BpfProgram)]
    lib.pcap_datalink.argtypes = [c_void_p]
    lib.pcap_next_ex.argtypes = [c_void_p, POINTER(POINTER(_PktHdr)), POINTER(POINTER(c_ubyte))]
    lib.pcap_geterr.argtypes = [c_void_p]
    lib.pcap_geterr.restype = c_char_p
    lib.pcap_close.argtypes = [c_void_p]
    return lib


def _local_ip() -> str:
    """기본 경로의 내 IP. UDP connect 는 주소만 정하고 아무것도 보내지 않는다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    finally:
        s.close()


def _pick_device(lib) -> bytes:
    devs = POINTER(_PcapIf)()
    err = ctypes.create_string_buffer(256)
    if lib.pcap_findalldevs(byref(devs), err) != 0:
        raise OSError(err.value.decode(errors="replace"))
    try:
        want = _local_ip()
    except OSError:
        want = ""
    first = None
    try:
        d = devs
        while d:
            a = d.contents.addresses
            while a:
                sa = a.contents.addr
                if sa and sa.contents.family == socket.AF_INET:
                    ip = socket.inet_ntoa(bytes(sa.contents.data[2:6]))
                    if ip == want:
                        return d.contents.name
                    if first is None and not ip.startswith("127."):
                        first = d.contents.name
                a = a.contents.next
            d = d.contents.next
    finally:
        lib.pcap_freealldevs(devs)
    if first is None:
        raise OSError("캡처할 네트워크 장치가 없음")
    return first


class _Capture:
    def __init__(self):
        self.lib = _load_wpcap()
        dev = _pick_device(self.lib)
        err = ctypes.create_string_buffer(256)
        self.h = self.lib.pcap_open_live(dev, 65535, 0, 200, err)
        if not self.h:
            raise OSError(err.value.decode(errors="replace"))
        prog = _BpfProgram()
        if self.lib.pcap_compile(self.h, byref(prog), f"tcp src port {SERVER_PORT}".encode(), 1, 0xFFFFFFFF) != 0:
            raise OSError(self.lib.pcap_geterr(self.h).decode(errors="replace"))
        self.lib.pcap_setfilter(self.h, byref(prog))
        self.lib.pcap_freecode(byref(prog))
        self.link = self.lib.pcap_datalink(self.h)
        self.device = dev.decode(errors="replace")

    def next(self) -> bytes | None:
        """패킷 하나 (없으면 0.2초 뒤 None)."""
        hdr = POINTER(_PktHdr)()
        data = POINTER(c_ubyte)()
        r = self.lib.pcap_next_ex(self.h, byref(hdr), byref(data))
        if r == 1:
            return ctypes.string_at(data, hdr.contents.caplen)
        if r == 0:
            return None
        raise OSError(self.lib.pcap_geterr(self.h).decode(errors="replace"))

    def close(self):
        if self.h:
            self.lib.pcap_close(self.h)
            self.h = None


# ── 이더넷/IP/TCP ───────────────────────────────────────────────────

def _ascii16_end(b: bytes, i: int) -> int | None:
    """i 에 u32 바이트 길이 + UTF-16 영문 문자열이 있으면 그 끝 위치."""
    if i + 4 > len(b):
        return None
    n = struct.unpack_from("<I", b, i)[0]
    if not (2 <= n <= 64 and n % 2 == 0) or i + 4 + n > len(b):
        return None
    s = b[i + 4:i + 4 + n]
    if any(s[x + 1] or not 0x41 <= s[x] <= 0x7A for x in range(0, n, 2)):
        return None
    return i + 4 + n


def appearing_name(body: bytes) -> str | None:
    """등장 캐릭터 메시지에서 캐릭터 이름. 이름 앞에 길이가 들쭉날쭉한 도구 목록이 있어 항목을 따라간다:
    [영문 도구 이름][u32 칸][u32 n][n×u32][u32 c][c×8 색] … 다음 [00 00 80 3f 00 00 00 00][u32 바이트 길이][UTF-16 이름].
    캡처 5개의 등장 메시지 427건 모두 이렇게 읽힘 (2026-10-25). 모양이 다르면 None."""
    try:
        i = body.find(_WEAPON)
        if i < 0:
            return None
        while (j := _ascii16_end(body, i)) is not None:
            n = struct.unpack_from("<I", body, j + 4)[0]
            if n > 16:
                return None
            j += 8 + 4 * n
            c = struct.unpack_from("<I", body, j)[0]
            if c > 32:
                return None
            i = j + 4 + 8 * c
        k = body.find(_ONE, i, i + 64)
        if k < 0:
            return None
        n = struct.unpack_from("<I", body, k + 8)[0]
        if not (2 <= n <= 40 and n % 2 == 0):
            return None
        return body[k + 12:k + 12 + n].decode("utf-16le")
    except (struct.error, UnicodeDecodeError):
        return None


def parse_tcp(frame: bytes, link: int = 1):
    """(서버 IP, 서버 포트, 내 포트, seq, flags, payload) 또는 None. link 1 = 이더넷."""
    if link != 1 or len(frame) < 14:
        return None
    off, etype = 14, struct.unpack_from("!H", frame, 12)[0]
    if etype == 0x8100:  # VLAN
        etype = struct.unpack_from("!H", frame, 16)[0]
        off = 18
    if etype != 0x0800 or len(frame) < off + 20:
        return None
    ihl = (frame[off] & 0x0F) * 4
    total = struct.unpack_from("!H", frame, off + 2)[0]
    if frame[off + 9] != 6:
        return None
    src = socket.inet_ntoa(frame[off + 12:off + 16])
    t = off + ihl
    if len(frame) < t + 20:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", frame, t)
    doff = (frame[t + 12] >> 4) * 4
    flags = frame[t + 13]
    end = min(len(frame), off + total) if total else len(frame)
    return src, sport, dport, seq, flags, frame[t + doff:end]


# ── 스트림 → 메시지 ─────────────────────────────────────────────────

class Stream:
    """서버 연결 하나의 수신 스트림. feed() 가 다 모인 메시지 (번호, 압축, 본문) 를 돌려준다."""

    def __init__(self, known: frozenset[int], on_desync=None):
        self.known = known
        self.on_desync = on_desync
        self.next_seq: int | None = None
        self.pending: dict[int, bytes] = {}
        self.buf = bytearray()
        self.synced = False

    def feed(self, seq: int, flags: int, payload: bytes) -> list[tuple[int, int, bytes]]:
        if flags & 0x02:  # SYN: 연결 처음부터 받음 → 메시지 경계가 맞다
            self.next_seq, self.pending, self.buf, self.synced = (seq + 1) & 0xFFFFFFFF, {}, bytearray(), True
            return []
        if not payload:
            return []
        if self.next_seq is None:  # 연결 중간부터 받기 시작함
            self.next_seq = seq
        diff = (seq - self.next_seq) & 0xFFFFFFFF
        if diff >= 0x80000000:  # 이미 받은 자리 (재전송) — 새 부분만
            cut = (self.next_seq - seq) & 0xFFFFFFFF
            if cut >= len(payload):
                return []
            payload, seq = payload[cut:], self.next_seq
            diff = 0
        if diff > 0:  # 앞 조각이 아직 안 옴
            self.pending[seq] = payload
            if len(self.pending) > MAX_PENDING:  # 빠진 조각이 끝내 안 옴 → 버리고 다시 맞춘다
                self._lost("gap")
            return []
        self._append(payload)
        while self.next_seq in self.pending:
            self._append(self.pending.pop(self.next_seq))
        return self._frames()

    def _append(self, data: bytes):
        self.buf += data
        self.next_seq = (self.next_seq + len(data)) & 0xFFFFFFFF

    def _lost(self, why: str):
        if self.on_desync:
            self.on_desync(why)
        self.pending.clear()
        self.buf.clear()
        self.next_seq = None
        self.synced = False

    def _plausible(self, off: int) -> int | None:
        """off 에서 시작하는 메시지 헤더가 말이 되면 다음 메시지 위치."""
        if off + HDR > len(self.buf):
            return None
        proto, n, flag = struct.unpack_from("<IIB", self.buf, off)
        if flag > 1 or n > MAX_FRAME or proto not in self.known:
            return None
        return off + HDR + n

    def _sync(self) -> bool:
        b = len(self.buf)
        for start in range(min(b, 65536)):
            off, count = start, 0
            while count < SYNC_FRAMES:
                nxt = self._plausible(off)
                if nxt is None:
                    break
                count += 1
                off = nxt
                if off >= b:
                    break
            if count >= SYNC_FRAMES or (count and off == b):
                del self.buf[:start]
                self.synced = True
                return True
        if b > 1 << 20:  # 1MB 를 모아도 못 맞춤
            self._lost("sync")
        return False

    def _frames(self) -> list[tuple[int, int, bytes]]:
        if not self.synced and not self._sync():
            return []
        out, off = [], 0
        while off + HDR <= len(self.buf):
            if self.buf[off:off + 4] == HELLO:
                n = struct.unpack_from("<I", self.buf, off + 4)[0]
                if off + 8 + n > len(self.buf):
                    break
                off += 8 + n
                continue
            proto, n, flag = struct.unpack_from("<IIB", self.buf, off)
            if flag > 1 or n > MAX_FRAME:
                del self.buf[:off]
                self.synced = False
                if self.on_desync:
                    self.on_desync("header")
                return out + self._frames()
            if off + HDR + n > len(self.buf):
                break
            out.append((proto, flag, bytes(self.buf[off + HDR:off + HDR + n])))
            off += HDR + n
        del self.buf[:off]
        return out


# ── 상태 ────────────────────────────────────────────────────────────

@dataclass
class Seen:
    seq: int
    at: float      # time.monotonic()
    key: str
    vals: dict


@dataclass
class PacketState:
    """패킷으로 알게 된 지금 상태. 감시를 켠 뒤 처음 오기 전까지는 모른다(None)."""
    channel: int | None = None
    channel_type: str = ""
    channel_name: str = ""
    loading: bool = False            # 맵을 떠났고 새 맵에 아직 안 들어감
    in_game: bool | None = None      # 게임 서버 입장 뒤 True, 로그아웃(캐릭터 선택 화면) 뒤 False. 감시를 켠 뒤 둘 다 없었으면 None
    dungeon_state: str | None = None  # NotInDungeon / Entering / InProgress / Cleared
    dungeon: int | None = None
    abyss_result: int = 0            # 어비스 결과 (클리어 순간 어비스 번호, 나가면 0)
    abyss_matching: int = 0          # 우연한 만남 매칭: 0 없음 · 1 요청 · 2 찾는 중 · 3 잡힘 (어비스 맵에 들어가면 0)
    # 레이드 (caps/raid1 2026-10-28): Lobby 배 위 · InProgress 출항~판 진행 · Cleared 보스 처치. 감시를 켠 뒤 안 왔으면 None
    raid_state: str | None = None
    raid_result: int = 0             # 레이드 결과 (보스 처치 순간 레이드 번호, 맵을 옮기면 0)
    raid_boss: bool = False          # 이 맵에서 레이드 보스전이 시작됨
    field_state: str | None = None   # 사냥터: NotInBattlefield / InProgress / WaitingForChannelTransfer(클리어)
    boss_battle: bool = False
    dead: bool | None = None         # 내 캐릭터가 쓰러짐 (부활 창 열림). 나한테만 오는 부활 가능 여부로 안다
    dead_at: float = 0.0             # 쓰러진 때 (monotonic)
    revives_used: int | None = None  # 이 판에서 쓴 부활 횟수 (화면의 '남은 부활 횟수' = 최대 - 쓴 횟수)
    revives_max: int | None = None
    satiety: int | None = None
    # 장비 내구도 비율 (현재/최대) — 수리(또는 캐릭터 바꿈) 뒤로 깎임 알림에서 본 가장 낮은 값. 알림에 장비 번호가 없어
    # 어느 장비인지 모르니 가장 낮은 것을 쓴다. 감시를 켠 뒤 아직 안 깎였으면 None
    durability: float | None = None
    weight: float | None = None
    max_weight: float | None = None
    char_id: int | None = None       # 내 캐릭터 고유 번호 (안 바뀜) — 맵을 옮길 때마다 오는 내 개인 데이터 맨 앞
    me: int | None = None            # 내 캐릭터 오브젝트 번호 — 맵마다 바뀐다. 등장 캐릭터 중 고유 번호가 든 것 (없으면 포만감 설정)
    my_name: str | None = None       # 접속한 캐릭터 이름 (내 등장 메시지에서). 캐릭터를 바꾸면 다음 맵 진입 때 새로 안다
    dialogue_npc: int | None = None  # 대화 중인 NPC 오브젝트 번호 (대화 중이 아니면 None)
    # 지금 대사 뒤 할 일 (대사 내용의 dialogueAction): SelectKeyword 메뉴 버튼 · EndDialogue 작별 인사(눌러야 끝남) ·
    # OpenNPCRepair 대장간 수리 창 · AfterRepair 수리 뒤 등. 대화가 아니면 ''
    dialogue_action: str = ""
    dialogue_step: int = 0           # 대사마다 1씩 오른다 — 눌러서 대사가 넘어갔는지 본다
    dialogue_menu: bool = False      # NPC 메뉴(선택지 버튼)가 떠 있음
    ai: str = ""                     # 내 캐릭터 자동 행동 (InteractAI = NPC 에게 다가가는 중)
    cutscene: bool = False           # 컷신(연출) 재생 중
    traveling: bool | None = None    # 내 자동 이동 중 (시작·끝은 나한테만 온다). 감시를 켠 뒤 한 번도 안 왔으면 None
    travel_points: int = 0           # 이번 자동 이동의 경로 점 개수
    travel_index: int = 0            # 지금 향하는 점 번호 (남은 점 = travel_points - travel_index)
    fast_travel_ok: bool | None = None  # 지금 빠른 이동(T)이 되는가 (FastTravelAvailableState == Enabled)
    combat: str | None = None        # 내 전투 상태 NonCombat / CombatReady / InCombat / CombatEnd. 내 번호를 알아야 안다
    entered_at: float = 0.0          # 마지막 맵 진입 (monotonic)
    dimensions_cleared: list | None = None  # 깬 검은 구멍들이 나타난 시각 (ms). 맵에 들어갈 때마다 온다
    # 퀘스트 창 '추천' 항목 종류 (RecommendedActivityType). 2(요일 던전)면 요일 던전을 아직 안 한 것.
    # 2 가 빠지는 건 클리어(Add 6 → Remove 2)일 수도, 가방 정리(5)에 밀린 것(weight1 13:12:45)일 수도 있어 완료 신호로 못 쓴다
    recommend: int | None = None
    # 출석 대화 시작 (monotonic, 0 = 없음). 날짜가 바뀐 뒤 메인 화면으로 갈 때 NPC 가 한두 마디(무작위) 한 뒤 출석부와
    # '출석부 건너뛰기' 가 뜬다. 끝 신호는 아직 모른다 → 건너뛰기를 누르거나 맵을 옮기면 지우고, 오래되면 끝난 것으로 본다
    attendance_at: float = 0.0
    changed_at: dict = field(default_factory=dict)  # CLI_FACTS 필드 → 패킷이 마지막으로 바꾼 때 (monotonic)
    extra: dict = field(default_factory=dict)

    def attending(self, limit: float = 90) -> bool:
        """출석 대화 중 (시작 패킷을 받고 아직 건너뛰지 않음)."""
        return bool(self.attendance_at) and time.monotonic() - self.attendance_at < limit

    @property
    def fresh(self) -> bool:
        """감시를 켠 뒤 맵에 들어온 적이 있나 — 그러면 대화·컷신처럼 '없음' 이 기본인 상태도 믿을 수 있다."""
        return self.channel is not None

    @property
    def in_combat(self) -> bool | None:
        return None if self.combat is None else self.combat in ("CombatReady", "InCombat")

    @property
    def in_dialogue(self) -> bool:
        return self.dialogue_npc is not None


class PacketMonitor:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.status = "off"          # off / running / no_npcap / no_table / error
        self.error = ""
        self.state = PacketState()
        self.recent: deque[Seen] = deque(maxlen=500)
        # 이벤트마다 그 뒤의 상태 사본 — '이 뒤에 한 번이라도 그랬나' (saw). 로딩·이동 시작처럼 금방 지나가는 상태를
        # 지금 값만 보고 기다리면, 화면을 보는 사이에 지나가 버려 놓친다 (2026-10-28 사용자와 정한 규칙)
        self.history: deque[tuple[int, PacketState]] = deque(maxlen=3000)
        self.last_rx = 0.0           # 마지막으로 서버 패킷을 받은 때 (monotonic)
        self._seq = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.table = None
        self.diag = None

    # 봇이 쓰는 것 ──────────────────────────────────

    @property
    def ok(self) -> bool:
        """신호를 믿어도 되는가 (돌고 있고 최근 30초 안에 서버 패킷을 받음 — 로딩 중엔 몇 초씩 조용하다)."""
        return self.status == "running" and time.monotonic() - self.last_rx < 30

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
        log.info("패킷 감시 시작 (%s)", cap.device)
        streams: dict[tuple, Stream] = {}
        try:
            while not self._stop.is_set():
                frame = cap.next()
                if frame is None:
                    continue
                p = parse_tcp(frame, cap.link)
                if p is None or p[1] != SERVER_PORT:
                    continue
                src, _, dport, seq, flags, payload = p
                self.last_rx = time.monotonic()
                key = (src, dport)
                st = streams.get(key)
                if st is None or flags & 0x02:
                    st = streams[key] = Stream(self.table.known, lambda why, k=key: self._desync(why, k))
                for proto, flag, body in st.feed(seq, flags, payload):
                    self._handle(proto, flag, body)
                if flags & 0x05:  # FIN/RST — 다른 서버로 옮겨 감
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
        if flag and ev.fields:  # 읽을 필드가 없으면 풀 필요도 없다
            try:
                import brotli
                body = brotli.decompress(body)
            except Exception as e:  # noqa: BLE001 — brotli.error 는 import 해야 보인다
                self.diag.record("decompress", ev.key, body, error=str(e))
                return
        _, vals = self.table.decode(proto, body)
        if ev.key == "char.appearing":  # 내 고유 번호가 들어 있으면 내 캐릭터 (death1 등 캡처 4개에서 확인, 위치는 3094~3150 으로 들쭉날쭉)
            cid = self.state.char_id
            vals["mine"] = cid is not None and struct.pack("<Q", cid) in body
            if vals["mine"]:
                vals["name"] = appearing_name(body)
        self.apply(ev.key, vals)

    def _desync(self, why: str, key) -> None:
        """스트림 조각을 잃었다 — 그 사이 이벤트(맵 이동·던전 나감·이동 끝 …)를 놓쳤을 수 있다. 기록하고 놓치면 틀리는
        상태를 모름으로 돌린다 (2026-10-30: 00:05 공백 뒤 지난밤 던전 Cleared 가 아침까지 남음)."""
        self.diag.record("stream_desync", why, server=f"{key[0]}:{key[1]}")
        self.forget(f"패킷 흐름 끊김 ({why})")

    def forget(self, why: str) -> None:
        """이벤트로만 바뀌는 상태를 모름(None)으로. 다음 패킷이 오거나, 그 전엔 CLI·화면으로 판단한다.
        맵도 모름으로 둔다 — fresh 가 거짓이 되어 대화·컷신의 '없음' 도 믿지 않게 된다."""
        s = self.state
        s.channel, s.channel_type, s.channel_name = None, "", ""
        s.dungeon_state = s.field_state = s.dead = s.traveling = s.fast_travel_ok = s.combat = None
        s.abyss_matching, s.boss_battle, s.cutscene = 0, False, False
        s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
        log.info("패킷: %s → 맵·던전·이동 등 상태를 모름으로 (다음 패킷이나 CLI 로 다시 앎)", why)
        with self._cond:
            self._cond.notify_all()

    def merge_cli(self, act: dict, asked_at: float) -> list[str]:
        """CLI get_activity 답이 올 때마다 오래 남는 상태(CLI_FACTS: 던전·사냥터 안팎·쓰러짐)를 그 답으로 맞춘다 — 가장
        믿을 정보는 CLI 이고, 패킷은 바뀌는 순간을 빨리 알리는 데 쓴다. 다만 패킷이 asked_at(물은 때) 이후나 CLI_LAG
        안에 바꾼 값은 패킷이 더 새로우니 둔다. 대화·이동·전투 같은 순간 상태는 패킷이 빠르고 CLI 와 뜻이 조금 달라
        (메뉴 대기 등) 여기서 덮지 않는다 — 작업 시작 점검(reconcile)에서만 맞춘다. 바뀐 것 ['이름 전 → 후']."""
        s = self.state
        dungeon = (act.get("Dungeon") or {}).get("State") or None
        field_in = bool((act.get("Battlefield") or {}).get("IsInBattleField"))
        want = {
            "dungeon_state": dungeon or s.dungeon_state,
            # 사냥터 안이면 InProgress·WaitingForChannelTransfer 를 CLI 가 가르지 못한다 → 밖이라던 패킷만 모름으로
            "field_state": ("NotInBattlefield" if not field_in
                            else None if s.field_state == "NotInBattlefield" else s.field_state),
            "dead": bool(act.get("IsDead")),
        }
        out = []
        recent = min(asked_at, time.monotonic() - CLI_LAG)
        for f, v in want.items():
            cur = getattr(s, f)
            if cur == v or s.changed_at.get(f, 0.0) > recent:
                continue
            setattr(s, f, v)
            out.append(f"{f} {cur} → {v}")
        if out:
            log.info("CLI 로 맞춤: %s", ", ".join(out))
            with self._cond:
                self._cond.notify_all()
        return out

    def reconcile(self, act: dict | None) -> list[str]:
        """새 작업을 시작할 때 (처음이든 이어 하기든 — 그 사이 사람이 무엇을 했을지 모른다): 지난 일에서 남은 상태를
        그대로 믿지 않고 지금 게임에 맞춘다. 상태가 바뀌는 패킷을 놓치면 (스트림 공백 등) 지난밤 상태가 아침까지 남는다
        (2026-10-30 06:44: 던전 Cleared 로 6명 모두 접속 실패).
        act(CLI get_activity) 가 있으면 그 답으로, 없으면(로딩·캐릭터 선택 화면) 모름(None)으로 — 다음 패킷이나
        CLI·화면으로 다시 본다. 맵 종류가 CLI 와 어긋나면 (마을인데 던전 안·사냥터 안이라 함, 던전·사냥터 맵인데
        밖이라 함) 맵도 모름으로 돌린다 — 장소 이름은 CLI 와 패킷이 달라 ('마스 심층 던전 1층 2구역' /
        '마스 3_2 던전 (심층 1층 2구역) 매우 어려움') 비교하지 않는다. 레이드·어비스 결과는 맵 종류로 가린다.
        바뀐 것 ['이름 전 → 후']."""
        s = self.state
        before = {"맵": s.channel_name, "던전": s.dungeon_state, "사냥터": s.field_state, "쓰러짐": s.dead,
                  "레이드": s.raid_state}
        if act:
            s.loading = False
            dungeon = (act.get("Dungeon") or {}).get("State") not in (None, "NotInDungeon")
            field = bool((act.get("Battlefield") or {}).get("IsInBattleField"))
            t = s.channel_type
            if t and ((t in OPEN_MAPS and dungeon) or (t == "BattleField") != field
                      or (t == "InstanceDungeon" and not dungeon)):
                s.channel, s.channel_type, s.channel_name = None, "", ""
            s.dungeon_state = (act.get("Dungeon") or {}).get("State") or None
            if not (act.get("Battlefield") or {}).get("IsInBattleField"):
                s.field_state = "NotInBattlefield"
            elif s.field_state in (None, "NotInBattlefield"):
                s.field_state = None  # 사냥터 안인데 패킷은 밖이라 한다 → 모름
            s.dead = bool(act.get("IsDead"))
            s.traveling = bool(act.get("IsAutoTraveling"))
            s.combat = "InCombat" if act.get("IsInCombat") else "NonCombat"
            s.boss_battle = bool((act.get("Dungeon") or {}).get("IsBossBattleInProgress"))
            if not s.traveling:
                s.fast_travel_ok = None  # 다음 자동 이동 때 다시 온다
            if not act.get("IsDialoguePlaying"):
                s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
        else:
            s.dungeon_state = s.field_state = s.dead = s.traveling = s.combat = s.fast_travel_ok = None
        if s.channel_type not in ("InstanceRaid", "InstanceRaidLobby"):
            s.raid_state, s.raid_result, s.raid_boss = None, 0, False
        if s.channel_type != "InstanceAbyssDungeon":
            s.abyss_result = 0
        after = {"맵": s.channel_name, "던전": s.dungeon_state, "사냥터": s.field_state, "쓰러짐": s.dead,
                 "레이드": s.raid_state}
        return [f"{k} {before[k]} → {after[k]}" for k in before if before[k] != after[k]]

    def apply(self, key: str, vals: dict) -> None:
        """이벤트 하나를 상태에 반영하고 기다리는 쪽을 깨운다 (시험에서 직접 부르기도 한다)."""
        s = self.state
        old = {f: getattr(s, f) for f in CLI_FACTS}
        if key == "channel.leaving":
            s.loading = True
            s.attendance_at = 0.0
        elif key == "channel.entering":
            s.loading = False
            s.channel, s.channel_type, s.channel_name = vals.get("channel"), vals.get("channel_type", ""), \
                vals.get("channel_name", "")
            s.entered_at = time.monotonic()
            s.in_game = True  # 감시를 켠 뒤 처음 맵을 옮긴 경우에도 알게
            s.cutscene = False
            s.fast_travel_ok = None  # 새 맵 — 빠른 이동 가능 여부는 다음 자동 이동 때 다시 온다
            if s.channel_type == "InstanceAbyssDungeon":
                s.abyss_matching = 0
            s.abyss_result = 0  # 새 맵 — 지난 판 결과는 끝났다 (나갈 때 0 이 오는지 실측이 없어 여기서도 지운다)
            s.raid_result, s.raid_boss = 0, False
            s.dead = None  # 쓰러진 채 맵을 옮기면 부활 신호가 안 올 수 있다 → 다시 쓰러질 때까지 CLI 로
            # 마을·사냥터면 던전 밖이다. 던전을 나가는 패킷(NotInDungeon)을 놓치면 지난밤 'Cleared' 가 남아,
            # 아침에 접속 단계가 메인 화면을 던전 클리어 화면으로 알고 6명 모두 3분씩 헛돌았다 (2026-10-30 06:44)
            if s.channel_type in OPEN_MAPS and s.dungeon_state not in (None, "NotInDungeon"):
                s.dungeon_state = "NotInDungeon"
            # 대화는 맵을 옮기면 끝난다 — 끝 패킷 없이 끊긴 대화가 '대화 중' 으로 남아 끼어들기·정리가 헛돌지 않게
            s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
            log.info("패킷: 맵 진입 %s (%s)", s.channel_name or s.channel, s.channel_type or "?")
        elif key == "session.logout_ok":  # 캐릭터 선택 화면으로 (me1 03:29:30 — 맵 떠남·세션 정리와 같은 때)
            s.in_game, s.loading = False, False
            s.me = s.my_name = None
            s.attendance_at = 0.0
            s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
            log.info("패킷: 로그아웃 → 캐릭터 선택 화면")
        elif key == "session.entered":  # 게임 서버 입장 (접속·서버 옮김). 맵 진입은 몇 초 뒤
            if s.in_game is False:
                s.loading = True
            s.in_game = True
        elif key == "daily.attendance_start":
            s.attendance_at = time.monotonic()
            log.info("패킷: 출석 대화 시작")
        elif key == "dungeon.state":
            s.dungeon_state = vals.get("state_name")
            log.info("패킷: 던전 상태 %s", s.dungeon_state)
        elif key == "abyss.result":
            s.abyss_result = vals.get("abyss") or 0
        elif key == "raid.state":
            s.raid_state = vals.get("state_name")
            log.info("패킷: 레이드 상태 %s", s.raid_state)
        elif key == "raid.result":
            s.raid_result = vals.get("raid") or 0
            log.info("패킷: 레이드 결과 옴")
        elif key == "raid.boss_begin":
            s.raid_boss = True
        elif key == "abyss.matching_update":
            s.abyss_matching = vals.get("state") or 0
        elif key == "abyss.matching_cancel_ok":
            s.abyss_matching = 0
        elif key == "field.context":
            s.field_state = vals.get("state_name")
            log.info("패킷: 사냥터 상태 %s", s.field_state)
        elif key == "dungeon.current":
            s.dungeon = vals.get("channel") or None
        elif key == "dungeon.boss_battle":
            s.boss_battle = bool(vals.get("on"))
        elif key == "dialogue.target":
            t = vals.get("target")
            s.dialogue_npc = None if t in (None, NO_TARGET) else t
        elif key in ("dialogue.cleared", "dialogue.force_end") or key == "dialogue.update" and vals.get("active") is False:
            s.dialogue_npc = None
            s.dialogue_action, s.dialogue_menu = "", False
        elif key == "dialogue.update":
            s.dialogue_action, s.dialogue_step = vals.get("action") or "", vals.get("step") or s.dialogue_step
        elif key == "dialogue.prompt":
            s.dialogue_menu = bool(vals.get("open"))
        elif key == "char.personal_data":
            if vals.get("char_id") != s.char_id:  # 다른 캐릭터로 접속 — 맵에 들어가야 새 번호·이름을 안다
                s.me = s.my_name = None
                s.durability = None
                s.recommend = None  # 앞 캐릭터의 추천 항목 (요일 던전 '안 함' 판단)이 남지 않게
            s.char_id = vals.get("char_id")
        elif key == "char.appearing":
            if vals.get("mine"):
                if vals.get("actor") != s.me:
                    s.combat = "NonCombat"  # 맵에 막 들어옴 — 싸우는 중이면 곧 전투 상태가 온다
                s.me = vals.get("actor")
                s.my_name = vals.get("name") or s.my_name
                log.info("패킷: 내 캐릭터 %s (번호 %s)", s.my_name or "?", s.me)
        elif key == "actor.dead":
            if s.me is not None and vals.get("actor") == s.me:  # 파티 판에서는 부활 창 신호가 안 온다 (death1 03:10:24)
                s.dead = bool(vals.get("dead"))
                if s.dead:
                    s.dead_at = time.monotonic()
                log.info("패킷: 내 캐릭터 %s", "쓰러짐" if s.dead else "일어남")
        elif key == "revive.availability":
            was, s.dead = s.dead, bool(vals.get("available"))
            if s.dead:
                s.dead_at = time.monotonic()
            if s.dead or was:  # 맵에 들어갈 때마다 0 이 오므로 쓰러져 있다가 풀릴 때만 '부활'로 남긴다
                log.info("패킷: %s", "쓰러짐" if s.dead else "부활")
        elif key == "dimension.cleared":
            s.dimensions_cleared = vals.get("times")
        elif key == "recommend.add":
            s.recommend = vals.get("type")
        elif key == "revive.count":
            s.revives_used, s.revives_max = vals.get("used"), vals.get("max")
        elif key in ("revive.checkpoint_ok", "revive.item_ok"):
            s.dead = False
        elif key == "cutscene.play":
            s.cutscene = True
        elif key in ("cutscene.end", "cutscene.abort"):
            s.cutscene = False
        elif key == "travel.begin":
            s.traveling, s.travel_points, s.travel_index = True, vals.get("points") or 0, 0
        elif key == "travel.target":
            s.travel_index = vals.get("index") or 0
        elif key == "travel.end":
            s.traveling, s.fast_travel_ok = False, False
        elif key == "fast_travel.state":
            s.fast_travel_ok = vals.get("available_name") == "Enabled"
        elif key == "actor.combat_state":
            if s.me is not None and vals.get("actor") == s.me:
                s.combat = vals.get("state_name")
        elif key == "char.ai":
            s.ai = vals.get("ai", "")
        elif key == "char.satiety":
            s.satiety = vals.get("satiety")
            s.me = vals.get("actor", s.me)
        elif key == "equip.durability":
            r = vals.get("ratio")
            if r is not None:
                s.durability = r if s.durability is None else min(s.durability, r)
        elif key == "equip.repair_ok":
            s.durability = None
            log.info("패킷: 장비 수리됨")
        elif key == "char.weight":
            s.weight = vals.get("weight")
        elif key == "char.max_weight":
            s.max_weight = vals.get("max_weight")
        now = time.monotonic()
        for f, v in old.items():
            if getattr(s, f) != v:
                s.changed_at[f] = now
        with self._cond:
            self._seq += 1
            self.recent.append(Seen(self._seq, time.monotonic(), key, vals))
            self.history.append((self._seq, copy.copy(s)))
            self._cond.notify_all()


_shared: PacketMonitor | None = None
_shared_lock = threading.Lock()


def shared(logs_dir: Path) -> PacketMonitor:
    """프로세스에 하나. 처음 부를 때 켠다."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PacketMonitor(logs_dir).start()
        return _shared
