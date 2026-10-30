"""판 사이 수리 판단 (어비스·레이드 공통) — 수리했는데 내구도가 그대로면 멈춘다 (매 판 대장간 왕복 방지)."""
import unittest
from unittest import mock

from mabi.tasks import repair
from mabi.tasks.content import CannotProceed


class RepairDueTest(unittest.TestCase):
    def bot(self, d):
        b = mock.MagicMock()
        b.packets.ok = True
        b.packets.state.durability = d
        return b

    def test_due(self):
        self.assertFalse(repair.due(self.bot(0.5), 0.05, None))
        self.assertTrue(repair.due(self.bot(0.03), 0.05, None))
        self.assertFalse(repair.due(self.bot(0.03), 0, None))  # 0 = 수리 안 함

    def test_repaired_but_same(self):
        with self.assertRaises(CannotProceed):
            repair.due(self.bot(0.03), 0.05, 0.03)


if __name__ == "__main__":
    unittest.main()
