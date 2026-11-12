"""패킷 상태를 CLI get_activity 답과 맞추기 — 물을 때마다(merge_cli), 작업 시작 점검(reconcile), 흐름이 끊겼을 때(forget).
PacketMonitor 가 상속한다 (self.state · self._cond 를 쓴다)."""
import logging
import time

from ..game_state import Activity
from ..place import ABYSS, DUNGEON, FIELD, OPEN_MAPS, RAID, RAID_LOBBY, is_instance

log = logging.getLogger("mabi")

MATCH_KEEP = 600     # 작업 시작 점검: 이보다 오래전에 받은 매칭(요청·찾는 중)은 끝난 것으로 (초)
CUTSCENE_KEEP = 120  # 작업 시작 점검: 이보다 오래전에 시작한 연출은 끝 신호를 놓친 것으로 (초)
CLI_LAG = 5.0  # CLI 가 패킷보다 늦게 바뀌는 시간 (쓰러짐 약 3초, death1 실측) — 패킷이 이보다 최근에 바꿨으면 패킷을 믿는다


def map_contradicts(channel_type: str, act: dict) -> bool:
    """패킷 맵 종류가 CLI 와 어긋나나 — 마을인데 던전 안·사냥터 안이라 함, 던전·사냥터 맵인데 밖이라 함.
    장소 이름은 CLI 와 패킷이 글자가 달라 비교하지 않는다. 어비스·레이드는 CLI 가 던전으로 치지 않아 보지 않는다."""
    t = channel_type
    a = Activity.of(act)
    dungeon, field = a.in_dungeon, a.in_field
    return bool(t) and ((t in OPEN_MAPS and dungeon) or (t == FIELD) != field
                        or (t == DUNGEON and not dungeon))


class CliSync:
    """상태를 CLI 로 맞추는 쪽. 상태를 고치는 일은 모두 잠금(self._cond) 안에서."""

    def forget(self, why: str) -> None:
        """상태를 고치는 일은 모두 잠금 안에서 — 패킷 받는 스레드(apply)와 작업 스레드(merge_cli·reconcile·forget)가
        같은 상태를 고친다. 자세한 것은 _forget."""
        with self._cond:
            self._forget(why)

    def _forget(self, why: str) -> None:
        """이벤트로만 바뀌는 상태를 모름(None)으로. 다음 패킷이 오거나, 그 전엔 CLI·화면으로 판단한다.
        맵도 모름으로 둔다 — fresh 가 거짓이 되어 대화·컷신의 '없음' 도 믿지 않게 된다."""
        s = self.state
        s.channel, s.channel_type, s.channel_name = None, "", ""
        s.dungeon_state = s.field_state = s.dead = s.traveling = s.fast_travel_ok = s.combat = None
        s.abyss_matching, s.boss_battle, s.cutscene = 0, False, False
        s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
        log.info("패킷: %s → 맵·던전·이동 등 상태를 모름으로 (다음 패킷이나 CLI 로 다시 앎)", why)
        self._cond.notify_all()

    def merge_cli(self, act: dict, asked_at: float) -> list[str]:
        """상태를 고치는 일은 모두 잠금 안에서 — 패킷 받는 스레드(apply)와 작업 스레드(merge_cli·reconcile·forget)가
        같은 상태를 고친다. 자세한 것은 _merge_cli."""
        with self._cond:
            return self._merge_cli(act, asked_at)

    def _merge_cli(self, act: dict, asked_at: float) -> list[str]:
        """CLI get_activity 답이 올 때마다 오래 남는 상태(CLI_FACTS: 던전·사냥터 안팎·쓰러짐)를 그 답으로 맞춘다 — 가장
        믿을 정보는 CLI 이고, 패킷은 바뀌는 순간을 빨리 알리는 데 쓴다. 다만 패킷이 asked_at(물은 때) 이후나 CLI_LAG
        안에 바꾼 값은 패킷이 더 새로우니 둔다. 대화·이동·전투 같은 순간 상태는 패킷이 빠르고 CLI 와 뜻이 조금 달라
        (메뉴 대기 등) 여기서 덮지 않는다 — 작업 시작 점검(reconcile)에서만 맞춘다. 바뀐 것 ['이름 전 → 후']."""
        s = self.state
        a = Activity.of(act)
        want = {
            "dungeon_state": a.dungeon or s.dungeon_state,
            # 사냥터 안이면 InProgress·WaitingForChannelTransfer 를 CLI 가 가르지 못한다 → 밖이라던 패킷만 모름으로
            "field_state": ("NotInBattlefield" if not a.in_field
                            else None if s.field_state == "NotInBattlefield" else s.field_state),
            "dead": a.dead,
        }
        out, fixed = [], False
        recent = min(asked_at, time.monotonic() - CLI_LAG)
        # 맵 종류도 CLI 와 맞춘다 (예전엔 작업 시작 점검에서만) — 흐름이 끊겨 맵 진입을 놓치면 틀린 맵에 머문다.
        # 막 들어온 맵은 CLI 가 늦게 따라오므로 둔다
        if not s.loading and s.entered_at < recent and map_contradicts(s.channel_type, act):
            out.append(f"맵 {s.channel_type} → 모름")
            fixed = True
            s.channel, s.channel_type, s.channel_name = None, "", ""
        for f, v in want.items():
            cur = getattr(s, f)
            if cur == v or s.changed_at.get(f, 0.0) > recent:
                continue
            setattr(s, f, v)
            out.append(f"{f} {cur} → {v}")
            fixed |= cur is not None
        if out:
            # 모르던 값(None)을 채운 것은 흔하다 (맵을 옮기면 쓰러짐을 모름으로 둔다 등) — 패킷 값이 틀렸던 것만 알린다
            (log.info if fixed else log.debug)("CLI 로 맞춤: %s", ", ".join(out))
            self._cond.notify_all()
        return out

    def reconcile(self, act: dict | None) -> list[str]:
        """상태를 고치는 일은 모두 잠금 안에서 — 패킷 받는 스레드(apply)와 작업 스레드(merge_cli·reconcile·forget)가
        같은 상태를 고친다. 자세한 것은 _reconcile."""
        with self._cond:
            return self._reconcile(act)

    def _reconcile(self, act: dict | None) -> list[str]:
        """새 작업을 시작할 때 (처음이든 이어 하기든 — 그 사이 사람이 무엇을 했을지 모른다): 지난 일에서 남은 상태를
        그대로 믿지 않고 지금 게임에 맞춘다. 상태가 바뀌는 패킷을 놓치면 (스트림 공백 등) 지난밤 상태가 아침까지 남는다
        (2026-10-30 06:44: 던전 Cleared 로 6명 모두 접속 실패).
        act(CLI get_activity) 가 있으면 그 답으로, 없으면(로딩·캐릭터 선택 화면) 모름(None)으로 — 다음 패킷이나
        CLI·화면으로 다시 본다. 맵 종류가 CLI 와 어긋나면 (마을인데 던전 안·사냥터 안이라 함, 던전·사냥터 맵인데
        밖이라 함) 맵도 모름으로 돌린다 — 장소 이름은 CLI 와 패킷이 달라 ('마스 심층 던전 1층 2구역' /
        '마스 3_2 던전 (심층 1층 2구역) 매우 어려움') 비교하지 않는다. 레이드·어비스 결과는 맵 종류로 가린다.
        바뀐 것 ['이름 전 → 후']."""
        s = self.state
        before = {"맵": s.channel_name, "던전": s.dungeon_state, "사냥터": s.field_state, "쓰러짐": s.dead,
                  "레이드": s.raid_state, "매칭": s.abyss_matching, "연출": s.cutscene}
        now = time.monotonic()
        # CLI 가 알려 주지 않는 순간 상태는 시작 전에 생긴 것이 오래됐으면 지운다 — 사람이 그 사이 무엇을 했는지 모른다
        # (2026-11-07 17:32: 사람이 한 레이드 매칭의 '잡힘' 이 남아 어비스 반복이 오지 않을 입장을 기다림).
        # 작업마다 점검하므로 바로 앞 작업이 막 받은 것(매칭을 걸고 일시정지 → 이어 하기 등)은 남긴다
        if s.abyss_matching and (s.abyss_matching == 3 or is_instance(s.channel_type) and
                                 s.channel_type != ABYSS
                                 or now - s.changed_at.get("abyss_matching", 0.0) > MATCH_KEEP):
            s.abyss_matching = 0
        if s.cutscene and now - s.changed_at.get("cutscene", 0.0) > CUTSCENE_KEEP:
            s.cutscene = False
        if act:
            s.loading = False
            if map_contradicts(s.channel_type, act):
                s.channel, s.channel_type, s.channel_name = None, "", ""
            a = Activity.of(act)
            s.dungeon_state = a.dungeon
            if not a.in_field:
                s.field_state = "NotInBattlefield"
            elif s.field_state in (None, "NotInBattlefield"):
                s.field_state = None  # 사냥터 안인데 패킷은 밖이라 한다 → 모름
            s.dead = a.dead
            s.traveling = a.traveling
            s.combat = "InCombat" if a.combat else "NonCombat"
            s.boss_battle = a.boss_battle
            if not s.traveling:
                s.fast_travel_ok = None  # 다음 자동 이동 때 다시 온다
            if not a.dialogue:
                s.dialogue_npc, s.dialogue_action, s.dialogue_menu = None, "", False
            if not a.minigame:
                s.dye_open_at = None  # 염색 미니게임 닫힘을 놓쳤어도
        else:
            s.dungeon_state = s.field_state = s.dead = s.traveling = s.combat = s.fast_travel_ok = None
        if s.channel_type not in (RAID, RAID_LOBBY):
            s.raid_state, s.raid_result, s.raid_boss = None, 0, False
        if s.channel_type != ABYSS:
            s.abyss_result = 0
            s.campfire = s.boss_scene = False
            s.revives_used = s.revives_max = None  # 지난 판의 부활 횟수로 '다 씀' 이라 보지 않게 (맵에 들어가면 다시 온다)
        after = {"맵": s.channel_name, "던전": s.dungeon_state, "사냥터": s.field_state, "쓰러짐": s.dead,
                 "레이드": s.raid_state, "매칭": s.abyss_matching, "연출": s.cutscene}
        return [f"{k} {before[k]} → {after[k]}" for k in before if before[k] != after[k]]
