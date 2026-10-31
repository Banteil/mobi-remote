"""염색 재질 그림 (Cloth·Leather·Metal·Wood, 254×254) — 게임 설치 폴더의 리소스에서 **읽기만** 해서 꺼낸다.

게임 파일은 저장소·배포본에 넣지 않는다. 처음 쓸 때 게임 폴더에서 꺼내 데이터 폴더에 캐시하고,
게임이 패치돼 목차(index)가 바뀌면 다시 꺼낸다.

리소스 묶음 (ResourcesPackage\\Starter):
  index        경로 목차 — 경로마다 (BlobKey, 묶음 안 번호). BlobKey 의 0x8000 은 Starter, 나머지 비트가 묶음 번호.
  NNNN.blob    항목 목록 = 오프셋 표 + 항목들. 항목 = Romu-trio 난수 XOR(시드: 항목 오프셋·크기)
               → 4바이트 원래 크기 + raw deflate. 묶음 안 번호는 1부터.
"""
from __future__ import annotations

import ctypes
import json
import struct
import zlib
from ctypes import wintypes
from pathlib import Path

import cv2
import numpy as np

NAMES = ("Cloth", "Leather", "Metal", "Wood")
TEX = 254
_DIR = "DyeMaterialColorPalettes/"

M64 = (1 << 64) - 1
_MUL = 0xD3833E804F4C574B


def _rol(v, r):
    return ((v << r) | (v >> (64 - r))) & M64


def _unxor(data: bytes, h1: int, h2: int) -> bytes:
    """항목 난독화 풀기 (GameAssembly 의 묶음 읽기와 같은 Romu-trio 흐름)."""
    h1 &= M64
    h2 &= M64
    t = ((((~h2) & M64) ^ h1) + 0x171974E5E5BDDA11) & M64
    x = (t * _MUL) & M64
    rdx = (h2 + 0x849EE64C9720BB37) & M64
    rcx = (h1 + 0x708B6BA5FB11F033) & M64
    z = _rol((t - rdx) & M64, 44)
    y = _rol((rdx - rcx) & M64, 12)
    out = bytearray(data)
    n = len(out)
    i = 0
    while i < n:
        xp = x
        x = (z * _MUL) & M64
        y2 = _rol((y - xp) & M64, 12)
        z = _rol((z - y) & M64, 44)
        y = y2
        k = struct.pack("<Q", xp)
        for j in range(min(8, n - i)):
            out[i + j] ^= k[j]
        i += 8
    return bytes(out)


def _lzs(data: bytes, pos: int) -> str:
    out = bytearray()
    b = data[pos]
    while b:
        pos += 1
        if b < 0x80:
            ln, src, nxt = b, pos, pos + b
        else:
            v = ((b & 0x7F) << 8) | data[pos]
            ln, src, nxt = (v & 0x1F) + 1, pos - (v >> 5) - 2, pos + 1
        out += data[src:src + ln]
        b = data[nxt]
        pos = nxt
    return out.decode("utf-8", "replace")


def _index(fn: Path) -> dict[str, tuple[int, int]]:
    """목차 → {경로: (BlobKey, 묶음 안 번호)}."""
    d = fn.read_bytes()
    p = 4
    n = struct.unpack_from("<i", d, p)[0]
    p += 4
    items = [struct.unpack_from("<HH", d, p + 4 * i) for i in range(n)]
    p += 4 * n
    nd = struct.unpack_from("<I", d, p)[0]
    p += 4
    for _ in range(nd):
        p += 4
        c = struct.unpack_from("<I", d, p)[0]
        p += 4 + 4 * c
    hn = struct.unpack_from("<i", d, p)[0]
    p += 4 + 4 * hn
    pn = struct.unpack_from("<i", d, p)[0]
    p += 4
    paths = struct.unpack_from("<%dQ" % pn, d, p)
    p += 8 * pn
    bn = struct.unpack_from("<i", d, p)[0]
    p += 4 + 4 * bn
    blocks = []
    for _ in range(3):
        ln = struct.unpack_from("<i", d, p)[0]
        blocks.append(d[p + 4:p + 4 + ln])
        p += 4 + ln
    dt, nm, pf = blocks
    cache: dict[int, str] = {}

    def dirpath(i):
        if i in cache:
            return cache[i]
        j = i + 1
        while dt[j] > 4:
            j += 1
        name, t = dt[i:j].decode("utf-8", "replace"), dt[j]
        r = name if t == 0 else dirpath(i - int.from_bytes(dt[j + 1:j + 1 + t], "little")) + "/" + name
        cache[i] = r
        return r

    out = {}
    for k, v in enumerate(paths):
        di, ni, po = v & 0xFFFFFF, (v >> 24) & 0xFFFFFFF, v >> 52
        path = dirpath(di) + "/" + _lzs(nm, ni) + _lzs(pf, po)
        if _DIR in path:
            out[path[path.index(_DIR):]] = items[k]
    return out


def _entry(blob: Path, i: int) -> bytes:
    with open(blob, "rb") as fh:
        head = fh.read(8)
        n = struct.unpack_from("<I", head, 4)[0]
        offs = struct.unpack("<%dI" % (n // 4), fh.read(n))
        s, e = offs[i], offs[i + 1]
        fh.seek(s)
        raw = fh.read(e - s)
    p = _unxor(raw, s, e - s)
    return zlib.decompress(p[4:], -15)


def game_dir_of(hwnd: int) -> Path | None:
    """게임 창을 띄운 프로세스의 실행 파일 폴더."""
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        return Path(buf.value).parent
    finally:
        k32.CloseHandle(h)


def load(cache_dir: Path, game_dir: Path | None) -> dict[str, np.ndarray] | None:
    """재질 이름 → 그림 (BGR, **행 아래부터** = 텍스처 v 증가 방향). 꺼낼 수 없으면 None.
    cache_dir 에 png 로 두고, 게임 목차의 크기·시각이 같으면 그대로 쓴다."""
    cache_dir = Path(cache_dir)
    stamp = None
    idx = None
    if game_dir:
        idx = Path(game_dir) / "ResourcesPackage" / "Starter" / "index"
        if idx.exists():
            st = idx.stat()
            stamp = [st.st_size, int(st.st_mtime)]
    meta = cache_dir / "materials.json"
    files = {n: cache_dir / f"{n}.png" for n in NAMES}
    try:
        old = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None
    except (OSError, ValueError):
        old = None
    have = all(f.exists() for f in files.values())
    if have and (stamp is None or old == stamp):
        return {n: cv2.imread(str(f))[::-1].copy() for n, f in files.items()}
    if stamp is None:
        return {n: cv2.imread(str(f))[::-1].copy() for n, f in files.items()} if have else None
    where = _index(idx)
    out = {}
    for n in NAMES:
        key = where.get(f"{_DIR}{n}.bmp")
        if not key:
            return None
        bk, ix = key
        blob = idx.parent / f"{bk & 0x7FFF:04d}.blob"
        img = cv2.imdecode(np.frombuffer(_entry(blob, ix - 1), np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.shape[:2] != (TEX, TEX):
            return None
        out[n] = img
    cache_dir.mkdir(parents=True, exist_ok=True)
    for n, img in out.items():
        cv2.imwrite(str(files[n]), img)
    meta.write_text(json.dumps(stamp), encoding="utf-8")
    return {n: img[::-1].copy() for n, img in out.items()}
