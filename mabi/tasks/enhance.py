"""각인 강화 반복 (기타 숙제): 열어 둔 각인 강화 창에서 Space(강화하기)를 성공할 때까지 누른다 (사용자, 2026-11-09).
어디로 찾아가지 않는다 — 창은 사람이 열어 둔다. 게임이 뒤에 있어도 된다 (키는 창에 직접 — 어비스 반복과 같다).

창·노리는 단계: 오른쪽 아래 버튼 글자 '+N 강화하기' (Space 배지) — N 이 이번에 노리는 단계.
결과는 패킷 (caps/enhance1, 2026-11-07 13번):
  한 번 강화될 때마다 장비 갱신(equip.update)과 강화 응답(equip.carving_enhance_ok)이 같이 온다 (갱신이 먼저).
  응답 본문은 암호화돼 있어 못 읽는다 → 성공·실패는 장비 갱신의 각인 강화 단계로 본다. 실패면 그대로(강화 포인트만 오름), 성공이면 N.
  거절 응답(골드·재료 부족·최대 단계 등)이 오면 바로 멈춘다 (사용자).
연출(불 3칸) 중에 누른 Space 로는 강화되지 않는다 — 응답이 없으면 다시 누른다. 한동안 눌러도 한 번도 안 되면 멈춘다.
골드·재료 소모량은 보지 않는다 (사용자 — 고정이 아님).
"""
import re
import time

from .. import gamedata as gd
from ..bot import Bot
from ..ocr import find_texts, nospace
from .content import CannotProceed

PRESS_WAIT = 1.0   # 누른 뒤 강화 응답을 기다리는 시간 (보통 0.1초 안에 온다 — 연출 중에 눌렀으면 안 온다)
RESULT_WAIT = 3.0  # 강화 응답 뒤 장비 갱신 (같이 온다)
QUIET = 20         # 이만큼 눌러도 한 번도 강화되지 않으면 멈춘다 (창이 닫힘·게임이 보내기 전에 막음 등)
_NEXT = re.compile(r"\+(\d+)강화하기")


def next_level(bot: Bot) -> int | None:
    """각인 강화 창이 떠 있으면 이번에 노리는 단계 (버튼 '+N 강화하기' 의 N), 아니면 None."""
    for t, _, _ in find_texts(bot.frame(), gd.region("enhance_button")):
        m = _NEXT.search(nospace(t))
        if m:
            return int(m.group(1))
    return None


def repeat(bot: Bot, on_try=None) -> dict:
    """성공할 때까지 Space. {'tries': 강화된 횟수, 'level': 오른 단계}. 성공 못 하고 멈추면 CannotProceed.
    on_try(tries, target) — 실패 한 번마다."""
    target = next_level(bot)
    if target is None:
        raise CannotProceed(f"각인 강화 창이 열려 있지 않음 — 창을 열어 두고 시작하세요 ({bot.snapshot('enhance_none').name})")
    if not bot.packets.ok:
        raise CannotProceed("패킷 감시가 꺼져 있어 성공을 알아볼 수 없음 — 누르지 않음")
    bot.log.info(f"각인 강화 +{target} 를 성공할 때까지 Space")
    tries, item, last = 0, None, time.monotonic()
    while True:
        mark = bot.packets.mark()
        bot.key("space")
        got = bot.packets.wait(("equip.carving_enhance_ok", "equip.carving_enhance_fail"), PRESS_WAIT, after=mark)
        if got is None:
            if not bot.packets.ok:
                raise CannotProceed(f"패킷이 끊겨 결과를 알 수 없음 → 멈춤 ({tries}번 강화)")
            if time.monotonic() - last > QUIET:
                why = "각인 강화 창이 닫힘" if next_level(bot) is None else f"{QUIET}초 동안 눌러도 강화되지 않음 (골드·재료 부족 등)"
                raise CannotProceed(f"{why} ({tries}번 강화, {bot.snapshot('enhance_quiet').name})")
            continue
        if got.key == "equip.carving_enhance_fail":
            raise CannotProceed(f"강화 거절 — 골드·재료 부족 등 ({tries}번 강화)")
        tries, last = tries + 1, time.monotonic()
        eq = bot.packets.wait("equip.update", RESULT_WAIT, after=mark,
                              check=lambda v: item is None or v.get("id") == item)
        level = eq.vals.get("carving_level") if eq else None
        if level not in (target - 1, target):  # 결과를 못 읽었거나 화면과 안 맞음 — 더 누르면 다음 단계를 강화할 수 있다
            raise CannotProceed(f"{tries}번째 결과를 알 수 없음 (패킷 단계 {level}, 화면 +{target}) → 멈춤")
        if level == target:
            bot.log.info(f"각인 강화 +{target} 성공 ({tries}번째)")
            return {"tries": tries, "level": level}
        item = eq.vals.get("id")
        bot.log.info(f"각인 강화 +{target} 실패 ({tries}번째)")
        if on_try:
            on_try(tries, target)
