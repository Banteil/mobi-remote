"""가공 레시피 → 시설 표 facility-map.json (리모콘 src/facilitymap.js).

커넥터가 주지 않는 정보라 파일로 들고 있는다. 실제로 큐에서 본 값(knowledge 의 itemFacility)이 항상 이긴다 —
이 표는 아직 돌려 본 적 없는 레시피용 보조라, 틀려도 한 번 써 보면 관측값으로 덮인다.
파일이 없거나 깨지면 빈 표로 돈다 (처음 돌리는 레시피만 미리 검사 못 할 뿐).
"""
import json
from pathlib import Path


class FacilityMap:
    def __init__(self, file: Path):
        self.file = file
        self._cached: dict | None = None
        self._broken = False

    def load(self) -> dict:
        if self._cached:
            return self._cached
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            self._cached = {"facilities": raw.get("facilities") if isinstance(raw.get("facilities"), list) else [],
                            "recipes": raw.get("recipes") if isinstance(raw.get("recipes"), dict) else {}}
            self._broken = False
        except (OSError, ValueError, AttributeError):
            self._cached, self._broken = {"facilities": [], "recipes": {}}, True
        return self._cached

    def facility_of(self, recipe_name) -> str | None:
        if not recipe_name:
            return None
        return self.load()["recipes"].get(recipe_name) or None

    def facilities(self) -> list[str]:
        """게임에 있는 가공 시설 이름들"""
        return list(self.load()["facilities"])

    def size(self) -> int:
        return len(self.load()["recipes"])

    def is_broken(self) -> bool:
        self.load()
        return self._broken
