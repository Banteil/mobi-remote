"""마족 공물 던전: 퀘스트 창(J) → 메인 탭 → '모험가 길드의 고난도 심층 공략' 카드의 '진행하기'.

이 퀘스트는 공물이 2개 이상일 때, 접속 후 몇 분이 지나야 나타난다 (CLI get_quests 로 확인).
'진행하기'를 누르면 이번 주 심층 던전 입구까지 이동해 '심층 던전' 탭, '매우 어려움'으로 던전 창이 열린다.
입장할 때마다 공물 cost 개가 소모된다. 숙제로는 하루 한 번(max_runs) — 퀘스트를 깨면 그 퀘스트가 목록에서 사라지고
공물이 남아 있어도 완료로 본다.
"""
import time

from .. import gamedata as gd
from ..bot import Bot, StepTimeout
from .content import CannotProceed, enter_from_dungeon_window, questwin_buttons, travel

QUEST_TITLE = gd.text("tribute_quest")
CARD_H = 450  # 퀘스트 카드 하나의 높이 (1920 기준, 제목 → '진행하기' 약 400px)


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
        # 같은 카드의 '진행하기' = 제목 아래 카드 안(CARD_H 이내)에서 가장 가까운 주황색 버튼.
        # 주말에는 '주말에는 어비스!' 같은 이벤트 카드도 주황 '진행하기' 라, 고난도 카드 버튼이 화면 밖이면
        # 아래 카드 버튼을 눌러 이벤트 탭이 열렸다 (2026-10-24 16:37 — 7분 동안 던전 입구를 기다림).
        # 버튼이 아래 탭 줄에 걸쳐 반쯤 보이면 누르지 않고 (questwin_buttons) 내린다
        go = [b for b in questwin_buttons(bot, c["quest_go"]) if card and 0 < b.y - card.y < CARD_H]
        if go:
            bot.click(go[0])
            return
        # 다른 퀘스트(주간 목표 등)가 위에 있으면 카드나 버튼이 화면 아래로 밀려난다 → 목록을 내린다
        bot.scroll(*c["list_scroll_at"], -3)
        bot.sleep(1, 1.3)
    raise RuntimeError(f"고난도 퀘스트의 '진행하기' 버튼을 찾지 못함 → {bot.snapshot('tribute_go').name}")


def _travel_started(bot: Bot, c: dict, wait: float = 12) -> bool:
    """'진행하기' 뒤 자동 이동이 시작됐나 (또는 이미 던전 창). 엉뚱한 버튼을 눌렀으면 몇 분씩 기다리지 않게."""
    if not bot.packets.ok and not bot.state.available():
        return True  # 패킷도 CLI 도 없으면 판단할 수 없다 — 예전처럼 도착을 기다린다
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if bot.auto_traveling() or bot.exists(c["dungeon_tab"]):
            return True
        bot.sleep(1.5)
    return False


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
        for attempt in range(2):
            open_quest(bot, c)
            bot.step("travel", "심층 던전 입구로 이동")
            if _travel_started(bot, c):
                break
            shot = bot.snapshot('tribute_go').name
            if attempt:
                raise RuntimeError(f"'진행하기' 를 눌렀는데 던전으로 이동하지 않음 → {shot}")
            bot.log.warning(f"'진행하기' 뒤 이동이 시작되지 않음 → 퀘스트 창을 다시 열어 봄 ({shot})")
            bot.to_main()
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
