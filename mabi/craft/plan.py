"""제작·가공 목표 사전 점검 (리모콘 src/plan.js). 쓰는 조회가 전부 무료라 날개를 쓰기 전에 판단할 수 있다.

N 은 보유량을 뺀 수가 아니라 "새로 만들 개수"다 (못 400개를 들고 600개 더 만들려면 1000을 적어야 했던 문제).
제작과 가공은 같은 모양이고(Craftable/ProducedPerCraft ↔ Alterable/ProducedPerWork), 다른 점은 가공은 레시피 이름이
산출물 이름이 아니라는 것 — 보유량은 산출물 이름으로 세야 한다.
Required 는 1회 제작당 소모량이다 (실측: 못 1회 = 철괴 2 → 못 10). 총량 = 1회분 × ceil(목표 / 산출량).

재료는 레시피 표(recipes.json — 게임 데이터)에서 온다. 게임은 만들 수 없는 레시피에만, 그것도 가방 기준 모자란 재료만
MissingIngredients 로 주므로, 표에 없는 레시피(패치로 새로 생긴 것)만 그 부족분과 직접 만들어 알아낸 값으로 센다.
"""
import math

from .. import gamedata as gd, richtext
from ..cache import QueryCache
from . import goal, needs

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
    """제작 목표 계획 (한 겹 — 이 레시피에 무엇이 몇 개 드는가). kw 는 QueryCache.get 인자.
    error 가 있으면 계산 실패. 사슬 끝까지는 deep_plan."""
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
    row = cd.recipes.first(recipe["DisplayName"], kind)
    product = (row and row.get("product")) or (kn.product_of(recipe["DisplayName"]) if is_alter else recipe["DisplayName"])

    gatherable = {x.get("DisplayName") for x in _items(gather)}
    owned = sum_by_name(items.get("data") if isinstance(items.get("data"), list) else [], "DisplayName", "Count")

    def classify(name):
        if name in gatherable:
            return SOURCE["GATHER"]
        m = cd.recipes.selectable_makers(name)
        if m:
            return SOURCE["ALTER"] if m[0]["via"] == "alter" else SOURCE["CRAFT"]
        return SOURCE["NONE"]

    per = recipe.get(per_key) or (row and row.get("per")) or 1
    have = owned.get(product) or owned.get(richtext.strip(product)) or 0
    short = max(0, target)  # 새로 만들 개수. 보유량은 빼지 않는다
    runs = math.ceil(short / per)

    base = {"kind": kind, "name": recipe["DisplayName"], "product": product,
            "displayName": richtext.strip(recipe["DisplayName"]), "productName": richtext.strip(product),
            "target": target, "have": have, "producedPerCraft": per, "runs": runs,
            "craftableNow": bool(recipe.get(ok_key)), "reason": recipe.get("Reason"), "cached": craft.get("cached")}
    if row:
        base.update(facility=row.get("facility"), facilityLevel=row.get("level"), skill=row.get("skill"),
                    skillLevel=row.get("skillLevel"), sec=row.get("sec"), recipeVariants=row.get("twins", 1))
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

    def result(ing, extra):
        blockers = [i for i in ing if is_blocker(i)]
        return {**base, "ingredients": ing, "blockers": blockers,
                "autoFixable": [i for i in ing if i["lack"] > 0 and i["source"] != SOURCE["NONE"]],
                "ok": not blockers, **extra}

    # 레시피 표 — 게임 데이터 그대로라 재료가 빠짐없다
    if row:
        return result(expand(row["ingredients"], "table"),
                      {"recipeSource": "table", "recipeComplete": True,
                       "note": "재료는 게임 데이터의 레시피 표에서 가져왔습니다."
                               + (f" 같은 이름의 레시피가 {row['twins']}가지라, 시키면 실제로 도는 첫 줄로 셌습니다."
                                  if row.get("twins", 1) > 1 else "")})

    # 표에 없는 레시피 (패치로 새로 생긴 것). 만들 수 있는 상태면 게임이 재료를 안 알려준다
    if recipe.get(ok_key):
        got = kn.recipe_ingredients(recipe["DisplayName"])
        if got:
            return result(expand(got["ingredients"], got["source"]),
                          {"learnedRecipe": True, "recipeSource": got["source"], "recipeComplete": got["complete"],
                           "note": "레시피 표에 없는 레시피입니다. "
                                   + ("이 숫자는 전에 이것을 만들어 봤을 때 알아낸 값입니다." if got["source"] == "observed"
                                      else "이 숫자는 게임이 전에 알려 준 부족분이라 재료가 더 있을 수 있습니다.")})
        return {**base, "unknownIngredients": True, "ingredients": [], "blockers": [],
                "note": "레시피 표에 없고 지금은 만들 수 있는 상태라 게임이 재료 목록을 주지 않습니다. "
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
    out = result(expand(per1, "game"), {})
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
    """사슬 끝까지 세우는 계획 — 무엇을 몇 번 캐고, 몇 번 가공·제작하고, 날개가 얼마 드는지 (조회만이라 무료).
    target 은 산출물 이름이든 레시피 이름이든 된다. count 는 새로 만들 개수 (들고 있는 목표품은 셈에 넣지 않는다).
    레시피 이름(철괴(광석))으로 받아도 산출물(철괴)로 세운다 — 작업 큐는 산출물로 돌면서 가장 싼 길을 고르므로,
    미리 보는 계획도 같은 길이어야 한다."""
    snap = goal.snapshot(cd, qc, refresh=bool(kw.get("refresh")), offline=bool(kw.get("offline")))
    if snap.get("error"):
        return {"ok": False, "error": snap["error"], "message": snap.get("message")}
    product, _ = needs.target_of(cd.recipes, target, snap["gather"])
    r = goal.full_plan(snap, product or target, count, fresh=True)
    return {**r, "cached": snap.get("cached", False)}
