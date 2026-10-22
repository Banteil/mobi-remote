"""레시피 장부 — 게임이 알려 준 재료 표를 모아 둔 곳 (리모콘 src/recipebook.js).

게임은 지금 만들 수 없는 레시피에만, 그것도 모자란 재료만 알려준다. 그 표를 미리 채워 같이 배포한다.
세 겹이고 위가 세다:
  3. 가공 재료표(alter-recipes.json) — 사람이 정리한 완전한 사실. 이름이 표에 있으면 통째로 갈아끼운다
  2. 내 수확분(데이터 폴더 recipe-book.json) — 이 계정에서 게임이 흘린 것
  1. 배포 씨앗(리소스 data\\recipe-book.json)
1과 2는 같은 종류의 관측("모자란 재료만")이라 이름마다 합친다.

한 이름에 조합이 여럿일 수 있다 (실측 1,834줄 중 79개, 많게는 3갈래). 이름 하나에 몰아 담으면
둘을 합친 가짜 레시피가 되므로 조합(variant)을 따로 담고, 확인되기 전에는 complete=False 로 둔다.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .altertable import AlterTable


def now_iso() -> str:
    """JS new Date().toISOString() 과 같은 꼴 (UTC, 밀리초, Z)"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read(f: Path) -> dict | None:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d["recipes"] if isinstance(d, dict) and isinstance(d.get("recipes"), dict) else None
    except (OSError, ValueError):
        return None  # 없거나 깨졌으면 없는 것으로 친다. 앱은 계속 돌아야 한다


def fits_into(a: dict, b: dict) -> bool:
    """a 가 b 의 부분집합이고 겹치는 값이 전부 같은가"""
    return all(k in b and b[k] == a[k] for k in a)


def compatible(a: dict, b: dict) -> bool:
    """겹치는 재료의 요구량이 전부 같은가. 겹치는 것이 없으면 True"""
    return all(k not in b or b[k] == a[k] for k in a)


def _variants(e) -> list:
    return [v for v in (e.get("variants") or []) if v and v.get("ingredients")]


def absorb_group(lst: list, sets: list[dict], single: bool) -> int:
    """이번에 본 재료 줄들을 조합 목록에 합친다.

    두 관측이 같은 조합의 다른 조각인지 다른 조합인지 원리적으로 구분할 수 없다. 붙잡을 수 있는 사실은 하나 —
    한 번의 조회 안에서는 줄 하나가 곧 조합 하나다.
      한 줄뿐 → 갈래도 하나. 본 것을 전부 합집합으로 쌓는다.
      여러 줄 → 같은 조회의 줄끼리는 절대 합치지 않고, 어긋나지 않으면서 가장 많이 겹치는 예전 갈래 하나에만 붙인다.
    """
    added = 0
    if single:
        seen = sets[0]
        if not lst:
            lst.append({"ingredients": dict(seen), "complete": False})
            return 1
        fit = next((v for v in lst if compatible(seen, v["ingredients"])), None)
        if fit:
            fit["ingredients"].update(seen)
        else:
            lst.append({"ingredients": dict(seen), "complete": False})
            added += 1
        return added

    used: list = []  # 한 갈래는 한 줄에게만 (dict 는 해시가 안 되므로 id 로 본다)
    for seen in sets:
        best, best_share = None, 0
        for v in lst:
            if any(v is u for u in used) or not compatible(seen, v["ingredients"]):
                continue
            share = sum(1 for k in seen if k in v["ingredients"])
            if share > best_share:
                best, best_share = v, share
        if best is not None and best_share > 0:
            used.append(best)
            best["ingredients"].update(seen)
        else:
            fresh = {"ingredients": dict(seen), "complete": False}
            lst.append(fresh)
            used.append(fresh)
            added += 1
    return added


def merge_entry(seed, mine):
    """씨앗과 내 수확분을 이름마다 합친다. 내 것이 통째로 덮으면 "조합 없음"이 씨앗의 재료까지 가린다."""
    if not seed:
        return mine
    if not mine:
        return seed
    sv, mv = _variants(seed), _variants(mine)
    if not sv:
        return {**seed, **mine, "variants": mv}
    if not mv:
        return {**seed, **mine, "variants": sv}
    out = copy.deepcopy(mv)
    single = len(sv) == 1 and len(mv) == 1  # 둘 다 한 갈래면 같은 레시피의 다른 조각
    for v in sv:
        absorb_group(out, [v["ingredients"]], single)
    for v in sv:
        if not v.get("complete"):
            continue
        fit = next((x for x in out if compatible(x["ingredients"], v["ingredients"])), None)
        if fit:
            fit["ingredients"] = dict(v["ingredients"])
            fit["complete"] = True
    return {**seed, **mine, "variants": out}


def merge_rows(book: dict, rows: list, via: str, ok_key: str, per_key: str, known: dict | None) -> dict:
    """목록 한 벌을 표에 합친다. 더하기만 한다 — 재고를 채워 목록에서 사라진 재료를 "이제 안 든다"로 읽으면 표가 망가진다."""
    stat = {"rows": 0, "named": 0, "lines": 0, "newNames": 0, "newVariants": 0, "completed": 0}
    by_name: dict[str, list] = {}
    for r in rows:
        if r.get("DisplayName"):
            by_name.setdefault(r["DisplayName"], []).append(r)

    for name, group in by_name.items():
        stat["rows"] += len(group)
        e = book.get(name)
        if not e:
            e = book[name] = {"via": via, "per": group[0].get(per_key) or 1, "variants": []}
            stat["newNames"] += 1
        e["via"] = via
        if group[0].get(per_key):
            e["per"] = group[0][per_key]
        if not isinstance(e.get("variants"), list):
            e["variants"] = []

        sets = []
        for r in group:
            miss = r.get("MissingIngredients") if isinstance(r.get("MissingIngredients"), list) else []
            if not miss:
                continue
            seen = {}
            for m in miss:
                if m.get("DisplayName"):
                    seen[m["DisplayName"]] = m.get("Required")
                    stat["lines"] += 1
            if seen:
                sets.append(seen)
                stat["named"] += 1
        if sets:
            stat["newVariants"] += absorb_group(e["variants"], sets, len(group) == 1)

        # 실제로 만들어 보고 알아낸 값이 있으면 그 조합은 완전하다. 어긋나지 않는 조합에만 붙인다
        k = (known or {}).get(name)
        if k and k.get("ingredients") and k.get("confidence") in ("diff", "confirmed"):
            fit = next((v for v in e["variants"] if compatible(v["ingredients"], k["ingredients"])), None)
            if fit:
                fit["ingredients"] = dict(k["ingredients"])
                if not fit.get("complete"):
                    fit["complete"] = True
                    stat["completed"] += 1
            else:
                e["variants"].append({"ingredients": dict(k["ingredients"]), "complete": True})
                stat["completed"] += 1
    return stat


class RecipeBook:
    def __init__(self, seed_file: Path, user_file: Path, altertable: AlterTable):
        self.seed_file, self.user_file, self.alt = seed_file, user_file, altertable
        self._cached: dict | None = None

    def load(self) -> dict:
        if self._cached:
            return self._cached
        seed = _read(self.seed_file) or {}
        mine = _read(self.user_file) or {}
        recipes = dict(seed)
        for k in mine:
            recipes[k] = merge_entry(seed.get(k), mine[k])
        # 가공 재료표에 있는 이름은 표로 갈아끼운다 (완전한 것에 불완전한 것을 섞으면 나빠지기만 한다)
        from_table = 0
        for product in self.alt.names():
            e = self.alt.get(product)
            recipes[product] = {"via": "alter", "per": e.get("per"), "fromTable": True,
                                "variants": [{"ingredients": dict(v["ingredients"]), "complete": True,
                                              "facility": v.get("facility"), "level": v.get("level"),
                                              "sec": v.get("sec")} for v in e["variants"]]}
            from_table += 1
        self._cached = {"recipes": recipes, "seedCount": len(seed), "userCount": len(mine), "tableCount": from_table}
        return self._cached

    def reload(self) -> dict:
        self._cached = None
        return self.load()

    def recipe(self, name) -> dict | None:
        """{via, per, variants: [{ingredients, complete}]} 또는 None"""
        if not name:
            return None
        return self.load()["recipes"].get(str(name))

    def pick(self, name, have: Callable[[str], int] | None = None) -> dict | None:
        """지금 재고로 가장 가까운 조합. 어느 조합으로 만들지는 게임이 정하므로(지정 인자 없음) 이건
        "무엇을 모아야 하나"를 말하기 위한 짐작이다. 개수를 아는 재료가 많은 쪽, 같으면 모자란 양이 적은 쪽."""
        e = self.recipe(name)
        if not e or not isinstance(e.get("variants"), list) or not e["variants"]:
            return None
        get = have if callable(have) else (lambda _n: 0)
        best = None
        for v in e["variants"]:
            ing = v.get("ingredients")
            if not ing:
                continue
            # 개수가 None 인 재료는 이름만 아는 것 (재료 훑기로 알아냄) — 점수에서 뺀다
            lack = known = unknown = 0
            for k, need in ing.items():
                if need is None:
                    unknown += 1
                    continue
                known += 1
                lack += max(0, need - (get(k) or 0))
            if best is None or known > best["known"] or (known == best["known"] and lack < best["lack"]):
                best = {"ingredients": ing, "complete": bool(v.get("complete")), "lack": lack,
                        "known": known, "unknown": unknown}
        if best is None:
            return None
        best["count"] = len(e["variants"])
        best["per"] = e.get("per") or 1
        best["via"] = e.get("via")
        return best

    def save_user(self, recipes: dict) -> dict:
        """내 수확분을 저장한다. 배포 씨앗은 건드리지 않는다."""
        out = {"_설명": "이 계정에서 모은 레시피 표. 배포판의 recipe-book.json 보다 우선한다.",
               "_수확시각": now_iso(), "recipes": recipes}
        try:
            self.user_file.parent.mkdir(parents=True, exist_ok=True)
            self.user_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # 저장 실패가 조회를 막지 않는다
        self._cached = None
        return out

    def stats(self) -> dict:
        b = self.load()
        with_ing = complete = variants = 0
        for e in b["recipes"].values():
            vs = e.get("variants") or []
            variants += len(vs)
            if any(v.get("ingredients") for v in vs):
                with_ing += 1
            if any(v.get("complete") for v in vs):
                complete += 1
        return {"total": len(b["recipes"]), "withIngredients": with_ing, "complete": complete,
                "variants": variants, "seed": b["seedCount"], "mine": b["userCount"]}

    def harvest_rows(self, rows, via, ok_key, per_key, known) -> bool:
        """목록 한 벌에서 새로 알게 된 것을 내 표에 담는다. 바뀐 게 없으면 파일을 쓰지 않는다 (조회마다 수백 KB).
        깊은 복사여야 한다 — 얕으면 캐시 안의 variants 를 그대로 건드려 before/after 가 같아 보인다."""
        if not isinstance(rows, list) or not rows:
            return False
        recipes = copy.deepcopy(self.load()["recipes"])
        before = json.dumps(recipes, ensure_ascii=False, sort_keys=False)
        merge_rows(recipes, rows, via, ok_key, per_key, known)
        if json.dumps(recipes, ensure_ascii=False, sort_keys=False) == before:
            return False
        self.save_user(recipes)
        return True
