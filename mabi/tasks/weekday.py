"""요일 던전: 퀘스트 창(J) → 아르바이트 탭 → '요일' 태그가 붙은 아르바이트의 '진행하기'.
요일에 맞는 던전 입구까지 자동 이동하면 던전 창이 '요일 던전' 탭으로 열리고,
기본 선택된 단계로 진입 → 임무 선택 화면에서 입장한다.
완료 여부는 콘텐츠 가이드('/')의 '일일 달성' 체크로 판단한다 (아르바이트 목록만으로는 잘못 판단한 적이 있음).

일요일은 카드('선택 가능' 태그)의 진행하기가 던전이 아니라 마을 임무 게시판으로 간다 (2026-10-25 실측):
게시판 대화 → '가고 싶은 장소는?' 선택지 [빛나는 동굴(골드) / 눈부신 저택(보석) / 찬란한 유적(연금술 재연소 촉매)]
→ 고르면 대화가 끝나고 메인 화면, 카드 목표가 '<고른 던전> 클리어' 로 바뀐다 → 카드 진행하기를 다시 누르면
평일처럼 던전 입구까지 가서 '요일 던전' 탭이 열린다. 요일을 따로 보지 않고, 진행하기 뒤에 대화가 열리면 게시판으로 본다
(게시판도 NPC 대화와 같은 판정). 이미 골라 둔 날(도중에 끊긴 뒤 이어 할 때)은 진행하기가 바로 던전으로 간다.
"""
import time

from .. import situation
from ..bot import Bot, StepTimeout
from .dialogue import in_dialog
from .content import (CannotProceed, daily_achieved, enter_from_dungeon_window, open_arbeit_tab, questwin_buttons, travel,
                      with_retries)

SUNDAY_CHOICES = ("골드", "보석", "촉매")  # 선택지 글자 괄호 안의 낱말. 이 낱말이 든 버튼을 누른다


def verify(bot: Bot, cfg: dict) -> bool:
    # 패킷: 퀘스트 창 '추천'이 요일 던전(2)이면 아직 안 한 것 — 가이드를 열지 않는다.
    # 다른 항목이면 깬 건지 다른 추천(가방 정리 등)에 가려진 건지 몰라 화면으로 본다
    if bot.packets.ok and bot.packets.state.recommend == 2:
        bot.log.debug("패킷: 추천 항목이 요일 던전 → 아직 안 함")
        return False
    return daily_achieved(bot, cfg["weekday_dungeon"]["achieved"])


def sunday_choice(cfg: dict, slot: int | None) -> str:
    """일요일 게시판에서 고를 던전: 캐릭터별 설정 → 공통 설정. 모르는 값이면 촉매."""
    c = cfg["weekday_dungeon"]
    own = c.get("sunday_by_slot", {}).get(str(slot)) if slot is not None else None
    v = own or c.get("sunday")
    return v if v in SUNDAY_CHOICES else SUNDAY_CHOICES[-1]


def find_tag(bot: Bot, c: dict):
    """'요일' 태그. 목록이 늦게 뜨거나 아래쪽에 있을 수 있어 몇 번 기다리고 스크롤하며 찾는다."""
    x, y, w, h = c["panel"]
    for i in range(4):
        tag = bot.find(c["tag"])
        if tag:
            return tag
        bot.sleep(1, 1.5)
        if i >= 1:
            bot.scroll(x + w // 2, y + h // 2, -5)
            bot.sleep(0.8, 1.0)
    return None


def click_card(bot: Bot, c: dict) -> None:
    """퀘스트 창 아르바이트 탭에서 '요일' 카드의 '진행하기'를 누른다."""
    open_arbeit_tab(bot)
    tag = find_tag(bot, c)
    if not tag:
        shot = bot.snapshot("weekday_none").name
        bot.to_main()
        raise CannotProceed(f"일일 달성에 체크가 없는데 요일 아르바이트를 찾지 못함 → {shot}")

    # 태그가 붙은 카드의 '진행하기' = 태그보다 아래에 있는 첫 번째 버튼.
    # 새 카드('NEW')는 태그가 먼저 보이고 버튼이 늦게 그려진다 (2026-10-22 탭 누르고 2초 만에 못 찾음) → 몇 초 기다린다
    # 버튼이 아래 탭 줄에 걸쳐 반쯤 보이면 누르지 않고 (questwin_buttons) 목록을 조금 내린다
    buttons = []
    x, y, w, h = c["panel"]
    for i in range(6):
        buttons = [b for b in questwin_buttons(bot, c["go"], region=c["panel"]) if b.y > tag.y]
        if buttons:
            break
        if i >= 2:
            bot.scroll(x + w // 2, y + h // 2, -2)
        bot.sleep(0.8, 1.0)
        tag = bot.find(c["tag"]) or tag  # 카드가 미끄러져 들어오면 태그 위치도 바뀐다
    if not buttons:
        raise RuntimeError("요일 아르바이트의 '진행하기' 버튼을 찾지 못함")
    bot.click(buttons[0])


def choose_on_board(bot: Bot, c: dict, want: str) -> None:
    """임무 게시판 대화에서 want('골드'·'보석'·'촉매')가 든 선택지를 고르고 대화가 끝날 때까지 — 점검자가 한다
    (Ctx.choose: 선택지가 뜨면 버튼 줄 글자에서 want 를 찾아 누르고, 대사는 넘긴다. 원하는 게 안 보이면 아무거나 누르지 않는다).
    대화가 고르기 전에 끝나거나 시간이 다 되면 멈춘다."""
    from .. import monitor
    from ..monitor import detect as d
    mon = monitor.of(bot)
    ctx = monitor.Ctx("weekday_dungeon", "임무 게시판", choose=want)
    end = time.monotonic() + c["board_timeout"]
    while time.monotonic() < end:
        seen = mon.check(ctx)
        if not seen.done and seen.what == d.MAIN and not (bot.dialogue_playing() or in_dialog(bot)):
            if "chosen" in ctx.events:
                bot.log.info(f"임무 게시판: {want} 던전 고름")
                return
            raise CannotProceed(f"임무 게시판 대화가 고르기 전에 끝남 → {bot.snapshot('board_closed').name}")
        bot.sleep(0.6, 0.9)
    shot = bot.snapshot("board_timeout").name
    bot.to_main()
    raise CannotProceed(f"임무 게시판에서 '{want}' 선택지를 고르지 못함 → {shot}")


def run(bot: Bot, cfg: dict) -> str:
    """NPC 대화를 스스로 다루는 일 — 그동안 대화는 끼어들기로 넘기지 않는다 (Bot.npc_talk, monitor.interrupts)."""
    with bot.npc_talk():
        return _task(bot, cfg)


def _task(bot: Bot, cfg: dict) -> str:
    c = cfg["weekday_dungeon"]
    # 요일 던전 창이 이미 열려 있으면 (입구에 선 채 끊김·다시 켬) 카드·이동을 건너뛰고 거기서 입장한다.
    # 완료 확인(verify)은 가이드 창을 열어 던전 창을 닫으므로 그보다 먼저 본다
    # (패킷 '추천' 이 요일 던전이 아니면 — 이미 깼을 수 있다 — 가이드로 확인부터)
    not_done = not bot.packets.ok or bot.packets.state.recommend in (None, 2)
    if not_done and situation.dungeon_tab(bot) == "weekday":
        bot.log.info("요일 던전 창이 이미 열려 있음 → 바로 입장")
        result = enter_from_dungeon_window(bot, c["clear_timeout"], c["extra_loot"])
        bot.verified = result == "clear"
        return f"요일 던전 {result}"
    # 단계: wd_card(요일 아르바이트 찾기) → travel → [일요일: wd_board → wd_card → travel] → dungeon_enter → in_dungeon
    # → dungeon_reward (content 가 남김). 던전 안에서 끊겼으면 접속 단계가 클리어까지 보고 나오고,
    # 여기서는 일일 달성 체크로 끝났는지 본다
    if verify(bot, cfg):
        bot.verified = True
        return "완료 (일일 달성 체크)"
    talk = [bot.cfg["arbeit"]["dialog_log"], bot.ui["dialog_skip"]]
    chosen = None
    for _ in range(2):  # 일요일이면 게시판에서 고른 뒤 카드를 한 번 더 누른다
        def go():
            bot.step("wd_card", "퀘스트 창 → 요일 아르바이트 찾기")
            click_card(bot, c)
            bot.step("travel", "요일 던전 입구로 이동")
            # 평일·이미 고른 일요일은 던전 창, 아직 안 고른 일요일은 임무 게시판 대화가 열린다.
            # 이동은 travel 이 빠른 이동(T)을 누를 수 있으면 누른다
            return travel(bot, arrive=[c["dungeon_tab"]] + ([] if chosen else talk), timeout=c["travel_timeout"])

        m = with_retries(bot, "요일 던전 입구로 가기", go)
        if m.name == c["dungeon_tab"]:
            result = enter_from_dungeon_window(bot, c["clear_timeout"], c["extra_loot"])
            bot.verified = result == "clear"  # 던전 클리어(패킷·CLI 상태 Cleared)가 곧 완료 — 가이드를 다시 열지 않는다
            return f"요일 던전{f'({chosen})' if chosen else ''} {result}"
        chosen = sunday_choice(cfg, bot.character["slot"] if bot.character else None)
        bot.step("wd_board", f"임무 게시판에서 {chosen} 던전 고르기")
        choose_on_board(bot, c, chosen)
        try:
            bot.wait(bot.ui["main_hud"], timeout=10)
        except StepTimeout:
            bot.to_main()
    raise CannotProceed(f"임무 게시판에서 고른 뒤에도 던전 창이 열리지 않음 → {bot.snapshot('weekday_board').name}")
