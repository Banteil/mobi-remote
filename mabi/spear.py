"""흩어진 물길(어비스) 투창병 속성 패턴 — 패킷으로 보는 상태. 이 어비스만의 예외 (다른 어비스는 쓰지 않는다).

패턴 (2026-11-02 abyss_runs/r1 실기 7판 + 11-03 자동 이동 실기, 사용자 설명):
- 주술사 6마리가 (X ±10, Y 142/151/160) 에 소환되고 3초 뒤 각자 속성 버프 (자리마다 속성은 판마다 섞임). 속성 버프는 소환 때 한 번뿐.
- 투창병이 속성 버프를 받고 0~1초 뒤 대상 캐릭터에 대상 표시(TARGET, 8초)를 건다 — 함께하기에서는 다른 캐릭터에도 걸린다.
  약 7~8초 뒤 대상 발밑(반지름 약 2.5)에 투창 → 그 범위에 같은 속성 주술사가 있으면 그 주술사 보호막이 깨진다(파훼).
- 못 깨면 10초마다 같은 속성을 다시 던진다 — 이때는 속성 버프 없이 대상 표시만 온다.
- 두 번 파훼하면 속성 패턴을 더 안 쓰고, 투창병이 쓰러지면 1초 안에 주술사 6마리도 쓰러진다 → 이 맵의 패턴 끝.
- 그 다음 방의 비틀린 송곳니(판마다 한 마리)가 쓰러지면 모닥불이 나오고 곧바로 보스방으로 걸어간다 (11-03 party2 10판).
보스 테로사의 틱택토 패턴도 같은 맵이라 여기서 쌓는다 (판은 tictactoe.TicTacToe).
패킷은 받기만 한다. 움직이는 쪽은 tasks/spear.py.
"""
import threading
import time

from .tictactoe import TicTacToe

MAP_NAME = "흩어진 물길"
# 주술사 속성 버프 · 투창병 속성 버프 (속성마다 고정, 7판 동안 같음)
SHAMAN_ATTR = {0x5224ab87: "독", 0x272f59cf: "번개", 0x4bf45118: "얼음", 0x6d19c6e5: "불", 0x57116604: "어둠", 0x662b9106: "빛"}
SPEAR_ATTR = {0x77d80d16: "독", 0x3e4b83ca: "번개", 0x26e5d29b: "얼음", 0x4556fffc: "불", 0x32897191: "어둠", 0x23935fb2: "빛"}
SPEAR_MARK = 0x2280fbaa   # 투창병에 늘 붙는 버프 (투창병 알아보기)
TARGET_MARK = 0x1f4ed331  # 투창병 → 대상 캐릭터 (8초)
FANG_KIND = 0x0d08006c_00000006  # 비틀린 송곳니 — 몬스터 등장 [694] 태그 개수 6 + 첫 태그 (party2·party3)
SPEAR_HOME = (0.0, 163.0)
FRESH = 3.0               # 대상 표시를 이만큼 지나서 보면 늦었다 (투창은 7~8초 뒤)
TTT = ("spear.timeline", "spear.path", "spear.breakpoint")
MOVES = ("spear.move_update", "spear.move_ensure", "spear.move_end", "spear.move_manual", "spear.move_location")


class SpearState:
    """흩어진 물길 맵 안에서만 쌓는다 (맵에 들어올 때마다 비움). 패킷 감시 스레드가 feed, 봇 스레드가 읽는다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset(False)

    def reset(self, active: bool) -> None:
        with self.lock:
            self.active = active
            self.pos: dict[int, tuple[float, float, float]] = {}   # 오브젝트 → (x, y, monotonic)
            self.appeared: dict[int, tuple[float, float]] = {}      # 몬스터 등장 자리 (주술사만 의미 있음)
            self.shaman: dict[int, tuple[float, float]] = {}        # 속성 버프가 붙은 주술사 → 자리
            self.attr: dict[int, str] = {}
            self.spears: set[int] = set()
            self.gone: set[int] = set()       # 쓰러졌거나 사라진 주술사
            self.broken: dict[int, float] = {}
            self.pending: str | None = None   # 아직 파훼 못 한 속성
            self.breaks = 0
            self.target_at = 0.0               # 내게 대상 표시가 붙은 때
            self.fang: int | None = None       # 비틀린 송곳니 번호
            self.fang_down = 0.0               # 비틀린 송곳니가 쓰러진 때 (보스방으로 감)
            self.taken_at = 0.0                # 봇이 그 표시를 맡은 때
            self.ttt = TicTacToe()             # 보스 틱택토

    @property
    def finished(self) -> bool:
        """이 맵의 패턴이 끝났나 — 주술사를 봤고 모두 쓰러졌거나 사라졌다 (투창병이 쓰러지면 같이 쓰러진다)."""
        return bool(self.shaman) and all(o in self.gone for o in self.shaman)

    def feed(self, key: str, v: dict, me: int | None) -> str | None:
        """이벤트 하나. 알릴 일이면 로그 문장을 돌려준다 (부른 쪽이 기다리는 봇을 깨운다)."""
        now = time.monotonic()
        a = v.get("actor")
        if a is None:
            return None
        with self.lock:
            if key in TTT:
                return self.ttt.feed(key, v, me, self.pos)
            if key in MOVES:
                x, y = v.get("x"), v.get("y")
                if x is not None and y is not None and abs(x) < 1e5 and abs(y) < 1e5:
                    self.pos[a] = (x, y, now)
                return None
            if key == "spear.monster":
                self.appeared[a] = (v.get("x", 0.0), v.get("y", 0.0))
                if v.get("kind") == FANG_KIND:
                    self.fang = a
                return None
            if key in ("spear.gone", "actor.dead"):
                if key == "actor.dead" and not v.get("dead"):
                    return None
                if key == "spear.gone":
                    self.pos.pop(a, None)
                # 사라짐(spear.gone)은 멀어져도 온다 (party2 17:08 — 쓰러지기 46초 전) → 쓰러짐만
                if a == self.fang and key == "actor.dead" and not self.fang_down:
                    self.fang_down = now
                    return "비틀린 송곳니 쓰러짐 → 보스방으로"
                if a in self.shaman and a not in self.gone:
                    self.gone.add(a)
                    if self.finished:
                        return "투창 패턴 끝 (주술사 모두 쓰러짐)"
                return None
            if key == "spear.break":
                if a in self.shaman:
                    if now - self.broken.get(a, -1e9) < 3:
                        return None  # 같은 깨짐이 두 번 온다 (r1 23:37:30)
                    self.broken[a] = now
                    self.breaks += 1
                    if self.attr.get(a) == self.pending:
                        self.pending = None
                    return f"파훼 — {self.attr.get(a)} 주술사 보호막 깨짐 ({self.breaks}번째)"
                return None
            if key != "spear.buff":
                return None
            b = v.get("buff")
            if b == SPEAR_MARK:
                self.spears.add(a)
            elif b in SHAMAN_ATTR and a in self.appeared:
                self.shaman[a], self.attr[a] = self.appeared[a], SHAMAN_ATTR[b]
                if len(self.attr) == 6:
                    return "주술사 배치 " + " · ".join(f"{n}({x:.0f},{y:.0f})" for o, n in sorted(
                        self.attr.items(), key=lambda kv: self.shaman[kv[0]]) for x, y in [self.shaman[o]])
            elif b in SPEAR_ATTR:
                self.pending = SPEAR_ATTR[b]
                return f"투창병 속성: {self.pending}"
            elif b == TARGET_MARK:
                if self.finished:  # 주술사가 다 쓰러진 뒤(보스방)에도 같은 표시가 온다 — 투창이 아니다
                    return None
                if me is not None and a == me:
                    self.target_at = now
                    return f"투창 대상 = 나 (남은 속성 {self.pending or '?'})"
                # 함께하기 — 다른 캐릭터가 대상. 남겨 둔다: 내게 걸렸는데 안 움직였다는 제보(11-03 16:05 어둠)를 가르려고
                return f"투창 대상 = 다른 캐릭터 (번호 {a}, 나 {me})"
        return None

    # 봇이 쓰는 것 ──────────────────────────────────

    def due(self) -> bool:
        """내게 대상 표시가 새로 붙었고 맡을 일이 있다."""
        return (self.active and not self.finished and self.target_at > self.taken_at
                and time.monotonic() - self.target_at < FRESH)

    def take(self) -> dict | None:
        """대상 표시를 맡는다. 갈 곳: {'attr', 'shaman', 'x', 'y', 'at'} — 속성이나 그 주술사를 모르면 None."""
        with self.lock:
            self.taken_at = self.target_at
            attr = self.pending
            o = next((o for o, n in self.attr.items() if n == attr and o not in self.gone), None)
            if o is None:
                return None
            x, y = self.shaman[o]
            return {"attr": attr, "shaman": o, "x": x, "y": y, "at": self.target_at}

    def broken_since(self, shaman: int, t: float) -> bool:
        return self.broken.get(shaman, 0.0) > t

    def where(self, actor: int | None, max_age: float) -> tuple[float, float] | None:
        """패킷으로 본 오브젝트 자리 (max_age 초 안에 받은 것만)."""
        if actor is None:
            return None
        p = self.pos.get(actor)
        return (p[0], p[1]) if p and time.monotonic() - p[2] <= max_age else None

    def spear_home(self) -> tuple[float, float]:
        """투창병 자리 — 패킷 자리가 제자리(0, 163) 근처일 때만 믿는다."""
        for o in list(self.spears):
            p = self.pos.get(o)
            if p and abs(p[0] - SPEAR_HOME[0]) + abs(p[1] - SPEAR_HOME[1]) < 20:
                return p[0], p[1]
        return SPEAR_HOME
