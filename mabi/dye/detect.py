"""염색 도우미 — 팔레트에서 원하는 색이 어디 있는지 짚는다. (순수 계산)

mobi-remote app/renderer/dye.js 를 그대로 옮긴 것이다. 임계값·순서·동점 처리까지 같게 두었다.
화면 픽셀만 읽고 게임에는 아무것도 보내지 않는다. 그리지도 않는다 — 게임 없이 시험할 수 있게.

입력: HxWx3 또는 HxWx4 uint8. 채널 순서는 Frame(order=) 로 준다. 기본 'bgr' —
mss(BGRA)·OpenCV(BGR) 를 그대로 받는다. 'rgb' 면 RGB/RGBA. 알파는 보지 않는다.
좌표는 모두 그 이미지의 픽셀 좌표. 이미지는 게임 창 클라이언트 영역이다 (팔레트 자리를 게임 화면 비율로 둔다).

── 팔레트는 어디 ──
게임 UI 라 자리가 정해져 있다 (PALETTE_AT). 그 자리를 두른 어두운 테두리가 보이면 염색 화면이다.
색은 틀 안쪽에서만 찾는다 — 테두리·섞인 가장자리·둥근 모서리는 뺀다 (frame_skip).

── 벡터화 ──
표본 자리(간격 s 격자)는 JS 와 똑같다. 난수 표본은 쓰지 않는다 — 결정적 격자 그대로.
최솟값은 래스터 순서 첫 번째(np.argmin)라 JS 의 '더 작을 때만 바꾼다' 와 같은 점을 고른다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np


def jround(v: float) -> int:
    """JS Math.round (.5 는 위로). 파이썬 round 는 짝수 쪽이라 결과가 달라진다."""
    return math.floor(v + 0.5)


# ── 색 ──────────────────────────────────────────────────────────

# 0~255 는 256가지뿐이라 미리 구한다. 픽셀마다 pow 세 번이 가장 비쌌다(실측 — 절반 아래로).
# JS 는 Float32Array 라 float32 로 반올림된 값을 쓴다. 같게 맞춘다.
_LIN32 = np.empty(256, dtype=np.float32)
for _i in range(256):
    _v = _i / 255
    _LIN32[_i] = _v / 12.92 if _v <= 0.04045 else ((_v + 0.055) / 1.055) ** 2.4
LINEAR = _LIN32.astype(np.float64)


def _labf(t):
    return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16 / 116)


def lab_arrays(r, g, b):
    """sRGB(정수 배열) → CIE Lab (D65). RGB 거리는 어두운 쪽·초록 언저리에서 눈과 어긋난다."""
    R, G, B = LINEAR[r], LINEAR[g], LINEAR[b]
    X = _labf((R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047)
    Y = _labf(R * 0.2126 + G * 0.7152 + B * 0.0722)
    Z = _labf((R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883)
    return 116 * Y - 16, 500 * (X - Y), 200 * (Y - Z)


def to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    L, A, B = lab_arrays(np.array([r]), np.array([g]), np.array([b]))
    return float(L[0]), float(A[0]), float(B[0])


def hex_to_rgb(s) -> tuple[int, int, int] | None:
    t = str(s or "").strip()
    if t.startswith("#"):
        t = t[1:]
    if len(t) != 6 or any(c not in "0123456789abcdefABCDEF" for c in t):
        return None
    n = int(t, 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def rgb_to_hex(r, g, b) -> str:
    return "#" + "".join(f"{max(0, min(255, int(v))):02X}" for v in (r, g, b))


@dataclass
class Target:
    hex: str
    rgb: tuple[int, int, int]
    lab: tuple[float, float, float]
    tol: float | None = None   # 색마다 오차를 따로 든다. 없으면 호출 쪽 기본(5)

    @property
    def tol_or_default(self) -> float:
        return 5 if self.tol is None else self.tol


def target(hex_: str, tol=None) -> Target | None:
    """화면에서 읽은 색을 목표로. 머리색(딱 맞아야)·배경(비슷하면 됨)이 섞이므로 오차는 색마다."""
    rgb = hex_to_rgb(hex_)
    if not rgb:
        return None
    t = tol if isinstance(tol, (int, float)) and not isinstance(tol, bool) else None
    return Target(rgb_to_hex(*rgb), rgb, to_lab(*rgb), t)


# ── 프레임 ──────────────────────────────────────────────────────

class Frame:
    """캡처 한 장. order='bgr'(mss/OpenCV, 기본) | 'rgb'."""

    __slots__ = ("img", "w", "h", "ri", "bi")

    def __init__(self, img: np.ndarray, order: str = "bgr"):
        img = np.asarray(img)
        if img.dtype != np.uint8 or img.ndim != 3 or img.shape[2] not in (3, 4):
            raise ValueError(f"HxWx3/4 uint8 이어야 함: {img.dtype} {img.shape}")
        self.img = img
        self.h, self.w = img.shape[:2]
        bgr = order.lower().startswith("bgr")
        self.ri = 2 if bgr else 0
        self.bi = 0 if bgr else 2

    def rgb(self, ys, xs):
        """ys, xs 는 slice 또는 (np.ix_ 용) 인덱스 배열. int32 R,G,B."""
        if isinstance(ys, slice) or isinstance(xs, slice) or np.isscalar(ys) or np.isscalar(xs):
            sub = self.img[ys, xs]
        else:
            sub = self.img[np.ix_(ys, xs)]
        sub = sub[..., :3].astype(np.int16)     # 한 번에 바꾼다 — 채널마다 바꾸면 세 배 느리다
        return sub[..., self.ri], sub[..., 1], sub[..., self.bi]

    def maxc(self, ys, xs):
        """세 색 채널의 최댓값(알파 제외). 어둡기 판정용."""
        sub = self.img[ys, xs] if (isinstance(ys, slice) or isinstance(xs, slice)) else self.img[np.ix_(ys, xs)]
        return sub[..., :3].max(axis=-1)


def as_frame(img, order: str = "bgr") -> Frame:
    return img if isinstance(img, Frame) else Frame(img, order)


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


def clamp_rect(rect, f: Frame) -> Rect:
    if rect is None:
        rx, ry, rw, rh = 0, 0, f.w, f.h
    else:
        rx, ry, rw, rh = int(rect.x), int(rect.y), int(rect.w), int(rect.h)   # JS |0 = 0쪽 버림
    x = max(0, min(f.w - 1, rx))
    y = max(0, min(f.h - 1, ry))
    return Rect(x, y, max(1, min(f.w - x, rw)), max(1, min(f.h - y, rh)))


# ── 팔레트 자리 ─────────────────────────────────────────────────

# 염색 화면의 팔레트 틀은 게임 UI 라 늘 같은 자리다 — 끌기·확대·회전은 틀 안의 무늬만 움직인다.
# 실측 (2026-10-31, 1920x1080 게임 화면 60장 모두 같음): 안쪽 x 1075~1823 · y 283~1031, 어두운 테두리 13px,
# 안쪽 모서리 반지름 약 36, 안쪽 가장자리 1줄은 배경과 섞인다.
# 예전엔 화면에서 "알록달록한 덩어리" 를 찾았는데, 틀 바깥에도 같은 무늬가 흐리게 깔려 있어 경계를 엉뚱하게
# 잡거나(60장 중 49장 못 찾음) 테두리까지 범위에 넣어 검정 목표가 테두리에 찍혔다.
# 그래서 자리는 정해 두고(게임 화면 대비 비율 — 사람이 고칠 수 있다), 그 자리를 두른 테두리가 보이는지만 본다.
PALETTE_AT = (1075 / 1920, 283 / 1080, 749 / 1920, 749 / 1080)   # (x, y, w, h) 게임 화면 대비
BORDER_W = 13 / 1080   # 테두리 굵기 (화면 높이 대비)
CORNER_R = 36 / 1080   # 안쪽 둥근 모서리 반지름
EDGE_IN = 2 / 1080     # 안쪽 가장자리 섞인 줄 — 색 찾기에서 뺀다

DARK_MAX = 70      # 이보다 어두우면 테두리
DARK_RATIO = 0.75  # 한 변의 이 비율 이상이 어두우면 테두리가 있다 (실측 100%, 무늬 위 0~8%)
INNER_DARK = 0.3   # 안쪽이 이보다 많이 어두우면 팔레트가 아니다 — 진짜 1~2%, 화면 전환 중·어두운 창 위에선 테두리 자리도 어둡다

# 색 선택 UI 는 순백으로 그려진다. 248/6 이면 지시선 100% 통과, 소용돌이 0.00~0.01%.
# 느슨하면(200/22) 흰 테와 안쪽 흰 계열 색이 안 갈려 동그라미 측정이 통째로 어긋났다.
WHITE_MIN = 248
WHITE_TINT = 6
LEADER_WIDE = 20   # 이보다 굵으면 지시선이 아니다 (실측 4~5px)
LEADER_PAD = 3     # 가장자리 번짐 여유
RING_REACH = 20    # 동그라미를 찾을 때 좌우로 이만큼
RING_LOOK = 40     # 넓어지기 시작한 곳에서 이만큼 아래까지 복판을 찾는다
RING_MIN = 8       # 바깥 반지름 하한
RING_MAX = 25      # 상한 (실측 13~15)
RING_SHARE = 0.5   # 안쪽 으뜸 색이 이만큼은 돼야 믿는다 (커서가 덮었나)
RING_INK = 7       # 바깥 반지름에서 이만큼 안쪽까지가 칠해진 부분 (테 5 + 여유 2)

DONE_RGB = (13, 179, 118)   # 염색 확정 단추 — 한 색으로 꽉 찬 초록 면
DONE_TOL = 24               # 세 채널 차이의 합
RING_PAD = 5                # 동그라미 둘레 여유 — 섞인 가장자리까지
LEADER_GAP = 4              # 이만큼까지 끊겨도 같은 선


@dataclass
class Palette(Rect):
    corner: int = 0   # 안쪽 둥근 모서리 반지름 (px)
    inset: int = 0    # 안쪽 가장자리에서 뺄 폭 (px)


def palette_rect(f: Frame, at=PALETTE_AT) -> Palette:
    """비율 자리(at) → 이 화면의 팔레트 안쪽 사각형. 크기 값은 화면 높이에 비례 (게임 UI 는 해상도에 비례한다)."""
    x, y, w, h = at
    return Palette(jround(x * f.w), jround(y * f.h), max(1, jround(w * f.w)), max(1, jround(h * f.h)),
                   corner=jround(CORNER_R * f.h), inset=max(1, jround(EDGE_IN * f.h)))


def palette_at(f: Frame, at=PALETTE_AT) -> Palette | None:
    """정해 둔 자리에 팔레트가 떠 있나 — 네 변 바로 바깥이 모두 어두운 테두리면 그 사각형, 아니면 None.
    둥근 모서리에 안 걸리게 변마다 가운데 60% 만, 테두리 굵기 한가운데 줄을 본다."""
    b = palette_rect(f, at)
    off = max(1, jround(BORDER_W * f.h / 2))
    if b.x - off < 0 or b.y - off < 0 or b.x + b.w + off >= f.w or b.y + b.h + off >= f.h:
        return None
    xs = np.arange(jround(b.x + b.w * 0.2), jround(b.x + b.w * 0.8), 2)
    ys = np.arange(jround(b.y + b.h * 0.2), jround(b.y + b.h * 0.8), 2)
    sides = (f.maxc(np.array([b.y - off]), xs), f.maxc(np.array([b.y + b.h - 1 + off]), xs),
             f.maxc(ys, np.array([b.x - off])), f.maxc(ys, np.array([b.x + b.w - 1 + off])))
    if not all((s < DARK_MAX).mean() >= DARK_RATIO for s in sides):
        return None
    if (f.maxc(ys[::8], xs[::8]) < DARK_MAX).mean() > INNER_DARK:
        return None
    return b


# ── 색 선택 UI (흰 지시선 + 스포이드 동그라미) ────────────────────

@dataclass
class SkipRect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class SkipCircle:
    cx: int
    cy: int
    r: int


@dataclass
class SkipOutside:
    """이 둥근 사각형 바깥은 팔레트가 아니다 — 틀 테두리·섞인 가장자리·둥근 모서리 (검정 목표가 테두리에 찍혔다)."""
    x: int
    y: int
    w: int
    h: int
    r: int


def frame_skip(box: Palette) -> SkipOutside:
    i = box.inset
    return SkipOutside(box.x + i, box.y + i, box.w - 2 * i, box.h - 2 * i, max(0, box.corner - i))


@dataclass
class Ring:
    x: int
    y: int
    r: int
    rgb: tuple[int, int, int]
    share: float

    @property
    def hex(self) -> str:
        return rgb_to_hex(*self.rgb)


@dataclass
class LeaderLine:
    x0: int          # 화면 x (왼쪽 끝, 포함)
    x1: int          # 오른쪽 끝 (포함)
    guessed: bool = False


@dataclass
class Leaders:
    skip: list = field(default_factory=list)
    rings: list[Ring] = field(default_factory=list)
    lines: list[LeaderLine] = field(default_factory=list)


def _white(f: Frame, ys, xs) -> np.ndarray:
    r, g, b = f.rgb(ys, xs)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return (mn >= WHITE_MIN) & (mx - mn <= WHITE_TINT)


def default_ring_r(box: Rect) -> int:
    """동그라미 크기를 못 쟀을 때. 749px 팔레트에서 바깥 반지름 13~14 → 대략 1/54."""
    return max(RING_MIN, min(RING_MAX, jround(min(box.w, box.h) / 54)))


def find_leaders(f: Frame, box: Rect) -> Leaders:
    """팔레트 위쪽에서 곧게 내려와 동그라미로 한 점을 가리키는 흰 선(파트 수만큼 1~3개).

    선은 팔레트 색이 아니다 — 흰색을 목표로 잡으면 선을 따라 점이 줄줄이 찍힌다. 그래서 찾아서 뺀다.
    실측 (749x749, 파트 3): 가로 자리 1/6·3/6·5/6, 굵기 4~5px, 지름 안 18~19·바깥 27~28 (테 5).
    선은 가는 띠로 세로 전체, 동그라미는 원으로만 지운다 — 통째로 지우면 팔레트 13% 가 날아간다.
    rings[].rgb 는 그 파트가 지금 고른 색 그 자체다 (게임 딱지의 HEX 와 정확히 일치).
    """
    wb = _white(f, slice(box.y, box.y + box.h), slice(box.x, box.x + box.w))   # (box.h, box.w)

    # 맨 위에서 아래로 끊기지 않고 흰 줄이 몇 개나 이어지나. 소용돌이의 흰 줄기는 휘어서 오래 못 머문다.
    band = max(24, jround(min(box.h * 0.16, 160)))
    need = jround(band * 0.7)
    cnt = np.zeros(box.w, dtype=np.int32)
    miss = np.zeros(box.w, dtype=np.int32)
    alive = np.ones(box.w, dtype=bool)
    for dy in range(2, min(band, wb.shape[0])):
        wr = wb[dy]
        hit = alive & wr
        cnt += hit
        miss = np.where(hit, 0, miss + (alive & ~wr))
        # 몇 줄 끊겨도 같은 선 — 우리 표시가 지나가거나 번지면 한두 줄이 빠진다
        alive &= ~(miss > LEADER_GAP)
    run = cnt

    lines: list[dict] = []
    st = -1
    for dx in range(box.w + 1):
        on = dx < box.w and run[dx] >= need
        if on and st < 0:
            st = dx
        if not on and st >= 0:
            if dx - st <= LEADER_WIDE:
                lines.append({"a": st, "z": dx - 1, "guessed": False})
            st = -1
    # 파트는 많아야 셋. 더 잡혔으면 굵은 것부터 셋 (안정 정렬, JS 와 같음).
    if len(lines) > 3:
        lines.sort(key=lambda g: -(g["z"] - g["a"]))
        del lines[3:]
    lines.sort(key=lambda g: g["a"])

    # 놓친 선 채우기 — n 개면 (2k+1)/2n 자리에 고르게 선다. 하나만 확실해도 나머지 자리를 안다.
    # 들어맞는 가장 작은 n. 한가운데 하나면 n=1 — 없는 선을 지어내는 쪽이 더 나쁘다.
    def ratio(g):
        return ((g["a"] + g["z"]) / 2) / box.w

    wide_of = jround(sum(g["z"] - g["a"] + 1 for g in lines) / len(lines)) if lines else 5
    for n in range(1, 4):
        if not lines:
            break
        slots = [(2 * k + 1) / (2 * n) for k in range(n)]
        fits = all(any(abs(ratio(g) - v) < 0.025 for v in slots) for g in lines)
        if not fits or n < len(lines):
            continue
        for v in slots:
            if any(abs(ratio(g) - v) < 0.025 for g in lines):
                continue
            c = jround(box.w * v)
            a = c - (wide_of >> 1)
            lines.append({"a": a, "z": a + wide_of - 1, "guessed": True})
        break
    lines.sort(key=lambda g: g["a"])

    out = Leaders()
    y_lo, y_hi = box.y + 2, box.y + box.h - 2
    for g in lines:
        cx = box.x + ((g["a"] + g["z"]) >> 1)
        wide = g["z"] - g["a"] + 1
        out.lines.append(LeaderLine(box.x + g["a"], box.x + g["z"], g["guessed"]))
        out.skip.append(SkipRect(box.x + g["a"] - LEADER_PAD, box.y, wide + LEADER_PAD * 2, box.h))

        # 선을 따라 내려가다 가로로 가장 넓게 퍼지는 줄이 복판. 좌우 ±20 안의 흰 점의
        # 가장 왼쪽~오른쪽 폭을 줄마다 잰다 — 안이 찼든 비었든 복판에서 최대.
        lo = max(0, cx - RING_REACH - box.x)
        hi = min(box.w - 1, cx + RING_REACH - box.x)
        if lo <= hi:
            win = wb[:, lo:hi + 1]
            anyw = win.any(axis=1)
            l = np.argmax(win, axis=1)
            r = win.shape[1] - 1 - np.argmax(win[:, ::-1], axis=1)
            ext_arr = np.where(anyw, r - l + 1, 0)
        else:
            ext_arr = np.zeros(box.h, dtype=np.int64)
        ext = ext_arr.tolist()

        def extent(y):
            return ext[y - box.y]

        # NOTE dye.js:594 — miss 분기는 grow<0 인 동안 아무 일도 안 한다(죽은 코드).
        # 그래서 '처음으로 wide+6 보다 넓은 줄' 을 끝까지 찾는다. 그대로 옮긴다.
        grow = -1
        for y in range(y_lo, y_hi):
            e = extent(y)
            if e and e > wide + 6:
                grow = y
                break
        # 동그라미는 반드시 있다(선 끝에 달려 있다). 못 찾으면 흰색이 마지막으로 보인 줄.
        # 못 찾은 채 넘어가면 그 프레임에서 흰 테가 통째로 노출돼 색으로 잡힌다.
        if grow < 0:
            seen, gap = box.y + 2, 0
            for y in range(y_lo, y_hi):
                if extent(y):
                    seen, gap = y, 0
                    continue
                gap += 1
                if gap > LEADER_GAP * 3:
                    break
            grow = seen

        # 복판은 가장 넓은 한 줄이 아니라 넓은 줄들이 이어진 구간의 한가운데 — 소용돌이가 한 픽셀
        # 스쳐도 끌려가지 않게 (실제로 표시가 반쯤 어긋났었다).
        last, peak = -1, 0
        y = grow
        while y <= grow + RING_LOOK and y < box.y + box.h:
            e = extent(y)
            if e <= wide + 6:
                break
            last = y
            peak = max(peak, e)
            y += 1
        if last < 0:
            last = grow
        cy = jround((grow + last) / 2)
        # 세로·가로 중 큰 쪽이 지름. 이상해도 버리지 않고 가둔다 — 버리면 흰 테가 노출된다.
        out_r = jround(max(last - grow + 1, peak) / 2)
        if not (RING_MIN <= out_r <= RING_MAX):
            out_r = default_ring_r(box)

        seen_c = ring_color(f, cx, cy, out_r)
        if seen_c is None:
            continue
        out.rings.append(Ring(cx, cy, out_r, seen_c[0], seen_c[1]))
        # 가장자리는 배경과 섞여 +1~2px 까지 흰기가 남는다. 원으로 가린다 (네모는 모서리를 괜히 지운다).
        out.skip.append(SkipCircle(cx, cy, out_r + RING_PAD))
    return out


def ring_color(f: Frame, x: int, y: int, r: int):
    """동그라미 안쪽 색 = 가장 많은 색 (평균 아님 — 커서가 덮으면 흰쪽으로 끌려간다).

    동점이면 그 개수에 먼저 도달한 색 (JS 의 Map 순회와 같다). → ((r,g,b), share) | None
    """
    rad = max(2, r - RING_INK)
    d = np.arange(-rad, rad + 1)
    DY, DX = np.meshgrid(d, d, indexing="ij")
    X, Y = x + DX, y + DY
    m = (DX * DX + DY * DY <= rad * rad) & (X >= 0) & (Y >= 0) & (X < f.w) & (Y < f.h)
    if not m.any():
        return None
    px = f.img[Y[m], X[m]]          # 래스터(dy 바깥, dx 안쪽) 순서 유지
    keys = (px[:, f.ri].astype(np.int64) << 16) | (px[:, 1].astype(np.int64) << 8) | px[:, f.bi]
    uniq, counts = np.unique(keys, return_counts=True)
    top = counts.max()
    cands = uniq[counts == top]
    if len(cands) == 1:
        key = int(cands[0])
    else:
        key = int(min(cands, key=lambda k: np.flatnonzero(keys == k)[top - 1]))
    return ((key >> 16) & 255, (key >> 8) & 255, key & 255), int(top) / len(keys)


def read_rings(f: Frame, rings: Iterable[Ring]) -> list[Ring]:
    """찾아 둔 동그라미의 안쪽 색만 다시 읽는다. UI 는 붙박이라 자리를 다시 찾으면 떨리기만 한다.
    커서에 가려 으뜸 색이 절반도 안 되면 들어온 값(호출 쪽이 넘긴 것)을 그대로 쓴다."""
    out = []
    for ring in rings:
        seen = ring_color(f, ring.x, ring.y, ring.r)
        if seen is None or seen[1] < RING_SHARE:
            out.append(ring)
        else:
            out.append(Ring(ring.x, ring.y, ring.r, seen[0], seen[1]))
    return out


def find_done_button(f: Frame, color=DONE_RGB) -> Rect | None:
    """염색이 끝나면 뜨는 '염색 확정' 단추. 찾으면 도우미를 끌 때다.

    염색 화면에도 같은 초록 '이대로 염색하기' 가 있어 색으로는 못 가른다. 크기·자리로 가른다:
      이대로 염색하기 폭 0.39 · 가운데 x 0.255   /   염색 확정 폭 0.18 · x 0.565 · 높이 0.07
    한 색으로 꽉 찬 면이라 소용돌이(픽셀마다 값이 다름)와 헷갈리지 않는다.
    """
    w, h = f.w, f.h
    C = color
    y0 = jround(h * 0.78)
    if y0 >= h:
        return None
    r, g, b = f.rgb(slice(y0, h, 2), slice(0, w, 2))
    same = (np.abs(r - C[0]) + np.abs(g - C[1]) + np.abs(b - C[2])) <= DONE_TOL
    closes_at_end = w % 2 == 0     # JS 는 x<=w 를 2씩 — w 가 홀수면 오른쪽 끝까지 이어진 줄은 안 닫힌다
    col_cache: dict[int, np.ndarray] = {}

    def col(cx):
        if cx not in col_cache:
            cr, cg, cb = f.rgb(slice(0, h), slice(cx, cx + 1))
            col_cache[cx] = ((np.abs(cr - C[0]) + np.abs(cg - C[1]) + np.abs(cb - C[2])) <= DONE_TOL)[:, 0]
        return col_cache[cx]

    for ri in np.flatnonzero(same.any(axis=1)):
        y = y0 + 2 * int(ri)
        row = same[ri].astype(np.int8)
        pad = np.concatenate(([0], row, [0]))
        d = np.diff(pad)
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        for s, e in zip(starts, ends):
            if e == len(row) and not closes_at_end:
                continue
            start, run = 2 * int(s), 2 * int(e - s)
            mid = start + run / 2
            if 0.13 <= run / w <= 0.26 and 0.45 <= mid / w <= 0.70:
                cxp = jround(mid)
                c = col(cxp)
                top = bot = y
                while top > 0 and c[top - 1]:
                    top -= 1
                while bot < h - 1 and c[bot + 1]:
                    bot += 1
                bh = bot - top + 1
                if 0.04 <= bh / h <= 0.11:
                    return Rect(start, top, run, bh)
    return None


# ── 가릴 자리 ───────────────────────────────────────────────────

def skip_mask(shapes, xs: np.ndarray, ys: np.ndarray) -> np.ndarray | None:
    """격자(ys × xs)에서 가릴 자리. 선은 네모, 스포이드는 원 — 원을 네모로 가리면 21% 더 지워진다."""
    if not shapes:
        return None
    X = xs[None, :]
    Y = ys[:, None]
    m = np.zeros((len(ys), len(xs)), dtype=bool)
    for s in shapes:
        if isinstance(s, SkipCircle):
            m |= (X - s.cx) ** 2 + (Y - s.cy) ** 2 <= s.r * s.r
        elif isinstance(s, SkipOutside):
            out = (X < s.x) | (X >= s.x + s.w) | (Y < s.y) | (Y >= s.y + s.h)
            # 모서리: 반지름 r 원의 중심보다 바깥 쪽에 있으면서 그 원 밖
            cx = np.clip(X, s.x + s.r, s.x + s.w - 1 - s.r)
            cy = np.clip(Y, s.y + s.r, s.y + s.h - 1 - s.r)
            m |= out | ((X - cx) ** 2 + (Y - cy) ** 2 > s.r * s.r)
        else:
            m |= (X >= s.x) & (X < s.x + s.w) & (Y >= s.y) & (Y < s.y + s.h)
    return m


# ── 색 찾기 ─────────────────────────────────────────────────────

@dataclass
class ColorHit:
    hex: str          # 목표
    x: int
    y: int
    color: str        # 그 자리의 실제 색
    delta: float      # ΔE76, 소수 첫째 자리
    tol: float
    found: bool       # delta <= tol (반올림 전 값으로)


def _d2(L, A, B, lab):
    dL, da, db = L - lab[0], A - lab[1], B - lab[2]
    return dL * dL + da * da + db * db


def find_colors(f: Frame, rect, targets: Sequence[Target], skip=None,
                samples: int = 150000, tolerance: float | None = None) -> list[ColorHit]:
    """목표색마다 가장 가까운 지점.

    건너뛰기 폭은 뽑을 표본 수에서 거꾸로 정한다 — 팔레트가 크든 작든 시간이 같다.
    15만 점이면 전수와 거의 같다 (전수 ΔE 0.4 / 15만 점 ΔE 0.8, 눈으로는 구분 불가).
    찾은 자리 주변(±s)만 원해상도로 다시 본다.
    """
    box = clamp_rect(rect, f)
    s = max(1, jround(math.sqrt((box.w * box.h) / (samples or 150000))))
    xs = np.arange(box.x, box.x + box.w, s)
    ys = np.arange(box.y, box.y + box.h, s)
    r, g, b = f.rgb(ys, xs)
    L, A, B = lab_arrays(r, g, b)
    sk = skip_mask(skip, xs, ys)

    out = []
    for t in targets:
        d = _d2(L, A, B, t.lab)
        if sk is not None:
            d = np.where(sk, np.inf, d)
        i = int(np.argmin(d))
        iy, ix = divmod(i, len(xs))
        if np.isfinite(d.flat[i]):
            best = (float(d.flat[i]), int(xs[ix]), int(ys[iy]), (int(r.flat[i]), int(g.flat[i]), int(b.flat[i])))
        else:   # 전부 가려졌다 — JS 는 처음 값(0,0,검정,∞)을 그대로 남긴다
            best = (math.inf, 0, 0, (0, 0, 0))
        fine = _refine(f, best, t, s, skip)
        delta = math.sqrt(fine[0])
        tol = t.tol if t.tol is not None else (5 if tolerance is None else tolerance)
        out.append(ColorHit(t.hex, fine[1], fine[2], rgb_to_hex(*fine[3]),
                            jround(delta * 10) / 10 if math.isfinite(delta) else math.inf,
                            tol, delta <= tol))
    return out


def _refine(f: Frame, b, t: Target, s: int, skip):
    if s <= 1:
        return b
    _, bx, by, _ = b
    x0, x1 = max(0, bx - s), min(f.w - 1, bx + s)
    y0, y1 = max(0, by - s), min(f.h - 1, by + s)
    xs, ys = np.arange(x0, x1 + 1), np.arange(y0, y1 + 1)
    r, g, bb = f.rgb(ys, xs)
    d = _d2(*lab_arrays(r, g, bb), t.lab)
    sk = skip_mask(skip, xs, ys)
    if sk is not None:
        d = np.where(sk, np.inf, d)
    i = int(np.argmin(d))
    if d.flat[i] < b[0]:
        iy, ix = divmod(i, len(xs))
        return float(d.flat[i]), int(xs[ix]), int(ys[iy]), (int(r.flat[i]), int(g.flat[i]), int(bb.flat[i]))
    return b


def find_spots(f: Frame, rect, targets: Sequence[Target], skip=None,
               samples: int = 60000, cap: int = 700) -> list[np.ndarray]:
    """오차 안에 드는 모든 지점 — 목표마다 (k,2) int 배열 [x,y], 래스터 순서.

    가장 가까운 한 점만 찍으면 "여기밖에 없나?" 하고 헷갈린다. 같은 색이 여러 군데 흩어져 있다.
    너무 많으면 그리는 쪽이 느려 상한을 두고, 넘치면 고르게 솎는다 (앞만 자르면 위쪽에 몰린다).
    오차 0 이면 점을 뿌리지 않는다.
    """
    box = clamp_rect(rect, f)
    s = max(1, jround(math.sqrt((box.w * box.h) / (samples or 60000))))
    cap = cap or 700
    xs = np.arange(box.x, box.x + box.w, s)
    ys = np.arange(box.y, box.y + box.h, s)
    r, g, b = f.rgb(ys, xs)
    L, A, B = lab_arrays(r, g, b)
    sk = skip_mask(skip, xs, ys)
    X, Y = np.meshgrid(xs, ys)
    out = []
    for t in targets:
        tol = t.tol_or_default
        if not tol:
            out.append(np.zeros((0, 2), dtype=np.int32))
            continue
        hit = _d2(L, A, B, t.lab) <= tol * tol
        if sk is not None:
            hit &= ~sk
        pts = np.stack([X[hit], Y[hit]], axis=1).astype(np.int32)
        n = len(pts)
        if n > cap:
            pts = pts[np.floor(np.arange(cap) * (n / cap)).astype(np.int64)]
        out.append(pts)
    return out


def find_bands(f: Frame, box: Rect, n: int, cut_ratio: float = 3) -> list[tuple[int, int]]:
    """파트마다 스포이드가 색을 고를 수 있는 가로 범위 [(x0,x1),...].

    파트마다 염색 타입(천·가죽·금속·나무)이 다르면 팔레트가 세로로 갈라진 별개 판이 되고,
    1번 스포이드는 1번 판 안에서만 고를 수 있다. 이웃 파트 타입이 같으면 이어져 있다.
    경계 후보 자리 열 차이 / 팔레트 평균: 진짜 4.8~9.0배, 아닌 곳 0.9~1.3배 → 3배.
    """
    parts = max(1, int(n))
    whole = [(box.x, box.x + box.w)]
    if parts < 2:
        return whole
    ys = np.arange(box.y + 6, box.y + box.h - 6, 3)
    c = len(ys)
    xs = np.arange(max(1, box.x), min(f.w, box.x + box.w + 1))
    if c:
        a = f.img[np.ix_(ys, xs)][..., :3].astype(np.int32)
        p = f.img[np.ix_(ys, xs - 1)][..., :3].astype(np.int32)
        sums = np.abs(a - p).sum(axis=(0, 2))       # 정수 합 — JS 와 똑같다
        cd = dict(zip(xs.tolist(), (sums / c).tolist()))
    else:
        cd = {}

    def col_diff(x):
        return cd.get(x, 0.0)

    vals = [col_diff(x) for x in range(box.x + 8, box.x + box.w - 8, 7)]
    mean = (sum(vals) / len(vals)) if vals else 0
    if mean <= 0:
        return whole

    cuts = []
    for i in range(1, parts):
        at = jround(box.x + (box.w * i) / parts)
        peak, where = 0, at
        for x in range(at - 8, at + 9):
            if x <= box.x or x >= box.x + box.w:
                continue
            v = col_diff(x)
            if v > peak:
                peak, where = v, x
        if peak >= mean * (cut_ratio or 3):
            cuts.append(where)

    edges = [box.x] + cuts + [box.x + box.w]
    out = []
    for i in range(parts):
        center = box.x + (box.w * (2 * i + 1)) / (2 * parts)
        lo, hi = box.x, box.x + box.w
        for e in edges:
            if center >= e > lo:
                lo = e
            if center <= e < hi:
                hi = e
        out.append((jround(lo), jround(hi)))
    return out


# ── 스포이드가 무엇을 물었나 ─────────────────────────────────────

@dataclass
class Pick:
    x: int
    y: int
    r: int
    slot: int              # 맞은 목표 번호 (targets 기준), 없으면 -1
    hex: str               # 동그라미 안쪽 색
    delta: float | None


def picks(rings: Sequence[Ring], targets: Sequence[Target]) -> list[Pick]:
    """동그라미 안쪽 색이 목표 오차 안이면 그 칸. 둘 이상이면 더 가까운 쪽 (같으면 앞 칸)."""
    out = []
    for ring in rings:
        lab = to_lab(*ring.rgb)
        slot, best = -1, math.inf
        for i, t in enumerate(targets):
            d = math.sqrt((lab[0] - t.lab[0]) ** 2 + (lab[1] - t.lab[1]) ** 2 + (lab[2] - t.lab[2]) ** 2)
            if d <= t.tol_or_default and d < best:
                best, slot = d, i
        out.append(Pick(ring.x, ring.y, ring.r, slot, ring.hex,
                        None if slot < 0 else jround(best * 10) / 10))
    return out


# ── 바뀌었는지 ───────────────────────────────────────────────────

def signature(f: Frame, rect, n: int = 16) -> np.ndarray:
    """팔레트가 움직였는지 싸게 가늠하는 지문. 소용돌이는 끌기·회전·줌 때만 바뀐다 — 16×16 점만 본다."""
    box = clamp_rect(rect, f)
    k = n or 16
    gy = np.arange(k)
    ys = box.y + np.floor((gy + 0.5) * box.h / k).astype(np.int64)
    xs = box.x + np.floor((gy + 0.5) * box.w / k).astype(np.int64)
    r, g, b = f.rgb(ys, xs)
    return np.stack([r, g, b], axis=-1).astype(np.uint8).ravel()


def signature_diff(a, b) -> float:
    """지문 차이. 0 이면 그대로. 없거나 길이가 다르면 ∞."""
    if a is None or b is None or len(a) != len(b):
        return math.inf
    return float(np.abs(a.astype(np.int32) - b.astype(np.int32)).sum() / len(a))
