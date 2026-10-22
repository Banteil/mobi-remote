"""요일 던전: 퀘스트 창(J) → 아르바이트 탭 → '요일' 태그가 붙은 아르바이트의 '진행하기'.
요일에 맞는 던전 입구까지 자동 이동하면 던전 창이 '요일 던전' 탭으로 열리고,
기본 선택된 단계로 진입 → 임무 선택 화면에서 입장한다.
완료 여부는 콘텐츠 가이드('/')의 '일일 달성' 체크로 판단한다 (아르바이트 목록만으로는 잘못 판단한 적이 있음).
"""
from ..bot import Bot
from .content import CannotProceed, daily_achieved, enter_from_dungeon_window, open_arbeit_tab, travel


def verify(bot: Bot, cfg: dict) -> bool:
    return daily_achieved(bot, cfg["weekday_dungeon"]["achieved"])


def find_tag(bot: Bot, c: dict):
    """'요일' 태그. 목록이 늦게 뜨거나 아래쪽에 있을 수 있어 몇 번 기다리고 스크롤하며 찾는다."""
    r = bot.window.client_rect()
    x, y, w, h = c["panel"]
    for i in range(4):
        tag = bot.find(c["tag"])
        if tag:
            return tag
        bot.sleep(1, 1.5)
        if i >= 1:
            bot.input.scroll(r.left + x + w // 2, r.top + y + h // 2, -5)
            bot.sleep(0.8, 1.0)
    return None


def run(bot: Bot, cfg: dict) -> str:
    c = cfg["weekday_dungeon"]
    # 단계: wd_card(요일 아르바이트 찾기) → travel → dungeon_enter → in_dungeon → dungeon_reward (content 가 남김).
    # 던전 안에서 끊겼으면 접속 단계가 클리어까지 보고 나오고, 여기서는 일일 달성 체크로 끝났는지 본다
    if verify(bot, cfg):
        return "이미 완료 (일일 달성 체크)"
    bot.step("wd_card", "퀘스트 창 → 요일 아르바이트 찾기")
    open_arbeit_tab(bot)
    tag = find_tag(bot, c)
    if not tag:
        shot = bot.snapshot("weekday_none").name
        bot.to_main()
        raise CannotProceed(f"일일 달성에 체크가 없는데 요일 아르바이트를 찾지 못함 → {shot}")

    # 태그가 붙은 카드의 '진행하기' = 태그보다 아래에 있는 첫 번째 버튼.
    # 새 카드('NEW')는 태그가 먼저 보이고 버튼이 늦게 그려진다 (2026-10-22 탭 누르고 2초 만에 못 찾음) → 몇 초 기다린다
    buttons = []
    for _ in range(6):
        buttons = [b for b in bot.find_all(c["go"], region=c["panel"]) if b.y > tag.y]
        if buttons:
            break
        bot.sleep(0.8, 1.0)
        tag = bot.find(c["tag"]) or tag  # 카드가 미끄러져 들어오면 태그 위치도 바뀐다
    if not buttons:
        raise RuntimeError("요일 아르바이트의 '진행하기' 버튼을 찾지 못함")
    bot.click(buttons[0])

    bot.step("travel", "요일 던전 입구로 이동")
    travel(bot, arrive=[c["dungeon_tab"]], timeout=c["travel_timeout"])
    result = enter_from_dungeon_window(bot, c["clear_timeout"], c["extra_loot"])
    return f"요일 던전 {result}"
