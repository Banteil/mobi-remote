"""염색 미니게임 맞출 자리 안내 + 자동 맞추기 — 화면 캡처와 마우스 입력만 쓴다 (패킷·메모리는 건드리지 않는다).

  Session     팔레트가 막 열린 첫 화면(위치 0·회전 0·배율 1)으로 팔레트를 복원하고, 프리셋 색을 스포이드들이
              동시에 집는 자리(회전·배율·위치)를 찾는다. 프리셋 칸 i ↔ 왼쪽부터 i 번째 스포이드 (파트는 가로 등분).
  guide()     지금 상태(fit.pose)에서 해 텍셀들이 화면 어디 있나 + 무엇을 할지 한 줄.
              회전·배율이 맞으면 점들이 스포이드 배치와 같은 모양이 되고, 끌어서 겹치면 끝.
  AutoDriver  측정 → 입력 → 측정. 회전(오른쪽 드래그로 원)·휠·왼쪽 드래그. 확정 단추는 누르지 않는다.

조작 실측 (2026-10-31): 화면 시계 방향으로 그리면 rot 이 준다. 작은 회전은 처음 ~1° 가 먹힌다.
휠 한 칸 = 정확히 ×1.01. 회전 반지름은 1080p(팔레트 749px)에서 340px 로 시험했다 → 팔레트 크기에 비례.
"""
from __future__ import annotations

import ctypes
import math
import threading
import time

import numpy as np

from . import detect as D
from . import fit as FT

ROT_R = 340 / 749          # 회전 원 반지름 ÷ 팔레트 폭
DRAG_MAX = 300 / 749       # 한 번에 끄는 거리 ÷ 팔레트 폭
TIERS = (1.5, 1.0, 0.5)    # 스포이드 둘레 여유 (화면 px) — 넓을수록 입력 오차에 강하다
WIDEN = (1.5, 2, 3, 5)     # 해가 없을 때 오차를 이만큼 늘려 '가장 가까운 자리'


def wrap(d: float) -> float:
    return (d + 180) % 360 - 180


def wheel_scales():
    """휠 칸 단위 배율 (1 에 가까운 것부터). 두 칸 간격 — 한 칸 차이는 해가 거의 같다."""
    ns = [n for n in range(-68, 111, 2) if n and FT.SCALE_MIN <= FT.WHEEL ** n <= FT.SCALE_MAX]
    return [FT.WHEEL ** n for n in sorted(ns, key=abs)]


def is_start(c, pal) -> bool:
    """복원에 쓴 화면이 정말 움직이기 전 화면인가 — 같은 화면을 재면 늘 제자리라, 가림(안내 창·카운트다운)이
    걷힌 뒤 다시 찍은 화면이 그 팔레트로 제자리에 맞는지 본다."""
    m = FT.measure(c, pal)
    if m is None:
        return False
    near0 = all(abs(((p + 0.5) % 1) - 0.5) < 0.01 for p in m[0])
    return near0 and abs(wrap(m[1])) <= 0.5 and abs(m[2] - 1) <= 0.01


class Session:
    """한 번 열린 팔레트. frame: 시작 화면 (BGR(A)), box: detect.Palette, rings/skip: detect.find_leaders 결과."""

    def __init__(self, frame, box, rings, skip_shapes, refs=None):
        S = box.w
        self.box, self.S = box, S
        rings = sorted(rings, key=lambda r: r.x)
        self.rings = rings
        c = self.crop(frame)
        skip = D.skip_mask(skip_shapes, np.arange(box.x, box.x + S), np.arange(box.y, box.y + S))
        self.pal = FT.Palette(c, skip, n=len(rings))
        self.mats = self.pal.add_materials(refs) if refs else None
        self.drops = [((r.x - box.x) / S, 1 - (r.y - box.y) / S) for r in rings]
        self.goal = None          # (rot, scale, pos)
        self.approx = 1.0         # 1 = 정한 오차 안, 그보다 크면 오차를 그만큼 늘려 찾은 자리
        self.use: list[int] = []  # 제약에 쓴 스포이드 번호 (빈 칸 제외)
        self.tl, self.tols = [], []
        self.last = None          # 마지막으로 잰 상태

    def crop(self, frame):
        b = self.box
        return np.ascontiguousarray(np.asarray(frame)[b.y:b.y + self.S, b.x:b.x + self.S, :3])

    def drops_of(self, idx=None):
        return [self.drops[i] for i in (self.use if idx is None else idx)]

    # ---- 해 찾기 ----
    def solve(self, targets, budget: float = 25.0, stop=None) -> bool:
        """targets: 프리셋 칸 순서의 detect.Target (빈 칸 None). 해를 찾으면 self.goal."""
        self.goal, self.approx = None, 1.0
        self.use = [i for i in range(min(len(targets), len(self.drops))) if targets[i]]
        if not self.use:
            return False
        self.tl = [np.array(targets[i].lab) for i in self.use]
        self.tols = [float(targets[i].tol_or_default) for i in self.use]
        drops = self.drops_of()
        t_end = time.monotonic() + budget
        scale_sets = ([1.0], wheel_scales())
        for widen in (1.0,) + WIDEN:
            tols = [t * widen for t in self.tols]
            for scales in scale_sets:
                for mp in (TIERS if widen == 1.0 else TIERS[-1:]):
                    if (stop and stop()) or time.monotonic() > t_end:
                        return False
                    found = FT.solve(self.pal, drops, self.tl, tols, scales=scales, margin_px=mp, limit=8,
                                     deadline=t_end)
                    if found:
                        # 회전이 적고 배율이 1 에 가까운 것
                        self.goal = min(found, key=lambda g: abs(wrap(g[0])) + 40 * abs(math.log(g[1])))
                        self.approx = widen
                        return True
        return False

    def resolve_at(self, m) -> bool:
        """휠을 돌린 뒤 잰 배율에서 지금 회전 둘레로 해를 다시 찾는다 (휠은 칸 단위라 배율이 조금 다를 수 있다)."""
        g = self.goal
        near = np.array(sorted(np.arange(g[0] - 6, g[0] + 6.01, 0.25), key=lambda r: abs(r - g[0])))
        tols = [t * self.approx for t in self.tols]
        for mp in TIERS:
            found = FT.solve(self.pal, self.drops_of(), self.tl, tols, scales=[m[2]], rots=near, margin_px=mp, limit=5)
            if found:
                self.goal = min(found, key=lambda x: abs(wrap(x[0] - m[1])))
                return True
        return False

    # ---- 지금 상태 ----
    def pose(self, frame):
        c = self.crop(frame)
        m = None
        if self.last is not None:   # 배율이 그대로면 고정해 재는 편이 빠르고 정확하다
            m = FT.pose(c, self.pal, scale=self.last[2])
            if m is not None and m[4] < 0.5:
                m = None
        if m is None:
            m = FT.pose(c, self.pal, last=self.last)
        if m is not None:
            self.last = m
        return m

    def ok(self, m, margin_px=1.0) -> bool:
        """지금 상태에서 스포이드들이 목표 색을 집나 — 둘레 margin_px 까지 (자동 맞추기는 1px 여유를 남긴다)."""
        if not self.use:
            return False
        tols = [t * self.approx for t in self.tols]
        return FT.colors_ok(self.pal, m, self.drops_of(), self.tl, tols, margin_px=margin_px)

    def to_frame(self, a, b):
        return self.box.x + a * self.S, self.box.y + (1 - b) * self.S

    def guide(self, m, caught: bool = False) -> dict:
        """{'points': [(slot, x, y, 스포이드 x, y)], 'text': 할 일, 'done': 맞았나} — 좌표는 프레임 픽셀.
        caught: 화면 고리 색이 이미 모두 목표 안 (tracker) — 계산보다 화면을 믿는다."""
        g = self.goal
        if caught or (m is not None and self.ok(m, 0.5)):
            return {"points": [], "text": "맞았습니다 — 확인하고 적용하세요", "done": True}
        if g is None:
            return {"points": [], "text": "이 색 조합이 되는 자리를 찾지 못했습니다", "done": False}
        if m is None:
            return {"points": [], "text": "지금 팔레트 상태를 재지 못했습니다", "done": False}
        pts = []
        for slot, (a, b) in zip(self.use, FT.goal_points(self.drops_of(), g, m)):
            x, y = self.to_frame(a, b)
            r = self.rings[slot]
            pts.append((slot, x, y, r.x, r.y))
        d_rot = wrap(g[0] - m[1])
        n = int(round(math.log(g[1] / m[2]) / math.log(FT.WHEEL)))
        if abs(d_rot) > 1.0:
            text = f"오른쪽 버튼으로 {'시계' if d_rot < 0 else '반시계'} 방향 {abs(d_rot):.0f}° 돌리세요"
        elif n:
            text = f"휠을 {'위로' if n > 0 else '아래로'} {abs(n)}칸 돌리세요"
        else:
            text = "점을 같은 색 스포이드에 겹치게 끌어 주세요"
        if self.approx > 1:
            text += f"  (정확한 자리가 없어 오차 ×{self.approx:g})"
        return {"points": pts, "text": text, "done": False}


# ---------------------------------------------------------------- 입력 (절대좌표 SendInput)
# mabi.inputs.Input 은 SetCursorPos 로 옮겨 회전 끝점이 정수 픽셀로 정확히 떨어지는지 보장하지 않는다 →
# 픽셀 가운데를 가리키는 절대좌표 이동을 따로 둔다 (회전 끝점이 1px 어긋나면 0.17° 틀린다).
user32 = ctypes.windll.user32


class _MI(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _INP(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


MOVE_ABS = 0x0001 | 0x8000 | 0x4000   # MOVE | ABSOLUTE | VIRTUALDESK
LDOWN, LUP, RDOWN, RUP, WHEEL = 0x0002, 0x0004, 0x0008, 0x0010, 0x0800


def _send(flags, x=0, y=0, data=0):
    i = _INP(type=0)
    i.mi = _MI(x, y, data & 0xFFFFFFFF, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INP))


def _abs(sx, sy):
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return int(((sx - vx) + 0.5) * 65536 / vw), int(((sy - vy) + 0.5) * 65536 / vh)


def _cands(t, r):
    out = []
    for rr in range(r - 6, r + 7):
        x0, y0 = rr * math.cos(t), rr * math.sin(t)
        for x in (math.floor(x0), math.ceil(x0)):
            for y in (math.floor(y0), math.ceil(y0)):
                out.append((x, y, math.atan2(y, x)))
    return out


def end_points(deg, r):
    """회전 시작·끝 정수 픽셀 ((sx, sy), (ex, ey), 실제 각도). 커서는 정수 픽셀이라 한 반지름·한 방향으로는
    1px ≈ 57/r 도 단위밖에 안 된다 → 시작 방향(20~70°)과 반지름을 조금씩 바꾼 조합에서 고른다
    (2026-10-31 실기: 0.1° 를 넣으면 0.2° 씩 왔다 갔다 했다)."""
    best = None
    for a_deg in range(20, 71, 2):
        a = math.radians(a_deg)
        for sx, sy, sa in _cands(a, r):
            for ex, ey, ea in _cands(a + math.radians(deg), r):
                got = wrap(math.degrees(ea - sa))
                e = abs(got - deg)
                if best is None or e < best[0]:
                    best = (e, (sx, sy), (ex, ey), got)
        if best[0] < 0.005:
            break
    return best[1], best[2], best[3]


class Stopped(Exception):
    pass


class Mouse:
    """to_screen(x, y): 프레임 픽셀 → 화면 픽셀. stop(): True 면 다음 움직임에서 버튼을 떼고 멈춘다."""

    def __init__(self, to_screen, stop=lambda: False):
        self.to_screen, self.stop = to_screen, stop

    def move(self, x, y):
        _send(MOVE_ABS, *_abs(*self.to_screen(x, y)))

    def _check(self, up=None):
        if self.stop():
            if up:
                _send(up)
            raise Stopped

    def drag(self, x1, y1, x2, y2, steps=30):
        self._check()
        self.move(x1, y1)
        time.sleep(0.08)
        _send(LDOWN)
        time.sleep(0.08)
        for i in range(1, steps + 1):
            self._check(LUP)
            self.move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
            time.sleep(0.012)
        time.sleep(0.15)          # 마지막 자리에서 잠깐 멈춰 관성 없이 놓는다
        _send(LUP)

    def rotate(self, cx, cy, deg, r):
        """(cx, cy) 를 축으로 화면에서 deg 도 원을 그린다 (+ = 화면 시계 방향 — 화면 y 가 아래라서)."""
        self._check()
        cx, cy = round(cx), round(cy)
        (sx, sy), (ex, ey), _ = end_points(deg, r)
        a0 = math.atan2(sy, sx)
        self.move(cx, cy)
        time.sleep(0.08)
        _send(RDOWN)
        time.sleep(0.08)
        self.move(cx + sx, cy + sy)            # 축에서 시작점으로 한 번에 (첫 움직임의 각도 = 시작 각도)
        time.sleep(0.03)
        n = max(2, int(abs(deg)))
        for i in range(1, n):
            self._check(RUP)
            t = a0 + math.radians(deg * i / n)
            self.move(cx + r * math.cos(t), cy + r * math.sin(t))
            time.sleep(0.012)
        self.move(cx + ex, cy + ey)            # 끝점도 정수 픽셀 그대로
        time.sleep(0.15)
        _send(RUP)

    def wheel(self, x, y, notches):
        self._check()
        self.move(x, y)
        time.sleep(0.05)
        for _ in range(abs(notches)):
            self._check()
            _send(WHEEL, data=120 if notches > 0 else -120)
            time.sleep(0.03)


# ---------------------------------------------------------------- 자동 맞추기
class AutoDriver:
    """측정 → 입력 → 측정. 회전 방향·먹히는 각도·휠 배율은 입력 결과로 보정한다.
    snap(): 새 프레임, on_step(m, 문구): 진행 알림, stop: threading.Event."""

    def __init__(self, sess: Session, snap, mouse: Mouse, stop: threading.Event, on_step=None):
        self.s, self.snap, self.mouse, self.stop = sess, snap, mouse, stop
        self.on_step = on_step or (lambda m, t: None)
        self.rot_dead = 1.0       # 작은 회전에서 먹히는 각도 (매번 다시 잰다)
        self.rot_sign = -1.0      # 화면에서 그린 각도(시계 +) → rot 는 반대로
        self.wheel_k = math.log(FT.WHEEL)
        self.cx, self.cy = sess.to_frame(0.5, 0.5)
        self.R = max(60, round(ROT_R * sess.S))
        self.scale = sess.last[2] if sess.last else None

    def now(self, tries=4):
        """화면이 멈출 때까지 (두 번 연속 같게 잴 때까지) 잰다."""
        last = None
        for _ in range(tries):
            if self.stop.is_set():
                raise Stopped
            time.sleep(0.25)
            frame = self.snap()
            if frame is None:
                continue
            c = self.s.crop(frame)
            if self.scale is None:
                m = FT.pose(c, self.s.pal, last=self.s.last)
                if m is None:
                    continue
                self.scale = m[2]
                last = m
                continue
            m = FT.measure(c, self.s.pal, scale=self.scale)
            if m is None:
                continue
            if last and abs(m[1] - last[1]) < 0.15 and abs(m[2] / last[2] - 1) < 0.002 \
                    and math.hypot(m[0][0] - last[0][0], m[0][1] - last[0][1]) * self.s.S < 0.6:
                m = FT.refine(c, self.s.pal, m)
                self.s.last = m
                return m
            last = m
        if last is not None:
            self.s.last = last
        return last

    def run(self, rounds=14):
        """맞으면 (True, m), 못 맞추면 (False, m)."""
        s, g = self.s, self.s.goal
        m = self.now()
        if m is None:
            return False, None
        fine, fine_all = 0, 0
        for _ in range(rounds):
            g = s.goal
            if s.ok(m) or max(FT.miss_texels(m, g, s.drops_of())) <= 0.3:
                return True, m
            d_rot = wrap(g[0] - m[1])
            # 1) 회전 — 미세 회전은 연달아 두 번까지, 모두 다섯 번까지 (측정이 흔들려 끝없이 돌지 않게)
            if abs(d_rot) > 0.03 and (abs(d_rot) > 3 or (fine < 2 and fine_all < 5 and (fine == 0 or abs(d_rot) > 0.08))):
                fine += abs(d_rot) <= 3
                fine_all += abs(d_rot) <= 3
                before = m
                cmd = d_rot + math.copysign(self.rot_dead, d_rot) if abs(d_rot) <= 3 else d_rot
                self.on_step(m, f"회전 {d_rot:+.1f}°")
                self.mouse.rotate(self.cx, self.cy, cmd * self.rot_sign, self.R)
                m = self.now() or m
                got = wrap(m[1] - before[1])
                if abs(cmd) <= 4:
                    lost = abs(cmd) - abs(got) if got * cmd >= 0 else abs(cmd)
                    self.rot_dead = max(0.0, min(2.5, lost))
                if abs(d_rot) > 3 and abs(got) > 1:
                    self.rot_sign *= d_rot / got if abs(d_rot / got) < 3 else 1
                    self.rot_sign = max(-1.3, min(1.3, self.rot_sign)) if abs(self.rot_sign) > 0.7 else \
                        math.copysign(1, self.rot_sign)
                continue
            # 2) 배율 — 휠 반 칸보다 차이가 클 때만
            d_ls = math.log(g[1] / m[2])
            n = int(round(d_ls / self.wheel_k)) if abs(d_ls) > abs(self.wheel_k) / 2 else 0
            if n:
                before = m
                n = max(-60, min(60, n))
                self.on_step(m, f"휠 {n:+d}칸")
                self.mouse.wheel(self.cx, self.cy, n)
                self.scale = None                    # 휠 뒤엔 배율도 잰다
                m = self.now() or m
                got = math.log(m[2] / before[2])
                if abs(n) >= 3 and abs(got) > 0.005:
                    self.wheel_k = got / n
                if abs(m[2] / g[1] - 1) > 1e-4:      # 칸 단위라 배율이 조금 다르면 그 배율에서 해를 다시
                    s.resolve_at(m)
                continue
            # 3) 위치 — 같은 무늬가 되는 자리 중 가장 가까운 곳
            tp = FT.best_pos(s.drops_of(), g, m)
            dx, dy = (tp[0] - m[0][0]) * s.S, -(tp[1] - m[0][1]) * s.S   # 프레임 픽셀 (y 아래 +)
            L = math.hypot(dx, dy)
            if L > 0.3:
                f = min(1.0, DRAG_MAX * s.S / L)
                x1, y1 = self.cx - dx * f / 2, self.cy - dy * f / 2
                self.on_step(m, f"끌기 {L:.0f}px")
                self.mouse.drag(x1, y1, x1 + dx * f, y1 + dy * f)
                m = self.now() or m
                fine = 0
                continue
            break
        return s.ok(m), m
