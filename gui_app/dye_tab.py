"""염색 도우미: 화면을 읽어 염색 팔레트에서 목표 색 위치를 찾아 게임 위에 표시하고,
Ctrl+Alt+W/A/S/D 로 마우스를 1px 씩 옮겨 스포이드를 정확히 맞춘다.

화면을 읽기만 하고 게임에 아무것도 보내지 않는다 (커서 이동은 사람이 누른 만큼만).
판단은 mabi/dye (리모콘 dye.js 이식). 여기는 캡처 스레드·오버레이 창·설정 화면.
- 우리 창(이 창·오버레이)은 SetWindowDisplayAffinity 로 캡처에서 뺀다. 안 빼면 색 견본·표시가
  팔레트와 한 덩어리로 잡힌다 (리모콘은 setContentProtection).
"""
import ctypes
import time

import mss
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from mabi.dye import draw as ddraw
from mabi.dye.presets import PresetStore
from mabi.dye.tracker import DyeTracker
from mabi.nudge import CursorNudge

from .services import Services
from .style import STATUS_COLORS

TICK_MS = 120
WDA_EXCLUDEFROMCAPTURE = 0x11
SLOT_HEX = ["#ff00ff", "#00ff00", "#00ffff"]


def exclude_from_capture(widget: QWidget, on: bool = True) -> None:
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE if on else 0)
    except Exception:
        pass


# ------------------------------------------------------------------ 캡처 스레드
class DyeWorker(QThread):
    state = Signal(object, float, float)  # (DyeState, 캡처 폭, 캡처 높이)

    def __init__(self, tracker: DyeTracker):
        super().__init__()
        self.tracker = tracker
        self.running = True

    def run(self) -> None:
        with mss.mss() as sct:
            mon = sct.monitors[1]  # 주 모니터
            while self.running:
                t0 = time.monotonic()
                img = np.asarray(sct.grab(mon))  # BGRA, 물리 픽셀
                st = self.tracker.tick(img)
                self.state.emit(st, img.shape[1], img.shape[0])
                if st.status == "done":
                    break
                rest = TICK_MS / 1000 - (time.monotonic() - t0)
                if rest > 0:
                    time.sleep(rest)


# ------------------------------------------------------------------ 오버레이
def _qc(c) -> QColor:
    return QColor(int(c[0]), int(c[1]), int(c[2]), int(c[3]) if len(c) > 3 else 255)


class Overlay(QWidget):
    """주 모니터 전체를 덮는 투명·클릭 통과·항상 위 창. 받은 도형만 그린다."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.items: list = []
        self.font = QFont("Malgun Gothic")
        self.font.setWeight(QFont.DemiBold)

    def place(self) -> None:
        self.setGeometry(QGuiApplication.primaryScreen().geometry())  # 작업 표시줄까지

    def measure(self, text: str, px: int) -> float:
        f = QFont(self.font)
        f.setPixelSize(px)
        return QFontMetricsF(f).horizontalAdvance(text)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        self.paint(p)
        p.end()

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        for it in self.items:
            kind = getattr(it, "kind", "")
            if kind == "dots":
                p.setPen(Qt.NoPen)
                p.setBrush(_qc(it.color))
                h = it.size / 2
                for x, y in it.points:
                    p.drawRect(QRectF(x - h, y - h, it.size, it.size))
                continue
            if kind == "text":
                f = QFont(self.font)
                f.setPixelSize(it.px)
                p.setFont(f)
                p.setPen(_qc(it.color))
                fm = QFontMetricsF(f)
                p.drawText(QPointF(it.x, it.y + (fm.ascent() - fm.descent()) / 2), it.text)
                continue
            path = QPainterPath()
            if kind == "polyline":
                path.moveTo(*it.points[0])
                for pt in it.points[1:]:
                    path.lineTo(*pt)
                if it.closed:
                    path.closeSubpath()
            elif kind == "circle":
                path.addEllipse(QPointF(it.cx, it.cy), it.r, it.r)
            else:  # rect
                if getattr(it, "radius", 0):
                    path.addRoundedRect(QRectF(it.x, it.y, it.w, it.h), it.radius, it.radius)
                else:
                    path.addRect(QRectF(it.x, it.y, it.w, it.h))
            fill = getattr(it, "fill", None)
            if fill:
                p.fillPath(path, QBrush(_qc(fill)))
            for st in (getattr(it, "under", None), getattr(it, "stroke", None)):
                if st:  # 어두운 받침 선을 먼저, 그 위에 밝은 선
                    pen = QPen(_qc(st.color), st.width)
                    pen.setJoinStyle(Qt.RoundJoin)
                    if getattr(it, "dash", None):
                        pen.setDashPattern([d / max(st.width, 0.1) for d in it.dash])
                    p.strokePath(path, pen)


# ------------------------------------------------------------------ 탭
class DyeTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.store = PresetStore(svc.paths.data)
        self.tracker = DyeTracker()
        self.worker: DyeWorker | None = None
        self.overlay = Overlay()
        self.nudge = CursorNudge(on_error=lambda m: svc.notice.emit("bad", m))

        self.start_btn = QPushButton("염색 도우미 켜기")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.toggle)
        self.status = QLabel("게임에서 염색 화면을 연 뒤 켜세요.")
        self.nudge_cb = QCheckBox("Ctrl+Alt+W/A/S/D 로 마우스 1px 이동")
        self.nudge_cb.setChecked(bool(svc.settings.get("dye_nudge")))
        self.nudge_cb.toggled.connect(self._nudge)

        pbox = QGroupBox("목표 색")
        self.preset = QComboBox()
        self.preset.currentIndexChanged.connect(self._select)
        new, ren, dele = QPushButton("새로"), QPushButton("이름"), QPushButton("삭제")
        new.clicked.connect(self._new)
        ren.clicked.connect(self._rename)
        dele.clicked.connect(self._delete)
        grid = QGridLayout(pbox)
        grid.addWidget(self.preset, 0, 0, 1, 3)
        grid.addWidget(new, 0, 3)
        grid.addWidget(ren, 0, 4)
        grid.addWidget(dele, 0, 5)
        self.slots = []
        for i in range(3):
            num = QLabel(f" {i + 1} ")
            num.setStyleSheet(f"background: {SLOT_HEX[i]}; color: black; font-weight: bold;")
            sw = QPushButton("")
            sw.setFixedWidth(60)
            sw.clicked.connect(lambda _=False, i=i: self._pick(i))
            hx = QLineEdit()
            hx.setMaxLength(7)
            hx.setPlaceholderText("#RRGGBB")
            hx.editingFinished.connect(lambda i=i: self._hex(i))
            tol = QSlider(Qt.Horizontal)
            tol.setRange(0, 20)
            tl = QLabel("")
            tol.valueChanged.connect(lambda v, i=i, tl=tl: (tl.setText(f"오차 {v}"), self._tol(i, v)))
            clr = QPushButton("✕")
            clr.setMaximumWidth(36)
            clr.clicked.connect(lambda _=False, i=i: self._set_color(i, ""))
            for c, w in enumerate((num, sw, hx, tol, tl, clr)):
                grid.addWidget(w, i + 1, c)
            self.slots.append((sw, hx, tol, tl))
        hint = QLabel("오차: 목표 색과 이만큼(ΔE) 가까운 곳을 모두 점으로 찍습니다. 0 이면 가장 가까운 한 곳만.")
        hint.setObjectName("muted")
        grid.addWidget(hint, 4, 0, 1, 6)

        top = QHBoxLayout()
        top.addWidget(self.start_btn)
        top.addWidget(self.nudge_cb)
        top.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.status)
        lay.addWidget(pbox)
        lay.addStretch(1)
        self._load()
        if self.nudge_cb.isChecked():
            self.nudge.start()

    # ---- 프리셋 ----
    def _load(self, select: str | None = None) -> None:
        s = self.store.load()
        cur = select or s.get("currentId")
        self.preset.blockSignals(True)
        self.preset.clear()
        for p in s["presets"]:
            self.preset.addItem(p["name"], p["id"])
        self.preset.setCurrentIndex(max(0, self.preset.findData(cur)))
        self.preset.blockSignals(False)
        self._show()

    def _cur(self) -> dict:
        return self.store.current() or {"colors": ["", "", ""], "tol": [5, 5, 5]}

    def _show(self) -> None:
        p = self._cur()
        for i, (sw, hx, tol, tl) in enumerate(self.slots):
            c = (p["colors"] + ["", "", ""])[i]
            sw.setStyleSheet(f"background: {c};" if c else "")
            sw.setText("" if c else "색 고르기")
            hx.setText(c)
            tol.blockSignals(True)
            tol.setValue(int((p.get("tol") or [5, 5, 5])[i]))
            tol.blockSignals(False)
            tl.setText(f"오차 {tol.value()}")
        self.tracker.set_targets(p["colors"], p.get("tol"))

    def _select(self) -> None:
        self.store.select(self.preset.currentData())
        self._show()

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, "새 프리셋", "이름")
        if ok:
            s = self.store.add(name.strip() or "새 프리셋", ["", "", ""])
            self._load(s.get("currentId"))

    def _rename(self) -> None:
        p = self.store.current()
        if p:
            name, ok = QInputDialog.getText(self, "이름 바꾸기", "이름", text=p["name"])
            if ok and name.strip():
                self.store.update(p["id"], name=name.strip())
                self._load()

    def _delete(self) -> None:
        p = self.store.current()
        if p and QMessageBox.question(self, "삭제", f"'{p['name']}' 프리셋을 지울까요?") == QMessageBox.Yes:
            self.store.remove(p["id"])
            self._load()

    def _set_color(self, i: int, hexstr: str) -> None:
        p = self._cur()
        colors = (list(p["colors"]) + ["", "", ""])[:3]
        colors[i] = hexstr.upper()
        if p.get("id"):
            self.store.update(p["id"], colors=colors)
        self._show()

    def _pick(self, i: int) -> None:
        """색 편집 창 ('화면에서 집기' 가 있다 — 오버레이는 클릭을 통과시키므로 그대로 집힌다)."""
        cur = self.slots[i][1].text()
        c = QColorDialog.getColor(QColor(cur) if cur else QColor("white"), self, f"{i + 1}번 목표 색")
        if c.isValid():
            self._set_color(i, c.name())

    def _hex(self, i: int) -> None:
        t = self.slots[i][1].text().strip()
        t = t if t.startswith("#") else "#" + t
        if len(t) == 7 and QColor(t).isValid():
            self._set_color(i, t)

    def _tol(self, i: int, v: int) -> None:
        p = self.store.current()
        if p:
            tol = list(p.get("tol") or [5, 5, 5])
            tol[i] = v
            self.store.update(p["id"], tol=tol)
            self.tracker.set_targets(self._cur()["colors"], tol)

    # ---- 1px 이동 ----
    def _nudge(self, on: bool) -> None:
        self.svc.save_settings(dye_nudge=on)
        self.nudge.start() if on else self.nudge.stop()

    # ---- 켜기/끄기 ----
    def toggle(self) -> None:
        if self.worker:
            self.stop()
            return
        self.tracker = DyeTracker()
        self._show()
        self.overlay.place()
        self.overlay.items = []
        self.overlay.show()
        exclude_from_capture(self.overlay)
        exclude_from_capture(self.window())
        self.worker = DyeWorker(self.tracker)
        self.worker.state.connect(self._on_state)
        self.worker.finished.connect(self._finished)
        self.worker.start()
        self.start_btn.setText("염색 도우미 끄기")

    def stop(self) -> None:
        if self.worker:
            self.worker.running = False
            self.worker.wait(2000)
        self._finished()

    def _finished(self) -> None:
        self.worker = None
        self.overlay.hide()
        exclude_from_capture(self.window(), False)
        self.start_btn.setText("염색 도우미 켜기")

    def _on_state(self, st, fw: float, fh: float) -> None:
        self.status.setText(st.text)
        self.status.setStyleSheet(f"color: {STATUS_COLORS['OK'] if st.tone == 'ok' else STATUS_COLORS['CHECK']}")
        if st.status == "done":
            self.svc.notice.emit("ok", st.text)
        if st.hidden:
            self.overlay.items = []
            self.overlay.update()
            return
        if not st.redraw:
            return
        g = self.overlay.geometry()
        self.overlay.items = ddraw.overlay_items(st, scale=g.width() / fw if fw else 1.0, origin=(0, 0),
                                                 screen_w=g.width(), measure=self.overlay.measure)
        self.overlay.update()

    def shutdown(self) -> None:
        self.stop()
        self.nudge.stop()
