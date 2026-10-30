"""염색 도우미의 겹쳐 그리는 창(Overlay)과 캡처 제외. 판단은 mabi/dye, 화면은 web/dye-ui.js, 돌리는 것은 dye_service.

- 우리 창(리모콘·오버레이)은 SetWindowDisplayAffinity 로 캡처에서 뺀다. 안 빼면 색 견본·표시가
  팔레트와 한 덩어리로 잡힌다 (리모콘은 setContentProtection).
"""
import ctypes

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
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
