"""염색 맞추기 계산 — 화면 읽기만 한다 (패킷·메모리는 건드리지 않는다).

계산식 (GameAssembly.dll DyeingPaletteInstanceImpl.UpdatePaletteAndColors 정적 분석):
  w = R(-rot) (d - 0.5 - pos) / scale,  (u, v) = F(w),  색 = 재질 팔레트[frac(v), frac(u)]
  d = 팔레트 안 정규 좌표 (a = x/S, b = 1 - y/S),  F = sin 비틀기 두 번 (시드 없는 고정식)

시작 화면은 늘 위치 0·회전 0·배율 1 이라 그 한 장을 거꾸로 되짚으면 팔레트(254×254) 거의 전부가 나온다.
그 뒤로는 화면에서 색을 찾지 않고 "얼마나 움직였나"(pos·rot·scale)만 잰다 — 스포이드가 가리거나 돌리고
줌해서 화면 색이 섞여도 상관없다.

재질이 섞인 옷은 화면 가로 칸(스포이드 수만큼 등분)마다 그 스포이드 재질 그림이 보이고, 판마다 다른
사각형 맞바꿈은 재질 공통이다 → 시작 화면의 천 칸을 원본 그림(materials.py)과 대조해 맞바꿈 지도를 만들고
재질마다 팔레트를 채운다 (2026-10-31 실측: 천 칸 출신 지도는 87~92% 맞고 금속·가죽 칸 출신은 20~60% 라 안 씀).

조작 실측 (2026-10-31): 휠 한 칸 = 정확히 ×1.01, 배율 0.5~3 에서 잘림. 회전 축 = 오른쪽 누른 점,
화면 시계 방향으로 그리면 rot 이 준다. 작은 회전은 처음 ~1° 가 먹힌다.
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import detect as D

K = 4 * np.pi
TEX = 254
SCALE_MIN, SCALE_MAX = 0.5, 3.0     # 시트 DyeMiniGameConstants PaletteSizeMin/Max
WHEEL = 1.01                        # 휠 한 칸 배율
MATS = ("Cloth", "Leather", "Metal", "Wood")


# ---------------------------------------------------------------- 계산식
def F(x, y):
    x = x + np.sin(K * y) / K
    y = y + np.sin(K * x) / K
    x = x + np.sin(K * y) / K
    y = y + np.sin(K * x) / K
    return x, y


def Finv(x, y):
    y = y - np.sin(K * x) / K
    x = x - np.sin(K * y) / K
    y = y - np.sin(K * x) / K
    x = x - np.sin(K * y) / K
    return x, y


def to_w(a, b, pos, rot, scale):
    px, py = (a - 0.5 - pos[0]) / scale, (b - 0.5 - pos[1]) / scale
    r = np.radians(-rot)
    c, s = np.cos(r), np.sin(r)
    return c * px - s * py, s * px + c * py


def uv_of(a, b, pos, rot, scale):
    return F(*to_w(a, b, pos, rot, scale))


def grid_ab(S):
    g = (np.arange(S) + 0.5) / S
    a, yy = np.meshgrid(g, g)
    return a, 1 - yy


def lab_of(bgr):
    bgr = np.asarray(bgr)
    b, g, r = [bgr[..., k].astype(np.intp) for k in range(3)]
    return np.stack(D.lab_arrays(r, g, b), -1)


def interior(img):
    """3×3 이웃이 같은 색인 픽셀 (칸 안쪽 — 경계에서 섞인 색 제외)."""
    i = img.astype(np.int16)
    m = np.ones(img.shape[:2], bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            m &= (np.abs(np.roll(np.roll(i, dy, 0), dx, 1) - i).max(-1) <= 2)
    m[[0, -1], :] = False
    m[:, [0, -1]] = False
    return m


def _tex(u, v):
    return (np.floor((np.asarray(v) % 1) * TEX).astype(int) % TEX,
            np.floor((np.asarray(u) % 1) * TEX).astype(int) % TEX)


# ---------------------------------------------------------------- 복원
class Palette:
    """시작 화면 팔레트 안쪽(S×S BGR)에서 복원한 팔레트 (행 아래부터 = v 증가) + 화면 RGB → 텍스처 좌표 표.
    n = 스포이드 수 (화면 가로 칸 수). 한 재질이면 칸과 상관없이 이 팔레트 하나."""

    def __init__(self, c, skip=None, n=1):
        S = c.shape[0]
        self.S, self.n = S, max(1, n)
        a, b = grid_ab(S)
        u, v = uv_of(a, b, (0, 0), 0, 1)
        ok = np.ones((S, S), bool) if skip is None else ~skip
        iy, ix = _tex(u, v)
        cnt = np.zeros((TEX, TEX))
        np.add.at(cnt, (iy[ok], ix[ok]), 1)
        # 텍셀마다 그 중심에 가장 가까운 화면 픽셀의 실제 색 (평균하면 경계 색이 섞여 실제에 없는 색이 된다)
        dc = np.abs((u % 1) * TEX % 1 - 0.5) + np.abs((v % 1) * TEX % 1 - 0.5)
        order = np.argsort(-dc[ok])                   # 먼 것부터 써서 가까운 것이 마지막에 남는다
        self.bgr = np.zeros((TEX, TEX, 3), np.uint8)
        self.bgr[iy[ok][order], ix[ok][order]] = c[ok][order]
        self.known = cnt > 0                          # 줄·고리에 가려 못 본 텍셀은 False
        self.lab = lab_of(self.bgr)
        # 색 표: 칸 안쪽 픽셀의 정확한 RGB → 텍스처 좌표 (원형 평균). 여러 곳에 흩어진 색은 버린다.
        m = interior(c) & ok
        code = (c[..., 0].astype(np.int64) << 16) | (c[..., 1].astype(np.int64) << 8) | c[..., 2]
        code, uu, vv = code[m], (u[m] % 1), (v[m] % 1)
        keys, inv = np.unique(code, return_inverse=True)
        cntk = np.bincount(inv)

        def ang(t):
            return np.bincount(inv, np.cos(2 * np.pi * t)) + 1j * np.bincount(inv, np.sin(2 * np.pi * t))
        zu, zv = ang(uu) / cntk, ang(vv) / cntk
        good = (np.abs(zu) > 0.995) & (np.abs(zv) > 0.995)   # 흩어짐 ≈ 텍셀 2개 안
        self.keys = keys[good]
        self.ku = (np.angle(zu[good]) / (2 * np.pi)) % 1
        self.kv = (np.angle(zv[good]) / (2 * np.pi)) % 1
        self.key_mat = None
        self.mats = None
        self.kbgr = [self.bgr] * self.n
        self.kknown = [self.known] * self.n
        self.klab = [self.lab] * self.n
        self.map_sure = None
        self._stack = None

    # 스포이드 k 는 화면 칸 k 에 있다 → 그 칸 재질 팔레트
    def strip(self, a):
        return np.floor(np.asarray(a) * self.n).astype(int).clip(0, self.n - 1)

    def color_at(self, u, v, a=None):
        iy, ix = _tex(u, v)
        if a is None or self._stack is None:
            return self.bgr[iy, ix]
        return self._stack[self.strip(a), iy, ix]

    def known_at(self, u, v, a):
        iy, ix = _tex(u, v)
        if self._stack is None:
            return self.known[iy, ix]
        return self._kstack[self.strip(a), iy, ix]

    # ---- 재질 섞인 옷 ----
    def add_materials(self, refs: dict, sure=0.5):
        """refs: 재질 이름 → 원본 그림 (행 아래부터). 칸마다 재질을 정하고, 섞였으면 재질별 팔레트를 만든다."""
        n = self.n
        st = strips(n)
        self.mats = detect_materials(self.bgr, self.known, st, n, refs)
        if len(set(self.mats)) > 1:
            d, vote = swap_map(self.bgr, self.known, st, [refs[m] for m in self.mats])
            iy, ix = np.mgrid[0:TEX, 0:TEX]
            sy, sx = (iy + d[..., 1]) % TEX, (ix + d[..., 0]) % TEX
            mats = np.array(self.mats)
            # 지도는 천 칸 출신만 믿는다. 원본 마지막 열(전부 검정)은 화면에 안 그려져 화면과 달라 뺀다
            ok = (vote >= sure) & (mats[st] == "Cloth") & (sx < TEX - 1)
            self.map_sure = float(ok.mean())
            self.kbgr, self.kknown = [], []
            for m in self.mats:
                own = self.known & (mats[st] == m)      # 같은 재질 칸에서 직접 본 곳은 그대로
                self.kbgr.append(np.where(own[..., None], self.bgr, refs[m][sy, sx]))
                self.kknown.append(own | ok)
            self.klab = [lab_of(b) for b in self.kbgr]
            self._stack = np.stack(self.kbgr)
            self._kstack = np.stack(self.kknown)
            # 측정 색 표: 그 색을 시작 화면 어느 재질 칸에서 봤나 — 화면 칸 재질과 같은 것만 대응점으로
            self.mat_idx = np.array([MATS.index(m) for m in self.mats])
            ky, kx = _tex(self.ku, self.kv)
            self.key_mat = self.mat_idx[st[ky, kx]]
        return self.mats


# ---------------------------------------------------------------- 재질
Q, TOL = 4, 3
_NB = [(dy, dx) for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2) if (dy, dx) != (0, 0)]
_NB8 = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
_occ_cache: dict[int, np.ndarray] = {}


def _occ(ref):
    key = id(ref)
    if key not in _occ_cache:
        g = np.zeros((64, 64, 64), bool)
        c = ref.reshape(-1, 3) // Q
        g[c[:, 0], c[:, 1], c[:, 2]] = True
        out = g.copy()
        for ax in range(3):
            out = out | np.roll(out, 1, ax) | np.roll(out, -1, ax)
        _occ_cache[key] = out
    return _occ_cache[key]


def strips(n):
    """시작 화면에서 텍셀이 보이던 화면 칸 번호 (가로 n 등분)."""
    iy, ix = np.mgrid[0:TEX, 0:TEX]
    wx, _ = Finv((ix + 0.5) / TEX, (iy + 0.5) / TEX)
    return np.floor(((wx + 0.5) % 1) * n).astype(int).clip(0, n - 1)


def detect_materials(bgr, known, st, n, refs):
    """칸마다 재질: 그 재질 원본에만 있는 색의 비율이 가장 높은 것 (천·금속은 색이 겹쳐 '그것에만' 으로 센다)."""
    q = bgr // Q
    names = [m for m in MATS if m in refs]
    hit = np.stack([_occ(refs[m])[q[..., 0], q[..., 1], q[..., 2]] for m in names], -1)
    only = hit & (hit.sum(-1, keepdims=True) == 1)
    out = []
    for k in range(n):
        sel = known & (st == k)
        out.append(names[int(only[sel].mean(0).argmax())] if sel.any() else names[0])
    return out


def _support(obs, known, R, kk, dmap, nb):
    iy, ix = np.mgrid[0:TEX, 0:TEX]
    sup = np.zeros((TEX, TEX), np.float32)
    for dy, dx in list(nb) + [(0, 0)]:
        ny, nx = (iy + dy) % TEX, (ix + dx) % TEX
        rv = R[kk[ny, nx], (ny + dmap[..., 1]) % TEX, (nx + dmap[..., 0]) % TEX]
        sup += (np.abs(rv - obs[ny, nx]).max(-1) <= TOL) & known[ny, nx]
    return sup / (len(nb) + 1)


def swap_map(bgr, known, st, refs, rounds=6):
    """텍셀마다 원본 출처까지의 이동 (dx, dy) 와 확실도(이웃이 같은 이동으로 원본과 맞는 비율).
    씨앗: 텍셀 색 → 원본에서 같은 색 자리들. 그다음 이웃의 이동을 후보로 번진다 (맞바꿈은 사각형)."""
    obs = bgr.astype(np.int16)
    R = np.stack(refs).astype(np.int16)
    T = []
    seed = np.zeros((TEX, TEX), bool)
    seed[::2, ::2] = True
    for k in range(len(refs)):
        ref = R[k]
        q = (ref // Q).astype(np.int64)
        key = ((q[..., 0] << 12) | (q[..., 1] << 6) | q[..., 2]).ravel()
        order = np.argsort(key)
        ks = key[order]
        sel = np.flatnonzero((known & (st == k) & seed).ravel())
        oq = (obs.reshape(-1, 3)[sel] // Q).astype(np.int64)
        for d0 in (-1, 0, 1):
            for d1 in (-1, 0, 1):
                for d2 in (-1, 0, 1):
                    qk = ((oq[:, 0] + d0) << 12) | ((oq[:, 1] + d1) << 6) | (oq[:, 2] + d2)
                    lo, hi = np.searchsorted(ks, qk, "left"), np.searchsorted(ks, qk, "right")
                    cnt = hi - lo
                    cnt[cnt > 40] = 0                       # 여기저기 있는 흔한 색은 단서가 안 된다
                    if not cnt.sum():
                        continue
                    rep = np.repeat(np.arange(len(sel)), cnt)
                    pos = order[np.repeat(lo - np.r_[0, np.cumsum(cnt)[:-1]], cnt) + np.arange(cnt.sum())]
                    t = sel[rep]
                    py, px = pos // TEX, pos % TEX
                    good = np.abs(ref[py, px] - obs.reshape(-1, 3)[t]).max(-1) <= TOL
                    T.append(np.stack([t[good], (px[good] - t[good] % TEX) % TEX,
                                       (py[good] - t[good] // TEX) % TEX], -1))
    d = np.zeros((TEX, TEX, 2), np.int64)
    if T:
        T = np.concatenate(T)
        ty, tx = T[:, 0] // TEX, T[:, 0] % TEX
        sup = np.zeros(len(T), np.int32)
        for dy, dx in _NB:
            ny, nx = (ty + dy) % TEX, (tx + dx) % TEX
            rv = R[st[ny, nx], (ny + T[:, 2]) % TEX, (nx + T[:, 1]) % TEX]
            sup += (np.abs(rv - obs[ny, nx]).max(-1) <= TOL) & known[ny, nx]
        o = np.lexsort((-sup, T[:, 0]))
        T = T[o]
        first = np.r_[True, T[1:, 0] != T[:-1, 0]]
        d.reshape(-1, 2)[T[first, 0]] = T[first, 1:]
    best_v = _support(obs, known, R, st, d, _NB8)
    for _ in range(rounds):
        best_d, cur = d.copy(), best_v.copy()
        for dy, dx in _NB8:
            cand = np.roll(np.roll(d, -dy, 0), -dx, 1)
            v = _support(obs, known, R, st, cand, _NB8)
            m = v > cur
            best_d[m], cur[m] = cand[m], v[m]
        d, best_v = best_d, cur
    return d, best_v


# ---------------------------------------------------------------- 측정
def measure(c, pal: Palette, rng=None, scale=None):
    """팔레트 안쪽 한 장 → (pos, rot, scale, 근거 수). 칸이 작으면 촘촘히 다시 잰다.
    scale 을 주면 배율은 그 값으로 두고 회전·위치만 잰다 (휠 칸 수로 정확히 아는 값이라 더 정밀)."""
    rng = rng or np.random.default_rng(0)
    m = _measure(c, pal, rng, 2, scale)
    if m is None or m[3] < 60:
        m2 = _measure(c, pal, rng, 1, scale)
        if m2 is not None and (m is None or m2[3] > m[3]):
            m = m2
    return m


def _measure(c, pal: Palette, rng, step, fixed_scale=None):
    """색 표 대응점 → 이웃 쌍 허프(배율·회전) → 평행이동 → 최소제곱."""
    S = c.shape[0]
    sub = c[::step, ::step]
    code = (sub[..., 0].astype(np.int64) << 16) | (sub[..., 1].astype(np.int64) << 8) | sub[..., 2]
    ys, xs = np.nonzero(interior(sub))
    cd = code[ys, xs]
    if not len(pal.keys):
        return None
    j = np.clip(np.searchsorted(pal.keys, cd), 0, len(pal.keys) - 1)
    hit = pal.keys[j] == cd
    ys, xs, j = ys[hit], xs[hit], j[hit]
    a = (xs * step + 0.5) / S
    if pal.key_mat is not None:     # 재질 섞인 옷: 화면 칸 재질과 같은 재질에서 본 색만
        same = pal.key_mat[j] == pal.mat_idx[pal.strip(a)]
        ys, xs, j, a = ys[same], xs[same], j[same], a[same]
    if len(j) < 30:
        return None
    b = 1 - (ys * step + 0.5) / S
    wx, wy = Finv(pal.ku[j], pal.kv[j])
    n = len(a)
    i1, i2 = rng.integers(0, n, 60000), rng.integers(0, n, 60000)
    da = (a[i2] - a[i1]) + 1j * (b[i2] - b[i1])
    near = (np.abs(da) > 0.01) & (np.abs(da) < 0.12)
    i1, i2, da = i1[near], i2[near], da[near]
    dwx, dwy = wx[i2] - wx[i1], wy[i2] - wy[i1]
    dw = (dwx - np.round(dwx)) + 1j * (dwy - np.round(dwy))
    z = dw / da
    lz, ang = np.log(np.abs(z) + 1e-9), np.degrees(np.angle(z))
    h, xe, ye = np.histogram2d(lz, ang, bins=(140, 360), range=((-1.4, 1.0), (-180, 180)))
    k = np.unravel_index(h.argmax(), h.shape)
    L0, A0 = (xe[k[0]] + xe[k[0] + 1]) / 2, (ye[k[1]] + ye[k[1] + 1]) / 2
    sel = (np.abs(lz - L0) < 0.03) & (np.abs(((ang - A0) + 180) % 360 - 180) < 1.5)
    if sel.sum() < 10:
        return None
    zm = np.median(z[sel].real) + 1j * np.median(z[sel].imag)
    w = wx + 1j * wy
    t = w - zm * (a + 1j * b)
    h2, xe2, ye2 = np.histogram2d(t.real % 1, t.imag % 1, bins=100, range=((0, 1), (0, 1)))
    k2 = np.unravel_index(h2.argmax(), h2.shape)
    T0 = (xe2[k2[0]] + 0.005) + 1j * (ye2[k2[1]] + 0.005)
    dd = t - T0
    dd = (dd.real - np.round(dd.real)) + 1j * (dd.imag - np.round(dd.imag))
    inl = np.abs(dd) < 0.02
    if inl.sum() < 10:
        return None
    off = t - T0
    wz = w - (np.round(off.real) + 1j * np.round(off.imag))
    A = np.stack([a[inl] + 1j * b[inl], np.ones(inl.sum())], 1)
    (zf, tf), *_ = np.linalg.lstsq(A, wz[inl], rcond=None)
    if fixed_scale:
        zf = zf / abs(zf) / fixed_scale
        tf = np.mean(wz[inl] - zf * (a[inl] + 1j * b[inl]))
    scale = 1 / abs(zf)
    rot = -np.degrees(np.angle(zf))
    pp = -tf / zf - (0.5 + 0.5j)
    return (float(pp.real), float(pp.imag)), float(rot), float(scale), int(inl.sum())


def refine(c, pal: Palette, m, rng=None, n=20000, free_scale=False):
    """정밀 맞춤: 칸 안쪽 화면 픽셀에서 예측 색 == 실제 색인 비율이 가장 높게 위치(0.15px)·회전(0.015°)을 다듬는다.
    돌려주는 값: (pos, rot, scale, 근거, 일치 비율)."""
    rng = rng or np.random.default_rng(1)
    S = c.shape[0]
    ys, xs = np.nonzero(interior(c))
    if len(ys) < 500:
        return (*m[:4], 0.0)
    k = rng.choice(len(ys), min(n, len(ys)), replace=False)
    ys, xs = ys[k], xs[k]
    a, b = (xs + 0.5) / S, 1 - (ys + 0.5) / S
    obs = c[ys, xs].astype(np.int16)
    scale = m[2]

    def score(p, r, sc_=None, a_=a, b_=b, o_=obs):
        u, v = uv_of(a_, b_, p, r, sc_ or scale)
        eq = np.abs(pal.color_at(u, v, a_).astype(np.int16) - o_).max(-1) <= 3
        kn = pal.known_at(u, v, a_)
        return float(eq[kn].mean()) if kn.any() else 0.0

    if free_scale:
        # 화면 가운데 무늬를 그대로 둔 채 배율만 바꾸면 pos 는 k 배 (pos+0.5 가 가운데 0.5 기준으로 k 배)
        bs = (score(m[0], m[1]), scale, m[0])
        for step in (0.0015, 0.0004):
            base = bs
            for j in range(-8, 9):
                kk = 1 + j * step
                p = (base[2][0] * kk, base[2][1] * kk)
                sc = score(p, m[1], base[1] * kk)
                if sc > bs[0]:
                    bs = (sc, base[1] * kk, p)
        scale = bs[1]
        m = (bs[2], m[1], scale, m[3])
    best = (score(m[0], m[1]), m[0], m[1])
    if m[3] < 1500:
        # 근거가 적으면 회전이 1° 가까이 틀릴 수 있다 (재질 섞인 옷·작은 배율) → 회전 ±1.2° × 위치 ±4.5px 를 거칠게 먼저
        sub = rng.choice(len(a), min(4000, len(a)), replace=False)
        a2, b2, o2 = a[sub], b[sub], obs[sub]
        c0 = (score(m[0], m[1], None, a2, b2, o2), m[0], m[1])
        for dr in np.arange(-1.2, 1.2001, 0.2):
            q = np.radians(dr)
            px0 = m[0][0] * np.cos(q) - m[0][1] * np.sin(q)
            py0 = m[0][0] * np.sin(q) + m[0][1] * np.cos(q)
            for i in range(-3, 4):
                for j in range(-3, 4):
                    p = (px0 + i * 1.5 / S, py0 + j * 1.5 / S)
                    sc = score(p, m[1] + dr, None, a2, b2, o2)
                    if sc > c0[0]:
                        c0 = (sc, p, m[1] + dr)
        best = (score(c0[1], c0[2]), c0[1], c0[2])
    for step_px in (0.6, 0.15):
        base = best
        for i in range(-4, 5):
            for j in range(-4, 5):
                p = (base[1][0] + i * step_px / S, base[1][1] + j * step_px / S)
                sc = score(p, base[2])
                if sc > best[0]:
                    best = (sc, p, base[2])
        base = best
        for dr in np.arange(-0.06, 0.0601, 0.015):
            sc = score(base[1], base[2] + dr)
            if sc > best[0]:
                best = (sc, base[1], base[2] + dr)
    return best[1], float(best[2]), float(scale), m[3], best[0]


def pose(c, pal: Palette, last=None, scale=None):
    """지금 상태 (pos, rot, scale, 근거, 일치). scale 을 알면(자동 입력 중) 고정, 모르면 재서 휠 칸에 맞춘다.
    배율이 작으면(0.8 아래) 자유 측정이 잘 안 돼 직전 배율 둘레를 휠 칸 단위로 찾아본다."""
    if scale is not None:
        m = measure(c, pal, scale=scale)
        return refine(c, pal, m) if m else None
    # 배율은 휠 칸 단위로만 바뀐다 → 자유롭게 잰 값(재질 섞인 옷에선 2% 넘게 틀림) 둘레의 칸 값들을
    # 하나씩 고정해 재 보고 화면과 가장 잘 맞는 것. 자유 측정이 안 되면(작은 배율) 직전 배율 둘레를 넓게.
    m = measure(c, pal)
    if m is not None and m[3] >= 60 and SCALE_MIN * 0.97 <= m[2] <= SCALE_MAX * 1.03:
        centre, span = m[2], 5
    else:
        centre, span = (last[2] if last else 1.0), 30
    cands = {SCALE_MIN, SCALE_MAX}
    # 끝(0.5·3)에 닿았다 돌아오면 칸 값이 어긋나는데(0.5·1.01^n) 드물어 시작 기준 칸 값만 본다
    n0 = round(math.log(centre) / math.log(WHEEL))
    for k in range(-span, span + 1):
        cands.add(round(min(SCALE_MAX, max(SCALE_MIN, WHEEL ** (n0 + k))), 6))
    cands = sorted(s for s in cands if abs(math.log(s / centre)) <= span * math.log(WHEEL) + 1e-9)
    rng = np.random.default_rng(2)
    S = c.shape[0]
    ys, xs = np.nonzero(interior(c))
    if len(ys) < 500:
        return None
    k = rng.choice(len(ys), min(4000, len(ys)), replace=False)
    a, b, obs = (xs[k] + 0.5) / S, 1 - (ys[k] + 0.5) / S, c[ys[k], xs[k]].astype(np.int16)
    best = None
    for s in cands:
        mm = measure(c, pal, scale=s)
        if mm is None:
            continue
        u, v = uv_of(a, b, mm[0], mm[1], s)
        eq = np.abs(pal.color_at(u, v, a).astype(np.int16) - obs).max(-1) <= 3
        kn = pal.known_at(u, v, a)
        sc = float(eq[kn].mean()) if kn.any() else 0.0
        if best is None or sc > best[0]:
            best = (sc, mm)
    return refine(c, pal, best[1]) if best else None


# ---------------------------------------------------------------- 해 찾기
OFFS = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)]


def solve(pal: Palette, drops, targets_lab, tols, scales=None, rots=None, margin_px=1.5, limit=200, deadline=None):
    """목표 Lab 들을 스포이드들이 동시에 집는 (rot, scale, pos) 후보들. tols 는 색마다 오차 (Lab 거리).
    여유는 화면 픽셀 기준 — 스포이드 둘레 margin_px 안 여러 점이 모두 목표 색이어야 한다. 비틀림이 심한 곳은
    화면 1px 이 텍셀 여러 개라 텍셀 기준 여유로는 실제 입력 오차(1~2px)에 옆 칸으로 넘어간다."""
    S = pal.S
    if scales is None:   # 1 에 가까운 배율부터 (움직임이 적고 칸이 커서 맞추기 쉽다)
        scales = np.exp(np.linspace(np.log(SCALE_MIN), np.log(SCALE_MAX), 37))
        scales = scales[np.argsort(np.abs(np.log(scales)))]
    if rots is None:     # 0 에 가까운 회전부터
        rots = np.array(sorted(np.arange(-179, 181, 1.0), key=abs))
    ks = [int(pal.strip(a)) for a, _ in drops]
    masks = [(((pal.klab[k] - t) ** 2).sum(-1) <= tol * tol) & pal.kknown[k]
             for k, t, tol in zip(ks, targets_lab, tols)]
    for m_ in masks:
        # 그림 가장자리 2텍셀은 뺀다 — 원본 Cloth 마지막 열(253)은 전부 검정인데 화면 팔레트엔 안 그려진다
        m_[:2], m_[-2:], m_[:, :2], m_[:, -2:] = False, False, False, False
    if not all(m.any() for m in masks):
        return []
    ys, xs = np.nonzero(masks[0])
    w0x, w0y = Finv((xs + 0.5) / TEX, (ys + 0.5) / TEX)
    d = np.array(drops)
    out = []
    for scale in scales:
        if deadline and time.monotonic() > deadline:
            break
        for rot in rots:
            r = np.radians(-rot)
            c, s = np.cos(r), np.sin(r)
            ok = np.ones(len(w0x), bool)
            for k in range(len(d)):
                for ex, ey in OFFS:
                    if k == 0 and ex == 0 and ey == 0:
                        continue
                    dx = (d[k][0] - d[0][0] + ex * margin_px / S) / scale
                    dy = (d[k][1] - d[0][1] + ey * margin_px / S) / scale
                    u, v = F(w0x + c * dx - s * dy, w0y + s * dx + c * dy)
                    iy, ix = _tex(u, v)
                    ok &= masks[k][iy, ix]
                    if not ok.any():
                        break
                if not ok.any():
                    break
            for jj in np.flatnonzero(ok)[:2]:
                cr, sr = np.cos(np.radians(rot)), np.sin(np.radians(rot))
                px = d[0][0] - 0.5 - scale * (cr * w0x[jj] - sr * w0y[jj])
                py = d[0][1] - 0.5 - scale * (sr * w0x[jj] + cr * w0y[jj])
                out.append((float(rot), float(scale), (float(px), float(py))))
            if len(out) >= limit:
                return out
    return out


def predicted(pal, drops, pos, rot, scale):
    return [pal.color_at(*uv_of(np.array(a), np.array(b), pos, rot, scale), np.array(a)) for a, b in drops]


def colors_ok(pal, m, drops, targets_lab, tols, margin_px=1.0):
    """지금 상태에서 스포이드마다 둘레 margin_px 까지 집을 색이 모두 목표 오차 안이고 아는 텍셀인가."""
    S = pal.S
    for (a, b), t, tol in zip(drops, targets_lab, tols):
        for ex, ey in OFFS:
            aa, bb = np.array(a + ex * margin_px / S), np.array(b + ey * margin_px / S)
            u, v = uv_of(aa, bb, m[0], m[1], m[2])
            if not pal.known_at(u, v, np.array(a)):
                return False
            cc = pal.color_at(u, v, np.array(a))
            if ((lab_of(np.array([[cc]], np.uint8))[0, 0] - t) ** 2).sum() > tol * tol:
                return False
    return True


def best_pos(drops, goal, m):
    """지금 회전·배율(m)에서 스포이드들이 목표 텍셀(goal 기준 w)에 가장 가까워지는 pos (평균)."""
    rot, scale = m[1], m[2]
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    out, ref = [], None
    for a, b in drops:
        wx, wy = to_w(np.array(a), np.array(b), goal[2], goal[0], goal[1])
        best = None
        for kx in range(-4, 5):
            for ky in range(-4, 5):
                X, Y = float(wx) + kx, float(wy) + ky
                p = (a - 0.5 - scale * (c * X - s * Y), b - 0.5 - scale * (s * X + c * Y))
                key = math.hypot(p[0] - (ref or m[0])[0], p[1] - (ref or m[0])[1])
                if best is None or key < best[0]:
                    best = (key, p)
        ref = ref or best[1]
        out.append(best[1])
    return sum(p[0] for p in out) / len(out), sum(p[1] for p in out) / len(out)


def goal_points(drops, goal, m):
    """해의 텍셀들이 **지금** 화면 어디에 있나 (정규 좌표, 스포이드마다 가장 가까운 것).
    회전·배율이 맞으면 이 점들이 스포이드 삼각형과 같은 모양이 되고, 끌어서 겹치면 끝."""
    rot, scale, pos = m[1], m[2], m[0]
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    out = []
    for a, b in drops:
        wx, wy = to_w(np.array(a), np.array(b), goal[2], goal[0], goal[1])
        best = None
        for kx in range(-6, 7):
            for ky in range(-6, 7):
                X, Y = float(wx) + kx, float(wy) + ky
                pa = 0.5 + pos[0] + scale * (c * X - s * Y)
                pb = 0.5 + pos[1] + scale * (s * X + c * Y)
                dd = math.hypot(pa - a, pb - b)
                if best is None or dd < best[0]:
                    best = (dd, (pa, pb))
        out.append(best[1])
    return out


def miss_texels(m, goal, drops):
    """스포이드마다 지금 집는 텍셀과 목표 텍셀의 거리 (텍셀 단위, 감싸기 고려)."""
    out = []
    for a, b in drops:
        u1, v1 = uv_of(np.array(a), np.array(b), m[0], m[1], m[2])
        u2, v2 = uv_of(np.array(a), np.array(b), goal[2], goal[0], goal[1])
        du, dv = (u1 - u2) - np.round(u1 - u2), (v1 - v2) - np.round(v1 - v2)
        out.append(float(np.hypot(du, dv) * TEX))
    return out
