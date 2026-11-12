import tempfile
import tomllib
import unittest
from pathlib import Path

from mabi import userconfig
from mabi.paths import Paths
from mabi.runner import load_config

DEFAULT = """# 기본 설정
[arbeit]
gather_timeout = 180   # 채집이 늘지 않으면 포기
max_jobs = 20

[tribute]
max_runs = 1

[silver]
dungeon = ""
"""

# 옛 판: 기본 설정을 통째로 복사해 둔 파일 (gather_timeout 은 옛 기본값 300)
OLD_USER = """# 기본 설정
[arbeit]
gather_timeout = 300
max_jobs = 30          # 사용자가 바꿈

[tribute]
max_runs = 1

[silver]
dungeon = "룬다 던전"

[silver.by_slot.2]
dungeon = "피오드 던전"
"""


class UserConfigTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        (root / "res").mkdir()
        (root / "res" / "config.default.toml").write_text(DEFAULT, encoding="utf-8")
        self.paths = Paths(data=root / "data", resources=root / "res")

    def test_new_user_gets_empty_file(self):
        self.assertEqual(load_config(self.paths)["arbeit"]["gather_timeout"], 180)
        self.assertEqual(tomllib.loads(self.paths.config.read_text(encoding="utf-8")), {})

    def test_migrate_keeps_only_changes(self):
        self.paths.data.mkdir()
        self.paths.config.write_text(OLD_USER, encoding="utf-8")
        cfg = load_config(self.paths)
        self.assertEqual(cfg["arbeit"]["gather_timeout"], 180)  # 옛 기본값은 버리고 새 기본값
        self.assertEqual(cfg["arbeit"]["max_jobs"], 30)
        self.assertEqual(cfg["silver"]["by_slot"]["2"]["dungeon"], "피오드 던전")
        saved = tomllib.loads(self.paths.config.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"arbeit": {"max_jobs": 30}, "silver": {"dungeon": "룬다 던전", "by_slot": {"2": {"dungeon": "피오드 던전"}}}})
        self.assertTrue((self.paths.data / "config.toml.bak").exists())
        self.assertFalse(userconfig.migrate(self.paths))  # 한 번만

    def test_doc_save_round_trip(self):
        d = userconfig.doc(self.paths)
        d["tribute"]["max_runs"] = 3
        userconfig.save(self.paths, d)
        self.assertEqual(load_config(self.paths)["tribute"]["max_runs"], 3)
        d = userconfig.doc(self.paths)
        d["tribute"]["max_runs"] = 1  # 기본값으로 돌리면 파일에서 빠진다
        userconfig.save(self.paths, d)
        self.assertNotIn("tribute", tomllib.loads(self.paths.config.read_text(encoding="utf-8")))


class HelpersTest(unittest.TestCase):
    """설정 화면·캐릭터 탭이 같이 쓰는 작은 도우미 (예전엔 화면마다 같은 줄을 따로 썼다)."""

    def test_silver_places_fkey(self):
        d = {"silver": {"field": "평원", "field_runs": "3", "dungeon": "던전", "floor": 2},
             "places": {"가": {"index": 0}, "나": {"index": 1}, "다": {"index": 2}}}
        self.assertEqual(userconfig.silver_defaults(d), {"field": "평원", "field_runs": 3, "dungeon": "던전", "floor": 2})
        self.assertEqual(userconfig.places(d, "dungeon"), ["가", "나"])
        self.assertEqual(userconfig.places(d, "field"), ["다"])
        self.assertTrue(userconfig.is_fkey("F12"))
        self.assertFalse(userconfig.is_fkey("f13"))
        self.assertFalse(userconfig.is_fkey("a"))


if __name__ == "__main__":
    unittest.main()
