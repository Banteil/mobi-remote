"""Npcap(wpcap.dll) 로 게임 서버가 보내는 TCP 조각을 받는다 — 수신 함수만 선언하고 보내는 함수(pcap_sendpacket 등)는 쓰지 않는다.
필터는 'tcp src port 16000' (게임 서버가 보내는 쪽)."""
import ctypes
import os
import socket
from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_long, c_uint, c_ubyte, c_ushort, c_void_p
from pathlib import Path

SERVER_PORT = 16000
NPCAP_DIR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Npcap"


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
