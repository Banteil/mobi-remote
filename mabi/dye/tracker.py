"""염색 도우미 한 바퀴 — mobi-remote app.js 의 dyeTick 상태 기계를 UI 없이 옮긴 것.

  waiting  정해 둔 자리(detect.PALETTE_AT 또는 사람이 고친 비율)에 팔레트 테두리가 안 보인다.
           그동안 확정 단추를 본다 — 두 바퀴 이어 보이면 done.
  active   테두리가 보인다 (매 바퀴 본다 — 네 변 몇 줄이라 싸다. 창을 닫으면 바로 waiting).
           16×16 지문이 거의 그대로(차이 < 1)면 아무것도 안 한다. 멈춘 화면은 정확히 0 이고 돌리는 중엔 수십.
           돌리는 동안엔 점을 그리지 않는다 — 바퀴마다 나왔다 말았다 해서 산만했다. 멈추면 그 바퀴에 그린다.
  done     염색 확정 화면. 더는 계산하지 않는다 (reset() 으로 다시).

호출 쪽은 120ms 마다 tick(frame) 을 부르고, redraw 가 True 일 때만 오버레이를 다시 그린다.
좌표는 모두 frame 픽셀 기준 — 화면 좌표로 옮기는 것은 호출 쪽(draw.overlay_items 의 scale/origin).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from . import detect as D

DONE_TICKS = 2        # 확정 단추를 한 번 스친 것으로 끄지 않는다


@dataclass
class RingState:
    x: int
    y: int
    r: int
    hex: str             # 안쪽 색 = 그 파트가 지금 고른 색
    share: float         # 으뜸 색 비율 (0.5 미만이면 처음 잰 색을 그대로 씀)
    slot: int            # 맞은 목표 번호 (targets 기준), 없으면 -1
    delta: float | None


@dataclass
class DyeState:
    status: str                                   # 'waiting' | 'active' | 'done'
    text: str = ""                                # 오버레이 맨 위 띠
    tone: str = "wait"                            # 'wait' | 'ok' — 띠 색
    hidden: bool = False                          # True 면 오버레이를 숨긴다 (JS mm.dye.hide)
    redraw: bool = True                           # False 면 직전 그림을 그대로 둔다
    palette: D.Palette | None = None
    lines: list[D.LeaderLine] = field(default_factory=list)
    rings: list[RingState] = field(default_factory=list)
    targets: list[D.ColorHit] = field(default_factory=list)
    spots: list[np.ndarray] = field(default_factory=list)   # targets 순서, (k,2) [x,y]
    bands: list[tuple[int, int]] | None = None
    chips: list[tuple[str, bool]] = field(default_factory=list)   # (목표 hex, 스포이드가 물었나)
    all_caught: bool = False
    pins: list[tuple[int, int]] | None = None     # 스포이드가 셋일 때 삼각형 꼭짓점
    shade: np.ndarray | None = None               # 흑백 강조 그림 (RGB, 팔레트의 1/SHADE_STEP 크기) — 켰을 때만


WAIT_TEXT = "염색 감지 중…"
DONE_TEXT = "염색이 끝나 도우미를 껐습니다"


class DyeTracker:
    def __init__(self, at=None, order: str = "bgr"):
        """at: 팔레트 자리 (x, y, w, h) 게임 화면 대비 비율. 없으면 detect.PALETTE_AT."""
        self.at = tuple(at) if at else D.PALETTE_AT
        self.order = order
        self.gray, self.light = False, 0.35
        self._targets: list[D.Target] = []
        self.reset()

    # ── 상태 ──
    def reset(self) -> None:
        self.box: D.Palette | None = None
        self.sig = None
        self.lead: D.Leaders | None = None
        self.lead_ok = False   # 멈춘 화면에서 두 번 이어 같은 자리로 찾았나 — 열리는 중에 찾으면 엉뚱한 자리를 잡는다
        self.lead_still = False   # 지금 lead 를 멈춘 화면에서 찾았나
        self.moving = False
        self.bands = None
        self.done_seen = 0
        self.done = False
        # 켜자마자는 아무것도 안 그린다 (JS 도 첫 draw 전까지 오버레이가 숨어 있다)
        self.last = DyeState("waiting", hidden=True)

    def set_targets(self, colors, tols=None) -> None:
        """현재 프리셋의 색 세 칸. 빈 칸·잘못된 값은 계산에서 빠지지만 칸 번호(=표시 색)는 그대로 둔다.
        리모콘(app.js:3086)은 남은 것끼리 번호를 다시 매겨 1번이 비면 2번 색이 1번 색으로 그려졌다.
        목표가 바뀌었으니 다음 바퀴에 다시 찾는다."""
        tols = list(tols or [])
        ts = [D.target(c, tols[i] if i < len(tols) else None) for i, c in enumerate(colors or [])]
        self._targets = [t for t in ts if t]
        self._slot_of = [i for i, t in enumerate(ts) if t]  # 계산 순번 → 원래 칸 번호
        self._n_slots = len(ts)
        self.sig = None

    def set_view(self, at=None, gray: bool = False, light: float = 0.35) -> None:
        """팔레트 자리(비율, 없으면 기본)와 흑백 강조. 바뀌면 다음 바퀴에 다시 그린다."""
        self.at = tuple(at) if at else D.PALETTE_AT
        self.gray, self.light = bool(gray), float(light)
        self.sig = None

    @property
    def targets(self) -> list[D.Target]:
        return list(self._targets)

    def _emit(self, st: DyeState) -> DyeState:
        self.last = st
        return st

    def _same(self) -> DyeState:
        return replace(self.last, redraw=False)

    # ── 한 바퀴 ──
    def tick(self, frame) -> DyeState:
        if self.done:
            return self._same()
        f = D.as_frame(frame, self.order)

        box = D.palette_at(f, self.at)
        if box is None:
            self.box = None
            # 확정 단추는 팔레트가 없을 때만 본다 — 염색 화면에도 같은 색 단추가 있다
            if D.find_done_button(f):
                self.done_seen += 1
                if self.done_seen >= DONE_TICKS:
                    self.done = True
                    self.lead = None
                    return self._emit(DyeState("done", DONE_TEXT, "ok", hidden=True))
            else:
                self.done_seen = 0
            return self._emit(DyeState("waiting", WAIT_TEXT, "wait"))
        if self.box is None or (box.x, box.y, box.w, box.h) != (self.box.x, self.box.y, self.box.w, self.box.h):
            # 새로 떴다(또는 자리를 고쳤다) — 지시선·동그라미·파트 경계를 다시 찾는다
            self.box, self.sig, self.lead, self.bands, self.lead_ok = box, None, None, None, False

        # 무늬가 달라졌거나, 막 멈췄거나, 동그라미 자리가 아직 안 굳었을 때만 다시 훑는다
        sig = D.signature(f, box)
        moved = self.sig is None or D.signature_diff(self.sig, sig) >= 1
        if not moved and not self.moving and self.lead_ok:
            return self._same()
        self.sig, self.moving = sig, moved

        box = self.box
        status = f"팔레트 감지 — {box.w} × {box.h}"
        targets = self._targets
        if not targets:
            # 색을 안 정했어도 어디를 팔레트로 보고 있는지는 보여 준다
            return self._emit(DyeState("active", status + " · 색을 정해 주세요", "ok", palette=box))

        # 흰 지시선·동그라미는 팔레트 색이 아니다. 자리는 멈춘 화면에서 두 번 이어 같게 나오면 굳힌다 — UI 는
        # 붙박이고 움직이는 것은 그 아래 팔레트다. 매번 찾으면 한두 픽셀씩 떨리고, 열리는 중의 화면에서 찾으면
        # 엉뚱한 자리가 두세 번 이어 나온다 (실측: 멈춘 화면 81장 중 77장 같은 자리, 처음 몇 장은 다른 자리).
        if not self.lead_ok and (self.lead is None or not moved):
            new = D.find_leaders(f, box)
            same = self.lead is not None and [(r.x, r.y) for r in new.rings] == [(r.x, r.y) for r in self.lead.rings]
            self.lead_ok = same and self.lead_still and not moved
            if not self.lead_ok:
                self.lead, self.bands, self.lead_still = new, None, not moved
        if self.bands is None and self.lead.rings:
            self.bands = D.find_bands(f, box, len(self.lead.rings))

        # NOTE JS 와 같게 읽은 색을 lead 에 되쓰지 않는다 — 가려졌을 때 쓰는 '직전 값' 은
        # 처음 찾을 때 잰 색이다.
        rings = D.read_rings(f, self.lead.rings)
        # 커서에 가려 못 읽을 때 쓰는 '직전 값'이 처음 잰 색에 머물지 않도록 읽은 색을 되쓴다 (리모콘 app.js:3320)
        self.lead.rings = list(rings)
        skip = self.lead.skip + [D.frame_skip(box)]
        # 표본 격자 하나를 색 찾기·점·흑백 강조가 같이 쓴다 (Lab 바꾸기를 한 번만)
        grid = D.Grid(f, box, D.grid_step(box, 150000), skip)
        found = D.find_colors(f, box, targets, grid=grid)
        spots = [] if moved else D.find_spots(f, box, targets, grid=grid)
        pk = D.picks(rings, targets)

        so = getattr(self, "_slot_of", list(range(len(targets))))
        n = max(getattr(self, "_n_slots", len(targets)), len(targets))
        caught = {so[p.slot] for p in pk if p.slot >= 0}
        all_caught = len(targets) >= 3 and all(i in caught for i in range(3))
        # 원래 칸 번호 자리에 놓는다 (빈 칸은 None / 빈 점 묶음)
        found_at, spots_at = [None] * n, [np.empty((0, 2), dtype=int) for _ in range(n)]
        for k, i in enumerate(so):
            found_at[i] = found[k]
            if spots:
                spots_at[i] = spots[k]
        return self._emit(DyeState(
            "active",
            status + ("  ·  셋 다 잡았습니다" if all_caught else ""),
            "ok",
            palette=box,
            lines=list(self.lead.lines),
            rings=[RingState(r.x, r.y, r.r, r.hex, r.share, so[p.slot] if p.slot >= 0 else -1, p.delta)
                   for r, p in zip(rings, pk)],
            targets=found_at,
            spots=spots_at,
            bands=self.bands,
            chips=[(t.hex, so[k] in caught, so[k]) for k, t in enumerate(targets)],
            all_caught=all_caught,
            pins=[(r.x, r.y) for r in rings] if len(rings) == 3 else None,
            shade=D.highlight(f, box, targets, light=self.light, grid=grid) if self.gray else None,
        ))
