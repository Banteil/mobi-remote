"""반복 콘텐츠(어비스·레이드)의 공통 틀.

판을 도는 순서는 같다: 캐릭터 확인 → (얻은 것 재기 시작) → 입장 → 판 → 결과 → 수리 → 다음 판, 판 수·시간이 차면 끝.
종류마다 다른 것(어디인가 · 입장 · 판 안에서 나가기 · 다음 판으로)은 하위 클래스가 덮어쓴다 (abyss.AbyssRepeat ·
raid.RaidRepeat). 공통으로 쥐는 것: 판 수·시간·사망 집계, 진행 알림, 캐릭터 확인(이름을 모르면 이어 하고 나중에
확인), 판 사이 수리(repair.due), 게임을 뒤로 돌려주기.
"""
import ctypes
import time

from ..bot import Bot
from . import login, repair
from .login import current_name, name_matches


class Repeat:
    KIND = ""    # 설정 칸·진행 이벤트 type ('abyss' · 'raid')
    TITLE = ""   # 로그에 쓰는 이름
    INSIDE = ()  # 콘텐츠 안이라 이름을 모를 수 있는 자리 (where 값) — 모르면 나가지 않고 이어 한 뒤 확인

    def __init__(self, bot: Bot, cfg: dict, runs: int = 0, minutes: float = 0, on_event=lambda e: None,
                 character: dict | None = None, loot=None, iface=None):
        self.bot, self.cfg, self.a = bot, cfg, cfg[self.KIND]
        self.runs, self.minutes, self.on_event = runs, minutes, on_event
        self.character, self.loot, self.iface = character, loot, iface  # iface: display.InterfaceFit (없으면 안 맞춤)
        self.unchecked = None  # 이름을 확인 못 한 채 이어 한 캐릭터 — recheck 가 확인한다
        self.behind = bool(self.a.get("background", True))
        self.user_window = ctypes.windll.user32.GetForegroundWindow()  # 입장 뒤 되돌려 줄 창 (리모콘 등)
        self.below = float(self.a.get("repair_below", 0.05) or 0)  # 이 내구도 이하면 판 사이에 수리 (0 = 안 함)
        self.repaired_from = None  # 바로 앞 수리 직전 내구도 (repair.due)
        self.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0}
        self.t0 = time.monotonic()

    # ---- 종류마다 덮어쓴다
    def target(self) -> str:
        """로그에 쓸 대상 ('던전 / 난이도')."""
        raise NotImplementedError

    def where(self) -> str:
        """지금 어디인가 (종류별 where_settled)."""
        raise NotImplementedError

    def setup(self) -> None:
        """시작 전 봇 설정 (연출 넘기기 등)."""

    def leave_for_switch(self, at: str) -> None:
        """다른 캐릭터로 바꾸려고 at 자리에서 콘텐츠 밖으로 나간다."""

    def loop(self, at: str) -> None:
        """판을 돈다 (done() 이면 돌아온다)."""
        raise NotImplementedError

    # ---- 공통
    def done(self) -> bool:
        return bool((self.runs and self.stat["clears"] >= self.runs)
                    or (self.minutes and time.monotonic() - self.t0 >= self.minutes * 60))

    def emit(self, **kw) -> None:
        self.on_event({"type": self.KIND, **self.stat, "seconds": round(time.monotonic() - self.t0), **kw})

    def to_back(self) -> None:
        """뒤에서 도는 설정이면 게임을 뒤로 보내고 하던 창을 돌려준다."""
        if self.behind:
            self.bot.background = True
            self.bot.window.give_back(self.user_window)

    def play_round(self, play, step: str) -> str:
        """판 하나 (종류별 play). 부활하면 같은 판으로 센다."""
        n = self.stat["clears"] + self.stat["deaths"] + self.stat["retries"] + 1
        self.bot.step(step, f"{n}번째 판 진행 중")
        self.emit(stage="play")
        return play(self.bot, self.a["run_timeout"], bool(self.a.get("revive", True)),
                    on_revive=lambda: (self.stat.__setitem__("revives", self.stat["revives"] + 1), self.emit(stage="play")))

    def cleared(self) -> None:
        self.stat["clears"] += 1
        secs = round(time.monotonic() - self.t0)
        self.bot.log.info(f"클리어 {self.stat['clears']}판 (부활 {self.stat['revives']} · 쓰러져 나감 {self.stat['deaths']} "
                          f"· 경과 {secs // 60}분 {secs % 60}초)")
        self.emit(stage="clear")

    def repair_between(self, go_out) -> bool:
        """판 사이 수리. 마지막 판 뒤엔 가지 않는다. go_out() 으로 콘텐츠를 나가 대장간에서 수리했으면 True."""
        if self.done() or not repair.due(self.bot, self.below, self.repaired_from):
            self.repaired_from = None
            return False
        self.bot.log.info(f"장비 내구도 {repair.durability(self.bot) * 100:.0f}% (기준 {self.below * 100:g}%) → 나가서 수리")
        self.emit(stage="repair")
        self.repaired_from = repair.durability(self.bot)
        go_out()
        repair.run(self.bot)
        self.stat["repairs"] = self.stat.get("repairs", 0) + 1
        return True

    def _switch(self, at: str) -> None:
        ch = self.character
        self.bot.log.info(f"다른 캐릭터 → {ch['name']} 로 접속")
        self.leave_for_switch(at)
        self.bot.character = ch
        self.bot.log.info(login.run(self.bot, self.cfg, ch))

    def ensure_character(self, at: str) -> str:
        """고른 캐릭터인지 확인하고 아니면 나가서 바꾼다. 콘텐츠 안이라 이름을 모르면(리모콘을 막 켬 — 패킷 이름은 맵에
        들어갈 때 온다) 나가지 않고 이어 한 뒤 recheck 가 확인한다. 바뀐 자리를 돌려준다."""
        ch = self.character
        if not ch:
            return at
        name = current_name(self.bot)
        if name and name_matches(name, ch.get("name", "")):
            return at
        if not name and at in self.INSIDE:
            self.bot.log.info(f"{self.TITLE} 진행 중이라 캐릭터 이름을 모름 → 그대로 잇고 이름을 알게 되면 확인")
            self.unchecked = ch
            return at
        self._switch(at)
        return self.where()

    def recheck(self, at: str) -> bool:
        """이름을 확인 못 한 채 이어 했으면, 이름을 알게 된 지금 확인한다. 다른 캐릭터였으면 바꾸고 True (입장부터 다시)."""
        if not self.unchecked or not (name := current_name(self.bot)):
            return False
        ch, self.unchecked = self.unchecked, None
        if name_matches(name, ch.get("name", "")):
            return False
        self.bot.log.warning(f"다른 캐릭터({name})로 이어 하던 중")
        self._switch(at)
        return True

    def run(self) -> dict:
        goal = " · ".join(s for s in [f"{self.runs}판" if self.runs else "", f"{self.minutes:g}분" if self.minutes else ""] if s)
        self.bot.log.info(f"{self.TITLE} 반복 시작: {self.target()} — {goal or '멈출 때까지'}")
        self.bot.check_in()
        self.bot.auto_clear = True
        self.setup()
        self.bot.background = False
        # 인터페이스는 접속 확인보다 먼저 (PC·80% 가 아니면 HUD 가 안 맞아 이름을 못 읽는다) — 콘텐츠 안이면 미뤘다가 접속 뒤에
        if self.iface:
            self.iface.attempt(self.bot)
        at = self.ensure_character(self.where())
        if self.iface and self.iface.attempt(self.bot):
            at = self.where()
        self.bot.watch_weight = True  # 가방이 꽉 차면 보상을 못 받는다 → Overweight 로 멈춤 (일일 숙제와 같게, 접속 뒤부터)
        if self.loot:  # 이 캐릭터로 접속을 마침 — 여기서부터 얻은 것을 잰다 (queue_report.LootMeter, 닫기는 부른 쪽)
            self.loot.open(self.bot, (self.character or {}).get("name") or current_name(self.bot) or "")
        self.loop(at)
        secs = round(time.monotonic() - self.t0)
        self.bot.log.info(f"{self.TITLE} 반복 끝: 클리어 {self.stat['clears']}판, 쓰러져 나감 {self.stat['deaths']}번 ({secs // 60}분)")
        return {**self.stat, "seconds": secs}
