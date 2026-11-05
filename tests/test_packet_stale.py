"""게임이 패치돼 패킷 표가 맞지 않으면 패킷 신호를 끈다 (11-05 자동 이동 시작을 못 알아봄)."""
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi import packet_monitor as pm


class StaleTableTest(unittest.TestCase):
    def monitor(self, data: bytes, want: str):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        f = Path(d.name) / "global-metadata.dat"
        f.write_bytes(data)
        m = pm.PacketMonitor(Path(d.name))
        m.table = SimpleNamespace(meta={"game_metadata_sha256": want})
        m.diag = mock.MagicMock()
        m.status, m.last_rx = "running", time.monotonic()
        m._game_file = f
        return m, f

    def test_same_game_keeps_running(self):
        m, _ = self.monitor(b"v1", hashlib.sha256(b"v1").hexdigest()[:16])
        self.assertTrue(m.ok)
        self.assertEqual(m.status, "running")

    def test_patched_game_turns_off(self):
        m, f = self.monitor(b"v1", hashlib.sha256(b"v1").hexdigest()[:16])
        self.assertTrue(m.ok)
        f.write_bytes(b"v2 patched")
        m._game_checked -= pm.PacketMonitor.GAME_CHECK  # 1분 뒤
        m._game_mtime = 0.0
        self.assertFalse(m.ok)
        self.assertEqual(m.status, "stale_table")

    def test_no_game_file_is_not_stale(self):
        m, _ = self.monitor(b"v1", "0000000000000000")
        m._game_file = False
        self.assertTrue(m.ok)


if __name__ == "__main__":
    unittest.main()
