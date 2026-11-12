"""받은 TCP 조각 → 메시지. 이더넷/IP/TCP 머리를 벗기고(parse_tcp), 서버 연결 하나의 수신 스트림을 순서대로 이어
[메시지 번호 u32][길이 u32][압축 u8][본문] 로 자른다(Stream). 연결 처음엔 인사 블록 'MMCG'[길이 u32][내용] 하나."""
import socket
import struct

HDR = 9
HELLO = b"MMCG"             # 연결 첫머리 인사 블록 (메시지가 아니다)
MAX_FRAME = 8 << 20         # 맵 진입 때 오는 것 중 큰 건 0.8MB 쯤
MAX_PENDING = 512           # 순서가 뒤바뀐 조각을 이만큼까지 들고 기다린다
SYNC_FRAMES = 3             # 중간부터 받기 시작했을 때 이만큼 연달아 말이 되면 맞춘 것으로 본다


# ── 이더넷/IP/TCP ───────────────────────────────────────────────────

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
