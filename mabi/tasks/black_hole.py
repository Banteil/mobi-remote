"""검은 구멍: '/' 콘텐츠 가이드 → 검은 구멍 카드 '바로 가기' → 자동 이동 후 즉시 입장.

입장하는 순간 횟수가 차감되므로 도중에 나가면 안 되고 클리어할 때까지 머문다.
입장하면 종류(몬스터, 보스, 낚시 등)와 상관없이 자동으로 진행되므로 아무것도 조작하지 않는다.
클리어하면 검은 구멍 밖(필드)으로 나온다. 장소는 패킷의 맵 이름(없으면 CLI get_current_environment)으로 판단한다.
오늘 끝냈으면 콘텐츠 가이드에서 카드가 사라진다.

검은 구멍은 사냥터 안에 30분마다 3개씩 나오고, 다 깨면 30분 동안 못 들어간다.
그래서 은동전 사냥터에 들어가면 먼저 검은 구멍을 한 번 처리하고 (silver.black_hole_in_field),
그러면 이 태스크는 오늘 완료로 기록되어 건너뛴다. 일일 숙제로는 하루 한 번만 간다.
"""
import time

from ..bot import Bot, StepTimeout
from ..profile import game_day_start
from .content import daily_achieved, game_space, inside_space, open_guide_card, watch


def cleared_today(bot: Bot) -> bool:
    """패킷: 깬 검은 구멍 목록(맵에 들어갈 때마다 온다)에 오늘(6시 뒤) 나타난 구멍이 있으면 True.
    목록이 비었거나 어제 나타난 것뿐이면 모른다 → False (화면으로 확인)."""
    times = bot.packets.state.dimensions_cleared if bot.packets.ok else None
    start = game_day_start().timestamp() * 1000
    return any(t >= start for t in times or [])


def verify(bot: Bot, cfg: dict) -> bool:
    if cleared_today(bot):
        bot.log.debug("패킷: 오늘 나타난 검은 구멍을 깸 → 완료")
        return True
    return daily_achieved(bot, cfg["black_hole"]["achieved"])


def enter(bot: Bot, c: dict) -> None:
    """'바로 가기' 후 검은 구멍 안에 들어갈 때까지 기다린다. 지역 이동 로딩 중에도 끊기지 않도록
    이동 상태가 아닌 '장소 이름'으로 도착을 판단한다.
    가는 길에 선공 몬스터에게 맞아 전투가 시작되면 자동 이동이 끊긴다 → 전투가 끝나면 '바로 가기'를 다시 누른다.
    전투 없이 이동이 멈춰 버린 경우(stall 초 동안 이동도 전투도 아님)도 다시 누른다.
    가는 길에 끼어든 창(대화·퀘스트 완료 등)과 쓰러짐은 점검자가 (content.watch)."""
    from .. import monitor
    ctx = monitor.Ctx("black_hole", "검은 구멍으로 이동", revive=True)
    end = time.monotonic() + c["travel_timeout"]
    fought = False
    idle_since = None
    retries = 0
    while c["space_keyword"] not in game_space(bot):
        if time.monotonic() > end:
            raise StepTimeout(f"{c['travel_timeout']}초 안에 검은 구멍에 들어가지 못함 → {bot.snapshot('black_hole').name}")
        bot.sleep(3)
        if bot.is_loading():  # 지역 이동 로딩 중
            idle_since = None
            continue
        if watch(bot, ctx).done:  # 끼어든 창을 넘겼다 — 멈춘 시간은 그 뒤부터 잰다
            idle_since = None
            continue
        if bot.in_combat():
            if not fought:
                bot.log.info("검은 구멍 가는 길에 전투 시작 → 끝날 때까지 대기")
            fought, idle_since = True, None
            continue
        if bot.auto_traveling() and not fought:
            idle_since = None
            continue
        idle_since = idle_since or time.monotonic()
        if fought or time.monotonic() - idle_since >= c["stall"]:
            if retries >= c["max_retries"]:
                raise StepTimeout(f"검은 구멍 다시 가기 {retries}회 실패 → {bot.snapshot('black_hole').name}")
            retries += 1
            bot.log.warning(f"검은 구멍 이동이 끊김{' (전투 후)' if fought else ''} → 바로 가기 다시 ({retries}회)")
            fought, idle_since = False, None
            if not open_guide_card(bot, c["card"]):
                raise StepTimeout("검은 구멍 카드가 사라짐 (다시 가기 실패)")


def run(bot: Bot, cfg: dict) -> str:
    c = cfg["black_hole"]
    if not bot.state.available() and bot.map_loading() is None:
        raise RuntimeError("검은 구멍은 장소 판단에 패킷이나 CLI 가 필요함")
    # 단계: bh_open(가이드 → 바로 가기) → bh_travel(이동) → bh_inside(안에서 클리어 대기) → bh_done(나와서 정리)
    # 이미 안에 있으면 (안에서 끊김) 나가지 않고 그대로 클리어를 기다린다 — 나가면 횟수만 날아간다
    if c["space_keyword"] in game_space(bot):
        bot.step("bh_inside", f"검은 구멍 안에서 이어 함: {game_space(bot)}")
    else:
        # 일일 달성 체크로 먼저 확인하지 않는다 — 오늘 끝냈으면 가이드에서 카드가 사라지므로 바로 가기를 열어 보면 된다.
        # (예전엔 확인에 한 번, 바로 가기에 또 한 번 가이드를 열어 캐릭터마다 10초 — 2026-10-25.)
        # 카드가 없을 때만 실행기가 일일 달성 체크로 확인한다
        if cleared_today(bot):
            bot.verified = True
            return "완료 (패킷: 오늘 깸)"
        if bot.resumed_at("bh_travel", "bh_inside"):
            bot.log.info("지난번에 검은 구멍으로 가다(또는 안에서) 끊김 → 바로 가기부터 다시")
        bot.step("bh_open", "콘텐츠 가이드 → 검은 구멍 바로 가기")
        if not open_guide_card(bot, c["card"]):
            return "검은 구멍 카드 없음"
        bot.step("bh_travel", "검은 구멍으로 이동")
        enter(bot, c)
        bot.step("bh_inside", f"검은 구멍 입장: {game_space(bot)}")

    # 안에서는 아무것도 조작하지 않는다 — 쓰러짐('여기서 부활')과 끼어든 창만 점검자가
    from .. import monitor
    ctx = monitor.Ctx("black_hole", "검은 구멍 안", revive=True)
    end = time.monotonic() + c["clear_timeout"]
    while inside_space(bot, c["space_keyword"]):
        if time.monotonic() > end:
            raise StepTimeout(f"{c['clear_timeout']:.0f}s 안에 검은 구멍 클리어 충족 안 됨")
        watch(bot, ctx)
        bot.sleep(5)
    bot.step("bh_done", "검은 구멍 클리어 → 정리")
    bot.sleep(2, 3)
    monitor.of(bot).settle(monitor.Ctx("black_hole", "검은 구멍 클리어 뒤"))  # 클리어 화면·퀘스트 완료·대화
    bot.dismiss_popups()
    bot.to_main()
    return f"검은 구멍 클리어 → {game_space(bot)}"
