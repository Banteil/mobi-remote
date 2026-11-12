"""던전·사냥터 한 판 — 단계 고르기·입장(더블 루팅 확인) → 진행 → 클리어 뒤(clear.after_clear). 개별 숙제 태스크가 조합해서 쓴다.

던전 진행 상태는 CLI get_activity 의 Dungeon.State 로 판단한다.
  NotInDungeon → (입장) InProgress → Cleared → (보상 화면에서 나가기) NotInDungeon
입장하면 자동 전투가 저절로 켜진다 (던전, 사냥터, 검은 구멍 모두).
우하단 ASSIST(H)는 자동 스킬 사용 여부라 켜져 있어야 하므로 절대 누르지 않는다. 클리어 후 화면 흐름:
  '화면을 터치해 주세요' → 보상 연출('장면 넘기기') → 보상 화면(추가 루팅 Space / 나가기 ESC)
  → (아르바이트로 들어온 경우) '퀘스트 클리어' 확인 → 필드
추가 루팅은 요일 던전에만 있다 (다른 던전, 심층 던전, 사냥터에는 없음).
"""
import time

from .. import gamedata as gd
from ..bot import Bot
from ..exceptions import CannotProceed, StepTimeout
from ..place import FIELD
from .clear import after_clear, cleared_now, touch_prompt_visible
from .fight import watch
from .space import hunt_quest, wait_dungeon
from .steps import wait_until
from .ui_text import has_word, read_button


def _in_ctx(bot: Bot, what: str):
    from .. import monitor
    return monitor.Ctx(bot.task_id or "dungeon", what, revive=True)


def select_zone(bot: Bot, difficulty: str, floor: int, zone: int) -> None:
    """일반 던전 창에서 난이도와 층-구역을 고르고, 진입 버튼 글자로 확인한다.
    해당 구역이 보이지 않으면 (미해금 등) CannotProceed."""
    ui = bot.ui
    if difficulty:
        tpl = {"일반": ui["dungeon_diff_normal"], "어려움": ui["dungeon_diff_hard"]}.get(difficulty)
        if tpl is None:
            raise CannotProceed(f"알 수 없는 난이도 '{difficulty}' (일반 / 어려움)")
        if not bot.click_if(tpl):
            raise CannotProceed(f"난이도 '{difficulty}' 버튼이 없음 → {bot.snapshot('difficulty').name}")
        bot.sleep(0.8, 1.2)
    m = bot.find(f"zone_{floor}-{zone}")
    if not m:
        raise CannotProceed(f"{floor}층 {zone}구역이 보이지 않음 (미해금이거나 템플릿 없음) → {bot.snapshot('zone').name}")
    bot.click(m)
    bot.sleep(0.8, 1.2)
    want = f"{floor}층 {zone}구역"
    _, win, ko = read_button(bot.frame(), ui["enter_button_region"])
    text = ko or win
    if has_word(gd.text("dungeon_deep"), win, ko):  # 심층 던전이 있는 던전은 창이 심층 탭으로 열린다. 은동전 숙제가 심층으로 들어가면 안 된다
        raise CannotProceed(f"심층 던전 구역이 선택됨: 버튼 '{text}' → {bot.snapshot('zone').name}")
    if not has_word(want, win, ko):
        raise CannotProceed(f"구역 선택 확인 실패: 버튼 '{text}' / '{win}' (기대 '{want}') → {bot.snapshot('zone').name}")
    bot.log.info(f"구역 선택: {text}")


# 임무 화면 왼쪽 '더블 루팅' 칸 (ui.json double_loot) — 꺼져 있으면 '도전' 버튼, 켜면 '선택됨'. 사냥터·던전 임무 화면이 같다


def mission_button(bot: Bot, expect_cost: int) -> tuple[int | None, str, str]:
    """임무 화면 입장 버튼 (가격, Windows 글자, 한글 글자). 가격이 expect_cost(소탕 + 더블 루팅)보다 적으면 더블 루팅이
    꺼진 것 → '도전' 을 눌러 켜고 다시 읽는다. 켜짐 여부는 게임이 캐릭터·장소마다 기억해서 어떤 캐릭터는 꺼진 채
    열려 은동전 숙제를 통째로 건너뛰었다 (2026-11-01 사용자: 꺼져 있으면 켜기). 그래도 다르면 부르는 쪽이 멈춘다."""
    from ..ocr import find_texts, nospace
    ui = bot.ui
    price, win, ko = read_button(bot.frame(), ui["mission_button_region"])
    if price is None or price >= expect_cost:
        return price, win, ko
    on = nospace(gd.text("double_loot_on"))
    hit = next(((x, y) for t, x, y in find_texts(bot.frame(), gd.region("double_loot")) if nospace(t) == on), None)
    if hit is None:
        return price, win, ko
    bot.log.info(f"입장 비용 {price} — 더블 루팅 꺼짐 → '도전' 눌러 켬")
    bot.click(hit)
    bot.sleep(0.8, 1.2)
    return read_button(bot.frame(), ui["mission_button_region"])


def enter_from_dungeon_window(bot: Bot, clear_timeout: float, extra_loot: int = 0,
                              expect_cost: int | None = None, again: str | None = None,
                              retry: bool = False) -> str:
    """던전 창(단계 선택)이 열린 상태에서 선택된 단계로 입장해 끝까지 진행. 반환 'clear' | 'fail' | 'again'.
    expect_cost 가 있으면 임무 화면의 입장 버튼 가격(예: 은동전 20 = 소탕 10 + 더블 루팅 10)을 확인한다.
    retry: 직전 보상 화면에서 '다시 하기'를 눌러 이미 임무 화면이 열려 있음 (단계 '진입' 생략).
    again: 보상 화면에서 누를 반복 버튼('다시 하기'). 누르면 'again' 을 반환한다."""
    ui = bot.ui
    missions = [ui["dungeon_mission_enter"], ui["dungeon_mission_enter_deep"], ui["dungeon_mission_enter_silver"],
                ui["dungeon_retry_enter"]]
    if not retry:
        # 단계 '진입' (점검자가 막는 화면을 먼저 정리). 다시 누르지는 않는다 — 임무 화면이 늦게 뜬 것이면
        # 두 번째 Space 가 가격 확인 없이 '입장하기' 가 된다
        from .. import monitor
        ctx = monitor.Ctx(bot.task_id or "dungeon", "던전 단계 진입", keep_dungeon_window=True)
        if not monitor.of(bot).act(ctx, "단계 진입", lambda: bot.key("space"),
                                   lambda: any(bot.exists(n) for n in missions), within=15, tries=1):
            raise StepTimeout(f"던전 창에서 진입했는데 임무 화면이 안 뜸 → {bot.snapshot('dungeon_mission').name}")
    bot.wait_any(missions, timeout=15)
    bot.sleep(0.8, 1.2)
    if expect_cost is not None:
        price, win, ko = mission_button(bot, expect_cost)
        if price != expect_cost or not has_word(gd.text("dungeon_enter"), win, ko):
            raise CannotProceed(f"입장 버튼 '{win}' / '{ko}' — 비용 {expect_cost} 이 아님 (더블 루팅 꺼짐?) "
                                f"→ {bot.snapshot('mission_cost').name}")
    bot.step("dungeon_enter", "던전 입장")
    bot.key("space")                     # 임무 선택 '입장하기' (일반 던전은 은동전, 심층 던전은 공물 소모)
    return play_dungeon(bot, clear_timeout, extra_loot, again)


def play_dungeon(bot: Bot, clear_timeout: float, extra_loot: int = 0, again: str | None = None) -> str:
    """입장 직후부터 클리어 → 보상 → 필드 복귀까지. 반환: 'clear' | 'fail' | 'again'(반복 버튼을 누름)
    도는 동안은 연출의 '장면 넘기기' 를 누르지 않는다 (Bot.scene_skip)."""
    prev, bot.scene_skip = bot.scene_skip, False
    try:
        return _play_dungeon(bot, clear_timeout, extra_loot, again)
    finally:
        bot.scene_skip = prev


def _play_dungeon(bot: Bot, clear_timeout: float, extra_loot: int, again: str | None) -> str:
    ui = bot.ui
    entered = wait_dungeon(bot, lambda s: s == "InProgress", bot.cfg["timing"]["loading"], interval=2)
    if entered == "":
        raise StepTimeout("던전 입장 확인 실패")
    if entered is not None:
        bot.step("in_dungeon", "던전 진행 중")
        ctx = _in_ctx(bot, "던전 진행 중")
        end = time.monotonic() + clear_timeout
        while True:
            state = wait_dungeon(bot, lambda s: s != "InProgress", 3)
            if state:
                break
            if state is None:  # 패킷도 CLI 도 끊김 → 클리어 화면으로
                bot.wait(ui["dungeon_touch"], timeout=max(1.0, end - time.monotonic()), interval=2.0)
                state = "Cleared"
                break
            watch(bot, ctx)  # 쓰러짐·끼어든 창
            if time.monotonic() > end:
                raise StepTimeout("던전 클리어 대기 시간 초과")
        result = "clear" if state == "Cleared" else "fail"
        if result == "clear":
            cleared_now(bot, "던전")
        bot.step("dungeon_reward", "던전 클리어 → 보상·나가기" if result == "clear" else f"던전 끝남({state}) → 나가기")
        if result == "fail":
            bot.log.warning(f"던전 종료 상태: {state} → {bot.snapshot('dungeon_end').name}")
    else:
        # CLI 를 못 쓰면 클리어 화면이 뜰 때까지 기다린다
        bot.wait(ui["dungeon_touch"], timeout=clear_timeout, interval=2.0)
        result = "clear"
        cleared_now(bot, "던전")

    if after_clear(bot, extra_loot, again) and result == "clear":
        return "again"
    return result


def dungeon_once(bot: Bot, open_steps: list[str], lack: list[str] = (), clear_timeout: float = 600) -> str:
    """메인 화면에서 open_steps 를 눌러 던전 창을 연 뒤 1회 진행.
    반환: 'clear' | 'fail' | 'lack'(입장 재화 부족)"""
    ui = bot.ui
    bot.to_main()
    bot.click_steps(open_steps)
    if lack:
        bot.key("space")
        m = bot.wait_any([*lack, ui["dungeon_mission_enter"]], timeout=15)
        if m.name in lack:
            bot.to_main()
            return "lack"
        bot.key("space")
        return play_dungeon(bot, clear_timeout)
    return enter_from_dungeon_window(bot, clear_timeout)


def play_field(bot: Bot, place: str, clear_timeout: float, on_enter=None, again: str | None = None) -> str:
    """사냥터 창에서 '입장하기'(또는 '임무 시작')를 누른 뒤 클리어까지. 반환 'clear' | 'again'.
    입장하면 퀘스트 목록에 '<장소> 사냥 …' 퀘스트가 생기고, 클리어하면 사라진다 (CLI get_quests).
    on_enter(bot) 는 입장 직후 한 번 호출된다 (사냥터 안의 검은 구멍 처리 등). 그동안에도 사냥터 시간은 흐른다.
    again 을 주면 보상 화면에서 그 버튼('새 임무 선택')을 눌러 사냥터 창으로 바로 돌아가고 'again' 을 반환한다."""
    bot.step("field_enter", f"{place} 사냥터 입장", place=place)
    bot.key("space")
    # 패킷이 먼저 (사냥터 상태 InProgress + 사냥터 맵 로딩 끝 — 상태는 로딩 전에 먼저 온다), 못 쓰거나 안 오면 CLI 퀘스트 목록
    entered = bot.wait_packet(lambda s: s.field_state == "InProgress" and s.channel_type == FIELD and not s.loading,
                              bot.cfg["timing"]["loading"])
    if not entered:
        wait_until(bot, lambda: bool(hunt_quest(bot, place)), bot.cfg["timing"]["loading"] if entered is None else 10,
                   what="사냥터 입장")
    bot.step("in_field", f"사냥터 진행 중: {hunt_quest(bot, place)}", place=place)
    if on_enter:
        on_enter(bot)
    return wait_field(bot, place, clear_timeout, again)


def wait_field(bot: Bot, place: str, clear_timeout: float, again: str | None = None) -> str:
    """사냥터 안에서 클리어까지 기다리고 마무리. 반환 'clear' | 'again'.
    사냥터 안에서 끊긴 뒤 다시 시작했을 때도 이걸로 그 판을 끝까지 본다 (은동전은 이미 나갔다)."""
    def hunt():
        return hunt_quest(bot, place)

    end = time.monotonic() + clear_timeout
    ctx = _in_ctx(bot, "사냥터 진행 중")
    # 패킷이 사냥터 상태를 알면 그걸로 — 클리어 순간(WaitingForChannelTransfer) 바로 안다. 퀘스트 목록으로 보는 아래 방식은
    # 3번 연속(15초+) 확인이 필요하고 창이 HUD 를 가리면 오판했다. 감시가 도중에 끊기면 아래 방식으로 넘어간다
    while bot.packets.ok and bot.packets.state.field_state == "InProgress":
        if bot.wait_packet(lambda s: s.field_state != "InProgress", 5):
            bot.log.info(f"패킷: 사냥터 끝남 ({bot.packets.state.field_state})")
            cleared_now(bot, "사냥터")
            bot.step("field_reward", "사냥터 클리어 → 마무리")
            return "again" if after_clear(bot, again=again) else "clear"
        watch(bot, ctx)
        if time.monotonic() > end:
            raise StepTimeout("사냥터 클리어 대기 시간 초과")
    # 끝남 신호가 watch 하는 동안 와서 위 wait_packet 이 못 봤어도 패킷은 이미 안다 — 아래 퀘스트 목록 방식(3번 · 15초+)으로
    # 넘어가 클리어 화면 앞에 40초 가까이 서 있었다 (2026-10-28 08:32:43~08:33:21)
    if bot.packets.ok and bot.packets.state.field_state is not None:
        bot.log.info(f"패킷: 사냥터 끝남 ({bot.packets.state.field_state})")
        cleared_now(bot, "사냥터")
        bot.step("field_reward", "사냥터 클리어 → 마무리")
        return "again" if after_clear(bot, again=again) else "clear"
    gone = 0
    covered_since = None
    # 조회 실패나 일시적인 빈 응답으로 끝났다고 오판하지 않도록 3번 연속 없어야 클리어로 본다
    while gone < 3:
        h = hunt()
        # CLI 퀘스트 목록은 화면에 보이는 추적 칸만 준다 → 지도 등 창이 열려 HUD 가 가려지면 사냥 퀘스트가 '없음' 으로
        # 나온다 (2026-10-23: 사냥 중 지도가 열려 클리어로 오판, 다음 던전으로 떠남). 메인 화면일 때만 셈에 넣는다
        if h == "" and not bot.at_main() and not bot.exists(bot.ui["reward_exit"]) and not touch_prompt_visible(bot):
            h = None  # 클리어 화면(터치·보상)도 아닌데 HUD 가 가려짐 = 다른 창이 열린 것
            covered_since = covered_since or time.monotonic()
            if time.monotonic() - covered_since > 30:  # 창이 계속 열려 있으면 닫는다 (사냥터 시간은 흐르고 있다)
                bot.log.info("사냥터: 창이 열려 진행 상황이 가려짐 → 닫음")
                try:
                    bot.to_main(tries=4)
                except StepTimeout:
                    pass
                covered_since = None
        else:
            covered_since = None
        gone = gone + 1 if h == "" else 0
        watch(bot, ctx)
        if time.monotonic() > end:
            raise StepTimeout("사냥터 클리어 대기 시간 초과")
        bot.sleep(5)
    cleared_now(bot, "사냥터")
    bot.step("field_reward", "사냥터 클리어 → 마무리")
    return "again" if after_clear(bot, again=again) else "clear"
