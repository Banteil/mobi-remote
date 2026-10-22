"""커넥터가 알려주지 않는 정보를 관측해서 쌓아 두는 곳 knowledge.json (리모콘 src/knowledge.js).

게임은 ✔/✘ 결론만 주고 판정에 쓴 값(시설 레벨·가공 칸 수·아이템 소속 시설 등)은 감춘다.
가공 칸이 꽉 찬 채 등록하면 이동까지 한 뒤 막히면서 날개 5가 나간다(실측) — 거부가 공짜가 아니라서
"해 보고 실패하면 멈춘다"를 못 쓰고, 시도 전에 칸이 남았는지 알아야 한다. 그 근거가 여기 쌓인다.

파일은 부를 때마다 다시 읽는다 (작고, GUI·실행기가 동시에 고쳐도 최신을 보게).
"""
import json
import math
import re
import threading
from pathlib import Path
from typing import Callable

from .facilitymap import FacilityMap
from .gamerules import GameRules, js_round
from .recipebook import RecipeBook, now_iso

# 한 번의 제작 호출로 만들 수 있는 최대 횟수. 종류를 따지지 않고 10 (실측: 못·탁월한 회복 물약·자동회복 물약)
CRAFT_LIMIT = 10

# 비용으로 나가는 재화. 재료가 아니므로 diff 에서 뺀다
CURRENCIES = ["정령의 날개", "골드", "두카트"]

_COST = re.compile(r"([^\s]+(?:\s[^\s]+)*?)\s+(\d+)\s+spent(?:,\s*(\d+)\s+left)?", re.I)
_PAREN_TAIL = re.compile(r"\s*\([^()]*\)$")


def empty() -> dict:
    return {
        "version": 1,
        "facilities": {},      # 시설명 → {level, autoLevel, maxSlots, observedMax, manual, fullAt, updatedAt}
        "itemFacility": {},    # 아이템명 → 시설명. get_altering_works 에서만 알 수 있다
        "craftLimits": {},     # 제작 레시피명 → {maxCount, at}. invalid_count 응답에서 배운다
        "recipes": {},         # 레시피명 → {kind, produced, ingredients, confidence, observed, conflicts, ...}
        "recipeProduct": {},   # 레시피명 → {item, at}. 이름이 곧 산출물은 아니다
        "updatedAt": None,
    }


def _gt(a, b) -> bool:
    """JS 의 a > b (None·문자열이 섞여도 예외 없이 False)"""
    try:
        return a is not None and b is not None and a > b
    except TypeError:
        return False


def _int_or_nan(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return float(js_round(x)) if not math.isnan(x) and not math.isinf(x) else x


def item_totals(items_data) -> dict[str, int]:
    """get_items 응답 → {이름: 총 개수}. 가방·보관함을 합친다 — 어느 쪽이 줄었는지는 레시피와 무관하다."""
    if isinstance(items_data, list):
        lst = items_data
    else:
        lst = (items_data or {}).get("items") or (items_data or {}).get("Items") or [] \
            if isinstance(items_data, dict) else []
    m: dict[str, int] = {}
    for x in lst:
        n = x.get("DisplayName")
        if not n:
            continue
        m[n] = m.get(n, 0) + (x.get("Count") or 0)
    return m


def diff_items(before: dict, after: dict) -> dict[str, int]:
    """두 스냅샷의 차이 {이름: 증감}. 변화 없는 것은 뺀다."""
    out = {}
    for k in list(before) + [k for k in after if k not in before]:
        d = (after.get(k) or 0) - (before.get(k) or 0)
        if d != 0:
            out[k] = d
    return out


def same_ingredients(a, b) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return all(k in b and a[k] == b[k] for k in a)


def recipe_is_complete(r) -> bool:
    """N회분 계산을 해도 되는가. partial 은 재료가 빠져 있어 안 된다."""
    return bool(r and r.get("ingredients") and r.get("confidence") in ("diff", "confirmed"))


def guess_product(recipe_name) -> str:
    """괄호 안은 원료 구분용이다. 벗기면 산출물 이름 (철괴(광석) → 철괴)"""
    return _PAREN_TAIL.sub("", str(recipe_name or "")).strip() or recipe_name


def product_from_rewards(recipe_name, rewards) -> str | None:
    """응답 rewards 에서 산출물을 고른다. 한 종류면 그것, 여럿이면 이름 추측과 맞는 쪽. 아니면 고르지 않는다 —
    틀린 확정보다 모르는 편이 낫다."""
    if not isinstance(rewards, list) or not rewards:
        return None
    names = [r.get("Name") or r.get("DisplayName") for r in rewards if isinstance(r, dict)]
    names = [n for n in names if n]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    g = guess_product(recipe_name)
    return g if g in names else None


def parse_cost(data) -> dict | None:
    """응답 cost 문장('정령의 날개 5 spent, 52510 left.')에서 실제 소모량. blocked 여도 붙을 수 있다.
    mabi.connector.parse_cost 와 달리 left 가 없는 문장도 받는다. {currency, amount, left, raw}"""
    if not isinstance(data, dict) or not isinstance(data.get("cost"), str):
        return None
    m = _COST.search(data["cost"])
    if not m:
        return None
    return {"currency": m.group(1).strip(), "amount": int(m.group(2)),
            "left": int(m.group(3)) if m.group(3) is not None else None, "raw": data["cost"]}


class Knowledge:
    def __init__(self, file: Path, rules: GameRules, book: RecipeBook, fmap: FacilityMap):
        self.file, self.rules, self.book, self.fmap = file, rules, book, fmap
        self._lock = threading.RLock()  # 읽고-고치고-쓰기 사이에 다른 스레드가 끼지 않게

    # ---------------------------------------------------------------- 파일
    def load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            return {**empty(), **d} if isinstance(d, dict) else empty()
        except (OSError, ValueError):
            return empty()

    def save(self, state: dict) -> dict:
        state["updatedAt"] = now_iso()
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # 저장 실패해도 동작은 계속된다
        return state

    # ---------------------------------------------------------------- 가공 시설
    def default_slots(self) -> int:
        """아무것도 모를 때의 칸 수 = 최고 레벨의 칸 수. 적게 잡으면 시설이 남는데 덜 채우고 이유도 안 보인다.
        크게 잡으면 한 번은 막혀 날개 5가 나가지만 그 한 번으로 레벨이 확정된다. 레벨을 직접 정하면 막힐 일도 없다."""
        return self.rules.slots_for_level(self.rules.max_level())

    @staticmethod
    def _facility_entry(state: dict, name: str) -> dict:
        if not state["facilities"].get(name):
            state["facilities"][name] = {"level": None, "autoLevel": False, "maxSlots": None, "observedMax": 0,
                                         "manual": False, "fullAt": None, "updatedAt": None}
        return state["facilities"][name]

    def learn_from_altering_works(self, data) -> dict:
        """get_altering_works 에서 배운다: 아이템 소속 시설(다른 조회로는 못 앎), 시설별 동시 작업 최대치(칸 수 하한)."""
        works = (data or {}).get("works") or [] if isinstance(data, dict) else []
        if not works:
            return self.load()
        with self._lock:
            state = self.load()
            count: dict[str, int] = {}
            for w in works:
                if not w.get("FacilityName"):
                    continue
                state["itemFacility"][w.get("DisplayName")] = w["FacilityName"]
                count[w["FacilityName"]] = count.get(w["FacilityName"], 0) + 1
            for fac, n in count.items():
                e = self._facility_entry(state, fac)
                if n > (e.get("observedMax") or 0):
                    e["observedMax"] = n
                    e["updatedAt"] = now_iso()
            # 지금 큐에 없는 시설도 다시 본다. 관측 기록은 이미 남아 있으니 결론은 같다
            for fac in list(state["facilities"]):
                self.confirm_top_level(state["facilities"][fac])
            return self.save(state)

    def confirm_top_level(self, e: dict) -> None:
        """큐에 최고 레벨의 칸 수만큼 올라갔다면 레벨이 확정된다 (칸 수는 레벨을 넘을 수 없다).
        중간 레벨은 이렇게 못 정한다 — 5칸 시설은 Lv.4 일 수도, 아직 5개만 넣어 본 것일 수도 있다."""
        if e.get("manual"):
            return  # 사용자가 고른 값이 우선
        top = self.rules.max_level()
        top_slots = self.rules.slots_for_level(top)
        if not ((e.get("observedMax") or 0) >= top_slots):
            return
        e.update(level=top, maxSlots=top_slots, manual=True, autoLevel=True, updatedAt=now_iso())

    def learn_facility_full(self, facility: str, used_slots) -> dict:
        """칸이 꽉 차서 거부당한 시점을 기록한다. 그때의 작업 수가 곧 칸 수다.
        blocked 가 늘 칸 부족은 아니라서(다른 팝업일 수도) 지금까지 본 최대 큐보다 작으면 무시한다 —
        7개까지 올라갔던 시설이 2에서 막혔다면 그건 칸 문제가 아니다."""
        with self._lock:
            state = self.load()
            e = self._facility_entry(state, facility)
            n = _int_or_nan(used_slots)
            if not (n > 0) or n < (e.get("observedMax") or 0):
                return state
            n = int(n)
            e["fullAt"] = {"slots": n, "at": now_iso()}
            if n > (e.get("observedMax") or 0):
                e["observedMax"] = n
            # 직접 지정하지 않았다면 꽉 찬 시점의 수를 칸 수로 본다. 칸 수가 정해지면 레벨도 정해진다
            if not e.get("manual"):
                e["maxSlots"] = n
                lv = self.rules.level_for_slots(n)
                if lv:
                    e.update(level=lv, manual=True, autoLevel=True)  # 이제 확정값. 더 유추하지 않는다
            e["updatedAt"] = now_iso()
            return self.save(state)

    def facility_level_auto(self, facility: str, state: dict | None = None) -> bool:
        """막혀서 자동으로 정해진 레벨인가 (화면에 "직접 지정"과 구분해 적을 때)"""
        e = (state or self.load())["facilities"].get(facility)
        return bool(e and e.get("autoLevel"))

    def set_facility_slots(self, facility: str, slots) -> dict:
        """사용자가 칸 수를 직접 지정한다 (레벨 기능 전의 방식)."""
        with self._lock:
            state = self.load()
            e = self._facility_entry(state, facility)
            ok = _gt(slots, 0)
            e["maxSlots"] = slots if ok else None
            e["manual"] = ok
            e["updatedAt"] = now_iso()
            return self.save(state)

    def facility_slots(self, facility: str, state: dict | None = None) -> dict:
        """이 시설의 칸 수. 사용자 레벨 > 직접 입력 칸 수 > 꽉 참 관측 > 기본값(최고 레벨).
        {slots, source, level, levelSet?}"""
        s = state or self.load()
        e = s["facilities"].get(facility)
        base = self.default_slots()
        if not e:
            return {"slots": base, "source": "레벨 미설정", "level": None}
        # 1) 사용자가 고른 레벨. 게임 화면을 보는 사람만 아는 값이라 무엇보다 우선한다
        if _gt(e.get("level"), 0):
            return {"slots": self.rules.slots_for_level(e["level"]), "source": f"레벨 {e['level']}",
                    "level": e["level"], "levelSet": True}
        # 2) 레벨 기능 전에 칸 수를 직접 넣어 둔 기록
        if e.get("manual") and e.get("maxSlots"):
            return {"slots": e["maxSlots"], "source": "직접 입력", "level": self.rules.level_for_slots(e["maxSlots"])}
        # 3) 꽉 차서 막혔던 적이 있으면 그때의 작업 수가 칸 수
        if e.get("fullAt"):
            return {"slots": e["fullAt"]["slots"], "source": "확인됨",
                    "level": self.rules.level_for_slots(e["fullAt"]["slots"])}
        # 4) 모른다. 최고 레벨인 셈 치고 가다가 막히면 그때 확정된다 (관측치로 낮추면 시설이 작아 보인다)
        return {"slots": base, "source": "레벨 미설정", "level": self.rules.level_for_slots(base)}

    def facility_room(self, facility: str, used, state: dict | None = None) -> dict:
        """지금 더 넣을 수 있는가. 레벨을 정해 둔 시설은 그 칸 수가 상한 — 넘겨 보내면 날개 5를 잃는다.
        {ok, slots, used, free, source, levelSet}"""
        cap = self.facility_slots(facility, state)
        x = _int_or_nan(used)
        u = max(0, int(x) if not math.isnan(x) and not math.isinf(x) else 0)
        return {"ok": u < cap["slots"], "slots": cap["slots"], "used": u, "free": max(0, cap["slots"] - u),
                "source": cap["source"], "levelSet": bool(cap.get("levelSet"))}

    def set_facility_level(self, facility: str, level) -> dict:
        """시설 레벨을 지정한다. 0·None 이면 지정을 지운다 (옛 감지 결과도 같이)."""
        with self._lock:
            state = self.load()
            e = self._facility_entry(state, facility)
            n = _int_or_nan(level)
            if n >= 1:
                e["level"] = min(int(n), self.rules.max_level())
                e["maxSlots"] = self.rules.slots_for_level(e["level"])
                e["manual"] = True
                e["autoLevel"] = False  # 사람이 고른 값이 자동 감지보다 우선
            else:
                e.update(level=None, manual=False, autoLevel=False, fullAt=None)
            e["updatedAt"] = now_iso()
            return self.save(state)

    def facility_of(self, item_name, state: dict | None = None) -> str | None:
        """이 레시피의 시설. 큐에서 본 값이 먼저, 없으면 facility-map.json (처음 돌리는 레시피도 미리 검사하려고)."""
        s = state or self.load()
        return s["itemFacility"].get(item_name) or self.fmap.facility_of(item_name) or None

    def room_report(self, works_data) -> list[dict]:
        """시설마다 몇 칸이 남았는지. 완료된 작업도 칸을 차지한다 (수령해야 비워진다). 여유 많은 순."""
        state = self.load()
        works = (works_data or {}).get("works") or [] if isinstance(works_data, dict) else []
        used: dict = {}
        completed: dict = {}
        for w in works:
            f = w.get("FacilityName")
            used[f] = used.get(f, 0) + 1
            if w.get("IsCompleted"):
                completed[f] = completed.get(f, 0) + 1
        names = list(used) + [k for k in state["facilities"] if k not in used]
        out = []
        for fac in names:
            cap = self.facility_slots(fac, state)
            u = used.get(fac, 0)
            fe = state["facilities"].get(fac)
            out.append({"facility": fac, "used": u, "completed": completed.get(fac, 0), "slots": cap["slots"],
                        "free": max(0, cap["slots"] - u), "source": cap["source"], "level": cap.get("level"),
                        "levelSet": bool(cap.get("levelSet")), "levelAuto": bool(fe and fe.get("autoLevel"))})
        out.sort(key=lambda r: -r["free"])
        return out

    # ---------------------------------------------------------------- 제작 상한
    def learn_craft_limit(self, recipe, max_count) -> dict:
        """invalid_count 응답의 maxCount 를 기억한다. 다음부터 미리 맞춘다."""
        if not recipe or not _gt(max_count, 0):
            return self.load()
        with self._lock:
            state = self.load()
            state["craftLimits"][recipe] = {"maxCount": max_count, "at": now_iso()}
            return self.save(state)

    def craft_limit(self, recipe, state: dict | None = None) -> int:
        """배운 값이 있으면 그쪽(게임이 invalid_count 로 알려 준 값), 없으면 규칙값 10."""
        e = (state or self.load())["craftLimits"].get(recipe)
        return e["maxCount"] if e else CRAFT_LIMIT

    # ---------------------------------------------------------------- 레시피
    # 출처가 둘이고 성격이 정반대다.
    #   MissingIngredients: 부족분만이라 불완전하지만 게임이 직접 말한 정확한 숫자
    #   인벤 diff: 재료 전체를 보지만 제작 중에 다른 일이 끼면 오염된다
    # 그래서 게임 숫자를 우선하고(confirmed), diff 값이 어긋나면 덮지 않고 conflicts 에 쌓았다가 같은 값이 두 번이면 확정한다.
    @staticmethod
    def _recipe_entry(state: dict, name: str) -> dict:
        if not state["recipes"].get(name):
            state["recipes"][name] = {"kind": None, "produced": None, "ingredients": None, "confidence": None,
                                      "observed": 0, "conflicts": [], "updatedAt": None}
        e = state["recipes"][name]
        e.setdefault("conflicts", [])
        e.setdefault("observed", 0)
        return e

    def learn_recipe_from_diff(self, name, kind, diff: dict | None = None, runs=None, rewards=None,
                               produced=None) -> dict:
        """실행 전후 인벤 비교로 레시피를 배운다. 1회 실행만 믿는다 (여러 회를 나누면 잡음이 소수점으로 번진다).
        줄어든 것만 재료 후보, 재화는 비용이라 제외, 자기 자신·산출물도 제외."""
        if not name or not diff:
            return self.load()
        if runs is not None and runs != 1:
            return self.load()
        product = product_from_rewards(name, rewards) or self.product_of(name)

        ingredients = {}
        for k, d in diff.items():
            if d >= 0 or k in CURRENCIES or k == name or k == product:
                continue
            ingredients[k] = -d
        if not ingredients:
            return self.load()

        # 산출량 — rewards 가 사실이고, 없으면 diff 증가분, 그것도 없으면 조회의 ProducedPer*
        made = None
        if isinstance(rewards, list):
            hit = [r for r in rewards if (r.get("Name") or r.get("DisplayName")) == product]
            if hit:
                made = sum(r.get("Amount") or 0 for r in hit)
        if made is None and _gt(diff.get(product), 0):
            made = diff[product]
        if made is None and produced:
            made = produced

        # rewards 가 산출물을 직접 말해 줬다면 추측을 사실로 바꾼다
        if product_from_rewards(name, rewards):
            self.learn_product(name, product)

        with self._lock:
            state = self.load()
            e = self._recipe_entry(state, name)
            e["kind"] = kind or e.get("kind")
            e["observed"] = (e.get("observed") or 0) + 1
            e["updatedAt"] = now_iso()
            if made:
                e["produced"] = made
            e["product"] = product

            if not e.get("ingredients"):
                e["ingredients"], e["confidence"] = ingredients, "diff"
            elif same_ingredients(e["ingredients"], ingredients):
                # 같은 값을 다시 봤다 — 쌓아 둔 충돌을 정리한다
                if e.get("confidence") != "confirmed":
                    e["confidence"] = "diff"
                e["conflicts"] = []
            elif e.get("confidence") == "confirmed":
                # 게임이 직접 준 값이 이미 있다. 덮지 않고 기록만
                e["conflicts"].append({"ingredients": ingredients, "at": e["updatedAt"], "from": "diff"})
            else:
                # 같은 충돌을 두 번 봤으면 그쪽이 맞다
                twice = any(same_ingredients(c.get("ingredients"), ingredients) for c in e["conflicts"])
                e["conflicts"].append({"ingredients": ingredients, "at": e["updatedAt"], "from": "diff"})
                if twice:
                    e["ingredients"], e["conflicts"] = ingredients, []
            return self.save(state)

    def learn_recipe_from_missing(self, name, kind, missing, produced=None) -> dict:
        """MissingIngredients 에서 배운다. 정확하지만 부족분만이라 단독으로는 레시피를 못 완성한다.
        아는 값과 일치하고 아는 재료를 전부 짚어 주면 confirmed, 어긋나면 게임 쪽으로 고친다, 모르면 partial."""
        if not name or not isinstance(missing, list) or not missing:
            return self.load()
        with self._lock:
            state = self.load()
            e = self._recipe_entry(state, name)
            e["kind"] = kind or e.get("kind")
            e["updatedAt"] = now_iso()
            if produced:
                e["produced"] = produced

            if not e.get("ingredients"):
                e["ingredients"] = {m.get("DisplayName"): m.get("Required") for m in missing}
                e["confidence"] = "partial"  # 전체 레시피가 아니다 — 부족했던 재료뿐
                return self.save(state)

            fixed = False
            for m in missing:
                if e["ingredients"].get(m.get("DisplayName"), _MISSING) != m.get("Required"):
                    e["ingredients"][m.get("DisplayName")] = m.get("Required")
                    fixed = True
            # 아는 재료를 전부 짚어 줬을 때만 확정. 일부만 맞았다고 전체를 믿으면 나머지가 확정으로 둔갑한다
            named = {m.get("DisplayName") for m in missing}
            all_named = all(k in named for k in e["ingredients"])
            if fixed:
                e["conflicts"].append({"fixedBy": "MissingIngredients", "at": e["updatedAt"]})
                e["confidence"] = "confirmed" if all_named else "partial"  # 하나가 틀렸으면 나머지도 의심
            elif all_named:
                e["confidence"] = "confirmed"
                e["conflicts"] = []
            return self.save(state)

    def recipe(self, name, state: dict | None = None) -> dict | None:
        return (state or self.load())["recipes"].get(name)

    def recipe_materials(self, name, state: dict | None = None, have: Callable | None = None) -> list[str]:
        """이 레시피에 드는 재료 이름 전부 (개수는 모를 수 있다). 자동으로 못 구하는 재료를 미리 알리는 데 쓴다."""
        mine = self.recipe(name, state)
        if recipe_is_complete(mine):
            return list(mine["ingredients"])
        b = self.book.pick(name, have)
        if b:
            return list(b["ingredients"])
        return list(mine["ingredients"]) if mine and mine.get("ingredients") else []

    def recipe_ingredients(self, name, state: dict | None = None, have: Callable | None = None) -> dict | None:
        """1회분 재료를 가장 믿을 만한 곳에서. 직접 만들어 알아낸 값 > 레시피 장부 > partial.
        장부에는 이름만 아는 재료(개수 None)가 섞여 있어, 계산엔 개수를 아는 것만 넘기고 이름은 따로 준다.
        {ingredients, complete, source, variants, unknownAmounts?} 또는 None"""
        mine = self.recipe(name, state)
        if recipe_is_complete(mine):
            return {"ingredients": mine["ingredients"], "complete": True, "source": "observed", "variants": 1}
        b = self.book.pick(name, have)
        if b:
            known = {k: v for k, v in b["ingredients"].items() if v is not None}
            unknown = [k for k, v in b["ingredients"].items() if v is None]
            if known:
                return {"ingredients": known, "unknownAmounts": unknown,
                        "complete": bool(b["complete"]) and not unknown, "source": "book", "variants": b["count"]}
        if mine and mine.get("ingredients"):
            return {"ingredients": mine["ingredients"], "complete": False, "source": "partial", "variants": 1}
        return None

    def forget_recipe(self, name) -> dict:
        """잘못 배운 것을 지운다. 관측은 틀릴 수 있다."""
        with self._lock:
            state = self.load()
            state["recipes"].pop(name, None)
            return self.save(state)

    # ---------------------------------------------------------------- 레시피 → 산출물
    # 응답 어디에도 "이 레시피가 무엇을 만드는가" 필드가 없다 (가공 91종 중 8종이 산출물(원료) 꼴).
    # 괄호를 벗겨 추측하되, 수령 보상으로 실제로 보면 그쪽으로 확정한다.
    def product_of(self, recipe_name, state: dict | None = None) -> str:
        s = state or self.load()
        e = (s.get("recipeProduct") or {}).get(recipe_name)
        return e["item"] if e else guess_product(recipe_name)

    def product_is_observed(self, recipe_name, state: dict | None = None) -> bool:
        s = state or self.load()
        return bool((s.get("recipeProduct") or {}).get(recipe_name))

    def learn_product(self, recipe_name, item) -> dict:
        if not recipe_name or not item:
            return self.load()
        with self._lock:
            state = self.load()
            if not state.get("recipeProduct"):
                state["recipeProduct"] = {}
            prev = state["recipeProduct"].get(recipe_name)
            if prev and prev.get("item") == item:
                return state
            state["recipeProduct"][recipe_name] = {"item": item, "at": now_iso()}
            return self.save(state)

    # 모듈 함수도 같은 이름으로 쓸 수 있게
    item_totals = staticmethod(item_totals)
    diff_items = staticmethod(diff_items)
    recipe_is_complete = staticmethod(recipe_is_complete)
    guess_product = staticmethod(guess_product)
    product_from_rewards = staticmethod(product_from_rewards)
    parse_cost = staticmethod(parse_cost)


_MISSING = object()
