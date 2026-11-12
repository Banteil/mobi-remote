"""화면 글자(OCR)로 찾고 누르기 — 여러 작업이 같이 쓴다 (어비스 입장 화면, 대장간 수리 등).

글자는 띄어쓰기를 빼고 비교한다. region 은 [x, y, 너비, 높이] (1920x1080 기준) — 보통 gamedata.region(키).
"""
import time

from .. import gamedata as gd
from ..bot import Bot
from ..ocr import find_texts, nospace as norm
from ..exceptions import CannotProceed


def match(items, want: str, exact: bool = True):
    """이미 읽은 글자들(find_texts 결과 [(글자, x, y)])에서 want 를 찾는다 → (글자, x, y), 없으면 None.
    exact=False 면 want 가 들어 있기만 해도. 한 번 읽은 화면에서 여러 번 찾을 때 (화면 설정 display 등)."""
    w = norm(want)
    for t, x, y in items:
        n = norm(t)
        if n == w if exact else w in n:
            return t, x, y
    return None


def find(bot: Bot, want: str, region=None, exact: bool = True):
    """want 글자의 가운데 (x, y), 없으면 None. exact=False 면 want 가 들어 있기만 해도."""
    hit = match(find_texts(bot.frame(), region), want, exact)
    return hit[1:] if hit else None


def wait(bot: Bot, want: str, region=None, timeout: float = 5, exact: bool = True):
    """want 글자가 보일 때까지 (최대 timeout 초). 자리, 못 찾으면 None."""
    end = time.monotonic() + timeout
    while True:
        hit = find(bot, want, region, exact)
        if hit or time.monotonic() > end:
            return hit
        bot.sleep(0.8, 1.2)


def click(bot: Bot, want: str, region=None, exact: bool = True, what: str = "", tries: int = 4,
          shot: str = "text", key: str | None = None) -> None:
    """want 글자를 찾아 누른다. tries 번 봐도 없으면 CannotProceed (스크린샷 shot).
    key: 버튼에 단축키가 붙어 있으면 글자로 있는 것만 확인하고 클릭 대신 그 키 (사용자 2026-10-28)."""
    for _ in range(tries):
        hit = find(bot, want, region, exact)
        if hit:
            if key:
                bot.key(key)
            else:
                bot.click(hit)
            bot.sleep(1.2, 1.6)
            return
        bot.sleep(1.0, 1.4)
    raise CannotProceed(f"'{what or want}' 를 화면에서 찾지 못함 → {bot.snapshot(shot).name}")


def open_menu(bot: Bot, text_key: str, what: str, shot: str, menu_open: bool = False) -> None:
    """메인 화면 → 메뉴(ESC) → 오른쪽 메뉴 칸의 text_key 항목(어비스·레이드·나이트메어 드릴·필드 보스)을 누른다.
    ESC 뒤 항목이 안 보이면 ESC 를 먹은 창(메인 HUD 가 보이는 채로 뜬 퀘스트 완료 창 등)을 넘기고 3번까지 다시.
    menu_open 이면 이미 열린 메뉴에서 바로 누른다. 끝내 못 누르면 CannotProceed (스크린샷 shot)."""
    want, region = gd.text(text_key), gd.region("menu_right")
    for _ in range(0 if menu_open else 3):
        bot.to_main()
        bot.key("esc")
        bot.sleep(1.5, 1.8)
        if find(bot, want, region):
            break
        bot.clear_blockers(ocr=True)
    click(bot, want, region, what=what, shot=shot)
