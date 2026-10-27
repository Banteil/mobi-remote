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

대사 넘기기·선택지 고르기·대화 마치기는 점검자(mabi.monitor — Ctx 의 choose · leave)가 한다. 루틴만의 창은
leave() 에 넘기는 처리기(handlers)로 끼워 넣는다 — 처리기가 먼저 자기 화면인지 보고 처리했으면 True. 예: 대장간의 수리 창 ESC.
"""
import time

from ..bot import Bot


def _packet(bot: Bot):
    """대화 상태를 믿을 수 있는 패킷 상태, 아니면 None (감시가 꺼졌거나 켠 뒤 맵을 옮긴 적이 없음)."""
    p = bot.packets
    return p.state if p.ok and (p.state.fresh or p.state.in_dialogue) else None


def in_dialog(bot: Bot, frame=None) -> bool:
    """NPC 와 대화 중인가 — 패킷(대화 대상)이 알면 그것, 모르면 화면: 왼쪽 위 '대화 기록' 또는 오른쪽 위 넘기기 버튼이
    대화 쪽(Bot.skip_button — CLI 대화 중 여부, 없으면 그림 점수)일 때.
    두 버튼은 반투명이라 뒤 배경이 밝으면 한쪽 템플릿이 안 맞는다 (2026-10-23 부자 NPC: 흰 건물 앞에서
    '대화 기록' 0.78 < 0.85 → 대화를 못 알아보고 멈춤). 둘 중 하나만 맞아도 대화로 본다.
    그림만 보던 때는 보스 출현 연출의 '장면 넘기기' 를 대화로 알아보고 눌렀다 (2026-10-25)."""
    s = _packet(bot)
    if s is not None:
        return s.in_dialogue
    frame = bot.frame() if frame is None else frame
    if bot.vision.find(frame, bot.cfg["arbeit"]["dialog_log"]):
        return True
    hit = bot.skip_button(frame)
    return bool(hit and hit[0] == "dialog")


def talking(bot: Bot) -> bool:
    """NPC 와 대화 중인가 (in_dialog)."""
    return in_dialog(bot)


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
    hit = bot.skip_button()
    return bool(hit and hit[0] == "dialog")


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


def line_ready(bot: Bot, frame=None) -> bool:
    """대사를 넘길 수 있게 대화 창이 떴나 — '대화 넘기기' 가 보이거나 (한마디 대사는 버튼이 없다) HUD 가 가려짐.
    패킷은 대화 창이 그려지기 전에 대화 중이라고 한다 — 그때 '대화 넘기기' 자리를 누르면 안 먹고, 그 자리의 미니맵이
    눌릴 수 있다 (사냥터를 나온 뒤 에반이 찾아왔을 때 넘기기 칸이 생기기 전에 눌러 진행이 안 됨 — 사용자 제보 2026-10-27)."""
    frame = bot.frame() if frame is None else frame
    hit = bot.skip_button(frame)
    if hit and hit[0] == "dialog":
        return True
    return not bot.vision.find(frame, bot.ui["main_hud"])


def next_line(bot: Bot, wait: bool = True, ready_within: float = 5) -> bool:
    """대사 하나 넘기기 — 대화 창이 뜨길 (ready_within 초까지) 기다렸다가 '대화 넘기기' 자리를 누른다.
    창이 안 뜨면 누르지 않고 False (부르는 쪽이 다음 차례에 다시 본다)."""
    end = time.monotonic() + ready_within
    while not line_ready(bot):
        if time.monotonic() > end:
            bot.log.debug("대화 창이 아직 안 떠 대사를 넘기지 않음")
            return False
        bot.sleep(0.3, 0.4)
    before = step(bot)
    bot.click(tuple(bot.cfg["arbeit"]["dialog_next_xy"]))
    if wait and wait_next(bot, before, 3) is None:
        bot.sleep(1.0, 1.4)
    return True


def leave(bot: Bot, handlers=(), timeout: float = 25) -> None:
    """NPC 대화에서 메인 화면으로. 차례마다 handlers(루틴이 연 창 닫기 등)를 먼저 묻고, 나머지는 점검자가 한다
    (Ctx leave — 메뉴면 ESC '대화 종료', 작별 인사 등 대사면 넘기기). 처리할 것이 없으면 to_main 에 맡긴다."""
    from .. import monitor
    mon = monitor.of(bot)
    ctx = monitor.Ctx(bot.task_id or "npc", "대화 마침", leave=True)
    end = time.monotonic() + timeout
    while not bot.at_main() and time.monotonic() < end:
        if any(h() for h in handlers):
            continue
        if not mon.check(ctx, guard=False).done:
            break
    bot.to_main()
