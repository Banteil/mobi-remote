"""마족 공물 던전: 퀘스트 창(J) → 메인 탭 → '모험가 길드의 고난도 심층 공략' 카드의 '진행하기'.

이 퀘스트는 공물이 2개 이상일 때, 접속 후 몇 분이 지나야 나타난다 (CLI get_quests 로 확인).
'진행하기'를 누르면 이번 주 심층 던전 입구까지 이동해 '심층 던전' 탭, '매우 어려움'으로 던전 창이 열린다.
입장할 때마다 공물 cost 개가 소모된다. 숙제로는 하루 한 번(max_runs) — 퀘스트를 깨면 그 퀘스트가 목록에서 사라지고
공물이 남아 있어도 완료로 본다.
"""
import time

from .. import gamedata as gd
from ..bot import Bot, StepTimeout
from .content import CannotProceed, enter_from_dungeon_window, travel

QUEST_TITLE = gd.text("tribute_quest")


def quest_visible(bot: Bot) -> bool:
    quests = bot.state.query("get_quests") if bot.state.available() else None
    return any(q.get("QuestTitle") == QUEST_TITLE for q in quests or [])


def open_quest(bot: Bot, c: dict) -> None:
    """퀘스트 창 메인 탭에서 고난도 퀘스트 카드의 '진행하기'를 누른다."""
    ui = bot.ui
    bot.to_main()
    bot.key("j")
    bot.click(ui["questwin_tab_main"], timeout=10)
    bot.sleep(1, 1.5)
    for _ in range(4):
        card = bot.find(c["quest_card"])
        # 같은 카드의 '진행하기' = 제목 아래에서 가장 가까운 주황색 버튼
        go = sorted((b for b in bot.find_all(c["quest_go"]) if card and b.y > card.y), key=lambda b: b.y)
        if go:
            bot.click(go[0])
            return
        # 다른 퀘스트(주간 목표 등)가 위에 있으면 카드나 버튼이 화면 아래로 밀려난다 → 목록을 내린다
        bot.scroll(*c["list_scroll_at"], -3)
        bot.sleep(1, 1.3)
    raise RuntimeError(f"고난도 퀘스트의 '진행하기' 버튼을 찾지 못함 → {bot.snapshot('tribute_go').name}")


def verify(bot: Bot, cfg: dict) -> bool:
    """고난도 퀘스트를 깼으면 (목록에서 사라짐) 완료. 공물이 남아 있어도 숙제로는 하루 한 번이면 된다.
    공물이 모자라 못 도는 날도 완료."""
    if not quest_visible(bot):
        return True
    count = bot.read_counter("tribute")
    return count is not None and count < cfg["tribute"]["cost"]


def run(bot: Bot, cfg: dict) -> str:
    c = cfg["tribute"]
    bot.to_main()
    start = bot.read_counter("tribute")
    if start is None:
        raise RuntimeError("공물 개수를 읽을 수 없어 중단")
    if start < c["cost"]:
        return f"공물 {start}개, 진행 없음"

    # 접속 직후에는 퀘스트가 아직 없을 수 있다
    # 단계: tr_wait(퀘스트 대기) → tr_open(n회차 진행하기) → travel → dungeon_enter → in_dungeon → dungeon_reward.
    # 몇 번 남았는지는 공물 개수가 알려 주므로 끊겨도 남은 만큼만 돈다 (던전 안이면 접속 단계가 클리어까지 본다)
    end = time.monotonic() + c["quest_wait"]
    if not quest_visible(bot):
        bot.step("tr_wait", f"공물 {start}개 — 고난도 퀘스트가 나타나길 기다림")
    while not quest_visible(bot):
        if time.monotonic() > end:
            raise CannotProceed(f"공물 {start}개인데 {c['quest_wait']}초 동안 고난도 퀘스트가 나타나지 않음 → 건너뜀")
        bot.log.info("고난도 퀘스트 대기 중")
        bot.sleep(5)  # 20초 간격이면 퀘스트가 뜬 뒤에도 한참 서 있어 멈춘 것처럼 보인다

    results = []
    count = start
    while count >= c["cost"] and len(results) < c["max_runs"] and quest_visible(bot):
        bot.step("tr_open", f"{len(results) + 1}회차 — 고난도 퀘스트 진행하기 (공물 {count}개)", tribute=count)
        open_quest(bot, c)
        bot.step("travel", "심층 던전 입구로 이동")
        travel(bot, arrive=[c["dungeon_tab"]], timeout=c["travel_timeout"])
        # 탭이 보인 직후엔 난이도 버튼이 아직 덜 그려졌을 수 있다 (2026-10-22 오탐) → 몇 초 기다려 본다
        try:
            bot.wait(c["very_hard"], timeout=5)
        except StepTimeout:
            raise RuntimeError(f"던전 창에서 '매우 어려움'이 선택되어 있지 않음 → {bot.snapshot('tribute').name}")
        results.append(enter_from_dungeon_window(bot, c["clear_timeout"]))
        count = bot.read_counter("tribute")
        if count is None:
            break

    return f"공물 {start} → {count}, 클리어 {results.count('clear')}회, 실패 {results.count('fail')}회"
