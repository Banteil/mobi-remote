"""보스전 궁극기·팔라딘 변신 — 어비스·레이드 반복(Repeat)의 판 진행 중에 쓴다. 일반 던전·숙제에서는 쓰지 않는다.

캐릭터마다 따로 켠다 ([boss_skills] ultimate_slots · paladin_slots, 캐릭터 탭). 키는 [game] ultimate_key · paladin_key.
쓰는 때: 보스전(종류마다 Repeat.boss_fight — 레이드는 보스전 시작 패킷, 어비스는 모닥불 뒤 보스 등장 연출 뒤) · 전투 중(CLI IsInCombat,
모르면 패킷) · 게이지가 참(패킷 ultimate.resource) · 컷신·쓰러짐·로딩이 아님. 게임 키만 누르고 패킷은 보내지 않는다.
게이지가 차 있는데 눌러도 안 줄면 RETRY 초마다 다시 누른다 (게임이 키를 놓치거나 아직 못 쓰는 순간).

팔라딘 변신 중에는 궁극기를 쓰지 않는다 — 변신 중엔 궁극기 키(6)가 '변신 해제' 가 된다 (사용자, 2026-10-30).
변신은 20초 간다 (사용자). 변신 키를 누른 뒤 TRANSFORM 초 동안은 궁극기를 누르지 않는다 — 변신 패킷(시작·끝, 보통
F5 1~3초 뒤 · 그 20초 뒤)이 둘 다 오면 그때 푼다. 시작 패킷이 안 와도 변신이 된 때가 있다 (2026-10-30 17:12·17:33 —
패킷이 없어 안 된 줄 알고 7초 뒤 6 을 눌러 변신이 풀림: 그 뒤 팔라딘 게이지가 비어 있었고 첫 6 은 궁극기를 안 썼다).
사람이 직접 변신하면 변신 패킷으로 안다.
팔라딘 변신은 던전(맵)마다 한 번 (사용자). 변신 패킷을 받았거나 변신 키를 누른 뒤 팔라딘 게이지가 줄었으면 그 맵에서는
다시 누르지 않는다. 둘 다 없으면 안 먹은 것으로 보고 TRANSFORM 초 뒤 다시 누른다 (MAX_TRIES 번까지).
게이지 (caps/boss1 실측): ultimate.resource [300, 궁극기, 500, 팔라딘]. 따로 쌓인다 (사용자) — 같은 행동으로 같은 속도로
차서 쓰기 전엔 같은 값. 궁극기를 쓰면 궁극기만 0, 변신하면 팔라딘이 0 (그 던전에선 다시 안 참).
맵을 나가면(클리어 뒤 다시 하기·나가기) 두 게이지가 처음으로 돌아간다 — packet_monitor 가 맵 진입 때 0 으로 둔다.
"""
import time

from .. import profile as prof
from ..bot import Bot


class BossSkills:
    RETRY = 8  # 같은 기술을 다시 누르기까지 (초)
    TRANSFORM = 20 + 3  # 팔라딘 변신 시간 20초 + 여유 — 이 동안 궁극기 키(6)는 변신 해제
    MAX_TRIES = 3       # 변신 키를 이만큼 눌러도 시작 패킷이 없으면 그 맵에서는 포기 (궁극기를 막지 않게)

    def __init__(self, bot: Bot, ultimate: bool, paladin: bool, boss_fight):
        self.bot, self.boss_fight = bot, boss_fight
        g = bot.cfg["game"]
        # (이름, 키, 게이지 읽기) — 팔라딘 먼저: 게이지를 같이 쓰면 궁극기를 먼저 쓸 때 500 까지 못 모은다
        self.skills = [s for s, on in (
            (("팔라딘 변신", g.get("paladin_key", "f5"), lambda st: (st.pal, st.pal_max) if st.can_paladin is not False else (None, None)), paladin),
            (("궁극기", g.get("ultimate_key", "6"), lambda st: (st.ult, st.ult_max)), ultimate),
        ) if on and s[1]]
        self.pressed: dict[str, float] = {}
        self.tries = (None, 0)  # (맵 entered_at, 그 맵에서 변신 키를 누른 횟수)

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
        """팔라딘 변신 중일 수 있나 — 그러면 궁극기 키가 변신 해제라 누르면 안 된다.
        변신 패킷이 변신 중이라 하거나, 변신 키를 누른 뒤 TRANSFORM 초 안이면서 시작·끝 패킷을 다 받지 못했으면."""
        now = time.monotonic()
        if st.transform_start and now - st.transform_start < self.TRANSFORM:
            return True
        last = self.pressed.get("팔라딘 변신", -1e9)
        if now - last >= self.TRANSFORM:
            return False
        ended = st.transform_seen > last and not st.transform_start  # 누른 뒤 시작과 끝이 다 왔다
        return not ended

    def paladin_spent(self, st) -> bool:
        """이 던전(맵)에서 변신은 끝났나 — 이미 변신했거나(변신 패킷 · 사람이 직접 한 것도 · 누른 뒤 팔라딘 게이지가 줄었다)
        MAX_TRIES 번 눌러도 안 됐다."""
        tries = self.tries[1] if self.tries[0] == st.entered_at else 0
        dropped = tries and st.pal is not None and bool(st.pal_max) and st.pal < st.pal_max
        return st.transformed_here or bool(dropped) or tries >= self.MAX_TRIES

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
            if name == "팔라딘 변신" and self.paladin_spent(st):
                continue
            cur, need = gauge(st)
            wait = self.TRANSFORM if name == "팔라딘 변신" else self.RETRY  # 변신이 됐는데 신호만 늦을 수 있다 — 변신 중엔 다시 안 누른다
            if cur is None or not need or cur < need or now - self.pressed.get(name, -1e9) < wait:
                continue
            self.bot.log.info(f"보스전 {name} ({cur:.0f}/{need:.0f}) → {key}")
            self.bot.key(key)
            self.pressed[name] = now
            if name == "팔라딘 변신":
                n = self.tries[1] if self.tries[0] == st.entered_at else 0
                self.tries = (st.entered_at, n + 1)
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
