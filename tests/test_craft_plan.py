"""레시피 표로 미리 세우는 제작·가공 계획 (mabi.craft.needs) 과 그 계획에서 고르는 다음 걸음 (goal.plan_step)."""
import json
import tempfile
import unittest
from pathlib import Path

from mabi.craft import goal, needs
from mabi.craft.recipes import RecipeTable

ROWS = [
    {"id": 1, "via": "alter", "name": "철괴(광석)", "product": "철괴", "per": 3, "facility": "금속 가공 시설",
     "level": 1, "sec": 60, "ingredients": {"광석": 20}},
    {"id": 2, "via": "alter", "name": "철괴(철 광석)", "product": "철괴", "per": 3, "facility": "금속 가공 시설",
     "level": 1, "sec": 60, "ingredients": {"철 광석": 10}},
    {"id": 3, "via": "alter", "name": "강철괴", "product": "강철괴", "per": 3, "facility": "금속 가공 시설",
     "level": 1, "sec": 300, "ingredients": {"철괴": 3, "석탄": 4}},
    {"id": 4, "via": "craft", "name": "못", "product": "못", "per": 10, "facility": "다목적 제작대", "level": 1,
     "skill": "대장 기술", "skillLevel": 1, "ingredients": {"철괴": 2}},
    {"id": 5, "via": "alter", "name": "은합금괴", "product": "은합금괴", "per": 3, "facility": "금속 가공 시설",
     "level": 4, "sec": 600, "ingredients": {"강철괴": 5, "은 광석": 20}},
    {"id": 6, "via": "alter", "name": "은합금괴", "product": "은합금괴", "per": 3, "facility": "금속 가공 시설",
     "level": 6, "sec": 900, "ingredients": {"마력 깃든 돌": 12, "은 광석": 20}},
    {"id": 7, "via": "craft", "name": "장검", "product": "장검", "per": 1, "facility": "무기 제작대", "level": 2,
     "skill": "대장 기술", "skillLevel": 5, "ingredients": {"강철괴": 2, "못": 5, "지배의 도안": 1},
     "quest": ["지배의 도안"]},
]
ALL_TOOLS = {"광석": True, "철 광석": True, "석탄": True, "은 광석": True}


def table() -> RecipeTable:
    d = Path(tempfile.mkdtemp())
    (d / "recipes.json").write_text(json.dumps({"recipes": ROWS}, ensure_ascii=False), encoding="utf-8")
    return RecipeTable(d / "recipes.json")


def plan(name, n, **ctx):
    return needs.plan(table(), name, n, {"gatherable": ALL_TOOLS, **ctx})


class RecipeTableTest(unittest.TestCase):
    def test_twins_only_first_selectable(self):
        t = table()
        self.assertEqual([r["level"] for r in t.makers("은합금괴")], [4, 6])
        self.assertEqual([r["level"] for r in t.selectable_makers("은합금괴")], [4])
        self.assertEqual(t.row_at("은합금괴", 1)["level"], 6)
        self.assertEqual(t.product_of("철괴(광석)"), "철괴")
        self.assertEqual(t.facility_of("못"), "다목적 제작대")

    def test_missing_file_is_empty(self):
        t = RecipeTable(Path(tempfile.mkdtemp()) / "없음.json")
        self.assertEqual(len(t), 0)
        self.assertFalse(needs.plan(t, "못", 10)["ok"])


class PlanTest(unittest.TestCase):
    def test_chain_totals(self):
        p = plan("못", 25)
        self.assertTrue(p["ok"])
        steps = {s["recipe"]: s for s in p["steps"]}
        self.assertEqual(steps["못"]["runs"], 3)          # 25개 → 10개씩 3회
        self.assertEqual(steps["못"]["calls"], 1)         # 제작은 10회까지 한 번에
        self.assertEqual(sum(s["runs"] for s in p["steps"] if s["product"] == "철괴"), 2)  # 철괴 6 → 3개씩 2회
        self.assertEqual(p["steps"][-1]["recipe"], "못")  # 재료가 먼저
        self.assertEqual(p["wings"], p["calls"]["total"] * 5)

    def test_aggregates_shared_ingredient(self):
        # 장검 2개: 강철괴 4 → 2회(철괴 6), 못 10 → 1회(철괴 2). 철괴 8 → 3개씩 3회 (한 단계로 묶여서)
        p = plan("장검", 2, owned={"지배의 도안": 2})
        iron = [s for s in p["steps"] if s["product"] == "철괴"]
        self.assertEqual(len(iron), 1)
        self.assertEqual(iron[0]["runs"], 3)
        self.assertEqual(p["missing"], [])

    def test_uses_stock_and_incoming(self):
        p = plan("못", 30, owned={"철괴": 4}, incoming={"철괴": 3})
        self.assertFalse([s for s in p["steps"] if s["product"] == "철괴"])  # 4 + 가공 중 3 ≥ 6
        self.assertEqual(p["gather"], [])

    def test_fresh_ignores_target_stock(self):
        self.assertEqual(plan("못", 10, owned={"못": 50, "철괴": 2})["steps"], [])
        self.assertEqual(plan("못", 10, owned={"못": 50, "철괴": 2}, fresh=True)["steps"][0]["runs"], 1)

    def test_picks_route_with_tool(self):
        p = plan("철괴", 3, gatherable={"광석": False, "철 광석": True})
        self.assertEqual(p["steps"][0]["recipe"], "철괴(철 광석)")
        self.assertEqual(p["gather"][0]["name"], "철 광석")

    def test_recipe_name_fixes_route(self):
        self.assertEqual(plan("철괴(광석)", 3)["steps"][0]["recipe"], "철괴(광석)")

    def test_quest_item_missing(self):
        p = plan("장검", 1)
        self.assertEqual([(m["name"], m["reason"]) for m in p["missing"]], [("지배의 도안", "quest")])

    def test_level_block_with_twin(self):
        p = plan("은합금괴", 3, levels={"금속 가공 시설": 3})
        self.assertEqual([b["recipe"] for b in p["blocked"]], ["은합금괴"])  # Lv.6 갈래는 시킬 수 없다
        self.assertEqual(p["steps"][-1]["recipe"], "은합금괴")               # 그래도 필요한 양은 끝까지 센다

    def test_transfer_cost_not_refused(self):
        # 반출 비용(분해된 장비 부품)만 모자란 레시피는 된다고 보고 계획한다
        craft = goal.recipe_map([{"DisplayName": "못", "Craftable": False, "ProducedPerCraft": 10,
                                  "Reason": "insufficient_transfer_cost"}], "Craftable", "ProducedPerCraft")
        self.assertTrue(craft["못"]["ok"])

    def test_refused_recipe_blocked(self):
        p = plan("못", 10, owned={"철괴": 2}, refused={"못": "insufficient_living_skill_level"})
        self.assertEqual(p["blocked"][0]["reason"], "insufficient_living_skill_level")


def snap(owned, room=None, completed=None, in_progress=None):
    facs = []
    if completed or in_progress:
        facs.append({"facility": "금속 가공 시설", "completed": [{"name": n} for n in completed or []],
                     "inProgress": [{"name": n, "remainingSec": 30} for n in in_progress or []]})
    return {"owned": owned, "works": {"room": room or [], "facilities": facs}}


class PlanStepTest(unittest.TestCase):
    def test_alter_before_gather(self):
        p = plan("강철괴", 6, owned={"철괴": 3, "석탄": 8})  # 강철괴 2회 — 1회분은 지금 된다, 철괴는 더 캐야 한다
        st = goal.plan_step(snap({"철괴": 3, "석탄": 8}), p)
        self.assertEqual((st["kind"], st["name"]), ("alter", "강철괴"))

    def test_gather_when_nothing_runs(self):
        p = plan("철괴", 3, gatherable={"광석": False, "철 광석": True})
        st = goal.plan_step(snap({}), p)
        self.assertEqual((st["kind"], st["name"], st["need"]), ("gather", "철 광석", 10))

    def test_craft_batch_limited_by_stock(self):
        p = plan("못", 50, owned={"철괴": 10})  # 계획 5회, 철괴 10 이면 5회 다 된다
        self.assertEqual(goal.plan_step(snap({"철괴": 10}), p)["batch"], 5)
        self.assertEqual(goal.plan_step(snap({"철괴": 4}), p)["batch"], 2)  # 그새 줄었으면 되는 만큼만

    def test_full_facility_collects(self):
        p = plan("강철괴", 3, owned={"철괴": 3, "석탄": 4})
        room = [{"facility": "금속 가공 시설", "used": 2, "slots": 2, "free": 0}]
        st = goal.plan_step(snap({"철괴": 3, "석탄": 4}, room, completed=["철괴(광석)"]), p)
        self.assertEqual((st["kind"], st["facility"]), ("collect", "금속 가공 시설"))

    def test_listed_queue_full_never_sends(self):
        # 배워 둔 칸 수로는 남아 보여도 게임 목록이 queue_full 이면 등록하지 않는다 (날개 5가 그냥 나간다)
        p = plan("강철괴", 3, owned={"철괴": 3, "석탄": 4})
        s = snap({"철괴": 3, "석탄": 4}, in_progress=["철괴(광석)"])
        s["alter"] = {"강철괴": {"name": "강철괴", "ok": False, "reason": "queue_full"}}
        self.assertEqual(goal.plan_step(s, p)["kind"], "wait")

    def test_waits_for_incoming(self):
        p = plan("못", 10, incoming={"철괴": 3})
        st = goal.plan_step(snap({}, in_progress=["철괴(광석)"]), p)
        self.assertEqual(st["kind"], "wait")

    def test_missing_blocks_first(self):
        st = goal.plan_step(snap({}), plan("장검", 1))
        self.assertEqual((st["kind"], st["reason"]), ("blocked", "not_obtainable"))


if __name__ == "__main__":
    unittest.main()
