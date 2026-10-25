"""오래된 스크린샷 자동 정리."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from mabi.bot import prune_shots


class PruneShotsTest(unittest.TestCase):
    def test_only_old_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            old, new = d / "20261001_120000_login.png", d / "20261025_120000_login.png"
            mine, other = d / "내 사진.png", d / "20261001_120000_note.txt"  # 사용자가 둔 파일은 건드리지 않는다
            for f in (old, new, mine, other):
                f.write_bytes(b"x")
            past = time.time() - 8 * 86400
            for f in (old, mine, other):
                os.utime(f, (past, past))
            self.assertEqual(prune_shots(d), 1)
            self.assertEqual(sorted(f.name for f in d.iterdir()), sorted([new.name, mine.name, other.name]))

    def test_missing_dir(self):
        self.assertEqual(prune_shots(Path(tempfile.gettempdir()) / "없는-폴더-shots"), 0)


if __name__ == "__main__":
    unittest.main()
