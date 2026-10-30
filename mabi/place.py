"""지금 어디인가 — 맵·로딩·던전·사냥터·쓰러짐 같은 '자리' 사실을 한곳에서 정한다.

예전엔 어비스(abyss.inside)·레이드(raid._map)·접속(login._in_field)·던전(content.dungeon_state)이 이 사실들을
저마다 다른 순서·다른 CLI 키로 따로 구했다 (구조 점검 2026-10-30). 이제 모두 place() 를 본다.
각 콘텐츠만의 화면 판단(입장 창·배·목록·보상 화면)은 그 태스크에 둔다.

출처 규칙: 패킷 상태(바뀌는 즉시 알고, CLI 를 물을 때마다 CLI 답으로 맞춰짐 — Bot.activity) → 패킷이 맵을 모르면 CLI.
장소 이름은 CLI 의 ChannelDisplayName 하나로 (패킷 맵 이름과는 글자가 다르다: '마스 심층 던전 1층 2구역' /
'마스 3_2 던전 (심층 1층 2구역) 매우 어려움').
"""
from dataclasses import dataclass

from . import gamedata as gd

ABYSS = "InstanceAbyssDungeon"
RAID = "InstanceRaid"
RAID_LOBBY = "InstanceRaidLobby"
DUNGEON = "InstanceDungeon"
FIELD = "BattleField"
ABYSS_NAMES = ("어비스", "허상의 정박지", "광기의 동굴", "흩어진 물길")


@dataclass
class Place:
    loading: bool | None      # 맵 로딩 중 (모르면 None)
    kind: str | None          # 맵 종류 (패킷 channel_type 이름을 쓴다). 모르면 None
    src: str                  # kind 를 무엇으로 알았나: packet / cli / ''
    name: str = ""            # 장소 이름 (패킷이면 맵 이름, CLI 면 ChannelDisplayName)
    dungeon: str | None = None  # 던전 상태 NotInDungeon / Entering / InProgress / Cleared
    in_field: bool | None = None  # 사냥터 안 (클리어 뒤 채널 옮김 대기 포함)


def env_name(bot) -> str:
    """CLI 장소 이름 (ChannelDisplayName). 답이 없으면 ''."""
    return (bot.environment() or {}).get("ChannelDisplayName", "") or ""


def place(bot) -> Place:
    """지금 자리. 패킷이 맵을 알면 그것으로, 모르면 CLI(get_activity 의 던전·사냥터 + 장소 이름)로 짐작한다."""
    p = bot.packets
    loading = bot.map_loading()
    s = p.state
    if loading is not None:  # 패킷이 맵을 안다
        field = None if s.field_state is None else s.field_state != "NotInBattlefield"
        return Place(loading, None if loading else (s.channel_type or None), "packet",
                     s.channel_name, s.dungeon_state, field)
    act = bot.activity()
    if act is None:  # 로딩 중이거나 게임 밖이거나 CLI 가 없다
        return Place(None, None, "", "", s.dungeon_state if p.ok else None, None)
    dungeon = (act.get("Dungeon") or {}).get("State")
    in_field = bool((act.get("Battlefield") or {}).get("IsInBattleField"))
    name = env_name(bot)
    kind = None
    if in_field:
        kind = FIELD
    elif name and any(n in name for n in ABYSS_NAMES):
        kind = ABYSS
    elif name and name == gd.text("raid_ship"):
        kind = RAID_LOBBY
    elif dungeon not in (None, "NotInDungeon"):
        kind = DUNGEON
    return Place(False, kind, "cli" if kind else "", name, dungeon, in_field)
