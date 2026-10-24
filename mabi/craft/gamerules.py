"""게임 쪽 규칙 표 game-rules.json (리모콘 src/gamerules.js).

커넥터가 알려주지 않지만 프로그램이 알아야 하는 값 — 지금은 가공 시설의 레벨별 칸 수 하나뿐이다.
코드에 박으면 패치 때마다 다시 빌드해야 해서 파일로 뺐다.
파일이 없거나 깨져도 프로그램은 떠야 하므로 같은 내용을 기본값으로 들고 있다가 그쪽으로 떨어진다.
"""
import json
import math
from pathlib import Path

# 파일을 못 읽었을 때 쓰는 값. game-rules.json 과 같은 내용을 유지할 것
FALLBACK = {"alteringFacility": {"maxLevel": 6, "slotsByLevel": {"1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7}}}


def js_round(x) -> int:
    """JS Math.round (0.5 는 위로). 파이썬 round 는 짝수 쪽으로 가서 값이 어긋난다."""
    return math.floor(x + 0.5)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


class GameRules:
    def __init__(self, file: Path):
        self.file = file
        self._cached: dict | None = None
        self._fallback = False

    def load(self) -> dict:
        if self._cached:
            return self._cached
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            f = raw.get("alteringFacility")
            # 최소한의 형태 검사. 깨진 값으로 칸 수를 계산하면 날개가 헛나간다
            if not f or not (_num(f.get("maxLevel")) > 0) or not f.get("slotsByLevel") \
                    or not (_num(f["slotsByLevel"].get("1")) > 0):
                raise ValueError("alteringFacility 형식이 올바르지 않습니다")
            self._cached, self._fallback = raw, False
        except (OSError, ValueError, AttributeError, TypeError):
            self._cached, self._fallback = FALLBACK, True
        return self._cached

    def altering_facility(self) -> dict:
        """{maxLevel, slotsByLevel}"""
        return self.load()["alteringFacility"]

    def _slot(self, lv) -> int | None:
        v = self.altering_facility()["slotsByLevel"].get(str(lv))
        return v if isinstance(v, (int, float)) and v > 0 else None

    def slots_for_level(self, level) -> int:
        """레벨 → 칸 수. 표에 없는 레벨은 최고 레벨 값으로 맞춘다."""
        f = self.altering_facility()
        x = _num(level)
        n = js_round(x) if not math.isnan(x) else None
        if n is None or not n >= 1:
            return self._slot(1)
        return self._slot(n) or self._slot(f["maxLevel"]) or self._slot(1)

    def level_for_slots(self, slots) -> int | None:
        """칸 수 → 레벨. 화면에 "지금 몇 레벨로 보고 있는지" 적을 때. 없으면 None."""
        for lv in range(1, self.max_level() + 1):
            if self.slots_for_level(lv) == slots:
                return lv
        return None

    def max_level(self) -> int:
        return int(self.altering_facility()["maxLevel"])

    def is_fallback(self) -> bool:
        """규칙 파일을 못 읽어 기본값으로 도는 중인가 (화면에 알릴 때)."""
        self.load()
        return self._fallback
