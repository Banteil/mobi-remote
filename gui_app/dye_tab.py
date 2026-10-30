"""염색 도우미의 겹쳐 그리는 창(Overlay)과 캡처 제외. 판단은 mabi/dye, 화면은 web/dye-ui.js, 돌리는 것은 dye_service.

- 우리 창(리모콘·오버레이)은 SetWindowDisplayAffinity 로 캡처에서 뺀다. 안 빼면 색 견본·표시가
  팔레트와 한 덩어리로 잡힌다 (리모콘은 setContentProtection).
"""
import ctypes

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_from_capture(widget: QWidget, on: bool = True) -> None:
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE if on else 0)
    except Exception:
        pass


def _qc(c) -> QColor:
    return QColor(int(c[0]), int(c[1]), int(c[2]), int(c[3]) if len(c) > 3 else 255)


class Overlay(QWidget):
    """게임이 있는 모니터 전체를 덮는 투명·클릭 통과·항상 위 창. 받은 도형만 그린다."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.items: list = []
        self.font = QFont("Malgun Gothic")
        self.font.setWeight(QFont.DemiBold)

    def place(self, screen=None) -> None:
        """게임이 있는 모니터 전체를 덮는다 (작업 표시줄까지)."""
        self.setGeometry((screen or QGuiApplication.primaryScreen()).geometry())

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
            if kind == "image":
                img = it.rgb
                h, w = img.shape[:2]
                q = QImage(img.data, w, h, w * 3, QImage.Format_RGB888)
                p.drawImage(QRectF(it.x, it.y, it.w, it.h), q)
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


class AreaEditor(QWidget):
    """팔레트 자리를 사람이 그려 정하는 창 — 게임 화면 위를 덮고 드래그로 사각형을 그린다.
    놓으면 done((x, y, w, h) 게임 화면 대비 비율), 오른쪽 클릭은 done(None) = 기본 자리, Esc 는 아무것도 안 하고 닫는다.
    대충 그려도 된다 — 받는 쪽이 가까운 테두리에 맞춘다 (detect.snap_area)."""

    def __init__(self, geom: QRectF, current, done):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(geom.toRect())
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.done = done
        w, h = geom.width(), geom.height()
        self.cur = QRectF(current[0] * w, current[1] * h, current[2] * w, current[3] * h) if current else None
        self.start = self.drag = None
        self.font = QFont("Malgun Gothic")
        self.font.setPixelSize(18)
        self.font.setWeight(QFont.DemiBold)

    def _finish(self, area) -> None:
        self.close()
        self.done(area)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape:
            self.close()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.RightButton:
            self._finish(None)
            return
        self.start = self.drag = e.position()
        self.update()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self.start is not None:
            self.drag = e.position()
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.start is None or e.button() != Qt.LeftButton:
            return
        r = QRectF(self.start, e.position()).normalized()
        self.start = self.drag = None
        if r.width() < 20 or r.height() < 20:
            self.update()
            return
        w, h = self.width(), self.height()
        self._finish((r.x() / w, r.y() / h, r.width() / w, r.height() / h))

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self.cur is not None:
            p.setPen(QPen(QColor(255, 210, 70), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.cur)
        if self.start is not None and self.drag is not None:
            r = QRectF(self.start, self.drag).normalized()
            p.fillRect(r, QColor(255, 255, 255, 40))
            p.setPen(QPen(QColor(255, 45, 45), 2))
            p.drawRect(r)
        p.setFont(self.font)
        text = "팔레트 안쪽을 드래그해 그리세요 (테두리에 맞춰 붙습니다) · 오른쪽 클릭: 기본 자리 · Esc: 취소"
        fm = QFontMetricsF(self.font)
        tw = fm.horizontalAdvance(text)
        box = QRectF((self.width() - tw) / 2 - 16, 18, tw + 32, 40)
        path = QPainterPath()
        path.addRoundedRect(box, 8, 8)
        p.fillPath(path, QBrush(QColor(16, 19, 26, 220)))
        p.setPen(QColor(238, 241, 246))
        p.drawText(box, Qt.AlignCenter, text)
        p.end()
