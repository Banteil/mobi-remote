"""가공 재료표 alter-recipes.json — 사람이 정리한 완전한 표 (리모콘 src/altertable.js).

장부(recipe-book)는 게임이 흘린 "모자란 재료"만 모은 관측이라 군데군데 비고 레벨·시간을 모른다.
이 표는 재료·레벨·시간이 다 있어서, 이름이 표에 있으면 장부와 합치지 않고 갈아끼운다.

이름 두 가지: 표는 산출물 이름, 게임에 시킬 때는 레시피 이름. 갈래가 여럿이면 게임이 괄호로 구분하기도 하지만
(철괴(광석)) 실측상 그런 건 철괴뿐이고, 은합금괴·최상급 가죽/목재/옷감은 같은 이름 하나로 온다.
execute_altering 본문은 {"displayName"} 뿐이라 갈래를 고를 수단이 없고, 시키면 언제나 목록의 첫 줄이 돈다.
그래서 이름을 지어내지 않고, 이름으로 못 가리는 가공품은 0번 갈래만 후보로 둔다.
"""
import json
import re
from pathlib import Path

_PAREN = re.compile(r"^(.*?)\s*\((.+)\)$")


def split_recipe_name(s) -> tuple[str, str] | None:
    """'철괴(광석)' → ('철괴', '광석'). 괄호가 없으면 None"""
    m = _PAREN.match(str(s or "").strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else None


class AlterTable:
    def __init__(self, file: Path):
        self.file = file
        self._cached: dict | None = None

    def load(self) -> dict:
        if self._cached is not None:
            return self._cached
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            self._cached = (d.get("recipes") if isinstance(d, dict) else None) or {}
        except (OSError, ValueError):
            self._cached = {}  # 표가 없거나 깨져도 장부만으로 계속 돈다
        return self._cached

    def reload(self) -> dict:
        self._cached = None
        return self.load()

    def get(self, product) -> dict | None:
        return self.load().get(product)

    def has(self, product) -> bool:
        return bool(self.load().get(product))

    def names(self) -> list[str]:
        return list(self.load().keys())

    def for_recipe(self, recipe_name) -> dict | None:
        """게임 레시피 이름으로 표의 갈래를 찾는다. 괄호가 이름의 일부인 경우(광휘의 결정(유령 반딧불이))가 있어
        이름 그대로 찾는 쪽을 먼저 본다. {product, entry, index(-1 = 못 가림)}"""
        tbl = self.load()
        direct = tbl.get(recipe_name)
        if direct:
            return {"product": recipe_name, "entry": direct, "index": 0 if len(direct["variants"]) == 1 else -1}
        p = split_recipe_name(recipe_name)
        if not p or not tbl.get(p[0]):
            return None
        entry = tbl[p[0]]
        i = next((i for i, v in enumerate(entry["variants"]) if p[1] in v["ingredients"]), -1)
        return {"product": p[0], "entry": entry, "index": i} if i >= 0 else None

    def recipe_name_of(self, product, index, known=None) -> dict:
        """갈래 하나를 게임에 시킬 이름으로. 게임이 실제로 쓰는 이름(known)에 있을 때만 괄호를 붙인다 —
        없는 이름을 만들어 시키면 그냥 실패한다. {name, ambiguous}"""
        e = self.get(product)
        if not e or len(e["variants"]) <= 1:
            return {"name": product, "ambiguous": False}
        vs = e["variants"]
        v = vs[index] if isinstance(index, int) and 0 <= index < len(vs) else vs[0]
        others = [o for i, o in enumerate(vs) if i != index]
        # 다른 갈래에는 없는 재료가 그 갈래의 이름표가 된다
        mark = next((k for k in v["ingredients"] if all(k not in o["ingredients"] for o in others)), None)
        guess = f"{product}({mark})" if mark else None
        if guess and known is not None and guess in known:
            return {"name": guess, "ambiguous": False}
        return {"name": product, "ambiguous": True}

    def variants_for(self, product, levels=None) -> dict | None:
        """지금 시설 레벨로 돌릴 수 있는 갈래들. 하나도 없어도 all 을 같이 준다 —
        "레벨이 모자라 못 한다"와 "그런 레시피가 없다"는 화면에 다르게 적어야 한다."""
        e = self.get(product)
        if not e:
            return None
        lv = levels or {}
        runnable = []
        for i, v in enumerate(e["variants"]):
            have = lv.get(v.get("facility"))
            if v.get("level") is None or (have is not None and have >= v["level"]):
                runnable.append(i)
        return {"entry": e, "runnable": runnable, "all": list(range(len(e["variants"])))}

    def selectable(self, product, known=None) -> list[int]:
        """실제로 골라서 시킬 수 있는 갈래 번호들. 이름이 하나뿐이면 첫 줄만 도니까 0번 하나뿐."""
        e = self.get(product)
        if not e:
            return []
        if len(e["variants"]) <= 1:
            return [0]
        out = [i for i in range(len(e["variants"])) if not self.recipe_name_of(product, i, known)["ambiguous"]]
        return out or [0]

    def match_row(self, recipe_name, missing=None, nth=0) -> dict | None:
        """목록의 한 줄을 표의 갈래에 맞춘다. 이름이 같은 줄이 여럿 오는 레시피(은합금괴 Lv.4/Lv.6)가 있어서
        1) 그 갈래에만 있는 재료가 모자란 목록에 있으면 그 갈래, 2) 아니면 나온 차례대로 (CLI 순서 = 표 순서)."""
        hit = self.for_recipe(recipe_name)
        if not hit:
            return None
        vs = hit["entry"]["variants"]
        if hit["index"] >= 0:
            return {"product": hit["product"], "index": hit["index"], "variant": vs[hit["index"]]}
        if len(vs) == 1:
            return {"product": hit["product"], "index": 0, "variant": vs[0]}
        miss = set(missing or [])
        if miss:
            only = [[k for k in v["ingredients"] if all(j == i or k not in o["ingredients"] for j, o in enumerate(vs))]
                    for i, v in enumerate(vs)]
            hits = [i for i, keys in enumerate(only) if any(k in miss for k in keys)]
            if len(hits) == 1:
                return {"product": hit["product"], "index": hits[0], "variant": vs[hits[0]]}
        i = min(max(0, nth or 0), len(vs) - 1)
        return {"product": hit["product"], "index": i, "variant": vs[i]}
