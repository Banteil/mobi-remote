"""단계 공용 도우미 — 막히면 다시 하기, 조건까지 기다리기, 스크롤 목록 한 화면씩."""
import time
from typing import Callable

from ..bot import Bot
from ..exceptions import StepTimeout


# 퀘스트 창 → 진행하기 → 이동 단계가 막히면 처음부터 다시 해 보는 횟수. 입구에 사람이 몰려 창이 안 뜨거나
# 창이 지난 스크롤 자리로 열리는 등 한 번 더 하면 되는 일이 많다 (2026-10-26)
STEP_RETRIES = 2


def with_retries(bot: Bot, what: str, fn: Callable, retries: int = STEP_RETRIES):
    """fn() 을 하고, 막히면(StepTimeout·RuntimeError) 메인 화면으로 돌아가 retries 번까지 다시 한다."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except (StepTimeout, RuntimeError) as e:
            if attempt == retries:
                raise
            bot.log.warning(f"{what} 막힘 → 다시 시도 ({attempt + 1}/{retries}): {e}")
            bot.to_main()


def list_views(bot: Bot, area, at, step: int, steps: int):
    """스크롤 목록을 맨 위부터 조금씩 내려가며 한 화면씩 넘겨준다 (yield 때마다 지금 화면을 본다). 더 내려가지 않으면 (맨 아래) 끝.
    한 번에 많이 내리면 가운데 줄을 건너뛴다 (2026-10-25, 미션 선물 7개를 못 보고 넘어감).
    area: 목록 영역 [x, y, 너비, 높이] (스크롤해도 안 바뀌면 맨 아래), at: 휠을 굴릴 자리, step: 한 번에 내리는 휠 칸 수."""
    def scroll(notches):
        bot.scroll(*at, notches)
        bot.sleep(0.8, 1.0)
    x, y, w, h = area
    scroll(15)
    before = None
    for _ in range(steps):
        yield
        now = bot.frame()[y:y + h, x:x + w].astype("int16")
        if before is not None and abs(now - before).mean() < 2:
            return
        before = now
        scroll(-step)


def wait_until(bot: Bot, pred: Callable[[], bool], timeout: float, interval: float = 3.0, what: str = "") -> None:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise StepTimeout(f"{timeout:.0f}s 안에 {what or '조건'} 충족 안 됨")
        bot.sleep(interval)
