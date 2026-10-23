"""목표 제작 루프 — "다음 한 걸음"을 정하는 곳 (리모콘 src/goal.js).

여기서는 결정만 한다. CLI 를 부르지도 사람에게 묻지도 않는다 (실행은 runner.py) — 게임 없이 판단을 시험할 수 있게.
미리 전체 계획을 짜면 금방 어긋나서(채집은 100개까지 들어오고 가공은 몇 분 뒤에 끝나고 그사이 칸이 찬다)
상태를 다시 읽고 그때 가장 나은 한 걸음을 고른다.

순서가 곧 정책이다:
 1. 목표 달성 확인
 2. 목표에 쓰이는 재료가 완성돼 있으면 수령 — 공짜이고 칸도 비운다
 3. 자동으로 못 구하는 재료가 있으면 멈추고 사람에게 넘긴다
 4. 부족분을 채집/가공/하위 제작으로 채운다 (가장 많이 모자란 것부터)
 5. 재료가 차면 제작
 6. 기다려야 한다면 그 시간에 남은 완료분을 거둔다
비용(실측): 날개 5는 호출당. 제작은 craftCount 로 10회까지 묶고, 채집은 호출당 100개, 가공은 1건씩, 수령은 무료.
"""
import math

from .. import errors, gamedata as gd, richtext
from ..cache import QueryCache
from . import lists

VIA = gd.labels()["source"]
MAX_DEPTH = 4  # 재귀 깊이 상한. 철괴 ← 철 광석 정도가 현실적인 최대다
# True 면 리모콘과 똑같이 레시피의 Reason 을 판단에 쓰지 않는다 (JS 와 결과를 맞춰 볼 때만)
STRICT_JS = False


def _list_of(data) -> list:
    if isinstance(data, list):
        return data
    return (data or {}).get("items") or (data or {}).get("Items") or [] if isinstance(data, dict) else []


def owned_map(data) -> dict:
    """이름 → 총 개수. 가방·보관함을 합친다 (MissingIngredients 의 Owned 는 가방만이라 쓰지 않는다)."""
    m: dict = {}
    for x in _list_of(data):
        n = x.get("DisplayName")
        if not n:
            continue
        c = x.get("Count") or 0
        m[n] = m.get(n, 0) + c
        bare = richtext.strip(n)
        if bare != n:
            m[bare] = m.get(bare, 0) + c
    return m


def recipe_map(data, ok_key: str, per_key: str) -> dict:
    """레시피 목록을 이름으로 찾게 편다. 태그가 붙은 이름은 벗긴 키도 같이 넣는다 (재료 이름과 맞추려고)."""
    m: dict = {}
    for r in _list_of(data):
        raw = r.get("DisplayName")
        if not raw:
            continue
        e = {"name": raw, "ok": bool(r.get(ok_key)), "per": r.get(per_key) or 1, "reason": r.get("Reason"),
             "missing": r.get("MissingIngredients")}
        m[raw] = e
        bare = richtext.strip(raw)
        if bare != raw:
            m[bare] = e
    return m


def gather_map(data) -> dict:
    return {r["DisplayName"]: {"name": r["DisplayName"], "ok": bool(r.get("ToolOk"))}
            for r in _list_of(data) if r.get("DisplayName")}


def maker_index(cd, snap: dict, kn: dict) -> dict:
    """산출물 → 그것을 만드는 레시피들. 철괴(광석)·철괴(철 광석)은 둘 다 철괴를 만든다.
    지금 가능한 것이 앞, 같으면 호출당 더 많이 나오는 쪽 (날개는 호출당이라 호출 수가 곧 비용)."""
    know = cd.knowledge
    m: dict[str, list] = {}

    def add(product, entry):
        m.setdefault(product, []).append(entry)

    for via, table in ((VIA["ALTER"], snap["alter"]), (VIA["CRAFT"], snap["craft"])):
        for name, e in table.items():
            if e["name"] != name:
                continue  # 태그를 벗긴 별칭 키는 건너뛴다
            # reason 은 리모콘에는 빠져 있다(goal.js:101 — 그래서 resolve 의 reason 검사가 죽은 코드였다).
            # 2026-10-15 판의 queue_full 을 칸 없음으로 다루려면 필요해서 같이 싣는다
            # 괄호 벗기기(철괴(광석) → 철괴)는 가공 레시피의 원료 구분용이다. 제작품은 이름에 괄호가 들어가는
            # 것("데코 트로피 상자(은)")이 있어 벗기면 '구할 수 없음'이 된다 — 리모콘(goal.js:105)의 버그를 고침
            prod = name if via == VIA["CRAFT"] and not STRICT_JS else know.product_of(name, kn)
            add(prod, {"recipe": name, "via": via, "ok": e["ok"], "per": e["per"],
                                            "missing": e["missing"], "reason": None if STRICT_JS else e["reason"]})

    def yield_per_call(e):
        return (e["per"] or 1) * (know.craft_limit(e["recipe"], kn) if e["via"] == VIA["CRAFT"] else 1)

    for lst in m.values():
        lst.sort(key=lambda e: (-(1 if e["ok"] else 0), -yield_per_call(e)))
    return m


def snapshot(cd, qc: QueryCache, refresh: bool = True, offline: bool = False) -> dict:
    """판단에 필요한 조회를 한 번에 모은다 (전부 무료). 한 걸음 실행한 뒤에는 반드시 새로 읽는다."""
    kw = {"refresh": refresh, "offline": offline}
    items = qc.get("get_items", **kw)
    craft = qc.get("get_craftable_items", **kw)
    alter = qc.get("get_alterable_items", **kw)
    gather = qc.get("get_gatherable_items", **kw)
    works = lists.altering_works(cd, qc, **kw)
    if any(not r or not r.get("data") for r in (items, craft, alter, gather)):
        return {"error": "query_failed", "message": "조회에 실패했습니다. 게임이 켜져 있는지 확인하세요."}
    if works.get("error"):
        return {"error": works["error"], "message": works.get("message")}

    kn = cd.knowledge.load()
    snap = {"cd": cd, "owned": owned_map(items["data"]),
            "craft": recipe_map(craft["data"], "Craftable", "ProducedPerCraft"),
            "alter": recipe_map(alter["data"], "Alterable", "ProducedPerWork"),
            "gather": gather_map(gather["data"]), "works": works, "recipes": kn.get("recipes") or {}, "kn": kn,
            "stale": bool(items.get("stale") or craft.get("stale") or alter.get("stale") or gather.get("stale"))}
    snap["makers"] = maker_index(cd, snap, kn)
    return snap


def have(snap: dict, name) -> int:
    return snap["owned"].get(name) or 0


def maker_for(snap: dict, name):
    lst = snap["makers"].get(name)
    return lst[0] if lst else None


def via_of(snap: dict, name) -> str:
    """채집을 가장 먼저 본다 — 호출당 100개라 효율이 제일 좋고 칸도 안 차지한다. 도구가 없으면 목록에 있어도 못 한다."""
    g = snap["gather"].get(name)
    if g:
        return VIA["GATHER"] if g["ok"] else VIA["NONE"]
    made = maker_for(snap, name)
    return made["via"] if made else VIA["NONE"]


def recipe_of(snap: dict, name) -> dict | None:
    """1회분 재료. 직접 만들어 알아낸 값이 먼저, 없으면 레시피 장부 ("적어도 이만큼"일 수 있어 complete 를 같이)."""
    got = snap["cd"].knowledge.recipe_ingredients(name, state=snap["kn"], have=lambda n: have(snap, n))
    return {"ingredients": got["ingredients"], "complete": got["complete"], "source": got["source"]} if got else None


def game_shortfall(maker) -> dict | None:
    """게임이 말한 부족 재료 {이름: 1회분}. 모자란 것만이지만 다음에 무엇을 구할지 고르기엔 충분하다."""
    lst = maker and maker.get("missing")
    if not lst:
        return None
    return {m.get("DisplayName"): m.get("Required") for m in lst}


def next_step(snap: dict, name: str, target: int) -> dict:
    """목표를 향한 다음 한 걸음. kind: done | collect | craft | gather | alter | wait | learn | blocked"""
    if snap.get("error"):
        return {"kind": "blocked", "reason": "query_failed", "message": snap.get("message") or "조회에 실패했습니다."}

    made_now = have(snap, name)
    if made_now >= target:
        return {"kind": "done", "have": made_now, "target": target}

    # 목표에 쓰이는 재료가 완성돼 있으면 먼저 가져온다. 무관한 시설까지 도는 것은 이동 시간만 버린다
    wanted = tree_items(snap, name)
    kn = snap["cd"].knowledge
    facs = snap["works"].get("facilities") or []
    useful = next((f for f in facs if f.get("completed") and
                   any(wanted.get(kn.product_of(w["name"], snap["kn"])) for w in f["completed"])), None)
    if useful:
        return {"kind": "collect", "facility": useful["facility"], "name": useful["completed"][0]["name"],
                "why": "목표에 쓰이는 재료가 완성돼 있습니다. 먼저 수령합니다 (무료)."}

    step = resolve(snap, name, target - made_now, 0, [])

    # 어차피 기다려야 한다면 그 시간에 남은 완료분을 거둔다 (공짜)
    if step["kind"] == "wait":
        any_f = next((f for f in facs if f.get("completed")), None)
        if any_f:
            return {"goal": name, "target": target, "have": made_now, "kind": "collect",
                    "facility": any_f["facility"], "name": any_f["completed"][0]["name"],
                    "why": "어차피 기다리는 중이라 완료된 가공을 거둡니다 (무료)."}
    return {"goal": name, "target": target, "have": made_now, **step}


def tree_items(snap: dict, name) -> dict:
    """목표에 쓰이는 아이템 전체(자신 포함). 수량은 안 보고 "쓰이긴 하는가"만."""
    seen: dict = {}

    def walk(n, depth):
        if depth > MAX_DEPTH or seen.get(n):
            return
        seen[n] = True
        maker = maker_for(snap, n)
        if not maker:
            return
        rec = recipe_of(snap, maker["recipe"])
        per1 = rec["ingredients"] if rec else game_shortfall(maker)
        if not per1:
            return
        for ing in per1:
            walk(ing, depth + 1)

    walk(name, 0)
    return seen


def _full_facility(snap: dict, fac, recipe_name, room) -> dict:
    """시설 칸이 없을 때: 그 시설에 수령할 것이 있으면 수령이 곧 칸을 비운다. 없으면 기다린다."""
    f = next((x for x in snap["works"].get("facilities") or []
              if x["facility"] == fac and x.get("completed")), None)
    if f:
        return {"kind": "collect", "facility": fac, "name": f["completed"][0]["name"],
                "why": f"{fac} 칸이 차 있습니다. 완료분을 수령하면 비워집니다 (무료)."}
    used = f"{room['used']}/{room['slots']}" if room else "?"
    return wait_step(snap, recipe_name, f"가공 칸이 모두 차 있습니다 ({fac} {used}).")


def resolve(snap: dict, name, need: int, depth: int, trail: list) -> dict:
    """"이것을 need 개 더 얻으려면 지금 무엇을 해야 하나"를 재귀로 푼다. 한 번에 한 걸음.
    부족한 재료가 여럿이면 가장 많이 모자란 것부터 — 조금씩 건드리면 아무것도 완성되지 않은 채 날개만 나간다."""
    kn = snap["cd"].knowledge
    if depth > MAX_DEPTH:
        return {"kind": "blocked", "reason": "too_deep", "name": name,
                "message": f"{name} 까지 가는 재료 단계가 너무 깊습니다."}
    if name in trail:
        return {"kind": "blocked", "reason": "cycle", "name": name,
                "message": "재료가 순환합니다: " + " → ".join(trail + [name])}

    via = via_of(snap, name)
    if via == VIA["NONE"]:
        return {"kind": "blocked", "reason": "not_obtainable", "name": name, "need": need,
                "message": f"{name} 은(는) 채집·가공·제작 어느 쪽으로도 구할 수 없습니다."}
    if via == VIA["GATHER"]:
        return {"kind": "gather", "name": name, "need": need, "times": math.ceil(need / 100),
                "why": f"{name} {need}개를 채집합니다."}

    # 여기부터는 얻고 싶은 것(name)과 부르는 레시피(maker.recipe)가 다르다. execute_* 에는 레시피 이름을 넘긴다
    maker = maker_for(snap, name)
    recipe_name = maker["recipe"]
    per = maker["per"] or 1
    runs = math.ceil(need / per)

    # 2026-10-15 판: 가공 목록이 칸 없음을 queue_full 로 직접 알려 준다. 재료 문제가 아니므로 칸 처리로 보낸다
    if not maker["ok"] and maker.get("reason") == "queue_full" and via == VIA["ALTER"]:
        fac = kn.facility_of(recipe_name, snap["kn"])
        room = next((r for r in snap["works"].get("room") or [] if r["facility"] == fac), None) if fac else None
        return _full_facility(snap, fac or "가공 시설", recipe_name, room)

    # 재료 말고 다른 이유(생활 스킬·시설 레벨·데코 점수)로 막혀 있으면 앱이 해 줄 수 있는 게 없다
    if not maker["ok"] and maker.get("reason") and maker["reason"] != "not_enough_ingredient":
        ko = errors.describe("execute_altering" if via == VIA["ALTER"] else "execute_crafting", maker["reason"])
        return {"kind": "blocked", "reason": maker["reason"], "name": recipe_name, "product": name,
                "message": f"{recipe_name} — {ko.get('text') or maker['reason']}" + (f" {ko['hint']}" if ko.get("hint") else "")}

    rec = recipe_of(snap, recipe_name)
    per1 = rec["ingredients"] if rec else game_shortfall(maker)
    if not per1:
        # 어느 쪽도 없다. 지금 가능하면 1회 해 보고 배우는 게 가장 싸다 (날개 5).
        # 반드시 1회 — 묶으면 대성공 보너스가 섞여 재료량을 나눌 수 없다
        if maker["ok"]:
            return {"kind": "learn", "via": via, "name": recipe_name, "product": name, "need": need, "per": per,
                    "why": f"{recipe_name} 의 재료를 아직 모릅니다. 1회만 만들어 보고 재료를 알아냅니다."}
        return {"kind": "blocked", "reason": "unknown_recipe", "name": recipe_name, "product": name, "need": need,
                "message": f"{recipe_name} 의 재료를 모르고, 지금은 만들 수도 없어 알아낼 방법이 없습니다. "
                           "재료를 갖춰 한 번 직접 만들어 보시면 그때 배웁니다."}

    # 부족량은 게임의 Owned(가방만)가 아니라 총량(가방+보관함)으로 센다
    short = []
    for ing, p in per1.items():
        want = p * runs
        has = have(snap, ing)
        if has < want:
            short.append({"name": ing, "lack": want - has, "want": want, "has": has})
    if short:
        short.sort(key=lambda s: -s["lack"])
        worst = short[0]
        sub = resolve(snap, worst["name"], worst["lack"], depth + 1, trail + [name])
        sub.update(forRecipe=recipe_name, otherShort=short[1:])  # 막힌 이유는 최종 목표까지 그대로 올린다
        return sub

    if not maker["ok"]:
        return {"kind": "blocked", "reason": "not_allowed", "name": recipe_name, "product": name,
                "message": f"{recipe_name} 은(는) 재료가 갖춰졌는데도 지금은 {via}할 수 없습니다. "
                           "시설 레벨이나 생활 스킬 조건일 수 있습니다."}

    if via == VIA["CRAFT"]:
        limit = kn.craft_limit(recipe_name, snap["kn"])
        batch = min(runs, limit)
        calls = math.ceil(runs / limit)
        return {"kind": "craft", "name": recipe_name, "product": name, "runs": runs, "batch": batch,
                "limit": limit, "calls": calls, "per": per, "need": need,
                "why": f"{recipe_name} {batch}회 제작 → {name} 약 {batch * per}개"
                       + (f" (상한 {limit}회라 나눠서 {calls}번 호출)" if runs > limit else "")}

    # 가공은 칸이 있어야 한다. 꽉 찬 채 등록하면 날개 5가 그냥 나간다(실측)
    fac = kn.facility_of(recipe_name, snap["kn"])
    room = next((r for r in snap["works"].get("room") or [] if r["facility"] == fac), None) if fac else None
    if room and room["free"] <= 0:
        return _full_facility(snap, fac, recipe_name, room)

    # 가공은 한 호출에 1건뿐이라 한 건만 지시하고 나머지는 다음 걸음에서 다시 판단한다
    free = room["free"] if room else None
    queued = room["used"] if room else 0
    return {"kind": "alter", "name": recipe_name, "product": name, "runs": 1, "wanted": runs, "per": per,
            "need": need, "facility": fac, "free": free, "queued": queued,
            "why": f"{recipe_name} 1건 등록 ({name} {need}개까지 총 {runs}건 필요"
                   + (f", 여유 {free}칸" if free is not None else "") + ")"}


def wait_step(snap: dict, name, why: str) -> dict:
    """기다리는 것 말고 할 일이 없을 때. 진행 중인 작업이 없으면 기다려도 안 풀린다."""
    left = [w.get("remainingSec") for f in snap["works"].get("facilities") or []
            for w in f.get("inProgress") or []]
    left = [x for x in left if isinstance(x, (int, float))]
    if not left:
        return {"kind": "blocked", "reason": "stuck", "name": name,
                "message": f"{why} 그런데 진행 중인 작업도 없어 기다려도 풀리지 않습니다."}
    return {"kind": "wait", "seconds": max(5, min(left)), "name": name, "why": why}


def estimate(snap: dict, name: str, target: int) -> dict:
    """시작 전 대략 비용. 어디까지나 하한이다 — 모르는 레시피 아래는 못 세고 채집량도 해 봐야 안다."""
    if snap.get("error"):
        return {"calls": 0, "wings": 0, "partial": True}
    kn = snap["cd"].knowledge
    seen: dict = {}
    acc = {"calls": 0, "partial": False}

    def walk(n, need, depth):
        if depth > MAX_DEPTH or need <= 0 or seen.get(n):
            return
        seen[n] = True
        via = via_of(snap, n)
        if via == VIA["NONE"]:
            acc["partial"] = True
            return
        if via == VIA["GATHER"]:
            acc["calls"] += math.ceil(need / 100)
            return
        maker = maker_for(snap, n)
        per = (maker and maker["per"]) or 1
        runs = math.ceil(need / per)
        if via == VIA["CRAFT"]:  # 제작만 묶을 수 있다
            acc["calls"] += math.ceil(runs / kn.craft_limit(maker["recipe"], snap["kn"]))
        else:
            acc["calls"] += runs
        rec = recipe_of(snap, maker["recipe"]) if maker else None
        per1 = rec["ingredients"] if rec else game_shortfall(maker)
        if not per1:
            acc["partial"] = True
            return
        # 재료를 다 아는 게 아니면(장부 값이 complete 가 아니어도) 아래 단계는 과소 집계다
        if not rec or not rec["complete"]:
            acc["partial"] = True
        for ing, p in per1.items():
            want = p * runs
            h = have(snap, ing)
            if h < want:
                walk(ing, want - h, depth + 1)

    walk(name, max(0, target - have(snap, name)), 0)
    return {"calls": acc["calls"], "wings": acc["calls"] * 5, "partial": acc["partial"]}


def next_for(cd, qc: QueryCache, name: str, target: int, refresh: bool = True, offline: bool = False) -> dict:
    """리모콘 goal:next IPC 와 같은 묶음 — {step, estimate, have} 또는 {error, message}."""
    try:
        snap = snapshot(cd, qc, refresh=refresh, offline=offline)
        if snap.get("error"):
            return {"error": snap["error"], "message": snap.get("message")}
        return {"step": next_step(snap, name, target), "estimate": estimate(snap, name, target),
                "have": snap["owned"].get(name) or 0}
    except Exception as e:  # 판단 실패가 루프를 죽이지 않게
        return {"error": "goal_failed", "message": str(e)}
