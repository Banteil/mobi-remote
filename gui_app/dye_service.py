"""염색 도우미의 파이썬 쪽: 게임 창 캡처 → DyeTracker → 게임 위 표시 창(Qt) + 화면(웹)에 상태 보내기.

게임 창 클라이언트 영역만 찍는다 (예전엔 주 모니터 전체 — 게임이 다른 모니터·창모드면 어긋났다).
팔레트 자리를 게임 화면 비율로 두므로 해상도가 달라도 같다. 우리 창은 캡처에서 빠지므로(exclude_from_capture)
게임 위에 겹쳐도 찍히지 않는다.

검출은 파이썬(mabi/dye)이 하고 게임 위 표시 창에 그린다. 리모콘 화면(웹)에는 켜짐·팔레트 찾음만 보낸다
— 염색하는 동안은 게임을 보고 있어 리모콘의 상태 표·미리보기는 보이지도 않았다 (2026-10-31 뺌).
"""
import re
import threading
import time

import mss
import numpy as np
from PySide6.QtCore import QObject, QRectF, Signal

from mabi.dye import draw as ddraw
from mabi.dye import detect as D
from mabi.dye.tracker import DyeTracker
from mabi.window import GameWindow

from .dye_tab import AreaEditor, Overlay, exclude_from_capture
from .queue_overlay import to_logical

TICK = 0.12
LIGHT = (5, 90, 35)  # 흑백 밝기 % (최소, 최대, 기본)


def clean_view(v) -> dict:
    """보기 설정 (설정 파일 dyeView): gray 흑백 강조, light 흑백 밝기 %, area 팔레트 자리 비율 (None = 기본),
    marks 1·2·3번 칸 표시 색 (점·스포이드 테·딱지 — 잘못된 칸은 기본색), still 돌리는 동안 점 끄기."""
    v = v if isinstance(v, dict) else {}
    mk = v.get("marks") if isinstance(v.get("marks"), list) else []
    marks = [str(mk[i]).upper() if i < len(mk) and isinstance(mk[i], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", mk[i])
             else ddraw.MARKS[i] for i in range(3)]
    a = v.get("area")
    ok = (isinstance(a, (list, tuple)) and len(a) == 4
          and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in a)
          and 0 <= a[0] < 1 and 0 <= a[1] < 1 and 0.05 <= a[2] <= 1 and 0.05 <= a[3] <= 1)
    lt = v.get("light")
    lt = LIGHT[2] if not isinstance(lt, (int, float)) or isinstance(lt, bool) else int(min(LIGHT[1], max(LIGHT[0], lt)))
    return {"gray": v.get("gray") is True, "light": lt, "area": [round(float(x), 5) for x in a] if ok else None,
            "marks": marks, "still": v.get("still") is True}


class _ToGui(QObject):
    state = Signal(object, object)
    stopped = Signal()


class DyeService:
    def __init__(self, presets, emit, title: str):
        """presets: PresetStore · emit(채널, 값): 화면 이벤트 · title: 게임 창 제목."""
        self.presets, self.emit = presets, emit
        self.game = GameWindow(title)
        self.overlay: Overlay | None = None
        self.gui = _ToGui()
        self.gui.state.connect(self._paint)
        self.gui.stopped.connect(self._hide)
        self.thread: threading.Thread | None = None
        self.running = False
        self.tracker: DyeTracker | None = None
        self.win = None  # 메인 창 (캡처에서 뺀다)
        self.view = clean_view(None)
        self.editor: AreaEditor | None = None

    # ---- 제어 (작업 스레드에서 불려도 된다) ----
    def start(self) -> dict:
        if self.running:
            return {"ok": True}
        cur = self.presets.current() or {}
        self.tracker = DyeTracker()
        self.tracker.set_targets(cur.get("colors"), cur.get("tol"))
        self.set_view(self.view)
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="dye", daemon=True)
        self.thread.start()
        try:
            self.game.focus()  # 리모콘에서 켜면 바로 게임에서 팔레트를 만질 수 있게
        except RuntimeError:
            pass  # 게임이 없으면 뜰 때까지 기다린다 (_loop)
        self.emit("mm:dye-state", {"started": True})  # 단축키로 켰을 때도 화면 단추가 따라오게
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

    def set_view(self, view: dict) -> None:
        self.view = clean_view(view)
        if self.tracker:
            v = self.view
            self.tracker.set_view(v["area"], v["gray"], v["light"] / 100, v["still"])

    def edit_area(self, on_done) -> dict:
        """화면 스레드에서. 게임 위에 그리기 창을 띄운다. 다 그리면 가까운 테두리에 맞춰 on_done(비율 | None)."""
        rect = self._rect()
        if rect is None:
            return {"error": "게임 창을 찾지 못했습니다"}
        _, lx, ly, r = to_logical(rect)

        def done(area):
            if area is not None:
                area = self._snap(area)
            on_done(area)
        if self.editor:
            self.editor.close()
        self.editor = AreaEditor(QRectF(lx, ly, rect[2] / r, rect[3] / r), self.view["area"] or D.PALETTE_AT, done)
        self.editor.show()
        exclude_from_capture(self.editor)  # 맞출 때 찍는 화면에 우리 창이 섞이지 않게
        self.editor.activateWindow()
        self.editor.setFocus()
        return {"ok": True}

    def _snap(self, area):
        """그린 사각형(비율)을 지금 게임 화면의 가까운 테두리에 맞춘다. 못 찍으면 그린 대로."""
        rect = self._rect()
        if rect is None:
            return area
        with mss.mss() as sct:
            img = np.asarray(sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]}))
        f = D.Frame(img)
        px = D.Rect(D.jround(area[0] * f.w), D.jround(area[1] * f.h), D.jround(area[2] * f.w), D.jround(area[3] * f.h))
        return list(D.area_of(f, D.snap_area(f, px)))

    def _rect(self):
        """게임 창 클라이언트 영역 (x, y, w, h) 실제 픽셀. 없거나 내려가 있으면 None."""
        try:
            r = self.game.client_rect()
        except RuntimeError:
            return None
        return (r.left, r.top, r.width, r.height) if r.width > 0 and r.height > 0 else None

    # ---- 캡처 루프 ----
    def _loop(self) -> None:
        with mss.mss() as sct:
            while self.running:
                t0 = time.monotonic()
                rect = self._rect()
                if rect is None:
                    time.sleep(1)
                    continue
                img = np.asarray(sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]}))
                try:
                    st = self.tracker.tick(img)
                except Exception as e:  # 한 바퀴 실패로 도우미가 죽지 않게
                    self.emit("mm:dye-state", {"error": str(e)})
                    time.sleep(1)
                    continue
                if st.redraw:
                    self.gui.state.emit(st, rect)
                rest = TICK - (time.monotonic() - t0)
                if rest > 0:
                    time.sleep(rest)

    # ---- 화면 스레드 ----
    def _ensure_overlay(self, screen) -> Overlay:
        if self.overlay is None:
            self.overlay = Overlay()
        if self.overlay.geometry() != screen.geometry():
            self.overlay.place(screen)  # 게임이 있는 모니터 전체
        if not self.overlay.isVisible():
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

    def _paint(self, st, rect) -> None:
        # 캡처는 게임 창 실제 픽셀, 그리기는 그 모니터의 논리 픽셀
        screen, lx, ly, r = to_logical(rect)
        ov = self._ensure_overlay(screen)
        g = screen.geometry()
        scale = 1 / r
        ov.items = [] if st.hidden else ddraw.overlay_items(st, scale=scale, origin=(lx - g.x(), ly - g.y()),
                                                             screen_w=g.width(), measure=ov.measure,
                                                             slots=self.view["marks"])
        ov.update()
        self.emit("mm:dye-state", {"found": st.palette is not None, "text": st.text})
