"""필드 보스 (주간 숙제): 캐릭터마다 이번 주 1번 잡는다 ('남은 토벌 전리품 1/1회').

흐름 (2026-11-09 12시에 6캐릭터로 확인, 사용자 설명):
  메뉴(ESC) → '필드 보스' → 창 왼쪽 보스 목록에서 보스 · 위쪽 난이도 → '이동하기'(Space) → '이동하시겠습니까' 이동하기(Space)
  → 사냥터 안 보스 지역으로 자동 이동 (빠른 이동) → 도착하면 '○○의 영역에 들어가시겠습니까'(고른 난이도) → 입장하기(Space)
  → 맵 FieldBoss → 그 출현 시간의 캐릭터별 첫 입장엔 컷신 — 로딩이 끝나고 오른쪽 위 '장면 넘기기' 가 뜨면 약 1초 뒤 누른다
    (너무 일찍 누르면 안 먹고, 컷신이 끝난 뒤 그 자리를 누르면 지도가 열린다) → Space 한 번 = 자동 전투
  → 보스가 쓰러지면 결과 창 '처치 완료' → 확인(Space) — 창은 아래 가운데 '확인' 으로 본다 (위쪽 글자는 연속 실행 제한 창이 가린다). 다른 사람들이 금방 잡아 컷신 중에 끝나기도 한다 —
    '전투에 참여하지 않아 획득할 수 있는 보상이 없습니다' 면 영역을 나갔다가 다시 들어간다 (새 보스)
  → 오른쪽 위 나가기 → '영역에서 나가시겠습니까' 나가기(Space). 나가지 않으면 퇴장 시간(4분) 뒤 보관함 쪽으로 뛰어간다.
열리는 때: 매일 12:00 · 18:00 · 20:00 · 22:00 (PC 시계, 한국 시간) 부터 30분. 한 캐릭터에 1~3분 (전환 포함).
잡았나는 CLI get_growth_guide 의 '필드 보스' Weekly IsCompleted — 들어가기 전에도 보고 이미 잡았으면 넘긴다.
보스는 [field_boss] boss · difficulty (주간 숙제 탭). 보스 목록: 페리 · 크라브바흐 · 크라마 · 드로흐에넴 (매우 어려움까지),
토르모그 · 앙그르바한 (어려움까지).
보스전이라 궁극기·팔라딘 변신을 어비스·레이드와 같은 설정으로 쓴다 (boss_skills).
"""
import datetime as dt
import time

from .. import gamedata as gd, monitor
from ..bot import Bot
from . import ui_text
from .boss_skills import BossSkills, slot_of
from .content import CannotProceed, confirm_text, growth_done, wait_arrival, watch

MAP = "FieldBoss"
HOURS = (12, 18, 20, 22)   # 출현 시간 (시)
OPEN_MIN = 30              # 열려 있는 시간 (분)
MIN_LEFT = 4 * 60          # 남은 시간이 이보다 적으면 새 캐릭터를 시작하지 않는다 (초) — 한 캐릭터 1~3분
GROWTH = "필드 보스"       # CLI 성장 가이드의 Target
SKIP_WAIT = 1.0            # '장면 넘기기' 가 뜬 뒤 누르기까지 (사용자 — 0.5초는 안 먹었다)
# 보스 → 고를 수 있는 난이도 수. 창 왼쪽 목록에 이 순서로 있다 — 누를 때는 순서로 (OCR 이 '드로흐에넴' 을 '…넬' 로 읽는다)
BOSSES = {"페리": 3, "크라브바흐": 3, "크라마": 3, "드로흐에넴": 3, "토르모그": 2, "앙그르바한": 2}
ROW_Y = (130, 230, 330, 440, 540, 640)  # 목록 카드 가운데 y (1920 기준, x 130)
DIFFICULTIES = ("일반", "어려움", "매우 어려움")


# ---- 열리는 시간

def window(now: dt.datetime | None = None) -> tuple[int, dt.datetime]:
    """(지금 열려 있으면 남은 초, 아니면 0, 다음에 열리는 때 — 열려 있으면 지금 회차의 시작)."""
    now = now or dt.datetime.now()
    for h in HOURS:
        start = now.replace(hour=h, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(minutes=OPEN_MIN)
        if start <= now < end:
            return int((end - now).total_seconds()), start
        if now < start:
            return 0, start
    tomorrow = (now + dt.timedelta(days=1)).replace(hour=HOURS[0], minute=0, second=0, microsecond=0)
    return 0, tomorrow


def not_ready(now: dt.datetime | None = None) -> str:
    """새 캐릭터를 시작하면 안 되는 까닭 (열린 시간이 아님 · 곧 닫힘), 시작해도 되면 빈 문자열."""
    left, at = window(now)
    if left >= MIN_LEFT:
        return ""
    if left:
        return f"필드 보스가 곧 닫힘 (남은 {left // 60}분) — 다음 열림 {window(now + dt.timedelta(seconds=left + 1))[1]:%H:%M}"
    return f"필드 보스가 열린 시간이 아님 — 다음 열림 {at:%H:%M}"


# ---- 상태

def done(bot: Bot) -> bool | None:
    """이번 주 잡았나 (CLI 성장 가이드). 모르면 None."""
    return growth_done(bot, GROWTH, "Weekly")


def inside(bot: Bot) -> bool:
    p = bot.packets
    return bool(p.ok and not p.state.loading and p.state.channel_type == MAP)


def _texts(bot: Bot, key: str) -> str:
    from ..ocr import find_texts, nospace
    return "".join(nospace(t) for t, _, _ in find_texts(bot.frame(), gd.region(key)))


# ---- 단계

def open_window(bot: Bot, boss: str, difficulty: str) -> None:
    """메뉴(ESC) → 필드 보스 창 → 보스 · 난이도를 고른다."""
    ui_text.open_menu(bot, "fb_menu", "메뉴의 필드 보스", "field_boss")
    if not ui_text.wait(bot, gd.text("fb_title"), gd.region("fb_title"), timeout=8):
        raise CannotProceed(f"필드 보스 창이 열리지 않음 → {bot.snapshot('field_boss').name}")
    bot.sleep(0.8, 1.2)
    if boss not in BOSSES:
        raise CannotProceed(f"모르는 필드 보스 '{boss}' (고를 수 있는 것: {', '.join(BOSSES)})")
    bot.click_xy(130, ROW_Y[list(BOSSES).index(boss)])
    bot.sleep(1.0, 1.4)
    if difficulty:
        ui_text.click(bot, difficulty, gd.region("fb_difficulty"), what=f"난이도 '{difficulty}'", shot="field_boss")
        bot.sleep(0.6, 0.9)


def travel(bot: Bot, boss: str) -> None:
    """창의 이동하기 → 확인 → 빠른 이동 → 보스 지역 입장 창이 뜰 때까지."""
    bot.step("fb_move", f"'{boss}' 지역으로 이동")
    bot.key("space")  # 이동하기
    if ui_text.wait(bot, gd.text("fb_move_confirm"), gd.region("fb_dialog"), timeout=5, exact=False):
        bot.key("space")  # '이동하시겠습니까' 이동하기
    bot.fast_travel(wait=6)
    wait_arrival(bot, lambda: bool(ui_text.find(bot, gd.text("fb_enter"), gd.region("fb_dialog"), exact=False)),
                 bot.cfg.get("field_boss", {}).get("travel_timeout", 300), "fb_travel",
                 f"'{boss}' 지역에 닿지 못함 (입장 창이 안 뜸)", retry_fast=True, interval=(1.0, 1.4))


def enter(bot: Bot) -> None:
    """입장하기(Space) → 보스 영역 맵 → 컷신이면 '장면 넘기기' → Space 한 번(자동 전투)."""
    bot.step("fb_enter", "보스 영역 입장")
    bot.key("space")
    if bot.packets.ok:
        if not bot.wait_packet(lambda s: s.channel_type == MAP and not s.loading, 40, since=bot.input_mark):
            raise CannotProceed(f"보스 영역에 들어가지 못함 → {bot.snapshot('fb_enter').name}")
    else:
        bot.sleep(8, 9)
    # 로딩이 끝나고 컷신이면 '장면 넘기기' 가 곧 뜬다. 안 뜨면(이 출현 시간에 이미 본 캐릭터) 그냥 지나간다
    end = time.monotonic() + 8
    while time.monotonic() < end:
        hit = ui_text.find(bot, gd.text("fb_skip"), gd.region("fb_skip"), exact=False)
        if hit:
            bot.sleep(SKIP_WAIT)
            bot.click(hit)
            bot.sleep(0.8, 1.0)
            if not ui_text.find(bot, gd.text("fb_skip"), gd.region("fb_skip"), exact=False):
                bot.log.info("필드 보스 컷신 넘김")
                break
            end = max(end, time.monotonic() + 3)  # 안 먹었다 — 다시
        else:
            bot.sleep(0.2)
    bot.sleep(0.6, 0.9)
    bot.key("space")  # 자동 전투


def fight(bot: Bot) -> bool:
    """결과 창까지 기다려 확인(Space). 보상을 받았으면 True, '참여하지 않아 보상 없음' 이면 False."""
    bot.step("fb_fight", "보스와 전투 중")
    name = bot.packets.state.my_name if bot.packets.ok else ""
    skills = BossSkills.for_character(bot, bot.cfg, slot_of(bot, bot.character, name or ""),
                                      lambda s: s.channel_type == MAP)
    ctx = monitor.Ctx("field_boss", "필드 보스 전투", revive=True)
    end = time.monotonic() + bot.cfg.get("field_boss", {}).get("fight_timeout", 900)
    asked = time.monotonic()
    while time.monotonic() < end:
        # 결과 창을 놓쳤어도(점검자가 먼저 닫음 등) 잡았으면 끝 — 성장 가이드로 가끔 본다
        if time.monotonic() - asked > 15:
            asked = time.monotonic()
            if done(bot):
                bot.log.info("필드 보스 처치 완료 (성장 가이드)")
                if confirm_text(bot.frame()):
                    bot.key("space")  # 결과 창이 떠 있으면 닫고 나간다
                    bot.sleep(1.2, 1.6)
                return True
        if confirm_text(bot.frame()):  # 결과 창 '처치 완료' (아래 가운데 '확인')
            bot.sleep(1.0, 1.5)  # 보상이 그려지는 동안
            got = gd.text("fb_noreward") not in _texts(bot, "fb_noreward")
            if got and done(bot) is False:  # '확인' 은 있는데 아직 안 잡음 — 퀘스트 완료 같은 다른 창 → 넘기고 계속
                bot.log.info("필드 보스 전투 중 '확인' 창 → 넘김")
                bot.key("space")
                bot.sleep(1.0, 1.3)
                continue
            bot.log.info("필드 보스 처치 완료 — " + ("보상 받음" if got else "전투에 참여하지 않아 보상 없음"))
            bot.key("space")  # 확인
            bot.sleep(1.2, 1.6)
            return got
        if bot.packets.ok and not bot.packets.state.loading and bot.packets.state.channel_type not in (MAP, None):
            raise CannotProceed(f"결과 창 없이 보스 영역 밖으로 나옴 → {bot.snapshot('fb_fight').name}")
        act = bot.activity() or {}
        skills.tick(act)
        seen = watch(bot, ctx, act)
        if not seen.done:
            bot.sleep(1.0, 1.3)
    raise CannotProceed(f"필드 보스 결과가 {bot.cfg.get('field_boss', {}).get('fight_timeout', 900) // 60}분 안에 안 나옴 "
                        f"→ {bot.snapshot('fb_fight').name}")


def leave(bot: Bot) -> None:
    """보스 영역 안이면 오른쪽 위 나가기 → '영역에서 나가시겠습니까' 나가기(Space). 영역 밖이면 아무것도 누르지 않는다
    (밖에서 그 자리를 누르면 다른 창이 열린다)."""
    for _ in range(3):
        if bot.packets.ok and not inside(bot):
            break
        x, y, w, h = gd.region("fb_exit_button")
        bot.click((x + w // 2, y + h // 2))
        if ui_text.wait(bot, gd.text("fb_exit"), gd.region("fb_dialog"), timeout=3, exact=False):
            bot.key("space")
            bot.log.info("보스 영역 나가기")
            break
    else:
        bot.log.warning(f"보스 영역 나가기 창이 안 뜸 → {bot.snapshot('fb_leave').name}")
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while time.monotonic() < end:
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if not inside(bot) and bot.at_main():
            return
        bot.sleep(1.0, 1.4)


def run(bot: Bot, cfg: dict) -> str:
    fb = cfg.get("field_boss", {})
    boss, difficulty = fb.get("boss", "드로흐에넴"), fb.get("difficulty", "매우 어려움")
    if done(bot):
        return "이번 주 이미 잡음"
    if inside(bot):
        bot.log.info("이미 보스 영역 안 → 나가서 다시")
        leave(bot)
    for attempt in range(3):
        if (why := not_ready()):
            raise CannotProceed(why)
        open_window(bot, boss, difficulty)
        travel(bot, boss)
        enter(bot)
        got = fight(bot)
        leave(bot)
        if got:
            return f"{boss} {difficulty} 처치"
        bot.log.info("보상을 못 받음 → 다시 들어가 새 보스를")
    raise CannotProceed(f"{boss}: 세 번 들어갔지만 다른 사람이 먼저 잡아 보상을 못 받음")


def verify(bot: Bot, cfg: dict) -> bool:
    return bool(done(bot))
