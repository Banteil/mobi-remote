"""화면 글자(OCR)로 찾고 누르기 — 여러 작업이 같이 쓴다 (어비스 입장 화면, 대장간 수리 등).

글자는 띄어쓰기를 빼고 비교한다. region 은 [x, y, 너비, 높이] (1920x1080 기준) — 보통 gamedata.region(키).
"""
import time

from ..bot import Bot
from ..ocr import find_texts, nospace as norm
from .content import CannotProceed


def find(bot: Bot, want: str, region=None, exact: bool = True):
    """want 글자의 가운데 (x, y), 없으면 None. exact=False 면 want 가 들어 있기만 해도."""
    w = norm(want)
    for t, x, y in find_texts(bot.frame(), region):
        n = norm(t)
        if n == w if exact else w in n:
            return x, y
    return None


def wait(bot: Bot, want: str, region=None, timeout: float = 5, exact: bool = True):
    """want 글자가 보일 때까지 (최대 timeout 초). 자리, 못 찾으면 None."""
    end = time.monotonic() + timeout
    while True:
        hit = find(bot, want, region, exact)
        if hit or time.monotonic() > end:
            return hit
        bot.sleep(0.8, 1.2)


def click(bot: Bot, want: str, region=None, exact: bool = True, what: str = "", tries: int = 4,
          shot: str = "text") -> None:
    """want 글자를 찾아 누른다. tries 번 봐도 없으면 CannotProceed (스크린샷 shot)."""
    for _ in range(tries):
        hit = find(bot, want, region, exact)
        if hit:
            bot.click(hit)
            bot.sleep(1.2, 1.6)
            return
        bot.sleep(1.0, 1.4)
    raise CannotProceed(f"'{what or want}' 를 화면에서 찾지 못함 → {bot.snapshot(shot).name}")
