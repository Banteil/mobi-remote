"""클리어 뒤 — 클리어 순간 기록, 연출 넘기기, 보상 메뉴(추가 루팅·다시 하기·나가기), 막는 화면 넘기기, '확인'·'화면 터치' 글자."""
import time

from .. import gamedata as gd
from ..bot import Bot
from ..exceptions import StepTimeout
from .space import dungeon_state
from .ui_text import has_word


# 클리어 한 번이면 그날 숙제가 끝나는 것 (공물은 고난도 퀘스트가 하루 한 번 — 남은 공물로 더 도는 건 덤)
CLEAR_DONE = {"weekday_dungeon", "tribute"}


def cleared_now(bot: Bot, what: str) -> None:
    """클리어 신호(던전 Cleared·사냥터 끝남)가 온 순간. 보상 화면 정리(다시 하기·나가기)를 기다리지 않고
    여기서 클리어로 친다 — 정리 도중 끊겨도 그 판은 깬 것으로 남는다 (2026-11-06 사용자)."""
    bot.log.info(f"{what} 클리어")
    if bot.task_id in CLEAR_DONE:
        bot.done_at_clear = True
    if bot.on_clear:
        bot.on_clear()


def touch_prompt_visible(bot: Bot, frame=None) -> bool:
    """'화면을 터치해 주세요' 글자가 보이나 (OCR, 느리다). frame 이 없으면 지금 화면을 찍는다. 점검자(detect.look)도 쓴다."""
    from ..ocr import read_ko, read_text
    frame = bot.frame() if frame is None else frame
    r = bot.cfg["dungeon"]["touch_text_region"]
    return has_word(gd.text("clear_touch"), read_ko(frame, r), read_text(frame, r, white=220))


def clear_blockers(bot: Bot, skip=(), ocr: bool = False) -> str | None:
    """다른 조작을 막는 화면을 하나 넘긴다 — 대화(대화 넘기기), 연출(장면 넘기기), 퀘스트 클리어 등의 초록 '확인',
    '화면을 터치해 주세요', 출석 대사, 작별 대사. 넘긴 것의 이름, 없으면 None. skip 에 든 템플릿은 건드리지 않는다 (지금 기다리는 것).
    숙제·어비스처럼 오래 혼자 도는 동안 언제든 끼어들 수 있다: 주말 어비스 3판 퀘스트가 반복 도중 깨지며
    클리어 창이 떠 매칭을 10분 막았다 (2026-10-24 06:07). Bot.wait_any 가 오래 못 찾을 때와 어비스 대기 중에 부른다.
    판단과 대응은 점검자(mabi.monitor)가 한다 — NPC 메뉴(수락·결과 보고)·전달 창은 누르지 않는다.
    ocr: '확인'·'화면을 터치해 주세요' 를 글자로도 본다 (느려서 가끔만)."""
    from .. import monitor
    return monitor.of(bot).clear(skip=skip, ocr=ocr)


def confirm_text(frame) -> tuple[int, int] | None:
    """화면 아래 가운데 버튼 글자가 '확인' 이면 그 자리 (OCR). 퀘스트 클리어 창·레이드·필드 보스 결과 창이 이 자리에
    '확인'(Space)을 둔다 — 결과 창 위쪽 '처치 완료' 글자는 연속 실행 제한 창이 가리는 자리라 결과 창도 이것으로 본다."""
    from ..ocr import find_texts
    from .ui_text import match
    hit = match(find_texts(frame, gd.region("confirm_button")), gd.text("confirm"))
    return hit[1:] if hit else None


# 클리어 뒤 연출 — 콘텐츠마다 '아직 그 안인가' 를 패킷으로 안다. 클리어 패킷은 보스를 잡거나 목표를 채운 즉시 오고,
# 그 뒤 연출(클리어 화면 '화면을 터치해 주세요'·여신상·장면)이 끝나야 보상 메뉴(나가기·다시 하기)가 뜬다.
# 어비스는 abyss.to_reward 가 따로 (뒤에서 도는 작업이라 클릭 대신 키로)
CLEAR_KINDS = {
    # 이름: (클리어 뒤 아직 그 안, 들어가 있음)
    "field": (lambda s: s.field_state == "WaitingForChannelTransfer",
              lambda s: s.field_state in ("InProgress", "WaitingForChannelTransfer")),
    "dungeon": (lambda s: s.dungeon_state == "Cleared",
                lambda s: s.dungeon_state in ("InProgress", "Cleared")),
}


def clear_kind(bot: Bot) -> str | None:
    """패킷: 지금 클리어 뒤 연출 중인 콘텐츠 ('field' · 'dungeon'), 모르거나 이미 나왔으면 None."""
    st = bot.packets.state
    # 패킷이 없거나 콘텐츠 상태를 아직 모르면(클리어 화면에서 켬) CLI — CLI 로는 던전만 안다
    if not bot.packets.ok or (st.dungeon_state is None and st.field_state is None):
        return "dungeon" if dungeon_state(bot) == "Cleared" else None
    return next((k for k, (cleared, _) in CLEAR_KINDS.items() if cleared(bot.packets.state)), None)


def field_cleared(bot: Bot) -> bool:
    """패킷: 사냥터를 클리어하고 아직 그 안 (보상을 받고 나가면 NotInBattlefield)."""
    return bool(bot.packets.ok and CLEAR_KINDS["field"][0](bot.packets.state))


def _clear_show(bot: Bot, mon, d, end: float) -> None:
    """1단계 연출: 클리어 패킷 뒤 보상 메뉴(나가기·다시 하기)가 뜰 때까지. 장면 넘기기·화면 터치·퀘스트 완료 '확인'·대화는
    점검자가 넘기고, 그 밖에는 (HUD 가 보이든 모르는 화면이든) 화면 위쪽 빈 곳을 가끔 누른다 — 반투명 '화면을 터치해 주세요' 는
    그림으로 잘 안 잡힌다. 사냥터는 끝남 패킷이 클리어 화면보다 먼저 와서, 화면이 뜨기 전 메인 화면만 보고 떠났다 (2026-10-27).
    메뉴가 뜨거나 그 콘텐츠를 나왔으면 (패킷) 끝. 패킷이 없으면 예전처럼 '화면 터치' 글자가 없는 메인 화면이 이어질 때까지."""
    from .. import monitor
    kind = clear_kind(bot)
    ctx = monitor.Ctx(bot.task_id or "dungeon", "클리어 뒤 연출", menus=True, finish_on={d.REWARD: "menu"})
    touched, quiet, closed, blind, scened = 0.0, 0, 0, 0, False
    close_x = bot.cfg["dungeon"].get("window_close")
    bot.log.debug(f"클리어 뒤 연출 ({kind or '패킷 모름'})")
    while True:
        if time.monotonic() > end:
            raise StepTimeout(f"클리어 후 화면 정리 실패 (연출) → {bot.snapshot('settle').name}")
        seen = mon.check(ctx, guard=False)
        if seen.finish:
            return  # 보상 메뉴
        inside = kind and CLEAR_KINDS[kind][1](bot.packets.state) if bot.packets.ok else kind
        if seen.what == d.LOADING or (kind and not inside):
            return  # 보상 메뉴 없이 나왔다
        scened = scened or seen.what == d.SCENE or bool(bot.cutscene_playing())
        if seen.done:
            quiet = 0
        elif (seen.what == d.UNKNOWN and closed < 3 and close_x and bot.vision.has(close_x)
              and bot.vision.find(seen.frame, close_x)):
            # 위쪽 빈 곳을 누르다 보상 물품을 눌러 장비 비교 창이 열리면, 그 창 앞에서 3분 동안 계속 눌렀다
            # (사냥터 클리어, 2026-10-28 07:51~07:54) → 연출 화면에는 없는 오른쪽 위 X 가 보이면 ESC 로 닫는다
            closed += 1
            bot.log.warning(f"클리어 뒤 연출 중 창이 열림 → 닫음 ({bot.snapshot('clear_window').name})")
            bot.key("esc")
            bot.sleep(1.0, 1.5)
            continue
        elif seen.what in (d.MAIN, d.UNKNOWN) and not (bot.dialogue_playing() or bot.cutscene_playing()):
            if kind:
                # 보지 않고 누르는 건 처음 3번만 2.5초 간격, 그 뒤엔 터치 글자가 보일 때 또는 10초에 한 번 — 요일 던전은
                # 보상 메뉴까지 40초 가까이 걸려 그동안 빈 곳을 계속 눌렀다 (2026-11-04). 터치 글자는 클리어 뒤 5~13초에
                # 뜨고 2~3번이면 넘어갔다 (10-25 로그). 사냥터의 반투명 글자는 잘 안 읽혀 10초 간격 누르기는 남긴다.
                # 던전은 터치 → 보상 상자 연출 → 보상 메뉴 순이라, 연출을 본 뒤로는 글자가 보일 때만 누른다 —
                # 연출이 끝나고 메뉴가 뜨기까지 10초 남짓 빈 곳을 누르는 게 눈에 띄었다 (사용자 11-04)
                gap = None if kind == "dungeon" and scened else 2.5 if blind < 3 else 10.0
                if ((gap is not None and time.monotonic() - touched > gap)
                        or (blind >= 3 or scened) and touch_prompt_visible(bot)):
                    touched = time.monotonic()
                    blind += 1
                    handlers_touch(bot, ctx, seen)
            elif touch_prompt_visible(bot):
                quiet = 0
                handlers_touch(bot, ctx, seen)
            elif seen.what == d.MAIN:
                quiet += 1
                if quiet >= 3:
                    return
        bot.sleep(1.0, 1.5)


def handlers_touch(bot: Bot, ctx, seen) -> None:
    from ..monitor import handlers
    handlers.touch(bot, ctx, seen)


def after_clear(bot: Bot, extra_loot: int = 0, again: str | None = None, timeout: float = 180) -> bool:
    """클리어 뒤: 1단계 연출(_clear_show) → 2단계 보상 메뉴에 맞춰 행동 — (추가 루팅) · again 버튼('다시 하기'·'새 임무 선택')이
    있으면 누르고 True (반복 플레이), 아니면 나가기 → 그 콘텐츠 밖 메인 화면이 몇 번 이어지면 끝.
    순서가 섞여 끼어드는 퀘스트 클리어 확인·대화·작별 화면은 두 단계 모두 점검자가 넘긴다."""
    from .. import monitor
    from ..monitor import detect as d
    mon = monitor.of(bot)
    end = time.monotonic() + timeout
    _clear_show(bot, mon, d, end)
    ctx = monitor.Ctx(bot.task_id or "dungeon", "클리어 뒤", menus=True, reward=True, extra_loot=extra_loot, again=again)
    stable = 0
    while stable < 3:
        if time.monotonic() > end:
            raise StepTimeout(f"클리어 후 화면 정리 실패 → {bot.snapshot('settle').name}")
        seen = mon.check(ctx, guard=False)
        if seen.finish and seen.finish.result == "again":
            return True
        if seen.finish or seen.done or clear_kind(bot):
            stable = 0  # 아직 그 안 (보상 화면을 나가기 전)
        elif seen.what == d.MAIN and not (bot.dialogue_playing() or bot.cutscene_playing()):
            stable += 1  # HUD 가 보여도 패킷이 대화·연출 중이라고 하면 아직 안 끝났다
        else:
            stable = 0
        bot.sleep(1.0, 1.5)
    bot.to_main()
    return False


def do_extra_loot(bot: Bot, n: int) -> int:
    """요일 던전 보상 화면에서 추가 루팅(Space)을 n 회 연달아 누른다 (0.5초 간격).
    회차별 골드 비용(game-rules.json extraLootGold)으로, 끝난 뒤 줄어든 골드를 보고 실제 횟수를 확인한다."""
    gold = bot.state.currency(gd.currency("gold")) if bot.state.available() else None
    for _ in range(n):
        bot.key("space")
        bot.sleep(0.5, 0.7)
    bot.sleep(2, 2.5)  # 마지막 루팅 연출
    done = n
    if gold is not None:
        now = bot.state.currency(gd.currency("gold"))
        if now is not None:
            spent = gold - now
            costs, total, done = gd.rules()["extraLootGold"]["costs"][:n], 0, 0
            for cost in costs:  # 회차 비용을 누적해 줄어든 골드가 그만큼 되면 그 회차까지 한 것
                total += cost
                done += spent >= total
    bot.log.info(f"추가 루팅 {done}회" + ("" if done == n else f" (요청 {n}회)"))
    return done
