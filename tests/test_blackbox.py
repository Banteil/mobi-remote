import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from mabi import blackbox
from mabi.packet_monitor import PacketMonitor


class BlackBoxTest(unittest.TestCase):
    def test_dump_writes_frames_and_timeline(self):
        b = blackbox.BlackBox(seconds=30, every=0)
        b.frame(np.zeros((1080, 1920, 3), np.uint8))
        b.input("키 space")
        pm = PacketMonitor(Path("."))
        pm.apply("MapEnter", {"map": 1})
        with tempfile.TemporaryDirectory() as t:
            d = b.dump(Path(t), "test", pm, np.zeros((1080, 1920, 3), np.uint8))
            self.assertIsNotNone(d)
            self.assertGreaterEqual(len(list(d.glob("*.jpg"))), 1)
            text = (d / "timeline.txt").read_text(encoding="utf-8")
            self.assertIn("키 space", text)
            self.assertIn("MapEnter", text)

    def test_old_entries_dropped(self):
        b = blackbox.BlackBox(seconds=1, every=0)
        b.inputs.append((time.time() - 5, "old"))
        b.input("new")
        self.assertEqual([w for _, w in b.inputs], ["new"])

    def test_prune_keeps_latest(self):
        with tempfile.TemporaryDirectory() as t:
            for i in range(5):
                (Path(t) / f"blackbox_2026102{i}_000000_x").mkdir()
            blackbox.prune(Path(t), keep=2)
            self.assertEqual(len(list(Path(t).glob("blackbox_*"))), 2)


if __name__ == "__main__":
    unittest.main()
