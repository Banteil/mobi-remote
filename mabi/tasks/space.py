"""지금 장소·콘텐츠 상태 읽기 — 장소 이름, 던전 상태(기다리기 포함), 사냥터 퀘스트."""
import time
from typing import Callable

from .. import gamedata as gd
from ..bot import Bot
from ..game_state import Activity


def game_space(bot: Bot) -> str:
    """지금 장소 이름. 패킷이 알면 맵 진입 때 온 맵 이름 (검은 구멍은 '지하로 뚫린 검은 구멍_<사냥터>'),
    로딩 중이거나 모르면 CLI get_current_environment (로딩 중엔 답이 없어 '')."""
    if bot.map_loading() is False and bot.packets.state.channel_name:
        return bot.packets.state.channel_name
    env = bot.state.query("get_current_environment") if bot.state.available() else None
    return (env or {}).get("GameSpaceDisplayName", "")


def inside_space(bot: Bot, keyword: str) -> bool:
    """장소 이름에 keyword 가 든 곳(검은 구멍 등) 안인가. 이름을 모르면('' — 로딩 중·CLI 조회 실패) 아직 안으로 본다 —
    한 번 못 읽은 것을 '나왔다' 로 봐서 판 중에 정리·이동으로 넘어가지 않게. 상한은 부르는 쪽이 둔다."""
    space = game_space(bot)
    return not space or keyword in space


def dungeon_state(bot: Bot) -> str | None:
    """던전 상태. 패킷 상태(바뀌는 즉시 + CLI 를 물을 때마다 CLI 답으로 맞춰짐), 모르면 CLI."""
    if bot.packets.ok and bot.packets.state.dungeon_state:
        return bot.packets.state.dungeon_state
    return Activity.of(bot.activity()).dungeon


def wait_dungeon(bot: Bot, pred: Callable[[str], bool], timeout: float, interval: float = 3.0) -> str | None:
    """던전 상태(NotInDungeon/Entering/InProgress/Cleared)가 pred 를 만족할 때까지 기다려 그 상태를 돌려준다.
    시간 초과면 "". 패킷이 상태를 알면 패킷으로 (바뀌는 즉시), 모르면 CLI 를 interval 마다 (CLI 조회 실패는 모르는 것 —
    pred 에 넘기지 않는다. 로딩·연출·실행 제한 중 한 번 실패한 것을 '진행 중 아님' 으로 봐 판을 실패로 끝냈다).
    둘 다 못 쓰면 None — 화면으로 판단할 것. 감시가 도중에 시작돼 아직 상태를 모를 때(던전 안에서 시작)도 CLI 로 간다."""
    end = time.monotonic() + timeout
    while True:
        p = bot.packets
        left = end - time.monotonic()
        if p.ok and p.state.dungeon_state is not None:
            if bot.wait_packet(lambda s: pred(s.dungeon_state), max(0.0, min(left, interval))):
                return p.state.dungeon_state
            # 바뀌는 패킷을 놓쳤을 수 있다 → interval 마다 CLI 에도 묻는다 (답은 패킷 상태에 맞춰진다 — Bot.activity)
            if bot.activity(max_age=0) and pred(p.state.dungeon_state):
                return p.state.dungeon_state
        elif bot.state.available():
            st = dungeon_state(bot)
            if st and pred(st):
                return st
            if left > 0:
                bot.sleep(min(left, interval))
        else:
            return None
        if time.monotonic() > end:
            return ""


def quest_titles(bot: Bot) -> list[str] | None:
    """퀘스트 제목 목록. CLI 조회 실패면 None (빈 목록과 구분해야 클리어로 오판하지 않는다)."""
    quests = bot.state.query("get_quests")
    return None if quests is None else [q.get("QuestTitle", "") for q in quests]


def hunt_quest(bot: Bot, place: str = "") -> str | None:
    """진행 중인 사냥터 퀘스트 제목 ('<장소> 사냥 …'), 없으면 '', 조회 실패면 None. place 가 비면 아무 사냥터나."""
    titles = quest_titles(bot)
    if titles is None:
        return None
    # 장소를 안 주면 config [places] 의 사냥터(index 2) 중 아무거나 — 이야기 퀘스트의 '사냥' 과 헷갈리지 않게
    places = [place] if place else [n for n, p in bot.cfg["places"].items() if int(p.get("index", -1)) == 2]
    return next((t for t in titles if gd.text("hunt_quest") in t and any(t.startswith(p) for p in places)), "")
