"""제작·가공 목표 사전 점검 (리모콘 src/plan.js). 쓰는 조회가 전부 무료라 날개를 쓰기 전에 판단할 수 있다.

N 은 보유량을 뺀 수가 아니라 "새로 만들 개수"다 (못 400개를 들고 600개 더 만들려면 1000을 적어야 했던 문제).
제작과 가공은 같은 모양이고(Craftable/ProducedPerCraft ↔ Alterable/ProducedPerWork), 다른 점은 가공은 레시피 이름이
산출물 이름이 아니라는 것 — 보유량은 산출물 이름으로 세야 한다.
Required 는 1회 제작당 소모량이다 (실측: 못 1회 = 철괴 2 → 못 10). 총량 = Required × ceil(목표 / 산출량).
게임은 제작 불가능한 레시피에만, 그것도 가방 기준 모자란 재료만 MissingIngredients 로 준다.
"""
import math

from .. import gamedata as gd, richtext
from ..cache import QueryCache
from . import needs

SOURCE = gd.labels()["source"]
GATHER_PER_CALL = 100


def sum_by_name(rows, name_key: str, count_key: str) -> dict:
    m: dict = {}
    for r in rows or []:
        n = r.get(name_key)
        m[n] = m.get(n, 0) + (r.get(count_key) or 0)
        bare = richtext.strip(n)
        if bare != n:
            m[bare] = m.get(bare, 0) + (r.get(count_key) or 0)
    return m


def _items(res) -> list:
    d = res.get("data")
    return (d or {}).get("items") or [] if isinstance(d, dict) else []


def make_plan(cd, qc: QueryCache, display_name: str, target: int, **kw) -> dict:
    """제작 목표 계획. kw 는 QueryCache.get 인자 (refresh, offline, max_age). error 가 있으면 계산 실패."""
    kn = cd.knowledge
    craft = qc.get("get_craftable_items", **kw)
    gather = qc.get("get_gatherable_items", **kw)
    alter = qc.get("get_alterable_items", **kw)
    items = qc.get("get_items", **kw)
    if not craft.get("data"):
        return {"error": craft.get("error") or "no_data"}

    recipes = _items(craft)
    alter_recipes = _items(alter)

    def find(lst):
        return next((r for r in lst if r.get("DisplayName") == display_name), None) or \
            next((r for r in lst if richtext.strip(r.get("DisplayName")) == richtext.strip(display_name)), None)

    recipe, kind = find(recipes), "craft"
    if not recipe:
        recipe, kind = find(alter_recipes), "alter"
    if not recipe:
        g = find(_items(gather))
        if g:
            return gather_plan(g, target, items, gather.get("cached"))
    if not recipe:
        return {"error": "not_found", "name": display_name}

    is_alter = kind == "alter"
    ok_key = "Alterable" if is_alter else "Craftable"
    per_key = "ProducedPerWork" if is_alter else "ProducedPerCraft"
    product = kn.product_of(recipe["DisplayName"]) if is_alter else recipe["DisplayName"]

    gatherable = {x.get("DisplayName") for x in _items(gather)}
    alterable = {x.get("DisplayName") for x in alter_recipes}
    craftable = {x.get("DisplayName") for x in recipes}
    owned = sum_by_name(items.get("data") if isinstance(items.get("data"), list) else [], "DisplayName", "Count")

    def classify(name):
        return SOURCE["GATHER"] if name in gatherable else SOURCE["ALTER"] if name in alterable \
            else SOURCE["CRAFT"] if name in craftable else SOURCE["NONE"]

    per = recipe.get(per_key) or 1
    have = owned.get(product) or owned.get(richtext.strip(product)) or 0
    short = max(0, target)  # 새로 만들 개수. 보유량은 빼지 않는다
    runs = math.ceil(short / per)

    base = {"kind": kind, "name": recipe["DisplayName"], "product": product,
            "displayName": richtext.strip(recipe["DisplayName"]), "productName": richtext.strip(product),
            "target": target, "have": have, "producedPerCraft": per, "runs": runs,
            "craftableNow": bool(recipe.get(ok_key)), "reason": recipe.get("Reason"), "cached": craft.get("cached")}
    if short == 0:
        return {**base, "done": True, "ingredients": [], "blockers": []}

    def expand(per1: dict, frm):
        out = []
        for name, p in per1.items():
            total = p * runs
            has = owned.get(name) or 0
            out.append({"name": name, "displayName": richtext.strip(name), "per": p, "total": total, "have": has,
                        "lack": max(0, total - has), "source": classify(name), "from": frm})
        return out

    def is_blocker(i):
        return i["lack"] > 0 and i["source"] == SOURCE["NONE"]

    # 만들 수 있는 상태면 게임이 재료를 안 알려준다. 전에 만들어 알아낸 값이나 레시피 장부에 기댄다
    if recipe.get(ok_key):
        got = kn.recipe_ingredients(recipe["DisplayName"], have=lambda n: owned.get(n) or 0)
        if got:
            ing = expand(got["ingredients"], got["source"])
            note = "게임은 지금 만들 수 있는 것의 재료를 알려주지 않습니다. " + \
                ("이 숫자는 전에 이것을 만들어 봤을 때 알아낸 값입니다." if got["source"] == "observed"
                 else "이 숫자는 레시피 표에서 가져왔습니다") + \
                (" — 재료가 더 있을 수 있습니다." if got["source"] != "observed" and not got["complete"]
                 else "." if got["source"] != "observed" else "") + \
                (f" 이 이름은 재료 조합이 {got['variants']}가지라, 지금 재고에 가까운 쪽을 보여 줍니다."
                 if (got.get("variants") or 0) > 1 else "")
            return {**base, "learnedRecipe": True, "recipeSource": got["source"], "recipeComplete": got["complete"],
                    "recipeVariants": got["variants"], "ingredients": ing,
                    "blockers": [i for i in ing if is_blocker(i)],
                    "autoFixable": [i for i in ing if i["lack"] > 0 and i["source"] != SOURCE["NONE"]],
                    "ok": all(not is_blocker(i) for i in ing), "note": note}
        return {**base, "unknownIngredients": True, "ingredients": [], "blockers": [],
                "note": "지금은 만들 수 있는 상태라 게임이 재료 목록을 주지 않습니다. "
                        f"{runs}회분 재료가 되는지는 미리 알 수 없습니다. "
                        "한 번 만들어 보면 재료를 알아내서, 다음부터는 미리 계산합니다."}

    # 게임이 준 부족분. 배워 둔 완전한 레시피가 있으면 빠진 재료까지 채운다
    per1 = {m.get("DisplayName"): m.get("Required") for m in recipe.get("MissingIngredients") or []}
    learned = kn.recipe(recipe["DisplayName"])
    filled = False
    if kn.recipe_is_complete(learned):
        for k, v in learned["ingredients"].items():
            if k not in per1:
                per1[k] = v
                filled = True
    ingredients = expand(per1, "game")
    blockers = [i for i in ingredients if is_blocker(i)]
    out = {**base, "ingredients": ingredients, "blockers": blockers,
           "autoFixable": [i for i in ingredients if i["lack"] > 0 and i["source"] != SOURCE["NONE"]],
           "ok": not blockers}
    if filled:
        out["filledFromKnowledge"] = True
        out["recipeConfidence"] = learned["confidence"]
    return out


def gather_plan(row: dict, target: int, items: dict, cached) -> dict:
    """채집 목표. 재료도 시설도 없고 "몇 번 부르면 되나"뿐이다. 한 호출 최대 100개는 상한이지 보장이 아니라
    횟수는 최소치 — 자동 진행이 매번 남은 수량을 다시 세어 모자라면 더 부른다."""
    owned = sum_by_name(items.get("data") if isinstance(items.get("data"), list) else [], "DisplayName", "Count")
    name = row["DisplayName"]
    have = owned.get(name) or owned.get(richtext.strip(name)) or 0
    short = max(0, target)
    ok = bool(row.get("ToolOk"))
    return {"kind": "gather", "gather": True, "name": name, "product": name, "displayName": richtext.strip(name),
            "productName": richtext.strip(name), "target": target, "have": have,
            "producedPerCraft": GATHER_PER_CALL, "runs": math.ceil(short / GATHER_PER_CALL), "craftableNow": ok,
            "toolOk": ok, "cached": cached, "done": short == 0, "ingredients": [], "blockers": [], "ok": ok,
            "note": f"한 번 부르면 최대 {GATHER_PER_CALL}개까지 들어옵니다. 실제 수량은 해 봐야 알아서 "
                    "아래 횟수는 최소치이며, 자동 진행이 남은 수량을 매번 다시 세어 모자라면 더 부릅니다."
            if ok else "도구가 없거나 망가져 지금은 채집할 수 없습니다. 도구를 갖춘 뒤 다시 계산하세요."}


def deep_plan(cd, qc: QueryCache, target: str, count: int, **kw) -> dict:
    """사슬 끝까지 세우는 계획. 게임에서 사실만 모아 needs.plan 에 넘긴다 (조회만이라 무료)."""
    if not cd.altertable.has(target):
        return {"ok": False, "error": "not_in_table", "target": target}
    items = qc.get("get_items", **kw)
    gather = qc.get("get_gatherable_items", **kw)
    alter = qc.get("get_alterable_items", **kw)
    owned = sum_by_name(items.get("data") if isinstance(items.get("data"), list) else [], "DisplayName", "Count")
    gatherable = {richtext.strip(x.get("DisplayName")) for x in _items(gather)}
    recipe_names = {richtext.strip(x.get("DisplayName")) for x in _items(alter)}
    levels, slots = {}, {}
    for fac in cd.facilitymap.facilities():
        s = cd.knowledge.facility_slots(fac)
        if s and s.get("level"):
            levels[fac] = s["level"]
        if s and s.get("slots"):
            slots[fac] = s["slots"]
    r = needs.plan(cd.altertable, target, count, {"owned": owned, "levels": levels, "gatherable": gatherable,
                                                  "slots": slots, "recipeNames": recipe_names})
    return {**r, "cached": bool(items.get("cached") and gather.get("cached") and alter.get("cached"))}
