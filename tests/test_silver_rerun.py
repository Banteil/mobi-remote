"""은동전: 도는 동안 저절로 찬 은동전으로 한 판 더 할 만큼 남으면 한 번 더 돈다."""
import unittest
from unittest import mock

from mabi.tasks import silver

CFG = {"silver": {"unit": 20}}


class RerunTest(unittest.TestCase):
    def test_runs_again_when_enough_left(self):
        with mock.patch.object(silver, "_run_round", side_effect=[("첫 판", 20), ("둘째 판", 0)]) as r:
            note = silver.run(mock.Mock(), CFG)
        self.assertEqual(r.call_count, 2)
        self.assertIn("더: 둘째 판", note)

    def test_stops_when_below_unit(self):
        with mock.patch.object(silver, "_run_round", return_value=("첫 판", 19)) as r:
            self.assertEqual(silver.run(mock.Mock(), CFG), "첫 판")
        self.assertEqual(r.call_count, 1)

    def test_only_one_extra_round(self):
        with mock.patch.object(silver, "_run_round", return_value=("판", 40)) as r:
            silver.run(mock.Mock(), CFG)
        self.assertEqual(r.call_count, 2)


if __name__ == "__main__":
    unittest.main()
