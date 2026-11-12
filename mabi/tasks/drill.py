"""나이트메어 드릴 (기타 숙제): 캐릭터마다 20구역까지 깬다. 구역은 30까지 있지만 보상은 20구역까지라 거기서 멈춘다 (사용자).

흐름 (2026-11-08 처음부터 확인, 캡처 caps/drill1):
  메뉴(ESC) → '나이트메어 드릴' → 드릴 창 (왼쪽 위 다음에 도전할 구역 'N구역', 오른쪽 아래 '이동하기' / '입장하기', 둘 다 Space)
  → 이동하기면 입구까지 자동 이동(빠른 이동) → 도착하면 드릴 창이 다시 뜬다 → 입장하기
  → 드릴이 초기화된 뒤 첫 입장에만 컷신 (화면을 길게 눌러 넘김 — 안 나오면 그냥 지나간다)
  → 맵 InstanceBreakthroughDungeon, 구역마다 120초 제한 · 자동 진행·자동 전투가 저절로 켜진다
  → 구역 클리어 = 결과 창 '나가기(ESC) · 다시 하기 · 다음으로(Space)'. 다음으로면 다음 구역으로 바로 (컷신 없음)
  → 20구역 결과에서 나가기(ESC) → 필드.
패킷: 최고 기록(직업마다, 드릴 맵 진입·클리어 때 — 필드 이동 때는 안 왔다) · 구역 입장 · 구역 결과(깬 구역). 결과 창 글자로도 본다.
이미 20구역 이상이면 입장하지 않는다 — 패킷 최고 기록, 모르면 드릴 창 왼쪽 위 다음 도전 구역(21 이상)으로 본다.
기록을 저장해 두지 않는다 — 드릴은 끝·초기화 시기가 정해져 있지 않아 매번 지금 기록으로 본다 (사용자).
입장한 뒤로는 게임을 뒤로 보내고 키(Space·ESC)는 창에 직접 보낸다 — 어비스 반복과 같다.
배고프면 판 중에 먹는다 (사용자).
궁극기·팔라딘 변신도 어비스·레이드와 같은 설정(기본값 + 캐릭터별)으로 쓴다 (사용자, 2026-11-09). 드릴은 구역마다 제한 시간이 있어
보스전을 따로 가리지 않고 드릴 안 전투 중이면 게이지가 찰 때마다 쓴다 (boss_skills.BossSkills) — 드릴엔 보스가 따로 없다 (사용자).
구역마다 새 맵이라(구역마다 맵 진입 패킷) 팔라딘 변신도 구역마다 새로 쓸 수 있다 (사용자) — 맵 진입 때 변신 기록을 지우는 것과 맞다.
"""
import re
import time

from .. import gamedata as gd
from ..bot import Bot, StepTimeout
from ..ocr import find_texts, nospace, read_text
from . import entry, ui_text
from .boss_skills import BossSkills
from .content import CannotProceed, Fight, wait_arrival

GOAL = 20
MAP = "InstanceBreakthroughDungeon"
ZONE_LIMIT = 120     # 구역 제한 시간 (초) — 넘기면 결과가 안 와도 끝난 것으로 보고 화면을 본다
ENTER_WAIT = 25      # 입장하기 뒤 드릴에 들어가기 시작할 때까지
SCENE_PRESS = 2.5    # 컷신 넘기기: 화면을 누르고 있는 시간 (초)
_ZONE = re.compile(r"(\d+)\s*구역")


# ---- 상태

def packet_best(bot: Bot) -> int | None:
    """패킷이 아는 지금 캐릭터의 최고 기록 구역. 직업별 기록이 여럿이면 어느 것이 지금 직업인지 몰라 None."""
    p = bot.packets
    if not p.ok or p.state.drill_best is None or p.state.drill_records > 1:
        return None
    return p.state.drill_best


def inside(bot: Bot) -> bool:
    p = bot.packets
    return bool(p.ok and not p.state.loading and p.state.channel_type == MAP)


def _texts(bot: Bot, key: str) -> list[str]:
    return [nospace(t) for t, _, _ in find_texts(bot.frame(), gd.region(key))]


def read_zone(bot: Bot, key: str) -> int | None:
    """영역의 'N구역' 숫자. 숫자는 Windows OCR 로 읽는다 — 한글 OCR 은 '11구역' 을 '1구역' 으로 읽었다 (2026-11-08)."""
    m = _ZONE.search(read_text(bot.frame(), gd.region(key)))
    return int(m.group(1)) if m else None


def result_buttons(bot: Bot) -> set[str]:
    """결과 창 아래 버튼 글자 ('나가기' · '다시하기' · '다음으로'), 결과 창이 아니면 빈 집합."""
    want = {nospace(gd.text(k)) for k in ("drill_exit", "drill_retry", "drill_next")}
    return {t for t in _texts(bot, "drill_result_buttons") if t in want}


# ---- 창 열기 · 입장

def open_window(bot: Bot) -> int | None:
    """메뉴(ESC) → 나이트메어 드릴 창. 창 왼쪽 위의 다음 도전 구역을 돌려준다 (못 읽으면 None)."""
    ui_text.open_menu(bot, "drill_menu", "메뉴의 나이트메어 드릴", "drill")
    if not ui_text.wait(bot, gd.text("drill_title"), gd.region("drill_title"), timeout=8):
        raise CannotProceed(f"나이트메어 드릴 창이 열리지 않음 → {bot.snapshot('drill').name}")
    bot.sleep(0.8, 1.2)
    return read_zone(bot, "drill_zone")


def _button(bot: Bot) -> str:
    """드릴 창 오른쪽 아래 버튼: 'enter'(입장하기) · 'move'(이동하기) · ''."""
    texts = _texts(bot, "drill_button")
    if nospace(gd.text("abyss_enter")) in texts:
        return "enter"
    if nospace(gd.text("abyss_move")) in texts:
        return "move"
    return ""


def _travel(bot: Bot) -> bool:
    """'이동하기' 로 입구까지 가는 동안. 도착해 드릴 창이 다시 뜨면 True, 창 없이 멈췄으면 False (raid._travel_to_dock 과 같음)."""
    if wait_arrival(bot, lambda: bool(ui_text.find(bot, gd.text("drill_title"), gd.region("drill_title"))),
                    bot.cfg.get("drill", {}).get("travel_timeout", 600), "drill_travel", "나이트메어 드릴 입구로 가지 못함",
                    still=3):
        bot.log.info("드릴 입구 도착 → 드릴 창")
        return True
    return False


def enter(bot: Bot) -> None:
    """드릴 창이 열린 상태에서 입장 — 멀면 이동하기로 입구까지 가서 다시 연 창에서 입장하기."""
    for _ in range(3):
        button = entry.wait_button(bot, _button)
        if not button:
            raise CannotProceed(f"드릴 창에 입장하기·이동하기가 없음 → {bot.snapshot('drill').name}")
        bot.key("space")
        if button == "move":
            bot.log.info("드릴 입구에서 멂 → 이동하기")
            bot.fast_travel(wait=5)
            if not _travel(bot):
                bot.log.info("이동이 멈췄는데 드릴 창이 없음 → 메뉴에서 다시 엶")
                open_window(bot)
            continue
        bot.step("drill_enter", "나이트메어 드릴 입장")
        mark = bot.input_mark
        # 입장하면 구역 입장 패킷 → (첫 입장이면 컷신) → 맵 이동. 패킷이 없으면 드릴 창이 닫혔나로
        got = bot.wait_packet(lambda s: s.loading or s.cutscene or s.channel_type == MAP, ENTER_WAIT, since=mark)
        if got or bot.packets.find("drill.enter", mark):
            return
        if got is None and not ui_text.find(bot, gd.text("drill_title"), gd.region("drill_title")):
            return
        raise CannotProceed(f"입장하기를 눌러도 드릴에 들어가지 않음 (전투력·잠김?) → {bot.snapshot('drill_enter').name}")
    raise CannotProceed(f"입구에 가도 입장하기가 나오지 않음 → {bot.snapshot('drill').name}")


def skip_cutscene(bot: Bot) -> None:
    """입장 컷신 — 드릴이 초기화된 뒤 첫 입장에만 나온다. 나오면 화면을 길게 눌러 넘기고, 안 나오면 그냥 지나간다."""
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    pressed = 0
    while time.monotonic() < end and not inside(bot):
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if bot.cutscene_playing() and pressed < 3:
            bot.log.info("드릴 입장 컷신 → 길게 눌러 넘김")
            bot.long_press(960, 540, SCENE_PRESS)
            pressed += 1
            bot.sleep(1.0, 1.5)
            continue
        if not bot.packets.ok and bot.at_main():
            return  # 패킷 없이 화면으로만: 메인 HUD 가 보이면 들어온 것
        bot.sleep(1.0, 1.3)


# ---- 구역 진행

def wait_zone(bot: Bot, skills: BossSkills | None = None) -> int:
    """한 구역이 끝날 때까지 — 결과 창이 뜨면 깬 구역 번호, 못 깨고 끝났으면 0.
    패킷이 있으면 결과 패킷을 기다리고 결과 창 글자는 결과가 왔거나 제한 시간이 지났을 때만 본다 (못 깬 결과는 패킷을 모른다).
    뼈대는 content.Fight (구역 제한 + 90초를 넘기면 StepTimeout)."""
    return ZoneFight(bot, skills).run()


class ZoneFight(Fight):
    KIND, WHAT = "drill", "나이트메어 드릴 진행"
    IDLE = 2.0

    def __init__(self, bot: Bot, skills: BossSkills | None):
        super().__init__(bot, ZONE_LIMIT + 90, revive=True)
        self.skills = skills

    def wake(self, s):
        return bool(s.drill_result)

    def packet_end(self):
        bot = self.bot
        zone = bot.packets.state.drill_result if bot.packets.ok else 0
        look = zone or not bot.packets.ok or time.monotonic() - self.start > ZONE_LIMIT
        buttons = result_buttons(bot) if look else set()
        if buttons:
            if nospace(gd.text("drill_next")) in buttons or zone:
                return zone or read_zone(bot, "drill_result_zone") or -1
            return 0  # 다음으로가 없는 결과 — 못 깸

    def before_watch(self, act):  # 드릴은 보스가 따로 없어 안 전체가 보스전 — 점검자보다 먼저, 처리한 게 있어도 쓴다
        if self.skills:
            self.skills.tick(act)

    def dead_end(self, seen):
        self.bot.log.warning(f"드릴에서 쓰러짐 → {self.bot.snapshot('drill_dead').name}")

    def timed_out(self):
        raise StepTimeout(f"드릴 구역이 {ZONE_LIMIT + 90}초 안에 끝나지 않음 → {self.bot.snapshot('drill_zone').name}")


def leave(bot: Bot) -> None:
    """결과 창에서 나가기(ESC) → 드릴 밖 필드 메인 화면까지."""
    for _ in range(3):
        bot.key("esc")
        if bot.wait_packet(lambda s: s.loading, 10, since=bot.input_mark) is not False or not result_buttons(bot):
            break
        bot.log.info("ESC 가 안 들음 → 나가기 버튼을 누름")
        if hit := ui_text.find(bot, gd.text("drill_exit"), gd.region("drill_result_buttons")):
            bot.click(hit)
            break
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while time.monotonic() < end:
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if not inside(bot) and bot.at_main():
            return
        bot.sleep(1.5, 2)
    raise StepTimeout(f"드릴에서 나온 뒤 메인 화면이 나오지 않음 → {bot.snapshot('drill_leave').name}")


def play(bot: Bot) -> str:
    """드릴 안에서 20구역까지 — 구역마다 결과 창의 다음으로(Space), 20구역(또는 그 위)이면 나가기."""
    if bot.cfg.get("drill", {}).get("background", True):
        # 들어온 뒤로는 게임을 뒤로 보내고 하던 창을 돌려준다 (사용자 — 어비스 반복과 같다). 키는 창에 직접 간다
        bot.background = True
        bot.window.give_back(bot.user_window)
    cleared = []
    # 드릴 안 전체를 보스전으로 친다
    skills = BossSkills.for_current(bot, bot.character, lambda s: s.channel_type == MAP)
    if skills.enabled:
        bot.log.info(f"드릴에서 쓸 것: {skills.describe()}")
    while True:
        bot.step("drill_play", f"나이트메어 드릴 진행 중{f' ({cleared[-1] + 1}구역)' if cleared and cleared[-1] > 0 else ''}")
        zone = wait_zone(bot, skills)
        if zone <= 0:
            bot.log.warning(f"드릴 구역을 못 깸 → 나감 ({bot.snapshot('drill_fail').name})")
            leave(bot)
            best = cleared[-1] if cleared and cleared[-1] > 0 else (packet_best(bot) or 0)
            raise CannotProceed(f"{best + 1 if best else '다음'}구역을 제한 시간 안에 못 깸 (최고 {best}구역)")
        cleared.append(zone)
        bot.log.info(f"드릴 {zone}구역 클리어")
        bot.sleep(1.0, 1.5)
        if zone >= GOAL:
            bot.step("drill_leave", f"{zone}구역까지 깸 → 나가기")
            leave(bot)
            return f"{zone}구역까지 클리어" + (f" (이번에 {len(cleared)}구역)" if len(cleared) > 1 else "")
        bot.key("space")  # 다음으로
        bot.wait_packet(lambda s: not s.drill_result, 15, since=bot.input_mark)


def run(bot: Bot, cfg: dict) -> str:
    bot.background = False
    if inside(bot):
        bot.log.info("이미 나이트메어 드릴 안 → 이 구역부터")
        return _play_behind(bot)
    # 드릴은 끝·초기화 시기가 정해져 있지 않다 → 저장해 둔 기록이 아니라 매번 지금 기록으로 본다 (사용자)
    best = packet_best(bot)
    if best is not None and best >= GOAL:
        return f"이미 {best}구역까지 깸 — 입장하지 않음"
    zone = open_window(bot)
    if zone is None and best is None:
        bot.to_main()
        raise CannotProceed(f"드릴 창에서 다음 구역을 읽지 못함 → {bot.snapshot('drill').name}")
    if zone is not None:
        bot.log.info(f"드릴 창: 다음 도전 {zone}구역" + (f" (패킷 최고 기록 {best}구역)" if best is not None else ""))
        if zone > GOAL:
            bot.to_main()
            return f"이미 {zone - 1}구역까지 깸 — 입장하지 않음"
    enter(bot)
    skip_cutscene(bot)
    return _play_behind(bot)


def _play_behind(bot: Bot) -> str:
    try:
        return play(bot)
    finally:
        bot.background = False


def verify(bot: Bot, cfg: dict) -> bool:
    """목표(20구역)까지 깼나 — 패킷 최고 기록, 모르면 드릴 창의 다음 도전 구역."""
    best = packet_best(bot)
    if best is not None:
        return best >= GOAL
    zone = open_window(bot)
    bot.to_main()
    return zone is not None and zone > GOAL
