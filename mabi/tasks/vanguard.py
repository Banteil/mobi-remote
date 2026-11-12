"""뱅가드 브리치 (주간 숙제): 캐릭터마다 이번 주 1번 클리어한다 ('남은 주간 전리품 1/1회').

흐름 (2026-11-09 직접 해 봄, 사용자 설명):
  '/' 콘텐츠 가이드 → 위쪽 '주간 달성' 칸의 하얀 '뱅가드 브리치' 글자 (카드의 '바로 가기' 와 같다. 안 되면 주간 콘텐츠 탭 카드
  — 남은 주간 콘텐츠가 많으면 카드가 아래로 밀려 있다) → 입구까지 자동 이동 (빠른 이동 T)
  → 도착하면 입장 창 (왼쪽 위 '뱅가드 브리치', 우연한 만남 켜짐) → 고를 것 없이 입장하기(Space)
  → 우연한 만남 매칭 (어비스와 같은 매칭 패킷) → 모이면 자동 입장 → 안에서는 자동 진행 (제한 20분)
  → 클리어하면 다른 던전과 같은 '화면을 터치해 주세요' → 보상 화면 '나가기(ESC) · 다시 하기' → 나가기 (다시 할 필요 없음)
  → 필드로 나오면 꼭 '[긴급 의뢰] 뱅가드 브리치' 퀘스트 클리어 창이 뜬다 → 확인(Space). 여기까지가 한 캐릭터 몫.
안: 맵 ID 가 패킷 표에 없어 맵 종류를 모르고 CLI 도 던전으로 치지 않는다 (Dungeon NotInDungeon) — CLI 장소 이름
  ('뱅가드 브리치 • 여신의 뜰') 으로 본다. 그래서 클리어는 던전의 화면 판정(dungeon_touch)과 클리어 뒤 정리(after_clear) 그대로.
입장한 뒤로는 게임을 뒤로 보내고 한다 (드릴·어비스와 같음).
끝냈나: CLI 성장 가이드 '뱅가드 브리치' Weekly IsCompleted (클리어 화면 때 바로 바뀌었다). 모를 때만 주간 달성 칸(회색 글자 + 체크),
  그것도 모르면 주간 탭 카드가 사라졌나로.
"""
import time

from .. import gamedata as gd, monitor
from ..bot import Bot, StepTimeout
from . import ui_text
from .content import CannotProceed, after_clear, cleared_now, game_space, go_from_guide, growth_done, wait_arrival, watch

GROWTH = "뱅가드 브리치"   # CLI 성장 가이드의 Target, 가이드 카드 제목
SPACE = "뱅가드"           # 안일 때 CLI 장소 이름에 들어가는 글자


def done(bot: Bot) -> bool | None:
    """이번 주 끝냈나 (CLI 성장 가이드). 모르면 None."""
    return growth_done(bot, GROWTH, "Weekly")


def inside(bot: Bot) -> bool:
    """뱅가드 브리치 안인가 — 장소 이름으로 (모르면 밖으로 본다. 들어가길 기다리는 쪽이 상한을 둔다)."""
    return SPACE in game_space(bot)


def _cfg(bot: Bot) -> dict:
    return bot.cfg.get("vanguard", {})


def travel(bot: Bot) -> None:
    """가이드 '바로 가기' 뒤 입구까지 (빠른 이동) → 입장 창이 뜰 때까지."""
    bot.step("vg_travel", "뱅가드 브리치 입구로 이동")
    bot.fast_travel(wait=6)
    wait_arrival(bot, lambda: bool(ui_text.find(bot, gd.text("vg_title"), gd.region("vg_title"), exact=False)),
                 _cfg(bot).get("travel_timeout", 600), "vg_travel", "뱅가드 브리치 입구에 닿지 못함 (입장 창이 안 뜸)",
                 retry_fast=True, interval=(1.5, 2))


def enter(bot: Bot) -> None:
    """입장 창에서 입장하기(Space) → 우연한 만남 매칭 → 안에 들어올 때까지."""
    bot.step("vg_enter", "뱅가드 브리치 입장 (우연한 만남)")
    ui_text.click(bot, gd.text("abyss_enter"), gd.region("vg_button"), what="입장하기", shot="vg_enter", key="space")
    end = time.monotonic() + _cfg(bot).get("match_timeout", 600)
    while time.monotonic() < end:
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if inside(bot):
            bot.log.info(f"뱅가드 브리치 입장: {game_space(bot)}")
            return
        bot.sleep(2, 2.5)
    raise CannotProceed(f"뱅가드 브리치 매칭·입장이 {_cfg(bot).get('match_timeout', 600) // 60}분 안에 안 됨 "
                        f"→ {bot.snapshot('vg_match').name}")


def play(bot: Bot) -> None:
    """안에서는 자동 진행 — 클리어까지 쓰러짐·끼어든 창만 본다. 클리어 뒤 보상 화면에서 나가기.
    클리어는 CLI 성장 가이드(이번 주 끝남 — 클리어 화면이 뜰 때 바로 바뀐다)가 먼저, 화면은 점검자의 '화면을 터치해 주세요'
    판정 (다른 던전과 같은 것 — 반투명 글자라 그림 틀로 안 잡혀 글자로도 본다. 그림 틀만 보다 클리어 화면에서 서 있었다)."""
    from ..monitor import detect as d
    bot.step("vg_play", "뱅가드 브리치 진행 중")
    ctx = monitor.Ctx("vanguard", "뱅가드 브리치 진행", revive=True)
    end = time.monotonic() + _cfg(bot).get("clear_timeout", 1500)
    asked = 0.0
    prev, bot.scene_skip = bot.scene_skip, False  # 던전처럼 도는 동안은 연출을 넘기지 않는다
    try:
        while True:
            if time.monotonic() - asked > 15:
                asked = time.monotonic()
                if done(bot):
                    bot.log.info("뱅가드 브리치 클리어 (성장 가이드)")
                    break
            if time.monotonic() > end:
                raise StepTimeout(f"뱅가드 브리치 클리어 화면이 안 나옴 → {bot.snapshot('vg_play').name}")
            if not bot.map_loading() and game_space(bot) and not inside(bot):
                raise CannotProceed(f"클리어 화면 없이 뱅가드 브리치 밖으로 나옴 (제한 시간?) → {bot.snapshot('vg_out').name}")
            seen = watch(bot, ctx, ocr=True)  # HUD 가 보이는 전투 중엔 글자를 읽지 않는다 (detect.look)
            if seen.what == d.TOUCH:
                bot.log.info("뱅가드 브리치 클리어 화면")
                break
            bot.sleep(2, 2.5)
        cleared_now(bot, "뱅가드 브리치")
        bot.step("vg_reward", "뱅가드 브리치 클리어 → 보상·나가기")
        after_clear(bot)  # 화면 터치 → 보상 화면 나가기 → 필드 메인 화면 (다시 하기는 누르지 않는다)
    finally:
        bot.scene_skip = prev


def quest_clear(bot: Bot) -> None:
    """나오면 꼭 뜨는 '[긴급 의뢰] 뱅가드 브리치' 퀘스트 클리어 창 — 점검자가 확인(Space)을 누른다. 안 뜨면 그냥 넘어간다."""
    from ..monitor import detect as d
    mon = monitor.of(bot)
    ctx = monitor.Ctx("vanguard", "뱅가드 퀘스트 클리어", menus=True)
    end = time.monotonic() + _cfg(bot).get("quest_wait", 20)
    seen_confirm = False
    while time.monotonic() < end:
        seen = mon.check(ctx, guard=False)
        if seen.what == d.CONFIRM:
            seen_confirm = True
        elif seen_confirm and seen.what == d.MAIN:
            bot.log.info("뱅가드 브리치 퀘스트 클리어 확인")
            return
        bot.sleep(1.0, 1.4)
    if not seen_confirm:
        bot.log.debug("뱅가드 브리치 퀘스트 클리어 창이 안 뜸")
    bot.to_main()


def run(bot: Bot, cfg: dict) -> str:
    # 안이면 먼저 — 클리어 화면에서 끊겼으면 성장 가이드는 이미 끝남이라, 그것부터 보면 안에 둔 채 넘어간다
    if not inside(bot) and done(bot):
        return "이번 주 이미 함"
    if not inside(bot):
        if not go_from_guide(bot, GROWTH, weekly=True, card=gd.text("vg_title"), text=True):
            # 주간 달성 칸이 끝냄이거나 카드가 없으면 이번 주 끝낸 것 — CLI 가 모를 때만 이것으로 친다 (사용자: 카드 확인은 최후의 방법)
            if done(bot) is False:
                raise CannotProceed(f"콘텐츠 가이드엔 뱅가드 브리치가 끝났거나 없는데 성장 가이드는 안 끝남 → {bot.snapshot('guide').name}")
            return "이번 주 이미 함 (콘텐츠 가이드)"
        travel(bot)
        enter(bot)
    else:
        bot.log.info("이미 뱅가드 브리치 안 → 클리어까지")
    try:
        if _cfg(bot).get("background", True):
            # 들어간 뒤로는 게임을 뒤로 보내고 하던 창을 돌려준다 (사용자 — 드릴·어비스와 같다). 키는 창에 직접 가고,
            # 클릭(화면 터치 등)만 누를 때 잠깐 앞으로 가져왔다가 되돌린다
            bot.background = True
            bot.window.give_back(bot.user_window)
        play(bot)
        quest_clear(bot)
    finally:
        bot.background = False
    if done(bot) is False:
        raise CannotProceed("뱅가드 브리치를 클리어했는데 성장 가이드가 안 끝남")
    return "클리어"


def verify(bot: Bot, cfg: dict) -> bool:
    return bool(done(bot))
