"""흩어진 물길 투창병 속성 패턴 — 내게 대상 표시가 붙으면 같은 속성 주술사 옆으로 WASD 로 간다 (상태는 mabi/spear.py).

이 어비스만의 예외다. 어비스 판 진행(abyss.play)이 기다리는 사이 패킷이 깨우면 부른다.
1. 같은 속성 주술사 옆 (주술사에서 가운데 쪽으로 1.5) 으로 이동. 도착은 1칸 안 — 투창 범위 반지름이 약 2.5 라 주술사가 들어간다.
2. 파훼(그 주술사 보호막 깨짐)를 볼 때까지 제자리를 지킨다 — 가만히 있으면 자동 전투·어그로가 끌고 가므로 짧게 움찔거리고,
   밀려나면 다시 들어간다 (사용자). 못 깨면 10초마다 같은 속성을 다시 던지니 계속 지킨다 (상한 HOLD).
   먼저 떠나지 않는다 — 몬스터 길막·후딜 큰 스킬로 늦게 닿을 수 있다 (2026-11-03 사용자).
3. 깨지면 투창병 근처로 돌아간다 (사용자: 돌아가는 건 파훼했을 때). 돌아오면 1 을 3번 눌러 바로 전투로 (사용자 11-03).
W·D 가 맵에서 어느 쪽인지는 카메라를 고정한 채 (사용자) 주술사가 나온 뒤 한 번 짧게 눌러 재고 저장한다 (속성 버프 3~4초 전).
키를 떼도 위치 읽기가 늦어 약 1.5칸 더 가므로 지금 속도 × LAG 만큼 앞에서 뗀다 (11-02 실측 초당 5.5칸, 수도사 이속 버프 때 ~7.9).
게임 키만 누른다 — 패킷은 보내지 않는다.
"""
import ctypes
import json
import math
import random
import time

from ..bot import Bot
from ..spear import SpearState
from ..tictactoe import TURN

TOL = 1.0          # 도착 (목표점에서)
NEAR_SPEAR = 4.0   # 투창병 근처
HOLD = 25.0        # 대상 표시 뒤 이만큼 지나도 못 깨면 포기
SPEED = 5.5        # 보통 이동 속도 (칸/초). 이동 중엔 실제 속도로
LAG = 0.22
GO_LIMIT = 8.0     # 한 번 가는 데 상한 (가장 먼 주술사가 약 24칸)
CALIB_FILE = "spear_calib.json"
SOLO = "솔로"        # 맵 이름 끝 '(… 솔로)' — 혼자하기
CAMERA_WAIT = 2.0  # 맵에 들어오고 이만큼 뒤 카메라를 맞춘다
CAMERA_AUTO = 4.0  # 자동 카메라로 이만큼 둔 뒤 수동으로 — 2초로는 덜 돌아간 채 고정됐다 (사용자 11-03)
FIGHT_KEY, FIGHT_PRESS = "1", 3  # 투창병 쪽으로 돌아온 뒤 전투로 빨리 돌아가게 (사용자)


class SpearDodge:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._calib = False     # 처음 쓸 때 파일에서 (흩어진 물길이 아니면 읽지도 않는다)
        self.calib_tried = 0.0  # 이 맵에서 보정을 해 봤나 (맵 진입 시각)
        self.camera_set = 0.0   # 이 맵에서 카메라를 맞췄나 (맵 진입 시각)
        self.camp_camera = 0.0  # 이 맵에서 모닥불 뒤(보스방으로 갈 때) 카메라를 다시 맞췄나 (맵 진입 시각)
        self.calib_map = 0.0    # W·D 를 잰 맵 (맵 진입 시각) — 카메라가 판마다 달라 맵마다 다시 잰다

    @property
    def file(self):
        return self.bot.paths.state / CALIB_FILE

    @property
    def calib(self):
        if self._calib is False:
            try:
                c = json.loads(self.file.read_text(encoding="utf-8"))
                self._calib = (tuple(c["w"]), tuple(c["d"]))
            except (OSError, ValueError, KeyError, TypeError):
                self._calib = None
        return self._calib

    @calib.setter
    def calib(self, v):
        self._calib = v

    @property
    def st(self) -> SpearState:
        return self.bot.packets.spear

    def wanted(self) -> bool:
        """지금 맡을 일이 있나 — 내가 투창 대상이거나 틱택토 O 담당, 또는 주술사가 나왔는데 W·D 방향을 아직 모름."""
        st = getattr(self.bot.packets, "spear", None)
        if not isinstance(st, SpearState) or not st.active:
            return False
        if self.camera_due():
            return True
        if st.ttt.due():
            return True
        if st.finished:
            return False
        return st.due() or (self.stale() and len(st.attr) == 6
                            and self.calib_tried != self.bot.packets.state.entered_at)

    def stale(self) -> bool:
        """이 맵에서 아직 W·D 를 안 쟀나. 카메라를 고정해도 판마다 캐릭터가 보는 쪽이 달라 저장된 방향이 거꾸로일 수 있다
        (2026-11-03 함께하기 — 틱택토에서 고른 칸의 정반대 칸으로 가 O 를 날리고 전멸). 못 재면 저장된 값으로 간다."""
        return self.calib is None or self.calib_map != self.bot.packets.state.entered_at

    def camera_due(self) -> bool:
        """함께하기는 카메라가 캐릭터 반대쪽을 보고 시작한다 (혼자하기는 캐릭터가 보는 쪽 — 2026-11-03 사용자).
        W·D 방향이 혼자하기와 달라지므로 맵에 들어와 로딩이 끝나면 한 번 맞춘다.
        모닥불이 나타나 보스방으로 갈 때도 한 번 더 — 첫 방에서 쓰러졌다 일어나면 시점이 뒤틀릴 수 있다 (사용자, 두 모드 다)."""
        s = self.bot.packets.state
        if not s.entered_at or s.loading or s.dead:
            return False
        if s.campfire and self.camp_camera != s.entered_at:
            return True
        return (self.camera_set != s.entered_at and SOLO not in (s.channel_name or "")
                and time.monotonic() - s.entered_at > CAMERA_WAIT)

    def set_camera(self) -> None:
        """Z(자동 카메라) → 4초 뒤 캐릭터 뒤로 돌아오면 다시 Z(수동 카메라)로 고정 (사용자).
        모닥불 뒤에 맞췄으면 시점이 바뀌었을 수 있어 W·D 를 다시 잰다 (못 재면 틱택토 때 다시)."""
        s = self.bot.packets.state
        camp = bool(s.campfire)
        self.camera_set = s.entered_at  # 모닥불 뒤에 처음 맞춰도 맵 진입 때 것은 다시 하지 않는다
        if camp:
            self.camp_camera = s.entered_at
        what = "모닥불 → 보스방" if camp else "함께하기"
        self.bot.log.info(f"{what}: 카메라를 캐릭터 뒤로 맞춤 (Z → {CAMERA_AUTO:.0f}초 → Z)")
        self.bot.key("z")
        time.sleep(CAMERA_AUTO)
        self.bot.key("z")
        if camp:
            self.calib_map = 0.0
            self.calibrate()

    def run(self) -> None:
        st = self.st
        if self.camera_due():
            self._with_focus(self.set_camera)
            return
        if st.ttt.due():
            job = st.ttt.take()
            if job and self.stale():
                self._with_focus(self.calibrate)
            if job and self.calib is not None:
                self._with_focus(lambda: self.tictactoe(job))
            return
        if self.stale() and not st.due():
            self.calib_tried = self.bot.packets.state.entered_at
            self._with_focus(self.calibrate)
            return
        job = st.take()
        if job is None:
            self.bot.log.info("투창 대상이지만 속성이나 그 주술사를 모름 (맵에 들어온 뒤 소환을 못 봄) — 움직이지 않음")
            return
        if self.calib is None:  # 주술사 소환 때 못 쟀다 — 지금이라도 (늦게 출발한다)
            self._with_focus(self.calibrate)
            if self.calib is None:
                return
        self._with_focus(lambda: self.dodge(job))

    # ── 순서 ──
    def dodge(self, job: dict) -> None:
        x, y = job["x"], job["y"]
        target = (x - math.copysign(1.5, x), y)
        t0, so = job["at"], job["shaman"]
        done = lambda: self.st.broken_since(so, t0)
        until = t0 + HOLD
        self.bot.log.info(f"투창 패턴: {job['attr']} 주술사 ({x:.0f}, {y:.0f}) 옆 {target[0]:.1f}, {target[1]:.1f} 로 이동")
        self.go(target, TOL, min(until, time.monotonic() + GO_LIMIT), done)
        # 파훼를 볼 때까지 붙어 있는다 — 길막·후딜 큰 스킬로 늦게 닿을 수 있어 먼저 떠나지 않는다 (사용자)
        self.hold(target, until, done)
        if not done():
            self.bot.log.info(f"투창 패턴: {HOLD:.0f}초 동안 파훼 못 봄 — 투창병 쪽으로")
        if self.ok():
            self.go(self.st.spear_home(), NEAR_SPEAR, time.monotonic() + GO_LIMIT, lambda: False)
        if self.ok(pattern=False):
            for _ in range(FIGHT_PRESS):
                self.bot.key(FIGHT_KEY)
                time.sleep(random.uniform(0.2, 0.35))

    def tictactoe(self, job: dict) -> None:
        """틱택토 O 담당 — 고른 칸 가운데로 가서 보스가 O 를 새기러 출발할 때까지 (차례 시작 약 9초 뒤) 그 칸에 선다."""
        ttt = self.st.ttt
        target, t0 = (job["x"], job["y"]), job["at"]
        done = lambda: ttt.resolved
        self.bot.log.info(f"틱택토: O 담당 → 칸 {job['cell']} ({target[0]:.0f}, {target[1]:.1f}) 로 이동 · 판 {ttt.text()}")
        self.go(target, TOL, t0 + TURN - 1, done, pattern=False)
        self.hold(target, t0 + TURN + 4, done, pattern=False)
        if not done():
            self.bot.log.info("틱택토: 보스가 O 를 새기러 오는 것을 못 봄")

    def ok(self, pattern: bool = True) -> bool:
        """계속해도 되나 — 맵을 떠났거나 쓰러졌거나 (투창이면) 패턴이 끝났으면 그만둔다."""
        p = self.bot.packets
        return self.st.active and not (pattern and self.st.finished) and not p.state.loading and not p.state.dead

    def _with_focus(self, fn) -> None:
        """게임 창을 앞으로 (키를 누른 채 있어야 해서 뒤에서는 못 한다). 뒤에서 돌던 중이면 끝나고 원래 창을 돌려준다."""
        bot = self.bot
        prev = ctypes.windll.user32.GetForegroundWindow()
        behind = bot.background and not bot.window.is_foreground()
        bot.ensure_focus()
        if not bot.window.is_foreground() and not bot.input.dry_run:
            bot.log.warning("투창 패턴: 게임 창을 앞으로 가져오지 못해 움직이지 못함")
            return
        try:
            fn()
        finally:
            bot.input.hold(())
            if behind:
                bot.window.give_back(prev)

    # ── 자리 ──
    def my_pos(self, fresh: bool = False) -> tuple[float, float] | None:
        """내 자리 — 패킷(내 이동 메시지)이 0.25초 안이면 그것, 아니면 CLI."""
        if not fresh:
            p = self.st.where(self.bot.packets.state.me, 0.25)
            if p:
                return p
        env = self.bot.environment(max_age=0.0) or {}
        w = env.get("WorldPosition") or {}
        return (w["X"], w["Y"]) if "X" in w else None

    # ── 움직이기 ──
    def keys_toward(self, dx: float, dy: float) -> list[str]:
        """월드 방향 (dx, dy) 로 가는 키 — W·D 성분으로 나눠 큰 쪽, 둘 다 크면 대각선."""
        (wx, wy), (ex, ey) = self.calib
        det = wx * ey - wy * ex
        a, b = (dx * ey - dy * ex) / det, (wx * dy - wy * dx) / det
        m = max(abs(a), abs(b)) or 1
        ks = []
        if abs(a) > 0.4 * m:
            ks.append("w" if a > 0 else "s")
        if abs(b) > 0.4 * m:
            ks.append("d" if b > 0 else "a")
        return ks

    def go(self, target, tol: float, until: float, done, pattern: bool = True) -> bool:
        """target 까지 키를 누른 채 다시 보며 간다. 속도 × LAG 앞에서 떼고, 멈춘 자리가 모자라거나 지나쳤으면 짧게 다시."""
        inp, fine, hist = self.bot.input, False, []
        while time.monotonic() < until and not done() and self.ok(pattern):
            self.bot.check_stop()
            p = self.my_pos()
            if not p:
                time.sleep(0.05)
                continue
            dx, dy = target[0] - p[0], target[1] - p[1]
            dist, now = math.hypot(dx, dy), time.monotonic()
            hist = [h for h in hist if now - h[0] < 0.6] + [(now, p)]
            speed = SPEED
            if inp.held and len(hist) >= 3 and now - hist[0][0] > 0.3:
                speed = math.dist(p, hist[0][1]) / (now - hist[0][0]) or SPEED
            lead = 0.0 if fine else min(2.5, max(0.6, speed * LAG))
            if dist <= tol + lead:
                inp.hold(())
                time.sleep(0.45)
                p = self.my_pos(fresh=True) or p
                dist = math.dist(target, p)
                if dist <= tol + (0.3 if fine else 0):
                    return True
                fine, hist = True, []
                continue
            inp.hold(self.keys_toward(dx, dy))
            time.sleep(0.05)
        inp.hold(())
        return False

    def hold(self, target, until: float, done, pattern: bool = True) -> None:
        """파훼까지 제자리 — 벗어나면 다시 들어가고, 아니면 0.3초마다 짧게 움찔 (반대 키로 되돌림)."""
        inp, back = self.bot.input, {"w": "s", "s": "w", "a": "d", "d": "a"}
        pair = None
        while time.monotonic() < until and not done() and self.ok(pattern):
            self.bot.check_stop()
            p = self.my_pos()
            if p and math.dist(target, p) > TOL + 0.4:
                self.go(target, TOL, until, done, pattern)
                continue
            if pair:  # 앞에서 움찔한 반대쪽으로 되돌린다
                k, pair = pair, None
            else:
                k = random.choice("wsad")
                pair = back[k]
            inp.hold((k,))
            time.sleep(0.06)
            inp.hold(())
            time.sleep(0.25)

    # ── 보정 ──
    def measure(self, key: str) -> tuple[float, float] | None:
        a = self.my_pos(fresh=True)
        self.bot.input.hold((key,))
        time.sleep(0.3)
        self.bot.input.hold(())
        time.sleep(0.3)
        b = self.my_pos(fresh=True)
        if not a or not b:
            return None
        d = math.dist(a, b)
        return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 0.4 else None

    def calibrate(self) -> None:
        """W·D 를 0.3초씩 눌러 맵 방향을 잰다. 둘이 거의 직각일 때만 믿고 저장한다 (맞아서 밀려나는 중에 재면 틀린 값이 나온다)."""
        w = self.measure("w")
        d = self.measure("d")
        if not w or not d or abs(w[0] * d[0] + w[1] * d[1]) > 0.35:
            self.bot.log.info(f"투창 패턴: W·D 방향 재기 실패 (W {w} · D {d}) — 다음 기회에")
            return
        self.calib = (w, d)
        self.calib_map = self.bot.packets.state.entered_at
        try:
            self.file.write_text(json.dumps({"w": w, "d": d}), encoding="utf-8")
        except OSError:
            pass
        self.bot.log.info(f"투창 패턴: W→({w[0]:.2f}, {w[1]:.2f}) · D→({d[0]:.2f}, {d[1]:.2f}) 저장")
