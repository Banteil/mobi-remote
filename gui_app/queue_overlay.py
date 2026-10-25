"""작업 큐 오버레이 — 게임 화면 구석에 지금 큐가 무엇을 하고 있는지 띄운다 (사람이 보는 용도).

봇이 화면을 찍어도 이 창은 찍히지 않는다 (SetWindowDisplayAffinity 캡처 제외 — 염색 도우미 겹쳐 그리기와 같다).
일일 숙제는 mss 로 화면 전체를 찍으므로 빼지 않으면 그 자리의 버튼·글자를 못 알아본다.
클릭은 통과하고(WindowTransparentForInput) 포커스도 가져가지 않아 봇의 클릭·'게임이 앞에 있나' 확인과 겹치지 않는다.

글은 작업 큐 카드와 같은 view (gui_app/queue_api.py 의 Kind.view) 를 쓴다 — 카드와 오버레이가 같은 말을 한다.
설정(settings.json 'overlay'): on · when(active=돌거나 멈춰 있을 때 / always=카드가 있으면) · bg(panel/none) ·
alpha(배경 불투명도 %) · size(s/m/l) · corner(bl/br/tl/tr) · dx·dy(가장자리에서 떨어질 거리, 게임 화면 픽셀) · next(다음 카드 몇 장).
"""
import ctypes
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .dye_tab import exclude_from_capture

DEFAULTS = {"on": True, "when": "active", "bg": "panel", "alpha": 55, "size": "m", "corner": "bl",
            "dx": 24, "dy": 200, "next": 2}
CHOICES = {"when": ("active", "always"), "bg": ("panel", "none"), "size": ("s", "m", "l"), "corner": ("bl", "br", "tl", "tr")}
RANGES = {"alpha": (0, 100), "dx": (0, 2000), "dy": (0, 2000), "next": (0, 5)}
PX = {"s": 12, "m": 14, "l": 17}
STATE = {"run": "진행 중", "pause": "일시정지", "wait": "대기", "fail": "실패"}
ACCENT = {"run": QColor(90, 167, 255), "pause": QColor(240, 180, 70), "wait": QColor(170, 176, 188), "fail": QColor(240, 100, 100)}


def clean(v) -> dict:
    """화면이 보낸 설정을 정해진 값만 남겨 고친다."""
    v = v if isinstance(v, dict) else {}
    out = dict(DEFAULTS)
    if isinstance(v.get("on"), bool):
        out["on"] = v["on"]
    for k, opts in CHOICES.items():
        if v.get(k) in opts:
            out[k] = v[k]
    for k, (lo, hi) in RANGES.items():
        if isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool):
            out[k] = int(min(hi, max(lo, v[k])))
    return out


def pick(items: list[dict]) -> dict | None:
    """크게 보일 카드: 돌고 있는 것 → 맨 위 일시정지 → 맨 위 대기 → 실패."""
    for st in ("run", "pause", "wait", "fail"):
        it = next((x for x in items if x.get("status") == st), None)
        if it:
            return it
    return None


def lines(snap: dict, cfg: dict, now_ms: float | None = None) -> list[tuple[str, str]]:
    """그릴 줄 [(모양, 글)]. 모양: head(머리) · title · dim(흐린 글) · text · bar('한/전체|글') · next. 보일 게 없으면 []."""
    items = [x for x in (snap or {}).get("items") or [] if x.get("status") in ("run", "pause", "wait", "fail")]
    cur = pick(items)
    if not cur:
        return []
    active = (snap or {}).get("running") or any(x.get("status") == "pause" for x in items)
    if cfg.get("when") != "always" and not active:
        return []
    st = cur.get("status")
    v = cur.get("view") or {}
    out = []
    waiting = sum(1 for x in items if x.get("status") == "wait")
    head = "작업 큐 · " + STATE.get(st, st) + (f" · 대기 {waiting}" if waiting and st != "wait" else "")
    el = ""
    if st == "run" and cur.get("startedAt"):
        s = max(0, int(((now_ms or time.time() * 1000) - cur["startedAt"]) / 1000))
        el = f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    out.append(("head:" + st, head + ("\t" + el if el else "")))
    out.append(("title", cur.get("label") or ""))
    if v.get("goal"):
        out.append(("dim", v["goal"]))
    if v.get("now"):
        out.append(("text", v["now"]))
    if v.get("step"):
        out.append(("dim", v["step"]))
    bar = v.get("bar")
    if isinstance(bar, list) and len(bar) == 2 and bar[1]:
        pct = min(100, round(bar[0] / bar[1] * 100))
        nums = f"{bar[0]:,}/{bar[1]:,}" if cur.get("kind") != "abyss" else ""
        out.append(("bar", f"{bar[0]}/{bar[1]}|" + " · ".join(s for s in (nums, f"{pct}%", v.get("stat")) if s)))
    elif v.get("stat"):
        out.append(("dim", v["stat"]))
    if cur.get("note") and st != "run":
        out.append(("dim", cur["note"]))
    rest = [x for x in items if x is not cur and x.get("status") in ("wait", "pause")]
    n = int(cfg.get("next", 2))
    if n and rest:
        names = " · ".join(x.get("label") or "" for x in rest[:n])
        out.append(("next", "다음  " + names + (f"  외 {len(rest) - n}" if len(rest) > n else "")))
    return out


def _game_rect(title: str):
    """게임 창 클라이언트 영역 (실제 픽셀). 없거나 최소화면 None."""
    from ctypes import wintypes
    u = ctypes.windll.user32
    h = u.FindWindowW(None, title)
    if not h or u.IsIconic(h) or not u.IsWindowVisible(h):
        return None
    rc = wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(rc))
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen(h, ctypes.byref(pt))
    return pt.x, pt.y, rc.right, rc.bottom


def _size(kind: str, px: int) -> float:
    """줄 모양별 글자 크기 (높이 계산과 그리기가 같이 쓴다)."""
    return px * (1.15 if kind == "title" else 1 if kind == "text" else 0.85)


class QueueOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.rows: list[tuple[str, str]] = []
        self.cfg = dict(DEFAULTS)
        self.font = QFont("Malgun Gothic")

    def _font(self, px: float, bold: bool = False) -> QFont:
        f = QFont(self.font)
        f.setPixelSize(max(8, round(px)))
        f.setWeight(QFont.Bold if bold else QFont.DemiBold)
        return f

    def layout(self, px: int) -> tuple[float, float]:
        """패널 크기 (논리 픽셀)."""
        pad, gap = px * 0.8, px * 0.35
        h = pad * 2 + sum((px * 0.6 + gap + px if k == "bar" else _size(k, px)) + gap for k, _ in self.rows) - gap
        return px * 24, h

    def paintEvent(self, e):  # noqa: N802
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        px = PX.get(self.cfg.get("size"), 14)
        pad, gap = px * 0.8, px * 0.35
        w = self.width()
        panel = self.cfg.get("bg") == "panel"
        if panel:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0.5, 0.5, w - 1, self.height() - 1), px * 0.5, px * 0.5)
            p.fillPath(path, QColor(16, 18, 24, round(255 * self.cfg.get("alpha", 55) / 100)))
        st_color = ACCENT["run"]
        y = pad
        inner = w - pad * 2
        for kind, text in self.rows:
            if kind.startswith("head:"):
                st_color = ACCENT.get(kind[5:], st_color)
            if kind == "bar":
                frac, label = text.split("|", 1)
                a, b = (float(n) for n in frac.split("/"))
                bh = max(3.0, px * 0.3)
                r = QRectF(pad, y + px * 0.15, inner, bh)
                bg = QPainterPath()
                bg.addRoundedRect(r, bh / 2, bh / 2)
                p.fillPath(bg, QColor(255, 255, 255, 60))
                fg = QPainterPath()
                fg.addRoundedRect(QRectF(r.x(), r.y(), r.width() * min(1, a / b), bh), bh / 2, bh / 2)
                p.fillPath(fg, st_color)
                y += px * 0.6 + gap
                self._text(p, label, pad, y, inner, self._font(px * 0.85), QColor(200, 205, 214), panel)
                y += px + gap
                continue
            size = _size(kind, px)
            f = self._font(size, bold=kind == "title")
            color = {"head": st_color, "dim": QColor(185, 191, 202),
                     "next": QColor(160, 166, 178)}.get(kind.partition(":")[0], QColor(240, 243, 248))
            left, _, right = text.partition("\t")
            self._text(p, left, pad, y, inner, f, color, panel)
            if right:
                fm = QFontMetricsF(f)
                self._text(p, right, pad + inner - fm.horizontalAdvance(right), y, inner, f, color, panel)
            y += size + gap
        p.end()

    @staticmethod
    def _text(p: QPainter, text: str, x: float, y: float, width: float, f: QFont, color: QColor, panel: bool) -> None:
        fm = QFontMetricsF(f)
        text = fm.elidedText(text, Qt.ElideRight, width)
        base = QPointF(x, y + fm.ascent() - (fm.ascent() + fm.descent() - f.pixelSize()) / 2)
        if not panel:  # 배경이 없으면 어두운 테두리로 게임 화면 위에서도 읽히게
            path = QPainterPath()
            path.addText(base, f, text)
            pen = QPen(QColor(0, 0, 0, 200), max(2.0, f.pixelSize() / 5))
            pen.setJoinStyle(Qt.RoundJoin)
            p.strokePath(path, pen)
            p.fillPath(path, color)
            return
        p.setFont(f)
        p.setPen(color)
        p.drawText(base, text)


class OverlayService(QObject):
    """화면 스레드에 산다. push() 는 어느 스레드에서 불러도 된다 (시그널이 화면 스레드로 옮긴다)."""
    _snap = Signal(object)
    _cfg = Signal(object)

    def __init__(self, title: str, cfg: dict, snap: dict | None = None):
        super().__init__()
        self.title = title
        self.cfg = clean(cfg)
        self.snap = snap or {}
        self.win: QueueOverlay | None = None
        self._snap.connect(self._on_snap)
        self._cfg.connect(self._on_cfg)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)  # 걸린 시간 · 게임 창이 움직였으면 따라가기

    def push(self, snap: dict) -> None:
        self._snap.emit(snap)

    def configure(self, cfg: dict) -> None:
        self._cfg.emit(cfg)

    @Slot(object)
    def _on_snap(self, snap):
        self.snap = snap or {}
        self.refresh()

    @Slot(object)
    def _on_cfg(self, cfg):
        self.cfg = clean(cfg)
        self.refresh()

    def refresh(self) -> None:
        rows = lines(self.snap, self.cfg) if self.cfg["on"] else []
        rect = _game_rect(self.title) if rows else None
        if not rows or not rect:
            if self.win and self.win.isVisible():
                self.win.hide()
            return
        if self.win is None:
            self.win = QueueOverlay()
        w = self.win
        w.cfg, w.rows = self.cfg, rows
        pw, ph = w.layout(PX[self.cfg["size"]])
        x, y = self._place(rect, pw, ph)
        w.setGeometry(round(x), round(y), round(pw), round(ph))
        if not w.isVisible():
            w.show()
            exclude_from_capture(w)  # 창 핸들이 생긴 뒤에 (보이기 전엔 없다)
        w.update()

    def _place(self, rect, pw: float, ph: float) -> tuple[float, float]:
        """게임 화면(실제 픽셀)의 구석 → Qt 좌표(논리 픽셀). 게임이 있는 모니터의 배율로 나눈다."""
        gx, gy, gw, gh = rect
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        for s in QGuiApplication.screens():
            g, r = s.geometry(), s.devicePixelRatio()
            if g.x() <= gx + gw / 2 < g.x() + g.width() * r and g.y() <= gy + gh / 2 < g.y() + g.height() * r:
                screen = s
                break
        g, r = screen.geometry(), screen.devicePixelRatio()
        lx, ly = g.x() + (gx - g.x()) / r, g.y() + (gy - g.y()) / r
        lw, lh = gw / r, gh / r
        dx, dy = self.cfg["dx"] / r, self.cfg["dy"] / r
        c = self.cfg["corner"]
        x = lx + dx if c in ("bl", "tl") else lx + lw - dx - pw
        y = ly + lh - dy - ph if c in ("bl", "br") else ly + dy
        return x, y

    def close(self) -> None:
        self.timer.stop()
        if self.win:
            self.win.hide()
