"""표가 풀어 준 이벤트(맵 진입·던전·사냥터·드릴·어비스·레이드·대화·변신 …)를 PacketState 에 반영한다.
PacketMonitor 가 상속한다 (self.state · self.spear · self._cond · recent · history 를 쓴다)."""
import logging
import time

from ..game_state import NOT_IN_DUNGEON
from ..place import ABYSS, OPEN_MAPS, is_instance
from ..spear import MAP_NAME
from .state import CLI_FACTS, Seen, _snapshot

log = logging.getLogger("mabi")

NO_TARGET = 0xFFFFFFFFFFFFFFFF


class Events:
    """이벤트 → 상태. 상태를 고치는 일은 모두 잠금(self._cond) 안에서."""

    def apply(self, key: str, vals: dict) -> None:
        """상태를 고치는 일은 모두 잠금 안에서 — 패킷 받는 스레드(apply)와 작업 스레드(merge_cli·reconcile·forget)가
        같은 상태를 고친다. 자세한 것은 _apply."""
        with self._cond:
            self._apply(key, vals)

    def _apply(self, key: str, vals: dict) -> None:
        """이벤트 하나를 상태에 반영하고 기다리는 쪽을 깨운다. 잠금(self._cond) 안에서 부른다 (apply)."""
        s = self.state
        old = {f: getattr(s, f) for f in CLI_FACTS}
        if key == "channel.leaving":
            s.loading, s.loading_at = True, time.monotonic()
            s.dye_open_at, s.dye_known = None, True
            s.attendance_at = 0.0
        elif key == "channel.entering":
            s.loading = False
            s.channel, s.channel_type, s.channel_name = vals.get("channel"), vals.get("channel_type", ""), \
                vals.get("channel_name", "")
            s.entered_at = time.monotonic()
            s.in_game = True  # 감시를 켠 뒤 처음 맵을 옮긴 경우에도 알게
            s.cutscene = False
            s.fast_travel_ok = None  # 새 맵 — 빠른 이동 가능 여부는 다음 자동 이동 때 다시 온다
            # 우연한 만남 매칭(ChanceMeetingGlobalMatching)은 레이드도 같이 쓴다 — 어비스 맵에서만 지우면 레이드 매칭으로
            # 출항선에 들어간 뒤에도 '잡힘' 이 남아, 다음 어비스 반복이 '매칭 중' 으로 보고 오지 않을 입장을 기다렸다
            # (2026-11-07 17:32). 콘텐츠 맵(Instance*)에 들어갔거나 잡힌(3) 뒤 맵을 옮겼으면 매칭은 끝났다.
            # 찾는 중(1·2)에 필드를 옮겨 다니는 것은 매칭이 이어진다
            if is_instance(s.channel_type) or s.abyss_matching == 3:
                s.abyss_matching = 0
            s.abyss_result = 0  # 새 맵 — 지난 판 결과는 끝났다 (나갈 때 0 이 오는지 실측이 없어 여기서도 지운다)
            s.raid_result, s.raid_boss, s.campfire, s.boss_scene = 0, False, False, False
            s.drill_result = 0
            s.transform_start, s.transformed_here = 0.0, False
            # 맵을 나가면(클리어 뒤 다시 하기·나가기) 궁극기·팔라딘 게이지가 처음으로 (사용자). 새 값이 오기 전에 지난 판 값을 믿지 않게
            if s.ult is not None:
                s.ult = s.pal = 0.0
            s.dead = None  # 쓰러진 채 맵을 옮기면 부활 신호가 안 올 수 있다 → 다시 쓰러질 때까지 CLI 로
            # 마을·사냥터면 던전 밖이다. 던전을 나가는 패킷(NotInDungeon)을 놓치면 지난밤 'Cleared' 가 남아,
            # 아침에 접속 단계가 메인 화면을 던전 클리어 화면으로 알고 6명 모두 3분씩 헛돌았다 (2026-10-30 06:44)
            if s.channel_type in OPEN_MAPS and s.dungeon_state not in (None, NOT_IN_DUNGEON):
                s.dungeon_state = NOT_IN_DUNGEON
            # 대화는 맵을 옮기면 끝난다 — 끝 패킷 없이 끊긴 대화가 '대화 중' 으로 남아 끼어들기·정리가 헛돌지 않게
            s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
            self.spear.reset(s.channel_type == ABYSS and MAP_NAME in (s.channel_name or ""))
            log.info("패킷: 맵 진입 %s (%s)", s.channel_name or s.channel, s.channel_type or "?")
        elif key == "session.logout_ok":  # 캐릭터 선택 화면으로 (me1 03:29:30 — 맵 떠남·세션 정리와 같은 때)
            s.in_game, s.loading = False, False
            s.me = s.my_name = None
            s.drill_best = None  # 다음에 접속하는 캐릭터의 기록은 맵 진입 때 새로 온다
            s.attendance_at = 0.0
            s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
            log.info("패킷: 로그아웃 → 캐릭터 선택 화면")
        elif key == "session.entered":  # 게임 서버 입장 (접속·서버 옮김). 맵 진입은 몇 초 뒤
            if s.in_game is False:
                s.loading, s.loading_at = True, time.monotonic()
            s.in_game = True
        elif key == "daily.attendance_start":
            s.attendance_at = time.monotonic()
            log.info("패킷: 출석 대화 시작")
        elif key == "dungeon.state":
            s.dungeon_state = vals.get("state_name")
            log.info("패킷: 던전 상태 %s", s.dungeon_state)
        elif key == "abyss.result":
            s.abyss_result = vals.get("abyss") or 0
        elif key == "raid.state":
            s.raid_state = vals.get("state_name")
            log.info("패킷: 레이드 상태 %s", s.raid_state)
        elif key == "raid.result":
            s.raid_result = vals.get("raid") or 0
            log.info("패킷: 레이드 결과 옴")
        elif key == "drill.best":
            # 직업마다 기록이 따로 있다 — 표는 첫 기록만 읽는다 (기록이 여럿이면 어느 직업 것인지 몰라 드릴 숙제가 창으로도 본다)
            s.drill_best = (vals.get("zone") or 0) if vals.get("count") else 0
            s.drill_records = vals.get("count") or 0
        elif key == "drill.enter":
            s.drill_result = 0
        elif key == "drill.result":
            s.drill_result = vals.get("zone") or 0
            log.info("패킷: 나이트메어 드릴 %s구역 클리어", s.drill_result)
        elif key == "raid.boss_begin":
            s.raid_boss = True
            log.info("패킷: 레이드 보스전 시작")
        elif key == "abyss.campfire":
            s.campfire = True
        elif key == "ultimate.resource":
            s.ult, s.ult_max, s.pal, s.pal_max = vals.get("ult"), vals.get("ult_max"), vals.get("pal"), vals.get("pal_max")
        elif key == "ultimate.can_paladin":
            s.can_paladin = bool(vals.get("on"))
        elif key == "transfigure.current":
            # 파티원 변신은 뺀다. 내 번호를 모르면(판 도중에 리모콘을 켬) 내 것으로 본다 — 변신 중에 6(변신 해제)을
            # 누르지 않는 쪽이 안전하다
            if s.me is None or vals.get("actor") == s.me & 0xFFFFFFFF:
                now = s.transform_seen = time.monotonic()
                if s.transform_start and now - s.transform_start < 30:  # 변신 중에 또 옴 = 끝
                    s.transform_start = 0.0
                    log.info("패킷: 변신 끝")
                else:
                    s.transform_start, s.transformed_here = now, True
                    log.info("패킷: 변신 시작")
        elif key == "abyss.matching_update":
            s.abyss_matching = vals.get("state") or 0
            s.changed_at["abyss_matching"] = time.monotonic()
        elif key == "abyss.matching_cancel_ok":
            s.abyss_matching = 0
        elif key == "field.context":
            s.field_state = vals.get("state_name")
            log.info("패킷: 사냥터 상태 %s", s.field_state)
        elif key == "dungeon.current":
            s.dungeon = vals.get("channel") or None
        elif key == "dungeon.boss_battle":
            s.boss_battle = bool(vals.get("on"))
        elif key == "dialogue.target":
            t = vals.get("target")
            s.dialogue_npc = None if t in (None, NO_TARGET) else t
        elif key in ("dialogue.cleared", "dialogue.force_end") or key == "dialogue.update" and vals.get("active") is False:
            s.dialogue_npc = None
            s.dialogue_action, s.dialogue_menu = "", False
        elif key == "dialogue.update":
            s.dialogue_action, s.dialogue_step = vals.get("action") or "", vals.get("step") or s.dialogue_step
        elif key == "dialogue.prompt":
            s.dialogue_menu = bool(vals.get("open"))
        elif key == "char.personal_data":
            if vals.get("char_id") != s.char_id:  # 다른 캐릭터로 접속 — 맵에 들어가야 새 번호·이름을 안다
                s.me = s.my_name = None
                s.durability = None
                s.recommend = None  # 앞 캐릭터의 추천 항목 (요일 던전 '안 함' 판단)이 남지 않게
            s.char_id = vals.get("char_id")
        elif key == "char.appearing":
            if vals.get("mine"):
                if vals.get("actor") != s.me:
                    # 내 번호는 맵에 들어올 때만 바뀐다. 이미 이 맵에서 정했으면 다른 오브젝트의 등장에도 내 고유 번호가
                    # 들어 있는 것 — 무시한다 (11-03 21:36 이멘 마하: 들어온 11초 뒤 다른 캐릭터를 '나' 로 바꿨다.
                    # CLI 칭호·직업은 처음 캐릭터). 바꾸면 '나' 판단(투창·틱택토·변신·쓰러짐)이 틀어진다
                    if s.me is not None and s.entered_at and s.me_map == s.entered_at:
                        log.warning("패킷: 이 맵에서 정한 내 번호 %s 를 두고 다른 등장(%s, %s)에도 내 고유 번호가 있음 → 무시",
                                    s.me, vals.get("actor"), vals.get("name") or "?")
                        return
                    s.combat = "NonCombat"  # 맵에 막 들어옴 — 싸우는 중이면 곧 전투 상태가 온다
                s.me, s.me_map = vals.get("actor"), s.entered_at
                s.my_name = vals.get("name") or s.my_name
                log.info("패킷: 내 캐릭터 %s (번호 %s)", s.my_name or "?", s.me)
        elif key == "actor.dead":
            if self.spear.active:
                self._spear(key, vals)  # 흩어진 물길 주술사가 모두 쓰러지면 투창 패턴 끝
            if s.me is not None and vals.get("actor") == s.me:  # 파티 판에서는 부활 창 신호가 안 온다 (death1 03:10:24)
                s.dead = bool(vals.get("dead"))
                if s.dead:
                    s.dead_at = time.monotonic()
                log.info("패킷: 내 캐릭터 %s", "쓰러짐" if s.dead else "일어남")
        elif key == "revive.availability":
            was, s.dead = s.dead, bool(vals.get("available"))
            if s.dead:
                s.dead_at = time.monotonic()
            if s.dead or was:  # 맵에 들어갈 때마다 0 이 오므로 쓰러져 있다가 풀릴 때만 '부활'로 남긴다
                log.info("패킷: %s", "쓰러짐" if s.dead else "부활")
        elif key == "dimension.cleared":
            s.dimensions_cleared = vals.get("times")
        elif key in ("dye.open", "dye.start"):
            s.dye_open_at, s.dye_known = time.monotonic(), True
        elif key in ("dye.finish", "dye.cancel", "dye.abort", "dye.cancel_free"):
            s.dye_open_at, s.dye_known = None, True
        elif key == "recommend.add":
            s.recommend = vals.get("type")
        elif key == "revive.count":
            s.revives_used, s.revives_max = vals.get("used"), vals.get("max")
        elif key in ("revive.checkpoint_ok", "revive.item_ok"):
            s.dead = False
        elif key == "cutscene.play":
            s.cutscene = True
            s.changed_at["cutscene"] = time.monotonic()
            if s.campfire or not s.entered_at:
                s.boss_scene = True
        elif key in ("cutscene.end", "cutscene.abort"):
            s.cutscene = False
        elif key == "travel.begin":
            s.traveling, s.travel_points, s.travel_index = True, vals.get("points") or 0, 0
        elif key == "travel.target":
            s.travel_index = vals.get("index") or 0
        elif key == "travel.end":
            s.traveling, s.fast_travel_ok = False, False
        elif key == "fast_travel.state":
            s.fast_travel_ok = vals.get("available_name") == "Enabled"
        elif key == "actor.combat_state":
            if s.me is not None and vals.get("actor") == s.me:
                s.combat = vals.get("state_name")
        elif key == "char.ai":
            s.ai = vals.get("ai", "")
        elif key == "char.satiety":
            # 함께하기에선 다른 캐릭터의 포만감도 온다 — 예전엔 이걸로 내 번호를 덮어써, 투창 대상·틱택토 O 담당이
            # 나인데도 '다른 캐릭터'로 봤다 (2026-11-03 16:05·16:10). 내 번호를 모를 때만 받아들인다
            a = vals.get("actor")
            if s.me is None or a is None or a == s.me:
                s.satiety = vals.get("satiety")
                s.me = s.me if a is None else a
        elif key == "equip.durability":
            r = vals.get("ratio")
            if r is not None:
                s.durability = r if s.durability is None else min(s.durability, r)
        elif key == "equip.repair_ok":
            s.durability = None
            log.info("패킷: 장비 수리됨")
        elif key == "char.weight":
            s.weight = vals.get("weight")
        elif key == "char.max_weight":
            s.max_weight = vals.get("max_weight")
        now = time.monotonic()
        for f, v in old.items():
            if getattr(s, f) != v:
                s.changed_at[f] = now
        self._seq += 1
        self.recent.append(Seen(self._seq, time.monotonic(), key, vals))
        self.history.append((self._seq, _snapshot(s)))
        self._cond.notify_all()
