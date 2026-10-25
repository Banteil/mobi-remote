"""게임 패킷 상태 표 (리소스 data\\packet-states.bin).

게임 서버가 보내는 메시지 번호 → 상태 이벤트(던전 상태, 맵 진입, 사망 등)와 본문 읽는 법,
상태값 이름(enum), 채널(맵) 이름·종류를 담는다. 화면 인식을 보조하는 신호로만 쓴다 — 패킷은 받기만 한다.

파일은 압축 + 암호화(SHA-256 스트림, HMAC-SHA256 위변조 검사)돼 있다. 키(packet.key)는 저장소에 넣지 않는다 —
개발 PC 의 프로젝트 폴더에만 두고, tools\\build.py 가 배포판 app\\ 에 넣는다. 배포판 안에는 키가 있으므로
공개 저장소에서 바로 보이지 않게 하는 정도이지 보안 장치는 아니다. 표에는 우리가 붙인 이벤트 이름·메시지 번호·읽는 자리만 두고
게임 내부 메시지 이름은 넣지 않는다. 원본 명세와 묶는 도구는 저장소 밖(mabi-packets)에 있다.

게임 패치로 메시지 번호가 바뀌면 표를 다시 묶어 데이터 폴더(paths.data)\\data 에 넣으면 그쪽이 우선한다 (gamedata 와 같은 규칙).
"""
import hashlib
import hmac
import json
import os
import struct
import zlib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import paths

FILE_NAME = "packet-states.bin"
KEY_NAME = "packet.key"   # 16진수 한 줄. 없으면 표를 못 연다 (패킷 신호 없이 화면 인식만으로 돈다)
MAGIC = b"MRPT"
VERSION = 2
_NONCE = 16
_TAG = 32


def key_file() -> Path:
    return paths.resource_dir() / KEY_NAME


@cache
def _keys() -> tuple[bytes, bytes]:
    f = key_file()
    if not f.exists():
        raise FileNotFoundError(f"키 파일 없음: {f}")
    secret = bytes.fromhex(f.read_text(encoding="ascii").strip())
    return (hashlib.sha256(b"enc" + secret).digest(),
            hashlib.sha256(b"mac" + secret).digest())


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(key + nonce + struct.pack("<Q", counter)).digest()
        counter += 1
    return bytes(out[:n])


def _xor(data: bytes, ks: bytes) -> bytes:
    return (int.from_bytes(data, "little") ^ int.from_bytes(ks, "little")).to_bytes(len(data), "little")


def seal(payload: dict) -> bytes:
    """표(dict) → 파일 내용. 묶는 도구(mabi-packets\\tools\\pack_states.py)가 쓴다."""
    enc, mac = _keys()
    nonce = os.urandom(_NONCE)
    plain = zlib.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    head = MAGIC + bytes([VERSION]) + nonce
    body = _xor(plain, _stream(enc, nonce, len(plain)))
    return head + body + hmac.new(mac, head + body, hashlib.sha256).digest()


def unseal(blob: bytes) -> dict:
    if blob[:4] != MAGIC or len(blob) < 5 + _NONCE + _TAG:
        raise ValueError("패킷 상태 표 형식이 아님")
    if blob[4] != VERSION:
        raise ValueError(f"패킷 상태 표 판 번호가 다름: {blob[4]}")
    enc, mac = _keys()
    head, body, tag = blob[:5 + _NONCE], blob[5 + _NONCE:-_TAG], blob[-_TAG:]
    if not hmac.compare_digest(tag, hmac.new(mac, head + body, hashlib.sha256).digest()):
        raise ValueError("패킷 상태 표가 손상됐거나 바뀜")
    plain = _xor(body, _stream(enc, head[5:], len(body)))
    return json.loads(zlib.decompress(plain).decode("utf-8"))


@dataclass(frozen=True)
class Field:
    name: str
    off: int
    type: str
    enum: str = ""
    lookup: str = ""
    size: int = 0  # u64list: 항목 하나의 바이트 수
    at: int = 0    # u64list: 항목 안에서 읽을 u64 위치


@dataclass(frozen=True)
class Event:
    key: str
    proto: int
    status: str  # confirmed(실측) / candidate(아직 실측 안 함)
    desc: str
    fields: tuple[Field, ...] = field(default_factory=tuple)

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


class Table:
    def __init__(self, data: dict):
        self.diag = None  # packet_diag.PacketDiag — 붙어 있으면 표와 안 맞는 패킷을 기록한다
        self.meta: dict = data["meta"]
        self.known: frozenset[int] = frozenset(data["known"])  # 게임에 있는 메시지 번호 전부 (처음 보는 번호 가려내기용)
        self.enums: dict[str, dict[int, str]] = {
            n: {int(k): v for k, v in vals.items()} for n, vals in data["enums"].items()}
        self.channels: dict[int, dict] = {int(k): v for k, v in data["channels"].items()}
        # 리모콘이 판단하는 상태 → 쓰는 이벤트·PacketState 필드·대체 수단·아직 못 하는 것 (spec/states.json 의 states)
        self.states: list[dict] = data.get("states", [])
        self._events: dict[int, Event] = {}
        self._by_key: dict[str, Event] = {}
        for e in data["events"]:
            ev = Event(e["key"], e["proto"], e["status"], e["desc"],
                       tuple(Field(**f) for f in e.get("fields", ())))
            self._events[ev.proto] = ev
            self._by_key[ev.key] = ev

    def event(self, proto: int) -> Event | None:
        return self._events.get(proto)

    def by_key(self, key: str) -> Event | None:
        return self._by_key.get(key)

    def events(self) -> list[Event]:
        return list(self._events.values())

    def channel(self, cid: int) -> dict | None:
        """{'type': 'InstanceDungeon' 등, 'name': 이름(던전·사냥터·필드만)} 또는 None (표에 없는 새 맵)."""
        return self.channels.get(cid)

    def enum(self, name: str) -> dict[int, str]:
        return self.enums.get(name, {})

    def decode(self, proto: int, body: bytes) -> tuple[Event, dict] | None:
        """상태 이벤트면 (이벤트, 읽은 값). 본문이 짧아 못 읽은 필드는 빠진다."""
        ev = self._events.get(proto)
        if ev is None:
            if proto not in self.known:
                self._problem("unknown_proto", f"0x{proto:06x}", body)
            return None
        vals = {}
        for f in ev.fields:
            v = _read(body, f.off, f.type, f.size, f.at)
            if v is None:
                self._problem("short_body", ev.key, body, field=f.name, off=f.off, type=f.type)
                continue
            vals[f.name] = v
            if f.enum:
                name = self.enum(f.enum).get(v)
                if name is None:
                    self._problem("unknown_enum", f"{ev.key}.{f.name}={v}", body, enum=f.enum)
                vals[f.name + "_name"] = name or "?"
            if f.lookup == "channels":
                ch = self.channel(v)
                if ch is None and v:
                    self._problem("unknown_channel", str(v), None, event=ev.key)
                vals[f.name + "_name"] = ch.get("name", "") if ch else ""
                vals[f.name + "_type"] = ch["type"] if ch else ""
        return ev, vals

    def _problem(self, kind: str, key: str, body: bytes | None, **info) -> None:
        if self.diag is not None:
            self.diag.record(kind, key, body, **info)


_FMT = {"u8": "<B", "u32": "<I", "i32": "<i", "u64": "<Q", "f32": "<f"}


def _read(body: bytes, off: int, typ: str, size: int = 0, at: int = 0):
    if typ == "u64list":  # u32 개수 + size 바이트씩 — 각 항목 at 위치의 u64
        if off + 4 > len(body):
            return None
        n = struct.unpack_from("<I", body, off)[0]
        if size < at + 8 or off + 4 + n * size > len(body):
            return None
        return [struct.unpack_from("<Q", body, off + 4 + i * size + at)[0] for i in range(n)]
    if typ == "bool":
        return bool(body[off]) if off < len(body) else None
    if typ == "str32":
        if off + 4 > len(body):
            return None
        n = struct.unpack_from("<I", body, off)[0]
        raw = body[off + 4: off + 4 + n]
        return raw.decode("utf-16le", "replace") if len(raw) == n else None
    fmt = _FMT[typ]
    if off + struct.calcsize(fmt) > len(body):
        return None
    return struct.unpack_from(fmt, body, off)[0]


def _candidates() -> list[Path]:
    out = []
    try:
        out.append(paths.load().data / "data" / FILE_NAME)
    except OSError:
        pass
    out.append(paths.resource_dir() / "data" / FILE_NAME)
    return out


@cache
def load() -> Table:
    for f in _candidates():
        if f.exists():
            return Table(unseal(f.read_bytes()))
    raise FileNotFoundError(f"데이터 파일 없음: data\\{FILE_NAME}")
