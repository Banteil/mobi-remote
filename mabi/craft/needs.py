""""이걸 N개 만들려면 지금 무엇을 얼마나 해야 하나" — 사슬 끝까지 (리모콘 src/needs.js).

plan.make_plan 은 게임이 알려 준 한 겹만 본다. 가공 재료표가 있으니 여기서는 끝까지 편다.
- 소지품을 주머니(pool) 하나에 담고 층마다 먼저 꺼낸다. 한 번 가공에 남는 것(철괴 3개)도 주머니로 돌린다.
- 갈래가 여럿이면 후보마다 계획을 세워 채집 횟수가 적은 쪽을 고른다 (어느 쪽이 싼지는 지금 재고에 달렸다).
- 다만 고를 수 있는 갈래만 후보 — 같은 이름으로 오는 갈래는 시켜도 첫 줄만 돈다.
"""
import math
from collections import deque

from .altertable import AlterTable

GATHER_PER_CALL = 100  # 채집 한 번에 최대 100개


def _to_map(owned) -> dict:
    return dict(owned) if owned else {}


def _run(alt: AlterTable, target, count, ctx: dict, choice: dict | None) -> dict:
    """한 가지 갈래 선택안으로 계획을 끝까지 세운다. choice = {산출물: 갈래번호} (미리 정한 것만)."""
    pool = _to_map(ctx.get("owned"))
    levels = ctx.get("levels") or {}
    gatherable = ctx.get("gatherable") or set()
    steps: dict[str, dict] = {}   # 산출물 → {product, index, runs}
    short: dict[str, int] = {}    # 더 못 만드는 것 → 모자란 개수
    blocked: list[dict] = []      # 레벨이 모자라 못 돌리는 것
    chosen: dict[str, int] = {}

    # 너비 우선. 깊이 우선이면 같은 재료를 여러 번 훑어 남는 것을 못 나눠 쓴다
    queue = deque([(target, count)])
    guard = 0
    while queue:
        guard += 1
        if guard > 20000:
            break  # 표가 이상해도 앱은 멈추지 않는다
        name, qty = queue.popleft()

        have = pool.get(name) or 0
        if have > 0:
            use = min(have, qty)
            pool[name] = have - use
            qty -= use
        if qty <= 0:
            continue

        info = alt.variants_for(name, levels)
        if not info:
            short[name] = short.get(name, 0) + qty
            continue
        pick = alt.selectable(name, ctx.get("recipeNames"))
        if choice is not None and name in choice:
            idx = choice[name]
        elif pick:
            ok_ones = [i for i in pick if i in info["runnable"]]
            idx = ok_ones[0] if ok_ones else pick[0]
        elif info["runnable"]:
            idx = info["runnable"][0]
        else:
            # 레벨이 모자란다. 무엇이 필요한지는 알려줘야 하니 계산은 계속하고 표시만 남긴다
            idx = info["all"][0]
            v = info["entry"]["variants"][idx]
            if not any(b["product"] == name for b in blocked):
                blocked.append({"product": name, "facility": v.get("facility"), "needLevel": v.get("level"),
                                "haveLevel": levels.get(v.get("facility"))})
        chosen[name] = idx

        v = info["entry"]["variants"][idx]
        per = info["entry"].get("per") or 1
        runs = math.ceil(qty / per)
        st = steps.get(name) or {"product": name, "index": idx, "runs": 0}
        st["runs"] += runs
        st["index"] = idx
        steps[name] = st

        made = runs * per
        if made > qty:
            pool[name] = (pool.get(name) or 0) + (made - qty)
        for ing, cnt in v["ingredients"].items():
            queue.append((ing, cnt * runs))

    gather, missing = [], []
    owned0 = _to_map(ctx.get("owned"))
    for name, need in short.items():
        row = {"name": name, "need": need,
               "have": ctx["ownedOf"](name) if ctx.get("ownedOf") else (owned0.get(name) or 0)}
        if name in gatherable:
            row["calls"] = math.ceil(need / GATHER_PER_CALL)
            gather.append(row)
        else:
            missing.append(row)
    gather.sort(key=lambda r: -r["need"])
    missing.sort(key=lambda r: -r["need"])
    return {"steps": steps, "short": short, "gather": gather, "missing": missing, "blocked": blocked,
            "chosen": chosen, "pool": pool}


def order(alt: AlterTable, steps: dict) -> list[dict]:
    """깊은 것부터 — 재료를 먼저 만들고 그다음 것을 만들도록."""
    rank: dict[str, int] = {}

    def depth(name, seen):
        if name in rank:
            return rank[name]
        if name in seen:
            return 0  # 순환 방어 (표에는 없다)
        st = steps.get(name)
        if not st:
            return 0
        e = alt.get(name)
        v = e["variants"][st["index"]] if e and 0 <= st["index"] < len(e["variants"]) else None
        d = 0
        for ing in (v or {}).get("ingredients", {}):
            if ing in steps:
                d = max(d, depth(ing, seen | {name}) + 1)
        rank[name] = d
        return d

    lst = list(steps.values())
    for st in lst:
        depth(st["product"], frozenset())
    return sorted(lst, key=lambda s: rank.get(s["product"]) or 0)


def plan(alt: AlterTable, target, count, ctx: dict | None = None) -> dict:
    """목표 하나를 끝까지 계획한다.
    ctx: owned {이름: 개수}(가방+창고), levels {시설: 레벨}, gatherable set, slots {시설: 칸수}(병렬 시간),
         recipeNames set(게임이 실제로 쓰는 가공 레시피 이름 — 괄호 이름을 지어내지 않으려고)"""
    c = ctx or {}
    if not alt.has(target):
        return {"ok": False, "error": "not_in_table", "target": target}
    if not (isinstance(count, (int, float)) and count > 0):
        return {"ok": False, "error": "bad_count", "target": target}

    multi = [n for n in alt.names() if len(alt.get(n)["variants"]) > 1]
    first = _run(alt, target, count, c, None)
    used = [n for n in multi if n in first["steps"]]

    best = first
    if used and len(used) <= 4:
        combos: list[dict] = []

        def build(i, acc):
            if i == len(used):
                combos.append(dict(acc))
                return
            n = used[i]
            info = alt.variants_for(n, c.get("levels"))
            sel = alt.selectable(n, c.get("recipeNames"))
            ok = [j for j in sel if j in info["runnable"]]
            for idx in (ok or sel or info["all"]):
                acc[n] = idx
                build(i + 1, acc)
            acc.pop(n, None)

        build(0, {})

        def cost(r):  # 채집 횟수가 적은 쪽, 같으면 가공 횟수가 적은 쪽
            return (sum(g["calls"] for g in r["gather"]), 1e9 if r["missing"] else 0,
                    sum(s["runs"] for s in r["steps"].values()))

        for combo in combos[:32]:
            r = _run(alt, target, count, c, combo)
            A, B = cost(r), cost(best)
            if A[1] < B[1] or (A[1] == B[1] and (A[0] < B[0] or (A[0] == B[0] and A[2] < B[2]))):
                best = r

    lst = []
    for st in order(alt, best["steps"]):
        e = alt.get(st["product"])
        v = e["variants"][st["index"]]
        rn = alt.recipe_name_of(st["product"], st["index"], c.get("recipeNames"))
        lst.append({"product": st["product"], "recipe": rn["name"],
                    # 같은 이름으로 오는 갈래는 시켜도 어느 쪽이 돌지 모르니 화면에 그대로 알린다
                    "ambiguous": rn["ambiguous"], "runs": st["runs"], "per": e.get("per"),
                    "produced": st["runs"] * (e.get("per") or 0), "facility": v.get("facility"),
                    "level": v.get("level"), "sec": v.get("sec"), "ingredients": v["ingredients"]})

    serial = sum((s["sec"] or 0) * s["runs"] for s in lst)
    # 시설마다 칸 수로 나눈 병렬 시간. 단계 사이 앞뒤 관계는 안 따지므로 아래쪽 어림값이다
    parallel = None
    if c.get("slots"):
        by_fac: dict = {}
        for s in lst:
            by_fac[s["facility"]] = by_fac.get(s["facility"], 0) + (s["sec"] or 0) * s["runs"]
        parallel = 0
        for fac, sec in by_fac.items():
            n = max(1, c["slots"].get(fac) or 1)
            parallel = max(parallel, math.ceil(sec / n))

    facilities: dict = {}
    for s in lst:
        facilities[s["facility"]] = max(facilities.get(s["facility"]) or 0, s["level"] or 0)

    return {"ok": True, "ambiguous": [s["product"] for s in lst if s["ambiguous"]], "target": target,
            "count": count, "steps": lst, "totalRuns": sum(s["runs"] for s in lst), "gather": best["gather"],
            "missing": best["missing"], "blocked": best["blocked"], "facilities": facilities,
            "time": {"serial": serial, "parallel": parallel}}
