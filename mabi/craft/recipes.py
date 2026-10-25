"""레시피 표 recipes.json — 게임 데이터에서 뽑은 제작·가공 레시피 전체 (tools/build_recipes.py 로 만든다).

예전에는 게임이 흘린 "모자란 재료"를 모으고(recipe-book) 사람이 정리한 표(alter-recipes·craft-weapons)를 덧대
레시피를 짐작했다. 이제 게임이 쓰는 표 그대로라 재료·개수·시설 레벨·생활 스킬이 빠짐없이 있다.
그래서 목표를 받으면 해 보고 부족분을 보는 대신, 처음부터 사슬 끝까지 계산한다 (needs.py).

이름 두 가지:
- name: 게임 목록과 execute_* 에 쓰는 레시피 이름 (철괴(광석))
- product: 만들어지는 아이템 (철괴). 보유량은 이것으로 센다
같은 name 이 여럿인 레시피가 있다 (은합금괴 Lv.4/Lv.6, 무기 SS 단계 등). execute_* 본문은 {"displayName"} 뿐이라
갈래를 고를 수 없고 시키면 언제나 목록의 첫 줄이 돈다. 표의 줄 순서가 게임 목록 순서와 같으므로(실측)
같은 이름의 첫 줄만 "고를 수 있는" 레시피로 본다.

파일이 없거나 깨져도 앱은 뜬다 — 빈 표로 돌고, 판단은 게임이 알려 주는 부족분으로 떨어진다.
"""
import json
import re
from pathlib import Path

_TAG = re.compile(r"<[^>]*>")


def bare(s) -> str:
    """색 태그를 벗긴 이름 (게임 목록 이름에 붙어 올 때가 있다)"""
    return _TAG.sub("", str(s or "")).strip()


class RecipeTable:
    def __init__(self, file: Path):
        self.file = file
        self._rows: list[dict] | None = None
        self._by_name: dict[str, list[dict]] = {}
        self._by_product: dict[str, list[dict]] = {}

    def load(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            rows = [r for r in d.get("recipes") or [] if isinstance(r, dict) and r.get("name")]
        except (OSError, ValueError, AttributeError):
            rows = []
        by_name: dict[str, list[dict]] = {}
        by_product: dict[str, list[dict]] = {}
        for r in rows:
            r.setdefault("per", 1)
            r.setdefault("ingredients", {})
            same = by_name.setdefault(r["name"], [])
            r["nth"] = len(same)            # 같은 이름 안에서 몇 번째 줄인가 (0 = 시키면 도는 줄)
            same.append(r)
            by_product.setdefault(r.get("product") or r["name"], []).append(r)
        for same in by_name.values():
            for r in same:
                r["twins"] = len(same)      # 같은 이름의 줄 수. 2 이상이면 첫 줄만 고를 수 있다
        self._rows, self._by_name, self._by_product = rows, by_name, by_product
        return rows

    def reload(self) -> list[dict]:
        self._rows = None
        return self.load()

    def __len__(self) -> int:
        return len(self.load())

    # ---------------------------------------------------------------- 찾기
    def rows(self, name, via: str | None = None) -> list[dict]:
        """레시피 이름의 줄들 (게임 목록 순서)"""
        self.load()
        lst = self._by_name.get(bare(name)) or []
        return [r for r in lst if via is None or r["via"] == via]

    def first(self, name, via: str | None = None) -> dict | None:
        """시키면 실제로 도는 줄"""
        lst = self.rows(name, via)
        return lst[0] if lst else None

    def row_at(self, name, nth: int, via: str | None = None) -> dict | None:
        """게임 목록에서 같은 이름 중 nth 번째 줄 (목록 한 줄을 표에 맞출 때)"""
        lst = self.rows(name, via)
        return lst[nth] if 0 <= nth < len(lst) else (lst[0] if lst else None)

    def has(self, name) -> bool:
        return bool(self.rows(name))

    def makers(self, product) -> list[dict]:
        """이 아이템을 만드는 레시피 줄 전부 (고를 수 없는 갈래 포함)"""
        self.load()
        return list(self._by_product.get(bare(product)) or [])

    def selectable_makers(self, product) -> list[dict]:
        """실제로 시킬 수 있는 줄만 — 같은 이름의 둘째 줄부터는 시켜도 첫 줄이 돈다"""
        return [r for r in self.makers(product) if r["nth"] == 0]

    def is_product(self, name) -> bool:
        self.load()
        return bare(name) in self._by_product

    def product_of(self, recipe_name) -> str | None:
        r = self.first(recipe_name)
        return r.get("product") if r else None

    def facility_of(self, recipe_name) -> str | None:
        r = self.first(recipe_name)
        return r.get("facility") if r else None

    def facilities(self, via: str | None = None) -> list[str]:
        out: dict[str, None] = {}
        for r in self.load():
            if via is None or r["via"] == via:
                out.setdefault(r.get("facility"), None)
        return [f for f in out if f]

    def names(self, via: str | None = None) -> list[str]:
        self.load()
        return [n for n, lst in self._by_name.items() if via is None or any(r["via"] == via for r in lst)]

    def stats(self) -> dict:
        rows = self.load()
        return {"total": len(rows), "craft": sum(1 for r in rows if r["via"] == "craft"),
                "alter": sum(1 for r in rows if r["via"] == "alter"), "file": str(self.file)}
