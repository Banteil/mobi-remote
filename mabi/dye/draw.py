"""염색 오버레이가 그릴 것 — mobi-remote app/overlay/draw.js 를 '그림 목록' 으로 옮긴 것.

캔버스 대신 도형 목록을 돌려준다. Qt 오버레이는 순서대로 칠하기만 한다.

화면에 그리는 것은 이만큼뿐: 맨 위 상태 띠와 찾는 색 딱지, 팔레트를 감싸는 빨간 박스,
오차 안에 드는 자리의 점, 스포이드 셋을 잇는 점선 삼각형, 목표에 맞은 스포이드 안쪽 테.
고리·십자·번호·안내선을 얹어 봤더니 정작 색을 고르는 데 방해가 됐다 — 게임 스포이드 UI 가 이미 그 아래 색을
가리고, 팔레트를 돌리는 동안 바뀌는 선은 산만하기만 했다 (2026-10-31).

── 소용돌이 위에서 보이게 ──
배경이 온갖 색이라 밝은 선만 그으면 사라진다. 선은 under(어두운 굵은 선)를 먼저, 그 위에 밝은 선.
점도 한 겹 큰 어두운 네모를 먼저 깐다.

색은 (r, g, b, a) — a 는 0~255. 좌표는 오버레이(화면) 좌표, 선 끝·이음은 둥글게(round).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

FONT = ("Pretendard", "Malgun Gothic")   # JS: "Pretendard","Malgun Gothic",system-ui

RGBA = tuple[int, int, int, int]


def rgba(s: str, a: float = 1.0) -> RGBA:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), round(a * 255)


def dark(a: float) -> RGBA:
    return 0, 0, 0, round(a * 255)


# 1·2·3번 칸 고유색. 찾는 색 그 자체로 찍으면 회색 위에 회색 점이 된다.
# sRGB 에서 가장 진한 마젠타·초록·시안 — 빨강은 팔레트 박스가 쓴다. 서로도 가장 멀다.
# 사람이 바꿀 수 있다 (보기 설정 marks → overlay_items(slots=…)). 이것은 기본값.
MARKS = ["#FF00FF", "#00FF00", "#00FFFF"]
SLOT = [rgba(h) for h in MARKS]
PALETTE_RED = rgba("#ff2d2d")
BANNER_BG = (16, 19, 26, round(0.86 * 255))
TONE_LINE = {"ok": (78, 201, 138, round(0.9 * 255)), "wait": (210, 170, 70, round(0.9 * 255))}
TONE_DOT = {"ok": rgba("#4ec98a"), "wait": rgba("#d2aa46")}
TEXT = rgba("#eef1f6")


@dataclass
class Stroke:
    color: RGBA
    width: float


@dataclass
class RectP:
    """네모. radius>0 이면 둥근 네모. fill 이 있으면 칠하고, stroke 가 있으면 긋는다 (under 먼저)."""
    x: float
    y: float
    w: float
    h: float
    radius: float = 0
    fill: RGBA | None = None
    stroke: Stroke | None = None
    under: Stroke | None = None
    kind: str = "rect"


@dataclass
class PolylineP:
    points: list[tuple[float, float]]
    stroke: Stroke
    under: Stroke | None = None
    closed: bool = False
    dash: tuple[float, float] | None = None   # (선, 틈) — under 와 밝은 선 모두 같은 점선
    kind: str = "polyline"


@dataclass
class CircleP:
    cx: float
    cy: float
    r: float
    fill: RGBA | None = None
    stroke: Stroke | None = None
    under: Stroke | None = None
    kind: str = "circle"


@dataclass
class ImageP:
    """그림 (RGB uint8 HxWx3) 을 (x, y, w, h) 에 늘려 그린다 — 흑백 강조."""
    x: float
    y: float
    w: float
    h: float
    rgb: object
    kind: str = "image"


@dataclass
class DotsP:
    """채운 정사각형 점들 (한 변 size, 가운데 정렬). 한 묶음을 한 색으로."""
    points: list[tuple[float, float]]
    size: float
    color: RGBA
    kind: str = "dots"


@dataclass
class TextP:
    """왼쪽 x, 세로 가운데 y (textBaseline=middle). 굵기 600."""
    x: float
    y: float
    text: str
    px: int
    color: RGBA
    weight: int = 600
    kind: str = "text"


def _approx_measure(text: str, px: int) -> float:
    # Qt 쪽은 QFontMetrics 를 넘겨 줄 것. 이건 없을 때의 어림값 (한글 1em, 그 밖 0.6em).
    return sum(px if ord(c) > 0x2E80 else px * 0.6 for c in text)


def overlay_items(state, presets=None, *, scale: float = 1.0, origin=(0, 0), screen_w: float = 1920,
                  k: float = 1.0, measure: Callable[[str, int], float] | None = None, slots=None,
                  guide=None) -> list:
    """DyeState → 그릴 도형 목록 (그리는 순서).

    scale/origin: 캡처 좌표 → 화면 좌표 (JS toScreen: round(v*scale + origin)).
    screen_w: 오버레이 폭 (띠·딱지 가운데 정렬용). k: 축소 배율 (미리보기는 1보다 작다).
    measure(text, px) → 글자 폭. Qt 는 QFontMetricsF(QFont('Pretendard', px, 600)).horizontalAdvance.
    presets: 쓰지 않는다 — 딱지는 JS 와 같게 실제로 찾는 목표(state.chips)에서 만든다.
    slots: 1·2·3번 칸 표시 색 ['#RRGGBB'×3] (없으면 MARKS) — 점·스포이드 테·딱지 테.
    guide: 맞출 자리 안내 {'points': [(칸, x, y, 스포이드 x, y)], 'text', 'done'} (캡처 좌표) — autofit.Session.guide.
    """
    if state is None or state.hidden:
        return []
    SLOT = [rgba(h) for h in (slots or MARKS)]  # noqa: N806 — 아래에서 모듈 SLOT 대신 쓴다
    m = measure or _approx_measure
    s = k or 1
    ox, oy = origin

    def X(v):
        return round(v * scale + ox)

    def Y(v):
        return round(v * scale + oy)

    out: list = []
    _banner(out, screen_w, state.text, state.tone, s, m)
    _chips(out, screen_w, state.chips, s, 54 * s, m, SLOT)
    if guide and guide.get("text"):
        _banner(out, screen_w, guide["text"], "ok" if guide.get("done") else "wait", s, m, y=86 * s)

    if state.palette is not None:
        b = state.palette
        if getattr(state, "shade", None) is not None:
            out.append(ImageP(X(b.x), Y(b.y), round(b.w * scale), round(b.h * scale), state.shade))
        _palette_box(out, (X(b.x), Y(b.y), round(b.w * scale), round(b.h * scale)), s)

    # 점 — 오차 안에 든 자리마다. 칸마다 제 고유색, 어두운 받침을 먼저.
    if state.spots:
        size = max(1.5, 3 * s)
        pad = max(1, s)
        for i, pts in enumerate(state.spots):
            if pts is None or not len(pts):
                continue
            xy = [(X(p[0]), Y(p[1])) for p in pts]
            out.append(DotsP(xy, size + pad * 2, dark(0.75)))
            out.append(DotsP(xy, size, SLOT[i] if i < len(SLOT) else SLOT[0]))

    # 스포이드 셋을 잇는 연한 점선 — 이 배치로 세 색을 어떻게 걸칠지 가늠하게
    if state.pins and len(state.pins) >= 3:
        out.append(PolylineP([(X(x), Y(y)) for x, y in state.pins[:3]],
                             Stroke((255, 255, 255, round(0.55 * 255)), 1.5 * s),
                             under=Stroke(dark(0.45), 3.5 * s), closed=True, dash=(5 * s, 5 * s)))

    # 맞출 자리 — 해 텍셀이 지금 있는 곳. 스포이드에서 그 점까지 점선, 점은 칸 색 동그라미.
    # 회전·크기가 맞으면 점들이 스포이드 배치와 같은 모양이 되고, 끌어서 겹치면 끝.
    for slot, gx, gy, rx, ry in (guide or {}).get("points", []):
        col = SLOT[slot] if slot < len(SLOT) else SLOT[0]
        out.append(PolylineP([(X(rx), Y(ry)), (X(gx), Y(gy))], Stroke(col[:3] + (round(0.8 * 255),), 2 * s),
                             under=Stroke(dark(0.5), 4.5 * s), dash=(6 * s, 4 * s)))
        out.append(CircleP(X(gx), Y(gy), 9 * s, stroke=Stroke(col, 3 * s), under=Stroke(dark(0.7), 6 * s)))
        out.append(CircleP(X(gx), Y(gy), 2.5 * s, fill=col))

    # 지금 고른 색이 목표에 맞은 스포이드만 — 흰 테 안쪽 가장자리를 따라 칸 색 테
    for rg in state.rings:
        if rg.slot < 0:
            continue
        pr = max(6, round(rg.r * scale))
        r = max(3, pr - 8 * s)
        out.append(CircleP(X(rg.x), Y(rg.y), r,
                           stroke=Stroke(SLOT[rg.slot] if rg.slot < len(SLOT) else SLOT[0], 2 * s),
                           under=Stroke(dark(0.55), 4 * s)))
    return out


def _banner(out, W, text, tone, k, m, y=None):
    """화면 맨 위 가운데 — 지금 무엇을 하는 중인지 한 줄. 게임을 보는 동안에도 보여야 한다."""
    if not text:
        return
    px = round(15 * k)
    w = m(text, px) + 34 * k
    x, y, h = (W - w) / 2, 14 * k if y is None else y, 34 * k
    tone = "ok" if tone == "ok" else "wait"
    out.append(RectP(x, y, w, h, radius=17 * k, fill=BANNER_BG, stroke=Stroke(TONE_LINE[tone], 1.5 * k)))
    out.append(CircleP(x + 16 * k, y + h / 2, 4.5 * k, fill=TONE_DOT[tone]))
    out.append(TextP(x + 27 * k, y + h / 2 + 1, text, px, TEXT))


def _chips(out, W, chips, k, top, m, SLOT=SLOT):
    """찾는 세 색. 스포이드에 잡힌 칸은 글씨가 또렷하고 테가 굵다."""
    if not chips:
        return
    px = round(12 * k)
    h, gap, pad, sw = 24 * k, 6 * k, 8 * k, 13 * k
    ws = [pad * 2 + sw + 6 * k + m(c[0], px) for c in chips]
    x = (W - (sum(ws) + gap * (len(chips) - 1))) / 2
    for i, c in enumerate(chips):
        hx, on = c[0], c[1]
        slot = c[2] if len(c) > 2 else i  # 칸 번호 (빈 칸이 있어도 색이 밀리지 않게)
        w = ws[i]
        line = SLOT[slot] if slot < len(SLOT) else SLOT[0]
        out.append(RectP(x, top, w, h, radius=6 * k, fill=BANNER_BG, stroke=Stroke(line, (2 if on else 1) * k)))
        sy = top + (h - sw) / 2
        out.append(RectP(x + pad, sy, sw, sw, radius=3 * k, fill=rgba(hx),
                         stroke=Stroke((255, 255, 255, round(0.4 * 255)), 1 * k)))
        out.append(TextP(x + pad + sw + 6 * k, top + h / 2 + 1, hx, px,
                         (255, 255, 255, 255) if on else (238, 241, 246, round(0.5 * 255))))
        x += w + gap


def _palette_box(out, b, k):
    """어디를 팔레트로 보고 있는지 — 잘못 잡았을 때 바로 알 수 있어야 한다. 소용돌이에 묻히지 않게 굵게."""
    x, y, w, h = b
    out.append(RectP(x + 0.5, y + 0.5, w - 1, h - 1,
                     stroke=Stroke(PALETTE_RED, 3.5 * k), under=Stroke(dark(0.6), 8 * k)))
    L = min(34 * k, w / 5, h / 5)
    for cx, cy, dx, dy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        out.append(PolylineP([(cx + dx * L, cy), (cx, cy), (cx, cy + dy * L)],
                             Stroke(PALETTE_RED, 5 * k), under=Stroke(dark(0.6), 10 * k)))
