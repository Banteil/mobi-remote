"""여러 신호로 판단하기 — 패킷·CLI·화면을 함께 보고 우선순위로 고른다.

예전엔 패킷이 알면 패킷만 보고, 모를 때만 CLI·화면을 봤다. 패킷이 끊겨 어비스 결과를 놓치자 보상 화면이 눈에 보이는데도
판 안으로 보고 다음 판을 통째로 놓쳤다 (2026-11-03 19:26). 사용자: "오직 패킷에만 판단을 의존하지 말고, 동시에
여러가지로 판단을 하되 우선 순위에 맞춰 판단을 하는 식으로".

- 신호(Sign)마다 아는 값 하나 또는 모름(None) 을 낸다. 모두 본다.
- 우선순위가 높은 순서로 처음 아는 값을 따른다.
- 아는 신호끼리 어긋나면 무엇을 따랐는지 남긴다 (같은 어긋남은 한 번) — 패킷이 틀린 때가 로그에 바로 보이게.
"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Sign:
    src: str                       # 신호 이름 — '패킷 결과', '화면 보상' 처럼 로그에 그대로
    value: object = None           # 아는 값, 모르면 None
    why: str = ""


@dataclass
class Verdict:
    value: object
    by: Sign | None
    signs: list[Sign] = field(default_factory=list)

    @property
    def known(self) -> list[Sign]:
        return [s for s in self.signs if s.value is not None]

    def text(self) -> str:
        return " · ".join(f"{s.src}={s.value}" for s in self.known) or "모두 모름"


def decide(bot, name: str, checks: list[tuple[str, Callable[[], object]]],
           same: dict | None = None) -> Verdict:
    """checks: 우선순위 순서의 (신호 이름, 값을 내는 함수). 함수는 아는 값 또는 None.
    same: 어긋남으로 치지 않는 값 묶음 {따른 값: {같이 있어도 되는 값, ...}} — 예: 매칭 중엔 보상 화면이 남아 있다."""
    signs = []
    for src, fn in checks:
        try:
            v = fn()
        except Exception as e:  # noqa: BLE001 — 신호 하나가 실패해도 나머지로 판단한다
            bot.log.debug(f"판단 {name}: {src} 신호 실패 ({e})")
            v = None
        signs.append(Sign(src, v))
    by = next((s for s in signs if s.value is not None), None)
    verdict = Verdict(by.value if by else None, by, signs)
    ok = {verdict.value} | set((same or {}).get(verdict.value, ()))
    odd = [s for s in verdict.known if s.value not in ok]
    seen = vars(bot).setdefault("_judge_conflicts", {})
    key = (verdict.value, tuple((s.src, s.value) for s in odd))
    if odd and seen.get(name) != key:
        bot.log.info(f"판단 {name}: {by.src} 를 따라 '{verdict.value}' — 어긋난 신호 "
                     + " · ".join(f"{s.src}={s.value}" for s in odd))
    seen[name] = key if odd else None
    return verdict
