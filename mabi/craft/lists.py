"""레시피 수확(harvest_recipes — 화면 목록을 볼 때마다)과 가공 작업 현황(altering_works — 목표 판단용).

게임은 지금 만들 수 없는 레시피에만 재료를 알려 주므로, 검색으로 좁히기 전의 전체 목록으로 수확한다.
학습·수확 실패는 조회를 막지 않는다.
kw 는 QueryCache.get 인자 (refresh, offline, max_age).
"""
from ..query import _fail


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
