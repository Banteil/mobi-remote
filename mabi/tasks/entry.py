"""어비스·레이드 입장 창 (둘이 같은 모양) — 입장 창인가 · 지금 탭 · 버튼 · '우연한 만남' 을 한 곳에서 본다.

화면 위 가운데 '혼자하기 / 함께하기' 탭은 연속 실행 제한 창이 가리는 자리라 (data/ui.json covers) 판단에 쓰지 않는다
(2026-11-10 친구 PC: 전멸 뒤 입장 창이 떴는데 탭이 가려져 입장 창으로 못 보고 74분 멈춤).
  · 입장 창인가 — 오른쪽 아래 버튼(입장하기 · 출항하기 · 이동하기) 또는 그 위 '주요 전리품'
  · 지금 탭     — '우연한 만남' 스위치는 함께하기 탭에만 있다 (혼자하기는 매칭이 없다)
탭 글자는 누를 때만 쓴다. 가려서 못 누르는데 탭이 원하는 쪽이 아니면 CannotProceed (게임을 다시 켜야 풀린다).
"""
import time
from dataclasses import dataclass

from .. import gamedata as gd
from ..bot import Bot
from ..ocr import find_texts, nospace
from . import ui_text
from .content import CannotProceed

BUTTONS = (("abyss_enter", "enter"), ("raid_sail", "sail"), ("abyss_move", "move"))  # ui.json 문구 → 버튼
SWITCH_DX = 95  # '우연한 만남' 글자 가운데 → 스위치 가운데 (1920 기준)


@dataclass
class Entry:
    button: str  # enter(입장하기) · sail(출항하기) · move(이동하기) · ''(버튼 없음 — 매칭 중 등)
    chance: tuple[bool, tuple[int, int]] | None  # '우연한 만남' 스위치 (켜짐, 자리). 없으면 혼자하기 탭

    @property
    def together(self) -> bool:
        return self.chance is not None


def parse(frame) -> Entry | None:
    """이 화면이 입장 창이면 Entry, 아니면 None — 오른쪽 아래를 한 번 읽어(OCR) 버튼·전리품·우연한 만남을 같이 본다.
    매칭 중 화면(필드 + 오른쪽 '우연한 만남' 창)은 버튼도 '주요 전리품' 도 없어 입장 창이 아니다."""
    hits = [(nospace(t), x, y) for t, x, y in find_texts(frame, gd.region("abyss_entry_right"))]
    texts = {t for t, _, _ in hits}
    button = next((b for key, b in BUTTONS if nospace(gd.text(key)) in texts), "")
    if not button and nospace(gd.text("entry_loot")) not in texts:
        return None
    label = next(((x, y) for t, x, y in hits if t == nospace(gd.text("abyss_chance"))), None)
    return Entry(button, (_switch_on(frame, label), (label[0] + SWITCH_DX, label[1])) if label else None)


def _switch_on(frame, label: tuple[int, int]) -> bool:
    """스위치가 켜져 있나 (켜지면 초록)."""
    x, y = label[0] + SWITCH_DX, label[1]
    patch = frame[y - 6:y + 6, x - 20:x + 20].reshape(-1, 3).astype(int)
    return bool(((patch[:, 1] > 150) & (patch[:, 2] < 120) & (patch[:, 0] < 150)).mean() > 0.2)


def read(bot: Bot) -> Entry | None:
    return parse(bot.frame())


def visible(bot: Bot) -> bool:
    return read(bot) is not None


def wait(bot: Bot, timeout: float) -> Entry | None:
    """입장 창이 뜰 때까지 (최대 timeout 초)."""
    end = time.monotonic() + timeout
    while True:
        e = read(bot)
        if e or time.monotonic() > end:
            return e
        bot.sleep(0.8, 1.2)


def button(bot: Bot) -> str:
    e = read(bot)
    return e.button if e else ""


def chance(bot: Bot) -> tuple[bool, tuple[int, int]] | None:
    """'우연한 만남' 스위치 (켜짐, 자리). 함께하기 탭 입장 창이 아니면 None."""
    e = read(bot)
    return e.chance if e else None


def wait_button(bot: Bot, read=None, tries: int = 5) -> str:
    """오른쪽 아래 버튼이 그려질 때까지 몇 번 본다 → 버튼 이름, 끝내 없으면 ''. read: 버튼 읽기 (기본은 이 입장 창의
    button — 나이트메어 드릴 창처럼 버튼 자리만 다른 창은 그 읽기를 넘긴다)."""
    read = read or button
    for _ in range(tries):
        if (got := read(bot)):
            return got
        bot.sleep(1.0, 1.4)
    return ""


def ensure_chance(bot: Bot, shot: str) -> None:
    """함께하기 탭 '우연한 만남' 스위치를 켠다 (어비스·레이드 입장 창이 같은 자리·모양). 못 찾거나 안 켜지면 CannotProceed."""
    on = chance(bot)
    if on is None:
        raise CannotProceed(f"'우연한 만남' 을 찾지 못함 → {bot.snapshot(shot).name}")
    if not on[0]:
        bot.click(on[1])
        bot.sleep(1.0, 1.3)
        on = chance(bot)
        if not on or not on[0]:
            raise CannotProceed(f"'우연한 만남' 을 켜지 못함 → {bot.snapshot(shot).name}")
        bot.log.info("우연한 만남 켬")


def _settled(bot: Bot, timeout: float = 3) -> Entry | None:
    """버튼까지 그려진 입장 창 — 스위치는 버튼과 같은 칸이라 버튼이 보이면 같이 그려져 있다. 끝내 버튼이 없으면 마지막 것."""
    end = time.monotonic() + timeout
    while True:
        e = read(bot)
        if (e and e.button) or time.monotonic() > end:
            return e
        bot.sleep(0.5, 0.8)


def set_tab(bot: Bot, solo: bool, shot: str) -> None:
    """탭을 혼자하기(solo) 또는 함께하기로 맞춘다. 탭 글자가 보이면 누르고(이미 골라져 있어도 해가 없다) 바뀌었나 스위치로 본다.
    글자가 안 보이면(연속 실행 제한 창이 가림 등) 지금 탭을 스위치로 보고 원하는 쪽이면 그대로 간다."""
    name = "혼자하기" if solo else "함께하기"
    for attempt in range(4):
        hit = ui_text.find(bot, gd.text("raid_solo" if solo else "abyss_together"), gd.region("abyss_entry_top"), exact=False)
        if hit:
            break
        e = _settled(bot) if attempt == 0 else read(bot)
        if e and e.together != solo:
            bot.log.info(f"입장 창 탭 글자가 안 보임 — 이미 {name} 탭 (우연한 만남 {'있음' if e.together else '없음'})")
            return
        bot.sleep(1.0, 1.4)  # 바꿔야 하는데 글자를 못 읽음 — 막 뜬 창이면 다시 본다
    else:
        why = " — 연속 실행 제한 창이 탭을 가림 (게임을 다시 켜야 함)" if bot.run_limit_popup() else ""
        raise CannotProceed(f"'{name}' 탭을 누르지 못함{why} → {bot.snapshot(shot).name}")
    for attempt in range(2):
        bot.click(hit)
        bot.sleep(1.2, 1.6)
        e = _settled(bot)
        if e and e.together != solo:
            return
        bot.log.info(f"'{name}' 탭을 눌렀는데 아직 {'함께하기' if solo else '혼자하기'} 모양 ({attempt + 1}/2)")
    raise CannotProceed(f"'{name}' 탭으로 바뀌지 않음 → {bot.snapshot(shot).name}")
