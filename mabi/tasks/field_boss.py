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
from ..bot import Bot, StepTimeout
from . import ui_text
from .boss_skills import BossSkills
from .content import CannotProceed, confirm_text, growth_done, wait_arrival, watch
from .exits import Exit

MAP = "FieldBoss"
MIN_LEFT = 4 * 60          # 남은 시간이 이보다 적으면 새 캐릭터를 시작하지 않는다 (초) — 한 캐릭터 1~3분
GROWTH = "필드 보스"       # CLI 성장 가이드의 Target
SKIP_WAIT = 1.0            # '장면 넘기기' 가 뜬 뒤 누르기까지 (사용자 — 0.5초는 안 먹었다)
# 보스·난이도·출현 시각은 게임 데이터(data/content.json, gamedata.field_bosses·field_boss_hours).
# 보스는 창 왼쪽 목록에 그 순서로 있다 — 누를 때는 순서로 (OCR 이 '드로흐에넴' 을 '…넬' 로 읽는다)
DEFAULT_BOSS, DEFAULT_DIFFICULTY = "드로흐에넴", "매우 어려움"  # 화면에서 아직 고른 적이 없을 때


def choices() -> dict:
    """화면(필드 보스 칸)이 고를 수 있는 것 — 보스 목록, 보스마다 고를 수 있는 난이도, 기본값."""
    bosses = gd.field_bosses()
    return {"bosses": list(bosses), "difficulties": bosses,
            "boss": DEFAULT_BOSS, "difficulty": DEFAULT_DIFFICULTY}


# ---- 열리는 시간

def window(now: dt.datetime | None = None) -> tuple[int, dt.datetime]:
    """(지금 열려 있으면 남은 초, 아니면 0, 다음에 열리는 때 — 열려 있으면 지금 회차의 시작)."""
    now = now or dt.datetime.now()
    hours, open_min = gd.field_boss_hours()
    for h in hours:
        start = now.replace(hour=h, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(minutes=open_min)
        if start <= now < end:
            return int((end - now).total_seconds()), start
        if now < start:
            return 0, start
    tomorrow = (now + dt.timedelta(days=1)).replace(hour=hours[0], minute=0, second=0, microsecond=0)
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
    bosses = list(gd.field_bosses())
    if boss not in bosses:
        raise CannotProceed(f"모르는 필드 보스 '{boss}' (고를 수 있는 것: {', '.join(bosses)})")
    rows = gd.point("field_boss_rows")  # 목록 카드 가운데
    if bosses.index(boss) >= len(rows):
        raise CannotProceed(f"필드 보스 목록 칸 자리(ui.json field_boss_rows)가 {len(rows)}개뿐 — '{boss}' 는 {bosses.index(boss) + 1}번째")
    bot.click_xy(*rows[bosses.index(boss)])
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
                 bot.cfg["field_boss"]["travel_timeout"], "fb_travel",
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
    skills = BossSkills.for_current(bot, bot.character, lambda s: s.channel_type == MAP)
    ctx = monitor.Ctx("field_boss", "필드 보스 전투", revive=True)
    end = time.monotonic() + bot.cfg["field_boss"]["fight_timeout"]
    asked = time.monotonic()
    while time.monotonic() < end:
        result = confirm_text(bot.frame())  # 결과 창 '처치 완료' (아래 가운데 '확인') — 한 바퀴에 한 번 읽는다
        # 결과 창을 놓쳤어도(점검자가 먼저 닫음 등) 잡았으면 끝 — 성장 가이드로 가끔 본다
        if time.monotonic() - asked > 15:
            asked = time.monotonic()
            if done(bot):
                bot.log.info("필드 보스 처치 완료 (성장 가이드)")
                if result:
                    bot.key("space")  # 결과 창이 떠 있으면 닫고 나간다
                    bot.sleep(1.2, 1.6)
                return True
        if result:
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


class FieldBossExit(Exit):
    """보스 영역에서 나간다: 오른쪽 위 나가기 (던전과 다른 자리 — fb_exit_button) → '영역에서 나가시겠습니까' 나가기(Space).
    영역 밖이면 아무것도 누르지 않는다 (밖에서 그 자리를 누르면 다른 창이 열린다). 패킷이 없으면 안으로 보고 누른다."""
    NAME, SNAP = "보스 영역", "fb_leave"
    TIMEOUT = 15  # 나가기 창을 띄우는 데 쓰는 시간 — 예전처럼 몇 번(누르기 + 3초)만 해 보고 그만둔다

    def inside(self, bot):
        return not bot.packets.ok or inside(bot)

    def gone(self, bot):
        return not inside(bot)

    def dialog(self, bot, timeout):
        return ui_text.wait(bot, gd.text("fb_exit"), gd.region("fb_dialog"), timeout=max(0.0, timeout), exact=False)

    def open_dialog(self, bot):
        x, y, w, h = gd.region("fb_exit_button")
        bot.click((x + w // 2, y + h // 2))
        return self.dialog(bot, 3)

    def confirm(self, bot, hit):  # 찾은 글자는 창의 문구라 누를 자리가 아니다 — Space 만
        bot.key("space")
        bot.log.info("보스 영역 나가기")


def leave(bot: Bot) -> None:
    """보스 영역 안이면 나간다 (FieldBossExit). 못 나가도 멈추지 않고 남긴다 — 영역은 퇴장 시간(4분)이 지나면 저절로 나가진다."""
    try:
        FieldBossExit().run(bot)
    except StepTimeout as e:
        bot.log.warning(f"보스 영역 나가기: {e}")


def run(bot: Bot, cfg: dict) -> str:
    fb = cfg.get("field_boss", {})
    boss, difficulty = fb.get("boss", DEFAULT_BOSS), fb.get("difficulty", DEFAULT_DIFFICULTY)
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
