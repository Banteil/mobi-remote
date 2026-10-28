"""블랙박스 — 직전 몇십 초의 화면·누른 것·패킷 이벤트를 들고 있다가 실패하면 폴더 하나로 남긴다.

실패 스샷 한 장은 '멈춘 순간' 만 보여 줘서, 그 앞에 무엇을 눌렀고 화면이 어떻게 바뀌었는지는 로그로 짐작해야
했다 (2026-10-28 사용자와 정한 개선 2번). 화면은 1초에 한 장, 반 크기 JPG 로 메모리에만 들고 있다가 dump() 때 쓴다.
"""
import shutil
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

SECONDS = 30    # 들고 있는 길이
EVERY = 1.0     # 화면을 몇 초마다 한 장
SCALE = 0.5     # 줄여서 담는다 (1920x1080 → 960x540, 장당 50KB 남짓)
KEEP = 20       # 남겨 두는 블랙박스 폴더 수 (오래된 것부터 지운다)


class BlackBox:
    def __init__(self, seconds: float = SECONDS, every: float = EVERY, scale: float = SCALE):
        self.seconds, self.every, self.scale = seconds, every, scale
        self.frames: deque[tuple[float, bytes]] = deque()   # (time.time(), jpg)
        self.inputs: deque[tuple[float, str]] = deque()     # (time.time(), '키 space' 등)
        self._last = 0.0
        self._lock = threading.Lock()

    def _trim(self, q: deque, now: float) -> None:
        while q and now - q[0][0] > self.seconds:
            q.popleft()

    def frame(self, img: np.ndarray | None) -> None:
        now = time.time()
        if img is None or now - self._last < self.every:
            return
        self._last = now
        small = cv2.resize(img, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return
        with self._lock:
            self.frames.append((now, buf.tobytes()))
            self._trim(self.frames, now)

    def input(self, what: str) -> None:
        now = time.time()
        with self._lock:
            self.inputs.append((now, what))
            self._trim(self.inputs, now)

    def dump(self, root: Path, tag: str, packets=None, last: np.ndarray | None = None) -> Path | None:
        """root/블랙박스_<시각>_<tag>/ 에 화면(장마다 시각)과 timeline.txt 를 쓴다. 쓴 폴더를 돌려준다.
        last: 지금 화면 (마지막 한 장이 1초 전 것일 수 있어 따로 받는다)."""
        if last is not None:
            self._last = 0.0
            self.frame(last)
        now = time.time()
        with self._lock:
            frames = [f for f in self.frames if now - f[0] <= self.seconds]
            inputs = [i for i in self.inputs if now - i[0] <= self.seconds]
        if not frames and not inputs:
            return None
        d = root / f"blackbox_{datetime.now():%Y%m%d_%H%M%S}_{tag}"
        try:
            d.mkdir(parents=True, exist_ok=True)
            for at, jpg in frames:
                (d / f"{datetime.fromtimestamp(at):%H%M%S}_{int(at * 10) % 10}.jpg").write_bytes(jpg)
            lines = [(at, f"누름  {what}") for at, what in inputs]
            lines += [(at, f"화면  {datetime.fromtimestamp(at):%H%M%S}_{int(at * 10) % 10}.jpg") for at, _ in frames]
            lines += packet_lines(packets, now, self.seconds)
            lines.sort(key=lambda x: x[0])
            text = "\n".join(f"{datetime.fromtimestamp(at):%H:%M:%S}.{int(at * 10) % 10}  {s}" for at, s in lines)
            (d / "timeline.txt").write_text(text + "\n", encoding="utf-8")
        except OSError:
            return None
        prune(root)
        return d


def packet_lines(packets, now: float, seconds: float) -> list[tuple[float, str]]:
    """패킷 이벤트(monotonic 시각)를 벽시계 시각으로 바꿔 timeline 줄로."""
    if packets is None:
        return []
    mono = time.monotonic()
    try:
        with packets._cond:
            seen = list(packets.recent)
    except AttributeError:
        return []
    out = []
    for s in seen:
        at = now - (mono - s.at)
        if now - at <= seconds:
            vals = ", ".join(f"{k}={v}" for k, v in s.vals.items()) if s.vals else ""
            out.append((at, f"패킷  {s.key} {vals}".rstrip()))
    return out


def prune(root: Path, keep: int = KEEP) -> None:
    dirs = sorted(p for p in root.glob("blackbox_*") if p.is_dir())
    for p in dirs[:-keep] if keep else dirs:
        shutil.rmtree(p, ignore_errors=True)
