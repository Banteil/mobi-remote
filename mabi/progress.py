"""'나아가고 있으면 계속 기다린다' 제한 시간.

정해진 시간으로 끊으면 오래 걸리지만 잘 되고 있는 일까지 실패가 된다 (2026-10-24: 100개짜리 채집을 5분에 끊어
82/100 에서 '물품 부족' 으로 건너뜀). 대신 진행 표시(sig — 남은 개수 등)가 바뀔 때마다 시계를 되감고,
stall 초 동안 그대로일 때 멈춘 것으로 본다. cap 은 아무리 나아가도 넘지 않는 상한.

    p = Progress(stall=180, cap=1800)
    while not p.expired:
        p.update(남은_개수())   # 바뀌었으면 시계를 되감는다
"""
import time


class Progress:
    def __init__(self, stall: float, cap: float | None = None):
        now = time.monotonic()
        self.stall = stall
        self.cap_at = now + cap if cap else None
        self.sig = None
        self.last = now

    def update(self, sig) -> bool:
        """진행 표시를 알려 준다. 지난번과 다르면(나아갔으면) 시계를 되감고 True."""
        if sig == self.sig:
            return False
        self.sig = sig
        self.poke()
        return True

    def poke(self) -> None:
        """나아간 것으로 친다 (다음 걸음으로 넘어갔을 때 등)."""
        self.last = time.monotonic()

    @property
    def stalled(self) -> bool:
        return time.monotonic() - self.last > self.stall

    @property
    def expired(self) -> bool:
        return self.stalled or (self.cap_at is not None and time.monotonic() > self.cap_at)
