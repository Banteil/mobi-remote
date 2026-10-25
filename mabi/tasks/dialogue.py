"""NPC 대화 공통 처리 — 아르바이트·요일 던전 게시판·대장간 수리 등 NPC 와 말하는 일이 함께 쓴다.

대화 화면은 왼쪽 위 '대화 기록', 대사가 이어질 때는 오른쪽 위 '대화 넘기기' 가 뜬다.
대사는 몇 마디일지(한마디·두마디) 그때그때 달라서, 대화 중이면 '대화 넘기기' 자리를 계속 누른다 — 버튼이 없는
한마디 대사도 그 자리를 누르면 넘어간다 (arbeit.dialog_next_xy). 메뉴 버튼이 떠 있는 동안은 ESC 가 '대화 종료' 이고,
그 뒤 NPC 의 작별 인사("안녕히 가세요")는 ESC 로 안 넘어가서 눌러야 끝난다 (2026-10-25 대장간).

패킷이 있으면 대사 단계를 화면보다 정확히 안다 (packet_monitor.PacketState):
  dialogue_action  이 대사 뒤 할 일 — SelectKeyword(메뉴 버튼) · EndDialogue(작별 인사) · OpenNPCRepair(수리 창) …
                   (로그·참고용. NPC 마다 대사 구성이 달라 흐름 판단은 메뉴·단계로 한다)
  dialogue_menu    메뉴(선택지 버튼)가 떠 있음
  dialogue_step    대사마다 1씩 오름 — 눌러서 넘어갔는지, 버튼을 눌러도 아무 일이 없었는지(예: 고칠 장비가 없어 꺼진 '수리')
패킷이 없으면 화면(대화 기록·대화 넘기기 템플릿)으로 본다.

루틴마다 다른 조작은 talk()/leave() 에 넘기는 처리기(handlers)로 끼워 넣는다 — 처리기가 먼저 자기 화면인지 보고
처리했으면 True, 아니면 공통 처리(대사 넘기기)로 간다. 예: 아르바이트의 '결과 보고' Space, 대장간의 수리 창 ESC.
"""
import time

from ..bot import Bot


def _packet(bot: Bot):
    """대화 상태를 믿을 수 있는 패킷 상태, 아니면 None (감시가 꺼졌거나 켠 뒤 맵을 옮긴 적이 없음)."""
    p = bot.packets
    return p.state if p.ok and (p.state.fresh or p.state.in_dialogue) else None


def in_dialog(bot: Bot, frame=None) -> bool:
    """NPC 대화 화면인가: 왼쪽 위 '대화 기록' 또는 오른쪽 위 '대화 넘기기'.
    두 버튼은 반투명이라 뒤 배경이 밝으면 한쪽 템플릿이 안 맞는다 (2026-10-23 부자 NPC: 흰 건물 앞에서
    '대화 기록' 0.78 < 0.85 → 대화를 못 알아보고 멈춤). 둘 중 하나만 맞아도 대화로 본다."""
    frame = bot.frame() if frame is None else frame
    return any(bot.vision.find(frame, n) for n in (bot.cfg["arbeit"]["dialog_log"], bot.ui["dialog_skip"]))


def talking(bot: Bot) -> bool:
    """NPC 와 대화 중인가 — 패킷이 알면 그것, 모르면 화면."""
    s = _packet(bot)
    return s.in_dialogue if s is not None else in_dialog(bot)


def action(bot: Bot) -> str | None:
    """지금 대사 뒤 할 일 (패킷). 대화가 아니면 '', 모르면 None."""
    s = _packet(bot)
    return s.dialogue_action if s is not None else None


def menu_open(bot: Bot) -> bool | None:
    """NPC 메뉴(선택지 버튼)가 떠 있나 (패킷). 모르면 None."""
    s = _packet(bot)
    return s.dialogue_menu if s is not None else None


def lines_left(bot: Bot) -> bool:
    """오른쪽 위 '대화 넘기기' 가 보이나 — 아직 넘길 대사가 있다. 패킷은 첫 대사와 같은 순간에 '메뉴' 를 알려 주지만
    화면의 메뉴 버튼은 대사를 넘긴 뒤에야 뜬다 (2026-10-25 대장간 도착 인사) → 메뉴가 보이는지는 이것과 같이 본다."""
    name = bot.ui.get("dialog_skip")
    return bool(name and bot.vision.has(name) and bot.exists(name))


def menu_shown(bot: Bot) -> bool | None:
    """메뉴 버튼이 화면에 떠 있나 = 패킷의 메뉴 + 넘길 대사 없음. 패킷을 모르면 None."""
    m = menu_open(bot)
    return None if m is None else m and not lines_left(bot)


def step(bot: Bot) -> int | None:
    s = _packet(bot)
    return s.dialogue_step if s is not None else None


def wait_next(bot: Bot, since: int | None, timeout: float = 4) -> bool | None:
    """대사가 since 다음으로 넘어가거나 대화가 끝날 때까지 (패킷). True 넘어감 / False 그대로 / None 모름."""
    if since is None:
        return None
    return bot.wait_packet(lambda s: s.dialogue_step != since or not s.in_dialogue, timeout)


def next_line(bot: Bot, wait: bool = True) -> None:
    """대사 하나 넘기기 — '대화 넘기기' 자리를 누른다."""
    before = step(bot)
    bot.click(tuple(bot.cfg["arbeit"]["dialog_next_xy"]))
    if wait and wait_next(bot, before, 3) is None:
        bot.sleep(1.0, 1.4)


def skip_lines(bot: Bot, max_n: int = 10) -> int:
    """대화가 끝날 때까지(또는 max_n 마디) 대사를 넘긴다. 넘긴 수."""
    n = 0
    while n < max_n and talking(bot):
        next_line(bot)
        n += 1
    return n


def _run_handlers(handlers) -> bool:
    return any(h() for h in handlers)


def talk(bot: Bot, until, handlers=(), timeout: float = 30) -> bool:
    """until() 이 참이 될 때까지 대화를 진행한다. 차례마다 handlers(루틴만의 조작)를 먼저 묻고, 아무도 처리하지 않았으면
    대사일 때 넘기기 자리를 누른다. 메뉴가 떠 있으면 누르지 않고 기다린다 (메뉴에서 고르는 건 부르는 쪽 일).
    시간 안에 됐으면 True."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if until():
            return True
        if _run_handlers(handlers):
            continue
        if talking(bot) and not menu_shown(bot):
            next_line(bot)
        else:
            bot.sleep(0.8, 1.2)
    return until()


def wait_menu(bot: Bot, shown, timeout: float = 20) -> bool:
    """NPC 에게 말을 건 뒤 메뉴 버튼이 보일 때까지 대사를 넘긴다. shown() 은 그 메뉴의 버튼이 화면에 보이는지
    (루틴이 정한다 — 예: 대장간 '수리' 글자). 대사가 몇 마디든 넘기기 자리를 계속 누른다."""
    return talk(bot, shown, timeout=timeout)


def leave(bot: Bot, handlers=(), timeout: float = 25) -> None:
    """NPC 대화에서 메인 화면으로. 차례마다 handlers(루틴이 연 창 닫기 등)를 먼저 묻고, 메뉴면 ESC('대화 종료'),
    대사(작별 인사 등)면 넘기기 자리를 누른다. 대화가 아닌 화면이 남으면 to_main 에 맡긴다."""
    end = time.monotonic() + timeout
    while not bot.at_main() and time.monotonic() < end:
        if _run_handlers(handlers):
            continue
        menu = menu_shown(bot)
        if menu:
            before = step(bot)
            bot.key("esc")
            if wait_next(bot, before, 3) is None:
                bot.sleep(1.2, 1.6)
        elif talking(bot):
            next_line(bot)
        else:
            break
    bot.to_main()
