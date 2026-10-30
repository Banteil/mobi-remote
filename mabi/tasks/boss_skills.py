"""보스전 궁극기·팔라딘 변신 — 어비스·레이드 반복(Repeat)의 판 진행 중에 쓴다. 일반 던전·숙제에서는 쓰지 않는다.

캐릭터마다 따로 켠다 ([boss_skills] ultimate_slots · paladin_slots, 캐릭터 탭). 키는 [game] ultimate_key · paladin_key.
쓰는 때: 보스전(종류마다 Repeat.boss_fight — 레이드는 보스전 시작 패킷, 어비스는 모닥불 뒤) · 전투 중(CLI IsInCombat,
모르면 패킷) · 게이지가 참(패킷 ultimate.resource) · 컷신·쓰러짐·로딩이 아님. 게임 키만 누르고 패킷은 보내지 않는다.
게이지가 차 있는데 눌러도 안 줄면 RETRY 초마다 다시 누른다 (게임이 키를 놓치거나 아직 못 쓰는 순간).

팔라딘 변신 중에는 궁극기를 쓰지 않는다 — 변신 중엔 궁극기 키(6)가 '변신 해제' 가 된다 (사용자, 2026-10-30).
변신은 20초 간다 (사용자) — 변신 키를 누른 뒤 TRANSFORM 초 동안, 또는 패킷이 변신 중(변신 번호가 0 이 아님, 실측 전)
이라 하면 궁극기를 누르지 않는다.
"""
import time

from .. import profile as prof
from ..bot import Bot


class BossSkills:
    RETRY = 8  # 같은 기술을 다시 누르기까지 (초)
    TRANSFORM = 20 + 3  # 팔라딘 변신 시간 20초 + 여유 — 이 동안 궁극기 키(6)는 변신 해제

    def __init__(self, bot: Bot, ultimate: bool, paladin: bool, boss_fight):
        self.bot, self.boss_fight = bot, boss_fight
        g = bot.cfg["game"]
        # (이름, 키, 게이지 읽기) — 팔라딘 먼저: 게이지를 같이 쓰면 궁극기를 먼저 쓸 때 500 까지 못 모은다
        self.skills = [s for s, on in (
            (("팔라딘 변신", g.get("paladin_key", "f5"), lambda st: (st.pal, st.pal_max) if st.can_paladin is not False else (None, None)), paladin),
            (("궁극기", g.get("ultimate_key", "6"), lambda st: (st.ult, st.ult_max)), ultimate),
        ) if on and s[1]]
        self.pressed: dict[str, float] = {}

    @classmethod
    def for_character(cls, bot: Bot, cfg: dict, slot: int | None, boss_fight) -> "BossSkills":
        c = cfg.get("boss_skills", {})
        on = lambda k: slot is not None and slot in [int(x) for x in c.get(k, [])]  # noqa: E731
        return cls(bot, on("ultimate_slots"), on("paladin_slots"), boss_fight)

    @property
    def enabled(self) -> bool:
        return bool(self.skills)

    def describe(self) -> str:
        return " · ".join(n for n, _, _ in self.skills)

    def transformed(self, st) -> bool:
        """팔라딘 변신 중일 수 있나 — 그러면 궁극기 키가 변신 해제라 누르면 안 된다."""
        return (time.monotonic() - self.pressed.get("팔라딘 변신", -1e9) < self.TRANSFORM
                or st.transfigure not in (None, 0))

    def tick(self, act: dict) -> bool:
        """판 진행 루프가 부른다 (act = 방금 받은 CLI get_activity). 하나를 눌렀으면 True."""
        if not self.skills:
            return False
        p = self.bot.packets
        st = p.state
        if not p.ok or st.loading or st.cutscene or st.dead or not self.boss_fight(st):
            return False
        combat = act.get("IsInCombat") if "IsInCombat" in act else st.in_combat
        if not combat:
            return False
        now = time.monotonic()
        for name, key, gauge in self.skills:
            if name == "궁극기" and self.transformed(st):
                continue
            cur, need = gauge(st)
            if cur is None or not need or cur < need or now - self.pressed.get(name, 0.0) < self.RETRY:
                continue
            self.bot.log.info(f"보스전 {name} ({cur:.0f}/{need:.0f}) → {key}")
            self.bot.key(key)
            self.pressed[name] = now
            return True  # 한 번에 하나 — 다음 것은 다음 확인 때 (게이지가 줄었는지 보고)
        return False


def slot_of(bot: Bot, character: dict | None, name: str = "") -> int | None:
    """설정을 고를 캐릭터 슬롯. 고른 캐릭터가 없으면(지금 캐릭터로) 지금 이름을 프로필에서 찾는다."""
    if character and character.get("slot") is not None:
        return int(character["slot"])
    if not name:
        return None
    from .login import name_matches
    chars = prof.characters(prof.load_profile(bot.paths.profile) or {"slots": []})
    return next((c["slot"] for c in chars if name_matches(name, c["name"])), None)
