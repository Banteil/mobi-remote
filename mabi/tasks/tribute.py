"""마족 공물 던전: 퀘스트 창(J) → 메인 탭 → '모험가 길드의 고난도 심층 공략' 카드의 '진행하기'.

이 퀘스트는 공물이 2개 이상일 때, 접속 후 몇 분이 지나야 나타난다 (CLI get_quests 로 확인).
'진행하기'를 누르면 이번 주 심층 던전 입구까지 이동해 '심층 던전' 탭, '매우 어려움'으로 던전 창이 열린다.
입장할 때마다 공물 cost 개가 소모된다. 숙제로는 하루 한 번(max_runs) — 퀘스트를 깨면 그 퀘스트가 목록에서 사라지고
공물이 남아 있어도 완료로 본다.
"""
import time

import numpy as np

from .. import gamedata as gd, situation
from ..bot import Bot, StepTimeout
from .content import (QUESTWIN_TAB_BAR_Y, CannotProceed, enter_from_dungeon_window, questwin_buttons, travel,
                      with_retries)

QUEST_TITLE = gd.text("tribute_quest")
CARD_H = 450  # 퀘스트 카드 하나의 높이 (1920 기준, 제목 → '진행하기' 약 400px)
LIST_X0, LIST_Y0 = 1220, 220  # 퀘스트 창 오른쪽 카드 목록의 왼쪽 위 (탭 줄 위까지가 목록)


def quest_visible(bot: Bot) -> bool | None:
    """CLI 퀘스트 목록에 고난도 퀘스트가 있나. 목록이 통째로 비었으면 None (모름) — 아르바이트·주간 목표도 없는 빈 목록이
    와서 3분을 기다리다 건너뛰었다 (2026-10-28 07:54, 사냥터 클리어 화면 정리 실패 뒤). 그때는 퀘스트 창에서 직접 찾는다."""
    quests = bot.state.query("get_quests") if bot.state.available() else None
    if not quests:
        return None
    return any(q.get("QuestTitle") == QUEST_TITLE for q in quests)


def open_quest(bot: Bot, c: dict) -> None:
    """퀘스트 창 메인 탭에서 고난도 퀘스트 카드의 '진행하기'를 누른다."""
    ui = bot.ui
    bot.to_main()
    bot.key("j")
    bot.click(ui["questwin_tab_main"], timeout=10)
    bot.sleep(1, 1.5)
    # 창은 지난번 스크롤 자리를 기억할 수 있다. 아래로만 내리면 위쪽 카드를 못 본다
    # (2026-10-26 월요일 — 주간 목표·전리품 카드가 생긴 뒤 목록 끝만 보다 실패) → 맨 위로 올리고 내려가며 찾는다
    bot.scroll(*c["list_scroll_at"], 15)
    bot.sleep(1, 1.3)
    last = None
    for _ in range(8):
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
        # 내려도 목록이 그대로면 끝까지 본 것
        view = bot.frame()[LIST_Y0:QUESTWIN_TAB_BAR_Y, LIST_X0:].astype(np.int16)
        if last is not None and float(np.abs(view - last).mean()) < 2:
            break
        last = view
        bot.scroll(*c["list_scroll_at"], -3)
        bot.sleep(1, 1.3)
    raise RuntimeError(f"고난도 퀘스트의 '진행하기' 버튼을 찾지 못함 → {bot.snapshot('tribute_go').name}")


def verify(bot: Bot, cfg: dict) -> bool:
    """고난도 퀘스트를 깼으면 (목록에서 사라짐) 완료. 공물이 남아 있어도 숙제로는 하루 한 번이면 된다.
    공물이 모자라 못 도는 날도 완료."""
    if quest_visible(bot) is False:
        return True
    count = bot.read_counter("tribute")
    return count is not None and count < cfg["tribute"]["cost"]


def run(bot: Bot, cfg: dict) -> str:
    c = cfg["tribute"]
    # 심층 던전 창(매우 어려움)이 이미 열려 있으면 (이동 뒤 끊긴 채 다시 켬 등) 퀘스트 창을 건너뛰고 거기서 입장한다
    ready = situation.dungeon_tab(bot) == "deep" and bot.exists(c["very_hard"])
    if ready:
        bot.log.info("심층 던전 창(매우 어려움)이 이미 열려 있음 → 바로 입장")
    else:
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
    if ready:
        return f"공물 {start} → " + _enter(bot, c, start)
    if not quest_visible(bot):
        bot.step("tr_wait", f"공물 {start}개 — 고난도 퀘스트가 나타나길 기다림")
    while not (seen := quest_visible(bot)):
        if seen is None:
            bot.log.info("CLI 퀘스트 목록이 비어 있음 → 퀘스트 창에서 직접 찾음")
            break
        if time.monotonic() > end:
            raise CannotProceed(f"공물 {start}개인데 {c['quest_wait']}초 동안 고난도 퀘스트가 나타나지 않음 → 건너뜀")
        bot.log.info("고난도 퀘스트 대기 중")
        bot.sleep(5)  # 20초 간격이면 퀘스트가 뜬 뒤에도 한참 서 있어 멈춘 것처럼 보인다

    results = []
    count = start
    while count >= c["cost"] and len(results) < c["max_runs"] and quest_visible(bot) is not False:
        bot.step("tr_open", f"{len(results) + 1}회차 — 고난도 퀘스트 진행하기 (공물 {count}개)", tribute=count)
        def go():
            open_quest(bot, c)
            bot.step("travel", "심층 던전 입구로 이동")
            # 엉뚱한 버튼을 눌러 이동이 시작되지 않으면 travel 이 바로 알린다 (content.started)
            travel(bot, arrive=[c["dungeon_tab"]], timeout=c["travel_timeout"])

        with_retries(bot, "심층 던전 입구로 가기", go)
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


def _enter(bot: Bot, c: dict, start: int) -> str:
    """열려 있는 심층 던전 창에서 입장해 클리어까지 (한 번)."""
    r = enter_from_dungeon_window(bot, c["clear_timeout"])
    return f"{bot.read_counter('tribute')}, 클리어 {int(r == 'clear')}회, 실패 {int(r == 'fail')}회"
