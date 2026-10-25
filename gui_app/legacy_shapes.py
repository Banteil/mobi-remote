"""레거시 화면(web/app.js)이 기대하는 조회 결과 모양 (리모콘 src/query.js 를 그대로 옮긴 것).

mabi/query.py · mabi/craft/lists.py 는 파이썬 화면용으로 키 이름(snake_case)과 모양을 바꿔 두었다.
웹 화면은 레거시 코드를 거의 그대로 쓰므로 여기서 레거시와 같은 객체를 만든다 — nameRaw·seg·reasonCode·
weightPct 같은 키, 빠진 필드는 아예 키가 없는 것(JS undefined 는 JSON 에서 사라진다)까지 맞춘다.
그래서 JS 의 참/거짓·숫자→문자열 규칙을 작은 도우미(_truthy, _s, _round …)로 흉내 낸다.

opts 는 레거시 그대로: refresh, offline, maxAgeMs(ms), search, onlyOk, detail, limit, category, nonZero, onlyOpen, name.
"""
import math
import re
import time

from mabi import errors, gamedata as gd, richtext
from mabi.craft import lists as craft_lists


class _Undef:
    """JS undefined. 결과에서 이 값을 가진 키는 clean() 이 지운다 (JSON.stringify 와 같게)."""

    def __repr__(self):
        return "undefined"


U = _Undef()


def g(o, k):
    return o.get(k, U) if isinstance(o, dict) else U


def _truthy(v) -> bool:
    if v is U or v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return v != ""
    return True  # 배열·객체는 비어 있어도 참 (파이썬과 다르다)


def _or(*vals):
    """a || b || c"""
    for v in vals[:-1]:
        if _truthy(v):
            return v
    return vals[-1]


def _num(v) -> float:
    """Number(v)"""
    if v is U:
        return math.nan
    if v is None or v is False:
        return 0
    if v is True:
        return 1
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0
        try:
            return float(s)
        except ValueError:
            return math.nan
    return math.nan


def _round(v):
    """Math.round — .5 는 위로 (파이썬 round 는 짝수 쪽이라 다르다)."""
    x = _num(v)
    if x != x or x in (math.inf, -math.inf):
        return x
    return int(math.floor(x + 0.5))


def _div(a, b):
    x, y = _num(a), _num(b)
    if y == 0:
        if x != x or x == 0:
            return math.nan
        return math.inf if x > 0 else -math.inf
    return x / y


def _s(v) -> str:
    """문자열 이어 붙이기('' + v) 에서 JS 가 쓰는 표기."""
    if v is U:
        return "undefined"
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v in (math.inf, -math.inf):
            return "Infinity" if v > 0 else "-Infinity"
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def _lt(a, b) -> bool:
    return _num(a) < _num(b)


def clean(o):
    """undefined 키를 지우고 NaN/Infinity 는 null 로 (JSON.stringify 와 같게)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if v is not U}
    if isinstance(o, (list, tuple)):
        return [None if v is U else clean(v) for v in o]
    if isinstance(o, float) and (o != o or o in (math.inf, -math.inf)):
        return None
    return o


def _arr(v) -> list:
    return v if isinstance(v, list) else []


# ---------------------------------------------------------------- 공통

_WS = re.compile(r"\s+")


def matches(haystack, needle) -> bool:
    """공백·대소문자 무시 부분 일치. 태그는 먼저 벗긴다."""
    if not _truthy(needle):
        return True
    h = richtext.strip(_s(_or(haystack, "")))
    h = _WS.sub("", (h if isinstance(h, str) else _s(h)).lower())
    return _WS.sub("", _s(needle).lower()) in h


def segments(s) -> list[dict]:
    return [{"text": t, "color": c} for t, c in richtext.segments(s)]


def name_fields(display) -> dict:
    """게임에 되돌려 보낼 때는 반드시 nameRaw — 태그를 벗긴 이름은 식별자가 아니다."""
    tagged = richtext.has_tags(display)
    return {"name": richtext.strip(display) if tagged else display, "nameRaw": display,
            "seg": segments(display) if tagged else None}


def _fail(res) -> dict:
    return {"error": g(res, "error"), "message": g(res, "message")}


def _meta(res) -> dict:
    return {"cached": g(res, "cached"), "stale": _truthy(g(res, "stale"))}


class Shapes:
    """레거시 QUERIES 표. 함수 이름이 곧 화면이 부르는 조회 이름이다 (me, craftFind, ...)."""

    NAMES = ("me", "activity", "environment", "inventory", "currencies", "wings", "items", "itemCount",
             "craft", "craftFind", "alter", "alteringWorks", "gather", "daily", "weekly", "quests",
             "nearNpcs", "nearPcs", "instruments", "musicScores", "socialActions")

    def __init__(self, qc, cd):
        self.qc, self.cd = qc, cd

    def run(self, name: str, opts) -> dict:
        fn = getattr(self, "q_" + name, None) if name in self.NAMES else None
        if fn is None:
            return {"error": "unknown_query", "message": name}
        return clean(fn(opts if isinstance(opts, dict) else {}))

    # ---- 캐시 ----
    def _get(self, command: str, o: dict) -> dict:
        ma = g(o, "maxAgeMs")
        # 레거시는 maxAgeMs 가 undefined 일 때만 기본 TTL 을 쓴다 (null 이면 캐시를 안 본다)
        max_age = None if ma is U else (0 if ma is None else _num(ma) / 1000)
        res = self.qc.get(command, refresh=_truthy(g(o, "refresh")), max_age=max_age, offline=_truthy(g(o, "offline")))
        return {**res, "ageMs": (res.get("age") or 0) * 1000}

    def _owned_totals(self, o) -> dict:
        """이름 → 가방+보관함 총량. MissingIngredients 의 Owned 는 가방만 센다."""
        res = self._get("get_items", o)
        m: dict = {}
        for it in _arr(res.get("data")):
            dn, n = g(it, "DisplayName"), g(it, "Count")
            m[dn] = _num(_or(m.get(dn, U), 0)) + _num(n)
            bare = richtext.strip(dn)
            if bare != dn:
                m[bare] = _num(_or(m.get(bare, U), 0)) + _num(n)
        return m

    @staticmethod
    def _split(lst, totals) -> dict:
        missing, covered = [], []
        for m in _arr(lst) if lst is not U else []:
            dn = g(m, "DisplayName")
            label = richtext.strip(dn)
            total = _or(totals.get(dn, U), totals.get(label, U), 0) if totals is not None else g(m, "Owned")
            if _lt(total, g(m, "Required")):
                missing.append(_s(label) + " " + _s(total) + "/" + _s(g(m, "Required")))
            elif _lt(g(m, "Owned"), g(m, "Required")):
                covered.append(_s(label) + " " + _s(total))
        return {"missing": missing, "covered": covered}

    @staticmethod
    def _reason(code) -> str:
        return errors.reason_text(None if code is U else code)

    # ---------------------------------------------------------------- 제작·가공·채집
    def q_craft(self, o):
        res = self._get("get_craftable_items", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        totals = self._owned_totals(o) if _truthy(g(o, "detail")) else None
        allrows = _arr(_or(g(res["data"], "items"), []))
        rows = allrows
        if _truthy(g(o, "search")):
            rows = [r for r in rows if matches(g(r, "DisplayName"), o["search"])]
        if _truthy(g(o, "onlyOk")):
            rows = [r for r in rows if _truthy(g(r, "Craftable"))]
        # 검색으로 좁히기 전의 전체 목록으로 수확한다. 걸러진 결과만 보면 표가 안 찬다
        craft_lists.harvest_recipes(self.cd, allrows, "craft", "Craftable", "ProducedPerCraft")

        out = []
        for r in rows:
            row = name_fields(g(r, "DisplayName"))
            row["ok"] = _truthy(g(r, "Craftable"))
            row["per"] = g(r, "ProducedPerCraft")
            if not _truthy(g(r, "Craftable")):
                row["reason"] = self._reason(g(r, "Reason"))
                row["reasonCode"] = g(r, "Reason")
                if _truthy(g(o, "detail")) and _truthy(g(r, "MissingIngredients")):
                    s = self._split(r["MissingIngredients"], totals)
                    row["missing"] = s["missing"]
                    if s["covered"]:
                        row["covered"] = s["covered"]
            out.append(row)
        lim = g(o, "limit")
        return {"unlocked": g(res["data"], "craftingUnlocked"), "total": len(allrows),
                "craftable": sum(1 for r in allrows if _truthy(g(r, "Craftable"))), "matched": len(out),
                **_meta(res), "ageSec": _round(res["ageMs"] / 1000),
                "items": out[:int(_num(lim))] if _truthy(lim) else out}

    def q_craftFind(self, o):  # noqa: N802
        return self.q_craft({**o, "search": g(o, "name"), "detail": True, "limit": 20})

    def q_alter(self, o):
        kn, tbl = self.cd.knowledge, self.cd.recipes
        res = self._get("get_alterable_items", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        allrows = _arr(_or(g(res["data"], "items"), []))
        rows = allrows
        if _truthy(g(o, "search")):
            rows = [r for r in rows if matches(g(r, "DisplayName"), o["search"])]
        if _truthy(g(o, "onlyOk")):
            rows = [r for r in rows if _truthy(g(r, "Alterable"))]
        totals = self._owned_totals(o)
        craft_lists.harvest_recipes(self.cd, allrows, "alter", "Alterable", "ProducedPerWork")

        state = kn.load()
        # 같은 이름이 전체 목록에서 몇 번째 줄인가. 게임 목록 순서 = 레시피 표 순서라 차례로 맞추면 제 갈래다.
        # 검색·필터로 줄이 빠져도 어긋나지 않게 걸러지기 전의 목록으로 센다
        seen: dict = {}
        nth_of: dict = {}
        for r in allrows:
            key = richtext.strip(g(r, "DisplayName"))
            nth_of[id(r)] = seen.get(key, 0)
            seen[key] = nth_of[id(r)] + 1
        lim = g(o, "limit")
        items = []
        for r in (rows[:int(_num(lim))] if _truthy(lim) else rows):
            dn = g(r, "DisplayName")
            row = name_fields(dn)
            row["ok"] = _truthy(g(r, "Alterable"))
            row["per"] = g(r, "ProducedPerWork")
            # 어느 시설인지. 큐에서 본 값이 먼저, 없으면 레시피 표
            row["facility"] = kn.facility_of(dn, state)
            # 레벨·시간은 게임이 안 알려줘 레시피 표에서 온다
            v = tbl.row_at(dn, nth_of.get(id(r), 0), "alter")
            if v:
                row["level"] = g(v, "level")
                row["sec"] = g(v, "sec")
                row["variant"] = v["nth"]
                row["variants"] = v["twins"]
                row["product"] = v["product"]
                if not _truthy(row["facility"]):
                    row["facility"] = g(v, "facility")
            if not _truthy(g(r, "Alterable")):
                row["reason"] = self._reason(g(r, "Reason"))
                row["reasonCode"] = g(r, "Reason")
                if _truthy(g(r, "MissingIngredients")):
                    s = self._split(r["MissingIngredients"], totals)
                    row["missing"] = s["missing"]
                    if s["covered"]:
                        row["covered"] = s["covered"]
            items.append(row)
        return {"total": len(allrows), "alterable": sum(1 for r in allrows if _truthy(g(r, "Alterable"))),
                "matched": len(rows), **_meta(res), "items": items}

    def q_gather(self, o):
        res = self._get("get_gatherable_items", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        allrows = _arr(_or(g(res["data"], "items"), []))
        rows = allrows
        if _truthy(g(o, "search")):
            rows = [r for r in rows if matches(g(r, "DisplayName"), o["search"])]
        if _truthy(g(o, "onlyOk")):
            rows = [r for r in rows if _truthy(g(r, "ToolOk"))]
        lim = g(o, "limit")
        return {"total": len(allrows), "toolOk": sum(1 for r in allrows if _truthy(g(r, "ToolOk"))),
                "matched": len(rows), **_meta(res),
                "items": [{**name_fields(g(r, "DisplayName")), "tool": _truthy(g(r, "ToolOk"))}
                          for r in (rows[:int(_num(lim))] if _truthy(lim) else rows)]}

    def q_alteringWorks(self, o):  # noqa: N802
        """완료분은 시설별로 묶어야 complete_altering_work 를 시설당 1회만 부른다.
        아이템↔시설 매핑과 시설별 칸 수는 여기서만 알 수 있어 볼 때마다 쌓는다."""
        kn = self.cd.knowledge
        res = self._get("get_altering_works", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        d = res["data"]
        works = _arr(_or(g(d, "works"), []))
        try:
            kn.learn_from_altering_works(d)
        except Exception:
            pass  # 학습 실패는 조회를 막지 않는다
        by: dict = {}
        for w in works:
            key = _or(g(w, "FacilityName"), "(시설 미상)")
            e = by.setdefault(key, {"facility": key, "completed": [], "inProgress": []})
            row = {"name": g(w, "DisplayName"), "state": g(w, "State"), "remainingSec": g(w, "RemainingSeconds")}
            (e["completed"] if _truthy(g(w, "IsCompleted")) else e["inProgress"]).append(row)
        return {"completedCount": _or(g(d, "completedCount"), sum(1 for w in works if _truthy(g(w, "IsCompleted")))),
                "inProgressCount": sum(1 for w in works if not _truthy(g(w, "IsCompleted"))), "total": len(works),
                **_meta(res),
                "facilities": sorted(by.values(), key=lambda f: -len(f["completed"])),
                "room": kn.room_report(d),
                "works": [{"name": g(w, "DisplayName"), "facility": g(w, "FacilityName"), "state": g(w, "State"),
                           "done": _truthy(g(w, "IsCompleted")), "remainingSec": g(w, "RemainingSeconds")}
                          for w in works]}

    # ---------------------------------------------------------------- 소지품·재화
    LOCATION_LABEL = gd.labels()["location"]
    # 무게는 가방만 차지하므로 보관처를 고정된 칸으로 나눈다 (어디에 없는지도 보이게)
    LOCATION_KEY = {"inventory": "bag", "character_storage": "charStore", "account_storage": "accStore"}

    def q_items(self, o):
        res = self._get("get_items", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        allrows = _arr(res["data"])
        rows = allrows
        if _truthy(g(o, "search")):
            rows = [r for r in rows if matches(g(r, "DisplayName"), o["search"])]
        if _truthy(g(o, "category")):
            rows = [r for r in rows if matches(g(r, "CategoryDisplayName"), o["category"])]
        by: dict = {}
        for r in rows:
            dn = g(r, "DisplayName")
            if dn not in by:
                by[dn] = {"name": richtext.strip(dn), "nameRaw": dn,
                          "seg": segments(dn) if richtext.has_tags(dn) else None,
                          "category": g(r, "CategoryDisplayName"), "total": 0, "where": {},
                          "at": {"bag": 0, "charStore": 0, "accStore": 0}, "locked": False}
            e = by[dn]
            n = _num(g(r, "Count"))
            e["total"] += n
            loc = g(r, "Location")
            label = self.LOCATION_LABEL.get(loc, loc) if isinstance(loc, str) else _s(loc)
            e["where"][label] = _num(_or(e["where"].get(label, U), 0)) + n
            k = self.LOCATION_KEY.get(loc) if isinstance(loc, str) else None
            if k:
                e["at"][k] += n
            if _truthy(g(r, "IsLocked")):
                e["locked"] = True
        out = sorted(by.values(), key=lambda e: -e["total"])
        # 필터 메뉴용. 필터를 건 뒤가 아니라 전체 기준이어야 고른 분류가 메뉴에서 사라지지 않는다
        cats = {c for c in (g(r, "CategoryDisplayName") for r in allrows) if _truthy(c)}
        lim = g(o, "limit")
        return {"totalRows": len(allrows), "matched": len(out), "categories": sorted(cats, key=_ko_key),
                **_meta(res), "items": out[:int(_num(lim))] if _truthy(lim) else out}

    def q_itemCount(self, o):  # noqa: N802
        name = g(o, "name")
        r = self.q_items({**o, "search": name})
        if _truthy(r.get("error", U)):
            return r
        # 태그가 붙은 원문으로 물어봐도, 벗긴 이름으로 물어봐도 찾히게 한다
        bare = richtext.strip(_s(_or(name, "")))
        exact = next((i for i in r["items"] if i["nameRaw"] == name or i["name"] == name or i["name"] == bare), None) \
            or (r["items"][0] if r["items"] else None)
        return {"name": exact["name"], "count": exact["total"], "where": exact["where"]} if exact \
            else {"name": bare, "count": 0, "where": {}}

    def q_currencies(self, o):
        res = self._get("get_currencies", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        rows = _arr(res["data"])
        if _truthy(g(o, "search")):
            rows = [r for r in rows if matches(g(r, "DisplayName"), o["search"])]
        if _truthy(g(o, "nonZero")):
            rows = [r for r in rows if _num(g(r, "Amount")) > 0]
        return {**_meta(res), "items": [{"name": g(r, "DisplayName"), "amount": g(r, "Amount")} for r in rows]}

    def q_wings(self, o):
        """정령의 날개 잔량. execute_gathering / execute_crafting / execute_altering 1회당 5 소모."""
        r = self.q_currencies({**o, "search": gd.currency("wings")})
        if _truthy(r.get("error", U)):
            return r
        w = next((i for i in r["items"] if i["name"] == gd.currency("wings")), None)
        return {"amount": w["amount"] if w else 0, "cached": r.get("cached", U)}

    # ---------------------------------------------------------------- 캐릭터·활동
    def q_me(self, o):
        """get_my_info 에는 캐릭터명이 없다. Title=착용 타이틀, RealmName=서버 — 이름으로 띄우지 말 것."""
        res = self._get("get_my_info", o)
        # 게임 밖이면 CLI 가 실패로 답하는데 캐시는 옛 값을 준다 → 접속 중이 아닌 것으로 알려 화면이 이름·정보를 지운다.
        # 로그인 화면은 'not_in_game', 캐릭터 선택 화면은 실제 로딩과 같은 'loading' 으로 답한다 (2026-10-23 확인)
        # → 'loading' 이 15초 넘게 이어지면 캐릭터 선택 화면으로 본다 (실제 로딩은 몇 초)
        failed = res.get("failed")
        if failed == "loading":
            self._loading_since = getattr(self, "_loading_since", None) or time.monotonic()
        elif not failed:
            self._loading_since = None
        if failed == "not_in_game" or (failed == "loading" and time.monotonic() - self._loading_since > 15):
            return {"error": "not_in_game", "message": "로그인·캐릭터 선택 화면"}
        if not _truthy(res.get("data")):
            return _fail(res)
        d = res["data"]
        v = _or(g(d, "Vitals"), {})
        cs, ls = g(d, "CombatScore"), g(d, "LivingScore")
        wc, wm = g(v, "InventoryWeightCurrent"), g(v, "InventoryWeightMax")
        return {"title": g(d, "Title"), "realm": g(d, "RealmName"), "level": g(d, "Level"),
                "job": g(d, "EnabledCombatJobDisplayName"),
                "combat": g(cs, "Value") if _truthy(cs) else cs, "living": g(ls, "Value") if _truthy(ls) else ls,
                "hp": _s(g(v, "HealthCurrent")) + "/" + _s(g(v, "HealthMax")),
                "satiety": _s(g(v, "SatietyValue")) + "/" + _s(g(v, "SatietyMax")),
                "weight": _s(_round(wc)) + "/" + _s(_round(wm)),
                "weightPct": _round(_div(wc, wm) * 100),
                "buffs": g(v, "ActiveBuffCount"), **_meta(res)}

    def q_activity(self, o):
        """항상 실시간. IsReviving 은 멀쩡히 돌아다녀도 true 로 남는 경우가 있어 노출만 하고 판단에 안 쓴다."""
        res = self._get("get_activity", {"maxAgeMs": 0, **o})
        if not _truthy(res.get("data")):
            return _fail(res)
        d = res["data"]
        perf, mode = _or(g(d, "Performance"), {}), _or(g(d, "Mode"), {})
        dun = g(d, "Dungeon")
        return {
            "autoPlaying": _truthy(g(d, "IsAutoPlaying")), "autoTraveling": _truthy(g(d, "IsAutoTraveling")),
            "inCombat": _truthy(g(d, "IsInCombat")), "dead": _truthy(g(d, "IsDead")),
            "reviving": _truthy(g(d, "IsReviving")),
            "dialogue": _truthy(g(d, "IsDialoguePlaying")) or _truthy(g(d, "IsWaitingForSelection")),
            "performing": _truthy(g(perf, "IsPlaying")),
            # 연주는 게임이 시간을 재서 준다. 진행바·남은 시간을 그릴 수 있는 유일한 값
            "perf": {"playing": _truthy(g(perf, "IsPlaying")), "instrument": _or(g(perf, "InstrumentName"), ""),
                     "title": _or(g(perf, "MusicTitle"), ""), "loop": _truthy(g(perf, "IsLoop")),
                     "total": _or(_num(g(perf, "TotalDurationSeconds")), 0),
                     "elapsed": _or(_num(g(perf, "ElapsedSeconds")), 0),
                     "remaining": _or(_num(g(perf, "RemainingSeconds")), 0),
                     "channels": _or(_num(g(perf, "ChannelCount")), 0),
                     "startAt": _or(g(perf, "StartAt"), "")},
            "sitting": g(mode, "SitState") == "Sitting", "mainButton": g(mode, "MainButtonState"),
            "dungeon": g(dun, "State") if _truthy(dun) else dun,
            "busy": any(_truthy(x) for x in (g(d, "IsAutoPlaying"), g(d, "IsAutoTraveling"), g(d, "IsInCombat"),
                                             g(perf, "IsPlaying"), g(d, "IsWaitingForSelection"))),
            **_meta(res)}

    def q_environment(self, o):
        res = self._get("get_current_environment", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        d = res["data"]
        h = _or(g(d, "Housing"), {})
        wp = g(d, "WorldPosition")
        return {"channel": g(d, "ChannelDisplayName"), "space": g(d, "GameSpaceDisplayName"),
                "pos": {"x": g(wp, "X"), "y": g(wp, "Y")} if _truthy(wp) else None,
                "weather": g(d, "Weather"), "erinnTime": g(d, "ErinnNow"),
                "housing": {"inside": _truthy(g(h, "IsInHousing")), "owned": _truthy(g(h, "IsOwnedHousing")),
                            "canEnter": _truthy(g(h, "CanEnterHousing")), "canExit": _truthy(g(h, "CanExitHousing"))},
                **_meta(res)}

    def q_inventory(self, o):
        res = self._get("get_inventory", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        d = res["data"]
        return {"current": g(d, "CurrentInventoryWeightAsDecimal"), "max": g(d, "MaxInventoryWeightAsDecimal"),
                "pct": _round(_div(g(d, "CurrentInventoryWeight"), g(d, "MaxInventoryWeight")) * 100), **_meta(res)}

    # ---------------------------------------------------------------- 미션·퀘스트
    @staticmethod
    def _mission_state(m) -> str:
        """open(더 해야 함) / unclaimed(다 했는데 보상 안 받음 — 게임에서 직접 눌러야 한다) / done"""
        if not _truthy(g(m, "IsCompleted")):
            return "open"
        return "done" if _truthy(g(m, "IsRewardReceived")) else "unclaimed"

    @staticmethod
    def _drop_phantoms(arr) -> list:
        """제목이 같은 묶음에 수령까지 끝난 건이 있으면, 같은 묶음의 '완료·미수령'은 지난 주기 잔재로 보고 버린다
        (실측: 주간 미션이 1회 수령함 + 2회 완료·미수령 두 건으로 온다). 진행 중인 건은 진짜 다음 단계일 수 있어 남긴다."""
        rows = _arr(arr)
        claimed = {_s(g(m, "Title")) for m in rows if _truthy(g(m, "IsCompleted")) and _truthy(g(m, "IsRewardReceived"))}
        return [m for m in rows if not (_s(g(m, "Title")) in claimed and _truthy(g(m, "IsCompleted"))
                                        and not _truthy(g(m, "IsRewardReceived")))]

    def _missions(self, command, o):
        res = self._get(command, o)
        if not _truthy(res.get("data")):
            return _fail(res)
        rows = self._drop_phantoms(res["data"])
        states = [self._mission_state(m) for m in rows]
        items = [{"title": g(m, "Title"), "desc": g(m, "Description"),
                  "progress": _s(g(m, "CurrentCount")) + "/" + _s(g(m, "GoalCount")),
                  "state": st, "done": _truthy(g(m, "IsCompleted")), "claimed": _truthy(g(m, "IsRewardReceived")),
                  "shortcut": _truthy(g(m, "HasShortcut"))}
                 for m, st in zip(rows, states) if not _truthy(g(o, "onlyOpen")) or st != "done"]
        return {"total": len(rows), "open": states.count("open"), "unclaimed": states.count("unclaimed"),
                **_meta(res), "items": items}

    def q_daily(self, o):
        return self._missions("get_daily_missions", o)

    def q_weekly(self, o):
        return self._missions("get_weekly_missions", o)

    def q_quests(self, o):
        res = self._get("get_quests", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        rows = _arr(res["data"])
        items = []
        for q in rows:
            qt = g(q, "QuestTitle")
            objs = []
            for ob in _arr(_or(g(q, "Objectives"), [])):
                raw = g(ob, "Description")
                desc = richtext.strip(raw)
                # Goal 이 0 인 목표는 개수형이 아니라 단발성
                prog = _s(g(ob, "Count")) + "/" + _s(g(ob, "Goal")) if _num(g(ob, "Goal")) > 0 else None
                objs.append({"desc": desc, "seg": segments(raw) if richtext.has_tags(raw) else None,
                             "done": _truthy(g(ob, "IsCompleted")),
                             # 설명 끝에 같은 진행도가 이미 붙어 오는 목표가 있다 ("심층 던전 클리어 2/3")
                             "progress": prog if prog and isinstance(desc, str) and prog not in desc else None})
            items.append({"title": richtext.strip(qt), "titleSeg": segments(qt) if richtext.has_tags(qt) else None,
                          "source": _or(g(q, "SourceDisplayName"), g(q, "Source")), "objectives": objs})
        return {"total": len(rows), **_meta(res), "items": items}

    # ---------------------------------------------------------------- 주변·연주·소셜
    def q_nearNpcs(self, o):  # noqa: N802
        res = self._get("get_near_npcs", {"maxAgeMs": 0, **o})
        d = res.get("data")
        if not _truthy(d):
            return {"total": 0, "items": []}
        rows = d if isinstance(d, list) else _or(g(d, "npcs"), [])
        return {"total": len(rows), "items": rows}

    def q_nearPcs(self, o):  # noqa: N802
        """이름 칸은 RealmName(서버). 캐릭터명은 어느 명령도 주지 않는다."""
        res = self._get("get_near_pcs", {"maxAgeMs": 0, **o})
        d = res.get("data")
        if not _truthy(d):
            return {"total": 0, "items": []}
        rows = _arr(d)
        items = [{"name": g(p, "RealmName"), "title": g(p, "Title"),
                  "distance": _round(_num(g(p, "Distance")) * 10) / 10, "level": g(p, "Level"),
                  "job": g(p, "EnabledCombatJobDisplayName"), "combat": g(p, "CombatScore"),
                  "living": g(p, "LivingScore"), "friend": _truthy(g(p, "IsFriend")),
                  "party": _truthy(g(p, "IsInParty")), "sameGuild": _truthy(g(p, "IsSameGuild")),
                  "inCombat": _truthy(g(p, "IsInCombat")),
                  "playing": _truthy(g(g(p, "Performance"), "IsPlaying")),
                  "musicTitle": _or(g(g(p, "Performance"), "MusicTitle"), "")} for p in rows]
        return {"total": len(rows), "items": sorted(items, key=lambda x: x["distance"])}

    def q_instruments(self, o):
        res = self._get("get_instruments", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        rows = _arr(res["data"])
        # 내구도 int 최대값은 사실상 무한(소모 없음)
        return {"total": len(rows), **_meta(res),
                "items": [{"name": g(i, "Name"),
                           "durability": None if _num(g(i, "Durability")) >= 2147483647 else g(i, "Durability"),
                           "equipped": _truthy(g(i, "IsEquipped"))} for i in rows]}

    def q_musicScores(self, o):  # noqa: N802
        """2026-10-15 판부터 게임이 준 악보만 온다 (직접 만들거나 복사한 악보는 빠짐)."""
        res = self._get("get_music_scores", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        rows = _arr(res["data"])
        allrows = rows
        if _truthy(g(o, "search")):
            rows = [r for r in rows if matches(g(r, "DisplayTitle"), o["search"])]
        return {"total": len(allrows) if isinstance(res["data"], list) else U, "matched": len(rows), **_meta(res),
                "items": [{"title": g(s, "DisplayTitle"), "location": g(s, "Location"),
                           "copyable": _truthy(g(s, "IsCopyingAllowed")), "locked": _truthy(g(s, "IsLocked"))}
                          for s in rows]}

    # 목록에는 없지만 하는 일은 다른 행동과 같다. 앉기는 목록에 있는데 짝인 일어서기만 빠져 있어 같은 자리에 얹는다.
    # 다른 점은 보내는 방식뿐 — 채팅 명령이 아니라 전용 명령(stand_up)
    STAND_UP = {"name": "일어서기", "commands": [], "via": "command", "command": "stand_up"}

    def q_socialActions(self, o):  # noqa: N802
        res = self._get("get_social_actions", o)
        if not _truthy(res.get("data")):
            return _fail(res)
        d = res["data"]
        beh = _arr(_or(g(d, "Behaviours"), []))
        fac = _arr(_or(g(d, "Facials"), []))
        if _truthy(g(o, "search")):
            beh = [b for b in beh if matches(g(b, "DisplayName"), o["search"])]
            fac = [f for f in fac if matches(g(f, "DisplayName"), o["search"])]
        rows = [{"name": g(b, "DisplayName"), "commands": _or(g(b, "ChatCommands"), []), "via": "chat"} for b in beh]
        if not _truthy(g(o, "search")) or matches(self.STAND_UP["name"], o["search"]):
            rows.append(dict(self.STAND_UP))
        return {**_meta(res), "behaviours": rows,
                "facials": [{"name": g(f, "DisplayName"), "emoji": g(f, "EmojiText")} for f in fac]}


def _ko_key(s):
    """localeCompare(…, 'ko') 근사. 한글·숫자·영문만 쓰는 분류 이름에서는 코드 순서와 같다."""
    return s.casefold() if isinstance(s, str) else _s(s)
