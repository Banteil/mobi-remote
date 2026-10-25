""""이걸 N개 만들려면 무엇을 얼마나 해야 하나" — 레시피 표로 사슬 끝까지 미리 계산한다 (리모콘 src/needs.js 를 넓힌 것).

예전에는 게임이 알려 주는 부족분을 보고 한 겹씩 내려갔다. 이제 게임 레시피 표(recipes.json)가 있어서
제작과 가공을 한 사슬로 놓고 처음부터 끝까지 센다.

- 총량으로 센다: 같은 재료를 여러 레시피가 쓰면 수요를 다 모은 뒤 한 번에 나눈다. 따로 올림하면 산출 단위(3개, 10개)
  만큼씩 남는 것이 생긴다. 그래서 "쓰는 쪽 → 재료" 차례(위상 순서)로 한 번만 훑는다.
- 소지품(가방+보관함)과 이미 가공 중인 것(incoming)을 먼저 쓴다. 한 번 만들고 남는 것도 다음 수요가 쓴다.
- 채집할 수 있는 것은 채집한다 (호출당 100개, 칸도 시간도 안 든다).
- 만드는 법이 여럿이면(철괴(광석) / 철괴(철 광석)) 조합마다 계산해 호출 수(= 날개)가 가장 적은 쪽을 고른다.
  같은 이름의 둘째 줄부터는 시켜도 첫 줄이 돌아서 후보가 아니다 (recipes.py).
- 시설 레벨이 모자라거나 게임이 다른 이유(생활 스킬·데코 점수)로 거절한 레시피는 다른 길이 있으면 피하고,
  없으면 계산은 끝까지 하되 blocked 로 알린다 — 무엇이 필요한지는 보여 줘야 한다.
"""
import math

from .recipes import RecipeTable, bare

GATHER_PER_CALL = 100  # 채집 한 번에 최대 100개
CRAFT_LIMIT = 10       # 제작 한 번에 묶을 수 있는 횟수 (knowledge 가 배운 값이 있으면 그쪽)
WINGS_PER_CALL = 5     # 채집·제작·가공 호출마다 정령의 날개 5 (수령은 무료)
MAX_COMBOS = 64


def _resolve(table: RecipeTable, product: str, ctx: dict, choice: dict) -> dict:
    """이 아이템을 어떻게 구하나. {how: gather|make|missing, row?, blocked?, reason?}"""
    gatherable = ctx.get("gatherable") or {}
    if product in gatherable:
        if gatherable[product]:
            return {"how": "gather"}
        if not table.selectable_makers(product):
            return {"how": "missing", "reason": "tool"}  # 채집 대상인데 도구가 없다
    makers = table.selectable_makers(product)
    if not makers:
        return {"how": "missing", "reason": "quest" if product in (ctx.get("questItems") or ()) else "none"}
    if product in choice:
        row = makers[min(choice[product], len(makers) - 1)]
    else:
        ok = [r for r in makers if not _block_of(r, ctx)]
        row = ok[0] if ok else makers[0]
    return {"how": "make", "row": row, "blocked": _block_of(row, ctx)}


def _block_of(row: dict, ctx: dict) -> dict | None:
    """이 레시피를 지금 못 돌리는 이유. 재료 부족은 이유가 아니다 (그건 계산이 채운다)."""
    reason = (ctx.get("refused") or {}).get(row["name"])
    if reason:
        return {"reason": reason}
    if row["via"] == "alter":
        have = (ctx.get("levels") or {}).get(row.get("facility"))
        if have is not None and row.get("level") is not None and have < row["level"]:
            return {"reason": "insufficient_facility_level", "haveLevel": have}
    return None


def _graph(table, target, ctx, choice) -> tuple[dict, list]:
    """목표에서 닿는 아이템마다 구하는 법을 정하고, 쓰는 쪽이 재료보다 먼저 오는 차례를 만든다."""
    how: dict[str, dict] = {}
    post: list[str] = []
    state: dict[str, int] = {}  # 1 = 보는 중, 2 = 끝

    def visit(p):
        if state.get(p):
            return  # 끝났거나 순환 — 표에는 순환이 없지만 앱은 멈추지 않는다
        state[p] = 1
        how[p] = h = _resolve(table, p, ctx, choice)
        if h["how"] == "make":
            for ing in h["row"]["ingredients"]:
                visit(ing)
        state[p] = 2
        post.append(p)

    visit(target)
    return how, post[::-1]  # 후위 순서를 뒤집으면 쓰는 쪽이 먼저다


def _run(table: RecipeTable, target: str, count: int, ctx: dict, choice: dict) -> dict:
    how, order = _graph(table, target, ctx, choice)
    pool = dict(ctx.get("owned") or {})
    for k, v in (ctx.get("incoming") or {}).items():
        pool[k] = pool.get(k, 0) + v
    if ctx.get("fresh"):
        pool.pop(target, None)  # "새로 N개" — 들고 있는 목표품은 셈에 넣지 않는다
    demand = {target: count}
    used: dict[str, int] = {}
    steps, gather, missing, blocked = [], [], [], []
    limit = ctx.get("craftLimit") or (lambda _r: CRAFT_LIMIT)

    for p in order:
        need = demand.get(p, 0)
        if need <= 0:
            continue
        take = min(pool.get(p, 0), need)
        if take:
            pool[p] -= take
            used[p] = used.get(p, 0) + take
            need -= take
        if need <= 0:
            continue
        h = how[p]
        if h["how"] == "gather":
            gather.append({"name": p, "need": need})
            continue
        if h["how"] == "missing":
            missing.append({"name": p, "need": need, "reason": h["reason"]})
            continue
        r = h["row"]
        per = r.get("per") or 1
        runs = math.ceil(need / per)
        pool[p] = pool.get(p, 0) + runs * per - need  # 남는 것은 다음 수요가 쓴다
        for ing, amt in r["ingredients"].items():
            demand[ing] = demand.get(ing, 0) + amt * runs
        lim = max(1, limit(r["name"])) if r["via"] == "craft" else 1
        steps.append({"via": r["via"], "recipe": r["name"], "product": p, "runs": runs, "per": per,
                      "produced": runs * per, "calls": math.ceil(runs / lim), "limit": lim,
                      "facility": r.get("facility"), "level": r.get("level"), "skill": r.get("skill"),
                      "skillLevel": r.get("skillLevel"), "sec": r.get("sec"), "ingredients": dict(r["ingredients"]),
                      "ambiguous": r.get("twins", 1) > 1, "options": len(table.selectable_makers(p))})
        if h["blocked"]:
            blocked.append({"recipe": r["name"], "product": p, "facility": r.get("facility"),
                            "needLevel": r.get("level"), "skill": r.get("skill"), "skillLevel": r.get("skillLevel"),
                            **h["blocked"]})
    return {"how": how, "steps": steps, "gather": gather, "missing": missing, "blocked": blocked, "used": used}


def _cost(r: dict) -> tuple:
    """못 구하는 것·막힌 것이 적은 쪽, 그다음 호출 수(= 날개)가 적은 쪽, 그다음 가공 시간이 짧은 쪽"""
    calls = sum(math.ceil(g["need"] / GATHER_PER_CALL) for g in r["gather"]) + sum(s["calls"] for s in r["steps"])
    sec = sum((s["sec"] or 0) * s["runs"] for s in r["steps"] if s["via"] == "alter")
    return (len(r["missing"]) + len(r["blocked"]), calls, sec)


def _depths(steps: list) -> dict:
    """재료 단계 깊이. 맨 아래(만든 재료를 안 쓰는 것)가 0 — 이 차례로 만들면 재료가 먼저 생긴다."""
    by = {s["product"]: s for s in steps}
    memo: dict[str, int] = {}

    def depth(p, seen=frozenset()):
        if p in memo:
            return memo[p]
        if p in seen or p not in by:
            return -1
        memo[p] = 1 + max((depth(i, seen | {p}) for i in by[p]["ingredients"]), default=-1)
        return memo[p]

    for p in by:
        depth(p)
    return memo


def target_of(table: RecipeTable, name: str, gatherable=None) -> tuple[str | None, str | None]:
    """화면이 넘긴 이름 → (산출물, 레시피 이름). 산출물 이름이든 레시피 이름(철괴(광석))이든 받는다."""
    n = bare(name)
    if table.has(n):
        return table.first(n).get("product") or n, n
    if table.is_product(n) or (gatherable and n in gatherable):
        return n, None
    return None, None


def plan(table: RecipeTable, target: str, count: int, ctx: dict | None = None) -> dict:
    """목표 하나를 끝까지 계획한다.
    ctx: owned {이름: 개수}(가방+보관함), incoming {산출물: 개수}(가공 중·수령 전),
         gatherable {이름: 도구 있음?}, levels {가공 시설: 레벨}(아는 것만), refused {레시피: 게임이 거절한 이유},
         craftLimit(레시피) → 한 번에 묶는 횟수, slots {가공 시설: 칸 수}, fresh(목표품 보유분을 안 씀)"""
    c = dict(ctx or {})
    product, recipe = target_of(table, target, c.get("gatherable"))
    if not product:
        return {"ok": False, "error": "not_in_table", "target": target}
    if not (isinstance(count, (int, float)) and count > 0):
        return {"ok": False, "error": "bad_count", "target": target}
    count = int(count)
    choice: dict[str, int] = {}
    if recipe:  # 레시피 이름으로 받았으면 그 레시피로 만든다
        idx = next((i for i, r in enumerate(table.selectable_makers(product)) if r["name"] == recipe), None)
        if idx is not None:
            choice[product] = idx
    c.setdefault("questItems", {q for r in table.load() for q in r.get("quest") or ()})

    best = _run(table, product, count, c, choice)
    # 만드는 법이 여럿인 아이템만 조합을 바꿔 본다 (보통 0~3개라 금방 끝난다)
    multi = [p for p, h in best["how"].items()
             if h["how"] == "make" and p not in choice and len(table.selectable_makers(p)) > 1]
    if multi:
        combos = [dict(choice)]
        for p in multi[:6]:
            n = len(table.selectable_makers(p))
            combos = [{**cb, p: i} for cb in combos for i in range(n)][:MAX_COMBOS]
        for cb in combos:
            r = _run(table, product, count, c, cb)
            if _cost(r) < _cost(best):
                best = r

    depth = _depths(best["steps"])
    for s in best["steps"]:
        s["depth"] = depth.get(s["product"], 0)
    # 만드는 차례: 재료 단계가 깊은 것부터, 같은 깊이는 가공(시간이 걸린다) → 제작, 같은 시설끼리 붙여서
    steps = sorted(best["steps"], key=lambda s: (s["depth"], 0 if s["via"] == "alter" else 1, s["facility"] or ""))

    owned = c.get("owned") or {}
    gather = sorted(({**g, "have": owned.get(g["name"], 0), "calls": math.ceil(g["need"] / GATHER_PER_CALL)}
                     for g in best["gather"]), key=lambda g: -g["need"])
    missing = sorted(({**m, "have": owned.get(m["name"], 0)} for m in best["missing"]), key=lambda m: -m["need"])

    calls = {"gather": sum(g["calls"] for g in gather),
             "alter": sum(s["calls"] for s in steps if s["via"] == "alter"),
             "craft": sum(s["calls"] for s in steps if s["via"] == "craft")}
    total_calls = sum(calls.values())

    serial = sum((s["sec"] or 0) * s["runs"] for s in steps if s["via"] == "alter")
    parallel = None
    if c.get("slots"):
        by_fac: dict = {}
        for s in steps:
            if s["via"] == "alter":
                by_fac[s["facility"]] = by_fac.get(s["facility"], 0) + (s["sec"] or 0) * s["runs"]
        # 시설마다 칸 수로 나눈 시간 중 가장 긴 것. 단계 사이 앞뒤 관계는 안 따지므로 아래쪽 어림값이다
        parallel = max((math.ceil(sec / max(1, c["slots"].get(f) or 1)) for f, sec in by_fac.items()), default=0)

    facilities: dict = {}
    skills: dict = {}
    for s in steps:
        if s["facility"]:
            facilities[s["facility"]] = max(facilities.get(s["facility"]) or 0, s["level"] or 0)
        if s.get("skill"):
            skills[s["skill"]] = max(skills.get(s["skill"]) or 0, s.get("skillLevel") or 0)

    top = next((s for s in steps if s["product"] == product), None)
    return {"ok": True, "target": product, "recipe": recipe or (top["recipe"] if top else None),
            "count": count, "have": owned.get(product, 0),
            "steps": steps, "totalRuns": sum(s["runs"] for s in steps),
            "gather": gather, "missing": missing, "blocked": best["blocked"],
            "fromStock": [{"name": k, "use": v} for k, v in best["used"].items()],
            "ambiguous": [s["product"] for s in steps if s["ambiguous"]],
            "facilities": facilities, "skills": skills,
            "calls": {**calls, "total": total_calls}, "wings": total_calls * WINGS_PER_CALL,
            "time": {"serial": serial, "parallel": parallel},
            "route": route(steps, gather)}


def route(steps: list, gather: list) -> list[dict]:
    """사람이 읽는 진행 차례. 채집을 먼저 몰아서 하고, 그다음 재료 단계 차례로 같은 시설 일을 묶는다.
    실제 진행(goal.next_step)은 이 차례를 따르되, 가공은 시간이 걸리므로 재료가 되는 대로 먼저 걸어 둔다."""
    out = []
    if gather:
        out.append({"kind": "gather", "items": [{"name": g["name"], "need": g["need"], "calls": g["calls"]}
                                                for g in gather]})
    for s in steps:
        last = out[-1] if out else None
        if last and last["kind"] == s["via"] and last.get("facility") == s["facility"] and last.get("depth") == s["depth"]:
            last["items"].append({"recipe": s["recipe"], "runs": s["runs"], "calls": s["calls"]})
        else:
            out.append({"kind": s["via"], "facility": s["facility"], "depth": s["depth"],
                        "items": [{"recipe": s["recipe"], "runs": s["runs"], "calls": s["calls"]}]})
    return out
