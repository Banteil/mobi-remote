"""염색 도우미의 파이썬 쪽: 주 모니터 캡처 → DyeTracker → 게임 위 표시 창(Qt) + 화면(웹)에 상태 보내기.

레거시는 화면(렌더러)이 getUserMedia 로 캡처하고 dye.js 로 검출했다. 웹 화면(QtWebEngine)에는 데스크톱
캡처가 없어서 검출은 파이썬(mabi/dye)이 하고, 화면에는 레거시 mm.dye.draw 와 같은 모양의 payload 를 보낸다
— 그래서 화면 쪽 미리보기(overlay-draw.js)와 상태 표(paintDyeInfo)는 손대지 않고 그대로 쓴다.
"""
import threading
import time

import mss
import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from mabi.dye import draw as ddraw
from mabi.dye import detect as D
from mabi.dye.tracker import DyeTracker

from .dye_tab import Overlay, exclude_from_capture

TICK = 0.12


class _ToGui(QObject):
    state = Signal(object, float, float)
    stopped = Signal()


class DyeService:
    def __init__(self, presets, emit):
        """presets: PresetStore · emit(채널, 값): 화면 이벤트."""
        self.presets, self.emit = presets, emit
        self.overlay: Overlay | None = None
        self.gui = _ToGui()
        self.gui.state.connect(self._paint)
        self.gui.stopped.connect(self._hide)
        self.thread: threading.Thread | None = None
        self.running = False
        self.tracker: DyeTracker | None = None
        self.win = None  # 메인 창 (캡처에서 뺀다)

    # ---- 제어 (작업 스레드에서 불려도 된다) ----
    def start(self) -> dict:
        if self.running:
            return {"ok": True}
        cur = self.presets.current() or {}
        self.tracker = DyeTracker()
        self.tracker.set_targets(cur.get("colors"), cur.get("tol"))
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="dye", daemon=True)
        self.thread.start()
        return {"ok": True}

    def stop(self) -> dict:
        self.running = False
        if self.thread:
            self.thread.join(2)
        self.gui.stopped.emit()
        return {"ok": True}

    def retarget(self) -> None:
        """프리셋·색·오차가 바뀌면 다음 바퀴에 다시 찾는다."""
        if self.tracker:
            cur = self.presets.current() or {}
            self.tracker.set_targets(cur.get("colors"), cur.get("tol"))

    # ---- 캡처 루프 ----
    def _loop(self) -> None:
        with mss.mss() as sct:
            mon = sct.monitors[1]
            while self.running:
                t0 = time.monotonic()
                img = np.asarray(sct.grab(mon))
                try:
                    st = self.tracker.tick(img)
                except Exception as e:  # 한 바퀴 실패로 도우미가 죽지 않게
                    self.emit("mm:dye-state", {"error": str(e)})
                    time.sleep(1)
                    continue
                if st.redraw or st.status == "done":
                    self.gui.state.emit(st, float(img.shape[1]), float(img.shape[0]))
                if st.status == "done":
                    self.running = False
                    break
                rest = TICK - (time.monotonic() - t0)
                if rest > 0:
                    time.sleep(rest)

    # ---- 화면 스레드 ----
    def _ensure_overlay(self) -> Overlay:
        if self.overlay is None:
            self.overlay = Overlay()
        if not self.overlay.isVisible():
            self.overlay.place()
            self.overlay.show()
            exclude_from_capture(self.overlay)
            if self.win:
                exclude_from_capture(self.win)
        return self.overlay

    def _hide(self) -> None:
        if self.overlay:
            self.overlay.items = []
            self.overlay.hide()
        if self.win:
            exclude_from_capture(self.win, False)
        self.emit("mm:dye-state", {"stopped": True})

    def _paint(self, st, fw: float, fh: float) -> None:
        ov = self._ensure_overlay()
        g = QGuiApplication.primaryScreen().geometry()
        scale = g.width() / fw if fw else 1.0
        ov.items = [] if st.hidden else ddraw.overlay_items(st, scale=scale, origin=(g.x(), g.y()),
                                                             screen_w=g.width(), measure=ov.measure)
        ov.update()
        self.emit("mm:dye-state", {"payload": self.payload(st, scale, (g.x(), g.y())), "info": self.info(st),
                                   "done": st.status == "done", "text": st.text})
        if st.status == "done":
            self._hide()

    # ---- 레거시 모양 (화면 미리보기·상태 표가 그대로 읽는다) ----
    @staticmethod
    def payload(st, scale: float, origin) -> dict:
        ox, oy = origin

        def sx(v):
            return D.jround(v * scale + ox)

        def sy(v):
            return D.jround(v * scale + oy)
        if st.hidden:
            return None
        p = {"status": st.text, "tone": st.tone}
        if st.palette:
            b = st.palette
            p["box"] = {"x": sx(b.x), "y": sy(b.y), "w": D.jround(b.w * scale), "h": D.jround(b.h * scale)}
        if st.chips:
            p["chips"] = [{"hex": c[0], "on": bool(c[1])} for c in st.chips]
        if st.spots:
            p["spots"] = [{"pts": [v for x, y in (pts.tolist() if len(pts) else []) for v in (sx(x), sy(y))]}
                          for pts in st.spots]
        if st.pins:
            p["tri"] = {"pins": [{"x": sx(x), "y": sy(y)} for x, y in st.pins]}
        if st.rings:
            p["picks"] = [{"x": sx(r.x), "y": sy(r.y), "r": max(6, D.jround(r.r * scale)), "slot": r.slot,
                           "hex": r.hex, "delta": r.delta} for r in st.rings]
        return p

    @staticmethod
    def info(st) -> dict:
        b = st.palette
        return {"box": {"x": b.x, "y": b.y, "w": b.w, "h": b.h} if b else None,
                "marks": [None if t is None else {"hex": t.hex, "color": t.color, "delta": t.delta, "tol": t.tol,
                                                  "found": t.found} for t in st.targets],
                "picks": [{"slot": r.slot} for r in st.rings]}
