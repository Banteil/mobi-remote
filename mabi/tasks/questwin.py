"""퀘스트 창(J) — 탭 줄에 걸치지 않은 버튼 고르기, 아르바이트 탭 열기."""
from .. import gamedata as gd, keys
from ..bot import Bot
from ..exceptions import StepTimeout


# 퀘스트 창(J) 아래 탭 줄(지도·퀘스트·아르바이트·이벤트) 윗선 (1920 기준). 카드 버튼이 이 줄에 반쯤 걸쳐 보일 때
# 그 자리를 누르면 버튼 대신 탭('이벤트')이 눌린다 — 공물 던전(2026-10-24 16:48)·알바(17:42, 18:10)에서 따로 터졌다.
# 퀘스트 창의 버튼은 모두 questwin_buttons / questwin_text_ok 로 걸러서 누른다 (안 보이면 목록을 내려서 다시)
QUESTWIN_TAB_BAR_Y = 950


def questwin_buttons(bot: Bot, name: str, region=None) -> list:
    """퀘스트 창에서 템플릿 name 버튼 중 탭 줄에 걸치지 않고 다 보이는 것 (위에서부터)."""
    return sorted((b for b in bot.find_all(name, region=region) if b.y + b.h <= QUESTWIN_TAB_BAR_Y), key=lambda b: b.y)


def questwin_text_ok(y: int) -> bool:
    """OCR 로 찾은 버튼 글자(가운데 y)가 탭 줄에 걸치지 않았나 (버튼 높이 약 60)."""
    return y <= QUESTWIN_TAB_BAR_Y - 30


def open_arbeit_tab(bot: Bot) -> None:
    """퀘스트 창(J)을 열고 아르바이트 탭으로."""
    ui = bot.ui
    bot.to_main()
    bot.hover_off()  # 지난번에 누른 탭 위에 커서가 남아 있으면 탭 그림이 커져 안 맞는다
    bot.key(keys.of(bot, "quest"))
    try:
        bot.click(ui["questwin_tab_arbeit"], timeout=5)
    except StepTimeout:
        # 퀘스트 탭 목록이 길면 맨 아래 카드의 '진행하기' 버튼이 탭 아이콘 위에 겹쳐 그림이 안 맞는다
        # (2026-10-22 '함께하는 대모험' 카드) → 탭 글자 '아르바이트' 를 읽어 확인하고 탭 자리를 누른다
        from ..ocr import find_texts
        hit = next(((tx, ty) for t, tx, ty in find_texts(bot.frame(), gd.region("arbeit_tab")) if gd.text("arbeit_tab") in t), None)
        if not hit:
            raise StepTimeout(f"퀘스트 창의 아르바이트 탭을 찾지 못함 → {bot.snapshot('questwin').name}")
        bot.log.debug(f"아르바이트 탭 그림이 가려짐 → 탭 글자 {hit} 를 누름")
        bot.click(hit)  # 아이콘 쪽은 겹친 '진행하기' 버튼이라 글자를 누른다
    bot.sleep(1, 1.5)
