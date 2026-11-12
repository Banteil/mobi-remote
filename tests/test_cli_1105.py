"""11-05 게임 패치로 바뀐 CLI — 성장 가이드로 일일 완료, 제작 갈래(variant), 재료 전체(Ingredients), 생활 스킬 레벨."""
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi import cache
from mabi.craft import execute, needs
from mabi.tasks import guide

GUIDE = {"Contents": [
    {"Target": "검은 구멍", "DayType": "Daily", "IsUnlocked": True, "IsCompleted": True, "RemainingCount": 2},
    {"Target": "요일 던전", "DayType": "Daily", "IsUnlocked": True, "IsCompleted": False},
    {"Target": "검은 구멍", "DayType": "Weekly", "IsUnlocked": True, "IsCompleted": False, "RemainingCount": 4},
]}


def fake_bot(data, ok=True):
    return SimpleNamespace(state=SimpleNamespace(available=lambda: ok, query=lambda *a, **k: data), log=mock.MagicMock())


class GrowthTest(unittest.TestCase):
    def test_daily_done_from_cli(self):
        bot = fake_bot(GUIDE)
        self.assertTrue(guide.growth_done(bot, "검은 구멍"))  # 이월된 횟수가 남아도 끝남은 IsCompleted
        self.assertFalse(guide.growth_done(bot, "요일 던전"))
        self.assertFalse(guide.growth_done(bot, "검은 구멍", "Weekly"))

    def test_unknown_falls_back(self):
        self.assertIsNone(guide.growth_done(fake_bot(GUIDE), "필드 보스"))
        self.assertIsNone(guide.growth_done(fake_bot(None), "요일 던전"))
        self.assertIsNone(guide.growth_done(fake_bot(GUIDE, ok=False), "요일 던전"))

    def test_daily_achieved_skips_guide_window(self):
        with mock.patch.object(guide, "open_guide") as og:
            self.assertFalse(guide.daily_achieved(fake_bot(GUIDE), "guide_daily_weekday"))
        og.assert_not_called()


class CraftCliTest(unittest.TestCase):
    def test_missing_from_ingredients(self):
        d = {"items": [{"DisplayName": "못", "Ingredients": [{"DisplayName": "철괴", "Required": 2, "Owned": 1},
                                                             {"DisplayName": "목재", "Required": 1, "Owned": 9}]}]}
        cache.normalize("get_craftable_items", d)
        self.assertEqual(d["items"][0]["MissingIngredients"], [{"DisplayName": "철괴", "Required": 2, "Owned": 1}])

    def test_pick_variant_by_ingredients(self):
        rows = {"items": [
            {"DisplayName": "은합금괴", "Variant": 1, "Ingredients": [{"DisplayName": "은괴", "Required": 3}]},
            {"DisplayName": "은합금괴", "Variant": 2, "Ingredients": [{"DisplayName": "은괴", "Required": 2},
                                                                     {"DisplayName": "철괴", "Required": 1}]}]}
        cli = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(ok=True, data=rows))
        cd = SimpleNamespace(recipes=SimpleNamespace(first=lambda n, v: {"ingredients": {"은괴": 2, "철괴": 1}}))
        self.assertEqual(execute.pick_variant(cd, cli, "은합금괴"), 2)
        cd.recipes.first = lambda n, v: None
        self.assertEqual(execute.pick_variant(cd, cli, "은합금괴"), 1)

    def test_skill_level_blocks_before_trying(self):
        row = {"name": "롱소드", "via": "craft", "skill": "대장 기술", "skillLevel": 30}
        self.assertEqual(needs._block_of(row, {"skills": {"대장 기술": 24}}),
                         {"reason": "insufficient_living_skill_level", "haveSkill": 24})
        self.assertIsNone(needs._block_of(row, {"skills": {"대장 기술": 30}}))
        self.assertIsNone(needs._block_of(row, {}))  # 레벨을 모르면 게임 목록의 거절 이유로만


if __name__ == "__main__":
    unittest.main()
