"""'/' 콘텐츠 가이드 — 열기, 일일·주간 달성(체크·글자 색), CLI 성장 가이드, 카드의 '바로 가기'."""
from typing import NamedTuple

from .. import keys
from ..bot import Bot
from ..exceptions import CannotProceed, StepTimeout
from ..vision import green, green_ratio
from .steps import list_views


def open_guide(bot: Bot) -> None:
    """'/' 콘텐츠 가이드를 연다. 지역 이동 직후 등에는 키가 무시되기도 해서 몇 번 다시 누른다."""
    for _ in range(3):
        bot.to_main()
        bot.key(keys.of(bot, "guide"))
        try:
            bot.wait(bot.ui["guide_title"], timeout=6)
            bot.sleep(1, 1.5)
            return
        except StepTimeout:
            bot.log.debug("콘텐츠 가이드가 열리지 않아 다시 누름")
            bot.sleep(2, 3)
    raise CannotProceed(f"콘텐츠 가이드(/)가 열리지 않음 → {bot.snapshot('guide').name}")


def achieved_mark(bot: Bot, label: str) -> bool:
    """(가이드가 열린 채로) 왼쪽 위 '일일 달성'에서 label(콘텐츠 이름 템플릿) 아이콘에 초록 체크가 있는지.
    체크는 이름 글자 왼쪽 아래(아이콘 오른쪽 아래 모서리)에 붙는다."""
    g = bot.cfg["guide"]
    m = bot.find(label, region=g["daily_panel"])
    if not m:
        bot.to_main()
        raise CannotProceed(f"콘텐츠 가이드 일일 달성에 '{label}' 이 없음 → {bot.snapshot('guide').name}")
    dx, dy = g["check_offset"]
    x, y = m.x + dx, m.y + dy
    return green_ratio(bot.frame()[y - 5:y + 5, x - 5:x + 5]) > 0.3


# 일일 달성 아이콘(템플릿) → CLI get_growth_guide 의 Target
GROWTH = {"guide_daily_weekday": "요일 던전", "guide_daily_blackhole": "검은 구멍"}


def growth_done(bot: Bot, target: str | None, day: str = "Daily") -> bool | None:
    """CLI get_growth_guide (11-05 패치에 생김) 로 그 콘텐츠를 이번 기간(Daily·Weekly)에 끝냈나.
    게임 성장 가이드와 같은 값이라 가이드 창을 열어 체크 아이콘을 보지 않아도 된다. 모르면 None (화면으로 본다).
    검은 구멍 일일은 이월된 주간 횟수 때문에 IsCompleted 뒤에도 RemainingCount 가 남을 수 있다 — 끝남은 IsCompleted."""
    if not target or not bot.state.available():
        return None
    data = bot.state.query("get_growth_guide", timeout=10)
    rows = data.get("Contents") if isinstance(data, dict) else None
    row = next((r for r in rows or [] if r.get("Target") == target and r.get("DayType") == day), None)
    if not row or not row.get("IsUnlocked") or "IsCompleted" not in row:
        return None
    bot.log.debug(f"CLI 성장 가이드: {target} ({day}) {'끝남' if row['IsCompleted'] else '남음'}"
                  + (f" · 남은 {row['RemainingCount']}" if "RemainingCount" in row else ""))
    return bool(row["IsCompleted"])


def daily_achieved(bot: Bot, label: str) -> bool:
    """오늘 끝냈나 — CLI 성장 가이드가 알면 그것, 모르면 '/' 콘텐츠 가이드를 열어 일일 달성 체크를 본다 (achieved_mark)."""
    done = growth_done(bot, GROWTH.get(label))
    if done is not None:
        return done
    open_guide(bot)
    done = achieved_mark(bot, label)
    bot.to_main()
    return done


def guide_tab(bot: Bot, weekly: bool = False) -> None:
    """(가이드가 열린 채로) '일일 콘텐츠' · '주간 콘텐츠' 탭을 누른다. 가이드는 마지막에 본 탭으로 열리는데, 주간 콘텐츠 탭에도
    같은 제목의 카드(검은 구멍)가 있어 일일 것을 다 한 날에도 주간 카드의 바로 가기를 눌렀다 (2026-11-02)."""
    from .. import gamedata as gd
    from . import ui_text
    name = "주간 콘텐츠" if weekly else "일일 콘텐츠"
    hit = ui_text.find(bot, gd.text("guide_weekly_tab" if weekly else "guide_daily_tab"), gd.region("guide_tabs"), exact=False)
    if not hit:
        bot.to_main()
        raise CannotProceed(f"콘텐츠 가이드의 '{name}' 탭을 찾지 못함 → {bot.snapshot('guide').name}")
    bot.click(hit)
    bot.sleep(0.8, 1.2)


GUIDE_CARD_W = 650   # 콘텐츠 가이드 카드 폭 — 같은 카드의 '바로 가기' 는 제목 아래 이 폭 안
GUIDE_SCROLL = 3     # 가이드 카드 목록을 한 번에 내리는 휠 칸 수
GUIDE_SCROLLS = 8    # 최대 몇 번 내려가며 볼지 (카드는 2열, 주간 콘텐츠가 다 남으면 3줄)


def open_guide_card(bot: Bot, card: str, opened: bool = False, weekly: bool = False, text: bool = False) -> bool:
    """'/' 콘텐츠 가이드의 일일(weekly 면 주간) 콘텐츠에서 card 카드의 '바로 가기'를 누른다. card 는 카드 제목 템플릿,
    text 면 제목 글자 (카드 칸 guide_cards 에서 OCR — 위 '주간 달성' 칸의 같은 이름과 섞이지 않게).
    끝낸 콘텐츠는 카드가 사라지므로 카드가 없으면 False (= 이미 완료). opened: 가이드가 이미 열려 있다.
    카드는 아직 안 끝낸 것만 2열로 놓여, 남은 게 많으면 뒤쪽 카드(뱅가드 브리치 등)는 아래로 내려야 보인다 — 글자로 찾을 때는
    목록을 내려가며 찾는다 (2026-11-09: 주간 콘텐츠가 다 남은 캐릭터는 뱅가드 브리치가 6번째 카드라 첫 화면에 없었다)."""
    from .. import gamedata as gd
    from . import ui_text
    ui = bot.ui
    if not opened:
        open_guide(bot)
    guide_tab(bot, weekly)

    def go_of(title):  # 같은 카드의 '바로 가기' = 제목보다 아래, 카드 폭 안에 있는 버튼
        return [b for b in bot.find_all(ui["guide_go"]) if b.y > title.y and 0 <= b.x - title.x < GUIDE_CARD_W]

    if text:
        area = gd.region("guide_cards")
        at = (area[0] + area[2] // 2, area[1] + area[3] // 2)
        for _ in list_views(bot, area, at, GUIDE_SCROLL, GUIDE_SCROLLS):
            hit = ui_text.find(bot, card, area, exact=False)
            go = go_of(type("Title", (), {"x": hit[0], "y": hit[1]})) if hit else []
            if go:  # 제목만 보이고 버튼이 아래로 잘렸으면 더 내려서
                bot.click(go[0])
                return True
        bot.to_main()
        return False
    title = bot.find(card)
    if not title:
        bot.to_main()
        return False
    go = go_of(title)
    if not go:
        raise RuntimeError(f"콘텐츠 가이드 '{card}' 카드의 바로 가기를 찾지 못함")
    bot.click(go[0])
    return True


# 위쪽 '일일 달성'·'주간 달성' 칸의 글자: 안 끝낸 것은 하얀 글자, 끝낸 것은 회색 글자 + 아이콘 모서리 초록 체크 (사용자).
# 2026-11-09 두 화면에서 잼 — 글자 가운데 밝기(95% 값) 하양 254~255 · 회색 91~106, 글자 왼쪽 초록 화소 끝냄 147~157 · 안 끝냄 0~15
GOAL_WHITE = 180
GOAL_CHECK = 60


class Goal(NamedTuple):
    x: int
    y: int
    done: bool | None  # 끝냈나 — 글자 색과 체크가 어긋나면 None (모름)


def guide_goal(bot: Bot, name: str, weekly: bool = False) -> Goal | None:
    """(가이드가 열린 채로) 위쪽 일일(weekly 면 주간) 달성 칸에서 name 글자를 찾는다. 없으면 None."""
    import numpy as np
    from . import ui_text
    g = bot.cfg["guide"]
    hit = ui_text.find(bot, name, g["weekly_panel" if weekly else "daily_panel"], exact=False)
    if not hit:
        return None
    x, y = hit
    frame = bot.frame()
    white = np.percentile(frame[y - 10:y + 10, x - 30:x + 30].mean(axis=2), 95) >= GOAL_WHITE
    # 글자 왼쪽 = 아이콘과 그 오른쪽 아래 체크
    check = int(green(frame[y - 5:y + 25, max(0, x - 140):x]).sum()) >= GOAL_CHECK
    return Goal(x, y, None if white == check else check)


def go_from_guide(bot: Bot, name: str, weekly: bool = False, card: str | None = None, text: bool = False) -> bool:
    """'/' 콘텐츠 가이드에서 name 콘텐츠로 간다 ('바로 가기'). 끝낸 콘텐츠라 갈 게 없으면 False.
    위쪽 달성 칸의 하얀 글자를 누르면 카드의 '바로 가기' 와 같다 (사용자) — 카드가 아래로 밀려 안 보여도 되므로 그게 먼저.
    글자가 안 보이거나 색과 체크가 어긋나거나 눌러도 가이드가 그대로면 아래 카드로 (card: 제목 템플릿, text 면 제목 글자)."""
    open_guide(bot)
    goal = guide_goal(bot, name, weekly)
    if goal and goal.done:
        bot.log.info(f"콘텐츠 가이드 {'주간' if weekly else '일일'} 달성: '{name}' 끝냄 (회색 글자 + 체크)")
        bot.to_main()
        return False
    if goal and goal.done is False:
        bot.click((goal.x, goal.y))
        bot.sleep(1.5, 2)
        if not bot.exists(bot.ui["guide_title"]):
            return True
        bot.log.info(f"콘텐츠 가이드 달성 칸 '{name}' 을 눌러도 가이드가 그대로 → 아래 카드로")
    elif not goal:
        bot.log.info(f"콘텐츠 가이드 달성 칸에서 '{name}' 을 못 읽음 → 아래 카드로")
    return open_guide_card(bot, card or name, opened=True, weekly=weekly, text=text)
