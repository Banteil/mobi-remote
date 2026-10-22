"""제작·가공 목록과 가공 작업 현황 (리모콘 src/query.js 의 craft·alter·alteringWorks).

목록을 볼 때마다 레시피 표를 채운다 — 게임은 지금 만들 수 없는 레시피에만 재료를 알려 주므로,
검색으로 좁히기 전의 전체 목록으로 수확한다. 학습·수확 실패는 조회를 막지 않는다.
kw 는 QueryCache.get 인자 (refresh, offline, max_age).
"""
from .. import errors, richtext
from ..query import Query, _fail, matches, name_fields


def split_ingredients(lst, totals: dict | None) -> dict:
    """MissingIngredients 를 실제 기준으로 정리한다. Owned 는 가방만 세지만 판정은 보관함까지 본다.
    missing = 보관함까지 합쳐도 모자란 것, covered = 가방엔 없지만 보관함으로 충당되는 것."""
    missing, covered = [], []
    for m in lst or []:
        label = richtext.strip(m.get("DisplayName"))
        total = (totals.get(m.get("DisplayName")) or totals.get(label) or 0) if totals is not None else m.get("Owned")
        req = m.get("Required")
        if total < req:
            missing.append(f"{label} {total}/{req}")
        elif (m.get("Owned") or 0) < req:
            covered.append(f"{label} {total}")
    return {"missing": missing, "covered": covered}


def harvest_recipes(cd, rows: list, kind: str, ok_key: str, per_key: str) -> None:
    """아는 레시피는 게임 숫자와 대조해 confidence 를 올리고, 모르는 레시피는 장부에 담는다."""
    kn = cd.knowledge
    known = None
    for r in rows:
        if r.get(ok_key) or not r.get("MissingIngredients"):
            continue
        if known is None:
            known = kn.load().get("recipes") or {}
        if not known.get(r.get("DisplayName")):
            continue
        try:
            kn.learn_recipe_from_missing(r["DisplayName"], kind, r["MissingIngredients"], r.get(per_key))
        except Exception:
            pass  # 검증 실패가 조회를 막으면 안 된다
    try:
        cd.recipebook.harvest_rows(rows, kind, ok_key, per_key, known or kn.load().get("recipes") or {})
    except Exception:
        pass  # 수확 실패도 조회를 막지 않는다


def _rows(res) -> list:
    d = res.get("data")
    return d.get("items") or [] if isinstance(d, dict) else []


def craft(cd, qc, search: str = "", only_ok: bool = False, detail: bool = False, limit: int = 0,
          harvest: bool = True, **kw) -> dict:
    """제작 목록. 줄: {name, name_raw, ok, per, reason?, reason_code?, missing?, covered?}"""
    res = qc.get("get_craftable_items", **kw)
    if not res.get("data"):
        return _fail(res)
    totals = Query(qc).owned_totals(**kw) if detail else None
    allrows = _rows(res)
    rows = [r for r in allrows if matches(r.get("DisplayName"), search) and (not only_ok or r.get("Craftable"))]
    if harvest:
        harvest_recipes(cd, allrows, "craft", "Craftable", "ProducedPerCraft")

    out = []
    for r in rows:
        row = {**name_fields(r["DisplayName"]), "ok": bool(r.get("Craftable")), "per": r.get("ProducedPerCraft")}
        if not r.get("Craftable"):
            # 코드 그대로면 화면에 insufficient_living_skill_level 이 뜬다
            row["reason"] = errors.reason_text(r.get("Reason"))
            row["reason_code"] = r.get("Reason")
            if detail and r.get("MissingIngredients"):
                s = split_ingredients(r["MissingIngredients"], totals)
                row["missing"] = s["missing"]
                if s["covered"]:
                    row["covered"] = s["covered"]
        out.append(row)
    return {"unlocked": res["data"].get("craftingUnlocked"), "total": len(allrows),
            "craftable": sum(1 for r in allrows if r.get("Craftable")), "matched": len(out),
            "cached": res.get("cached", False), "stale": bool(res.get("stale")), "age_sec": round(res.get("age") or 0),
            "items": out[:limit] if limit else out}


def craft_find(cd, qc, name: str, **kw) -> dict:
    """이름 하나의 제작 가능 여부와 부족 재료."""
    return craft(cd, qc, search=name, detail=True, limit=20, **kw)


def alter(cd, qc, search: str = "", only_ok: bool = False, limit: int = 0, harvest: bool = True, **kw) -> dict:
    """가공 목록. 줄: {name, name_raw, ok, per, facility, level?, sec?, variant?, variants?,
    reason?, reason_code?, no_slot?, missing?, covered?}.
    no_slot: Reason 이 queue_full(2026-10-15 판) — 재료가 아니라 시설 칸이 없어 못 하는 것."""
    kn, alt = cd.knowledge, cd.altertable
    res = qc.get("get_alterable_items", **kw)
    if not res.get("data"):
        return _fail(res)
    allrows = _rows(res)
    rows = [r for r in allrows if matches(r.get("DisplayName"), search) and (not only_ok or r.get("Alterable"))]
    totals = Query(qc).owned_totals(**kw)
    if harvest:
        harvest_recipes(cd, allrows, "alter", "Alterable", "ProducedPerWork")

    state = kn.load()
    seen: dict[str, int] = {}  # 같은 이름이 몇 번째로 나왔는지 (갈래를 차례로 맞추려고)
    out = []
    for r in (rows[:limit] if limit else rows):
        row = {**name_fields(r["DisplayName"]), "ok": bool(r.get("Alterable")), "per": r.get("ProducedPerWork"),
               # 어느 시설인지. 관측값이 없으면 facility-map.json
               "facility": kn.facility_of(r["DisplayName"], state)}
        # 레벨·시간은 게임이 안 알려줘 재료표에서 온다. 같은 이름의 줄이 여럿이면 줄마다 제 갈래를 찾는다
        key = richtext.strip(r["DisplayName"])
        nth = seen.get(key, 0)
        seen[key] = nth + 1
        hit = alt.match_row(r["DisplayName"],
                            [richtext.strip(m.get("DisplayName")) for m in r.get("MissingIngredients") or []], nth)
        if hit and hit.get("variant"):
            row["level"] = hit["variant"].get("level")
            row["sec"] = hit["variant"].get("sec")
            row["variant"] = hit["index"]
            row["variants"] = len(alt.get(hit["product"])["variants"])
            if not row["facility"]:
                row["facility"] = hit["variant"].get("facility")
        if not r.get("Alterable"):
            row["reason"] = errors.reason_text(r.get("Reason"))
            row["reason_code"] = r.get("Reason")
            if r.get("Reason") == "queue_full":
                row["no_slot"] = True
            if r.get("MissingIngredients"):
                s = split_ingredients(r["MissingIngredients"], totals)
                row["missing"] = s["missing"]
                if s["covered"]:
                    row["covered"] = s["covered"]
        out.append(row)
    return {"total": len(allrows), "alterable": sum(1 for r in allrows if r.get("Alterable")), "matched": len(rows),
            "cached": res.get("cached", False), "stale": bool(res.get("stale")), "items": out}


def altering_works(cd, qc, **kw) -> dict:
    """가공 작업 현황. 완료분은 시설별로 묶어야 complete_altering_work 를 시설당 1회만 부른다.
    아이템↔시설 매핑과 시설별 칸 수는 여기서만 알 수 있어 볼 때마다 쌓는다.
    {completed_count, in_progress_count, total, facilities: [{facility, completed:[], inProgress:[]}], room, works}"""
    kn = cd.knowledge
    res = qc.get("get_altering_works", **kw)
    if not res.get("data"):
        return _fail(res)
    works = res["data"].get("works") or [] if isinstance(res["data"], dict) else []
    try:
        kn.learn_from_altering_works(res["data"])
    except Exception:
        pass  # 학습 실패는 조회를 막지 않는다

    by: dict[str, dict] = {}
    for w in works:
        key = w.get("FacilityName") or "(시설 미상)"
        e = by.setdefault(key, {"facility": key, "completed": [], "inProgress": []})
        row = {"name": w.get("DisplayName"), "state": w.get("State"), "remainingSec": w.get("RemainingSeconds")}
        (e["completed"] if w.get("IsCompleted") else e["inProgress"]).append(row)

    return {"completed_count": res["data"].get("completedCount") or sum(1 for w in works if w.get("IsCompleted")),
            "in_progress_count": sum(1 for w in works if not w.get("IsCompleted")), "total": len(works),
            "cached": res.get("cached", False), "stale": bool(res.get("stale")),
            "facilities": sorted(by.values(), key=lambda f: -len(f["completed"])),
            "room": kn.room_report(res["data"]),
            "works": [{"name": w.get("DisplayName"), "facility": w.get("FacilityName"), "state": w.get("State"),
                       "done": bool(w.get("IsCompleted")), "remainingSec": w.get("RemainingSeconds")} for w in works]}
