"""이동을 시작한 뒤 도착·정착까지 기다리기 — '진행하기' 뒤 이동(travel), 도착 화면(wait_arrival), 메인 화면까지(wait_settled),
NPC 에게 가서 대화 열기(go_talk)."""
import time
from typing import Callable

from ..bot import Bot
from ..exceptions import CannotProceed, StepTimeout


# 자동 이동이 끝난 뒤 도착 화면(던전 창 등)이 뜰 때까지 기다리는 상한 (초). 빠른 이동 뒤 걸어서 들어가는 시간까지 넉넉히
ARRIVE_GRACE = 45


def started(bot: Bot, arrive: list[str], within: float = 12) -> None:
    """'진행하기' 뒤 무엇이든 시작됐나 — 이동·로딩·대화거나 도착 화면이 보임. 엉뚱한 버튼·창을 눌렀으면 이동 상한(몇 분)까지
    기다리지 않고 StepTimeout (단계 다시 하기가 정리하고 한 번 더 한다). 패킷도 CLI 도 없으면 알 수 없어 그냥 둔다."""
    if not bot.packets.ok and not bot.state.available():
        return
    end = time.monotonic() + within
    while time.monotonic() < end:
        if bot.auto_traveling() or bot.map_loading() or bot.dialogue_playing() or any(bot.exists(n) for n in arrive):
            return
        bot.sleep(1, 1.3)
    from .. import monitor
    shot = bot.snapshot("travel_start").name
    monitor.of(bot).record(None, "동작", did="진행하기 → 이동", ok=False, why="이동이 시작되지 않음", shot=shot)
    raise StepTimeout(f"진행하기 뒤 {within:.0f}초 안에 이동이 시작되지 않음 → {shot}")


def travel(bot: Bot, arrive: list[str], timeout: float) -> None:
    """'진행하기' 등으로 시작된 자동 이동이 끝나 arrive 중 하나가 보일 때까지 대기.
    이동이 시작되면 한 번 빠른 이동(Bot.fast_travel)."""
    # 패킷: 자동 이동 시작이 오면 바로 (빠른 이동 가능 여부도 같이 온다). 모르면 예전처럼 2~3초 뒤 CLI 로
    moved = bot.wait_packet(lambda s: s.traveling, 5, since=bot.input_mark) is True  # 진행하기를 누른 뒤 이동이 시작됐나
    if moved:
        bot.sleep(0.5)
    else:
        bot.sleep(2, 3)
        started(bot, arrive)
    bot.fast_travel()
    # 이동이 끝났는데(패킷·CLI) 도착 화면이 한참 안 뜨면 엉뚱한 곳에 선 것 — 상한(timeout)까지 기다리지 않는다
    # (2026-10-26 요일 던전 입구에서 던전 창 없이 5분 서 있음)
    end = time.monotonic() + timeout
    stopped = None
    while True:
        try:
            return bot.wait_any(arrive, timeout=min(10, max(0, end - time.monotonic())), interval=1.0)
        except StepTimeout:
            if time.monotonic() >= end:
                raise
        if bot.auto_traveling() or bot.map_loading():
            moved, stopped = True, None
        elif moved:
            stopped = stopped or time.monotonic()
            if time.monotonic() - stopped > ARRIVE_GRACE:
                raise StepTimeout(f"이동이 끝났는데 {ARRIVE_GRACE}s 안에 {arrive} 중 아무것도 나타나지 않음")


def wait_settled(bot: Bot, timeout: float) -> bool:
    """로딩·자동 이동이 끝나 메인 화면이 보일 때까지. 보이면 True.
    로딩이 끝났는데(CLI 가 답함) 메인 화면이 아니면 막는 창을 넘긴다 — 판을 마치고 나가거나 캐릭터를 바꾸려는 순간
    퀘스트 완료 창이 뜨면 그대로 서 있었다 (2026-10-24 사용자). 어비스·레이드가 같이 쓴다."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if bot.map_loading():  # 패킷: 맵 로딩 중 — 끝나는 순간까지 화면은 안 본다
            bot.wait_loaded(end - time.monotonic())
            continue
        if not bot.auto_traveling() and bot.at_main():
            return True
        if not bot.is_loading():
            bot.clear_blockers(ocr=True)
        bot.sleep(2, 2.5)
    return False


def where_settled(bot: Bot, where: Callable[[], str]) -> str:
    """where() (콘텐츠마다 '지금 어디인가'), 단 'loading' 이면 끝날 때까지 다시 본다 (상한 timing.loading).
    어비스·레이드 반복이 시작·캐릭터 바꾸기 전에 쓴다."""
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while (at := where()) == "loading" and time.monotonic() < end:
        if not bot.wait_loaded(end - time.monotonic()):  # 패킷이 모르면 CLI 로 다시 본다
            bot.sleep(2, 2.5)
    return at


def wait_arrival(bot: Bot, visible: Callable[[], bool], timeout: float, shot: str, fail: str,
                 still: int = 0, retry_fast: bool = False, interval: tuple[float, float] = (2, 2.5)) -> bool:
    """'이동하기'·'바로 가기' 로 자동 이동을 시작한 뒤 도착 화면(visible — 입장 창·NPC 대화 등)이 뜰 때까지. 뜨면 True.
    로딩 동안은 화면을 보지 않는다. still 이 있으면 메인 화면에 멈춘(자동 이동 아님) 것을 still 번 연달아 보면 False —
    창 없이 멈춘 것이라 부르는 쪽이 메뉴에서 다시 연다 (걷는 중이거나 창이 떠 있으면 셈을 다시 — 막 뜬 창을 닫지 않게
    ESC 는 누르지 않는다). retry_fast 면 늦게 시작한 자동 이동에 빠른 이동(T)을 한 번 될 때까지 해 본다.
    timeout(초, 각자 설정의 travel_timeout 등) 안에 못 닿으면 CannotProceed(fail → 스크린샷 shot).
    어비스·레이드 입구, 나이트메어 드릴, 뱅가드 브리치, 필드 보스, NPC 대화(go_talk)가 같이 쓴다."""
    end = time.monotonic() + timeout
    stopped, fast = 0, False
    while time.monotonic() < end:
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if visible():
            return True
        if still:
            if bot.at_main() and not bot.auto_traveling():
                stopped += 1
                if stopped >= still:
                    return False
            else:
                stopped = 0
        elif retry_fast and not fast:
            fast = bot.fast_travel()
        bot.sleep(*interval)
    raise CannotProceed(f"{fail} → {bot.snapshot(shot).name}")


def npc_moving(bot: Bot) -> bool | None:
    """NPC 에게 가는 버튼을 누른 뒤 움직이기 시작했나 (패킷: 자동 이동 · NPC 에게 다가가는 AI · 대화 시작 · 맵 이동). 모르면 None."""
    if not bot.packets.ok:
        return None
    return bot.wait_packet(lambda s: s.traveling or s.loading or bool(s.ai) or s.in_dialogue, 5, since=bot.input_mark)


def go_talk(bot: Bot, start: Callable[[], None], what: str, shot: str, timeout: float) -> None:
    """start() 로 NPC 에게 가는 이동을 시작하고, 도착해 그 NPC 대화가 열릴 때까지 (도착하면 대화가 저절로 열린다).
    timeout: 도착 상한 (초, 부르는 쪽 설정).
    눌렀는데 패킷으로 움직임이 없으면 한 번 더 start(). 이동 중 빠른 이동이 되면 T.
    대장간 수리(퀵 내비게이터 '대장간') · 어비스 주간 전리품(관청 에반) 이 같이 쓴다."""
    from .dialogue import talking
    for _ in range(2):
        start()
        if npc_moving(bot) is not False:
            break
        bot.log.info(f"'{what}' 을 눌렀는데 움직이지 않음 (패킷) → 다시")
    else:
        raise CannotProceed(f"'{what}' 을 눌러도 움직이지 않음 → {bot.snapshot(shot).name}")
    bot.log.info(f"{what} 으로 이동")
    # 도착해 대화가 열리면 끝 — 메뉴는 인사말을 넘긴 뒤에 뜬다
    wait_arrival(bot, lambda: talking(bot), timeout, shot + "_npc",
                 f"{what} NPC 대화가 열리지 않음", retry_fast=True, interval=(1.5, 2))
