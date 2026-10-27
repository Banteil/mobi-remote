"""무작위 이벤트 — 어느 태스크든, 언제든 끼어드는 것을 콜백처럼 처리한다.

NPC 가 갑자기 말을 거는 것(주간 목표 첫 달성 뒤 에반 등)·출석처럼 '이 일 뒤에 뜰 수도 안 뜰 수도' 있는 것을 태스크마다
'여기서 볼까' 하며 끼워 넣던 것을 한곳으로 (사용자 2026-10-27). 패킷이 신호를 주면 Bot 기본 동작(check_stop —
sleep·frame·wait_packet 이 늘 거친다)이 하던 일을 잠깐 멈추고 점검자로 넘긴 뒤 돌아간다. 별도 스레드가 직접 누르지
않는다 — 태스크의 입력과 섞이면 엉뚱한 곳이 눌린다.

여기에 드는 것은 태스크가 열지 않은 것뿐이다. NPC 대화를 스스로 다루는 일(접속·아르바이트·요일 던전 게시판·수리)은
Bot.npc_talk() 로 '내 몫' 이라고 알리고, 그동안 대화는 끼어들기로 보지 않는다. 메뉴(선택지)가 있는 대화는 늘 태스크 몫.
패킷이 없으면 아무것도 하지 않는다 (예전처럼 태스크가 부르는 점검자가 본다).
"""
import time

# 끼어들기 하나를 붙잡고 있는 상한 (초). 넘기지 못하면 손을 떼고 한동안 같은 신호를 보지 않는다 —
# 패킷 상태가 끝 신호를 놓쳐 '대화 중' 으로 남아도 태스크를 막지 않게
HOLD = 25
COOLDOWN = 30
# 대화가 막 열리는 중(HUD 가 남음)이면 넘기지 않고 기다린다 — 그동안 아무것도 못 하는 상한
IDLE = 6


def pending(bot) -> str | None:
    """지금 처리할 무작위 이벤트 (패킷). 'attendance' · 'dialog' · None."""
    p = bot.packets
    if not p.ok:
        return None
    s = p.state
    if s.attending():
        return "attendance"
    if s.in_dialogue and not s.dialogue_menu and not bot.npc_owned():
        return "dialog"
    return None


def handle(bot, what: str) -> bool:
    """하던 일을 멈추고 what 을 넘긴다. 넘겼으면 True. 점검자가 화면을 보고 처리한다 (출석 — 대사 넘기다 건너뛰기,
    대화 — 대사 넘기기, 이어 뜨는 퀘스트 클리어 '확인' 도). 못 넘기면 COOLDOWN 동안 같은 신호를 보지 않는다."""
    from . import Ctx, of
    mon = of(bot)
    ctx = Ctx(bot.task_id or "interrupt", f"끼어들기 ({what})", revive=False)
    label = {"attendance": "출석", "dialog": "NPC 대화"}.get(what, what)
    bot.log.info(f"끼어들기: {label} → 하던 일 잠깐 멈춤")
    t0 = time.monotonic()
    last_done = t0
    done = False
    while pending(bot) == what:
        now = time.monotonic()
        if now - t0 > HOLD or now - last_done > IDLE:
            bot.log.warning(f"끼어들기: {label} 을 넘기지 못함 → {COOLDOWN}초 동안 두고 하던 일로 ({bot.snapshot('interrupt').name})")
            bot.interrupt_cooldown(what, COOLDOWN)
            return done
        seen = mon.check(ctx, guard=False)
        if seen.done:
            last_done, done = time.monotonic(), True
        bot.sleep(0.6, 0.9)
    # 대화 뒤 이어 뜨는 '퀘스트 클리어!!' 확인 — 패킷 신호가 없어 화면으로 몇 번 더 본다
    for _ in range(3):
        bot.sleep(0.8, 1.0)
        if not mon.check(ctx, guard=False).done:
            break
    bot.log.info(f"끼어들기: {label} 넘김 ({time.monotonic() - t0:.0f}s) → 하던 일로")
    return True
