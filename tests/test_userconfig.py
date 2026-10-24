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


if __name__ == "__main__":
    unittest.main()
