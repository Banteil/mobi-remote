"""각인 강화 반복 (mabi.tasks.enhance) — 누를 때마다 오는 패킷으로 성공·실패·거절을 가린다."""
import types
import unittest
from unittest import mock

from mabi.tasks import enhance
from mabi.tasks.content import CannotProceed


class FakePackets:
    """누를 때마다 script 의 다음 결과를 이벤트로 쌓는다. None = 연출 중이라 강화 안 됨, 'fail' = 거절, 숫자 = 오른 뒤 단계."""

    def __init__(self, script):
        self.script, self.seq, self.recent, self.ok = list(script), 0, [], True

    def mark(self):
        return self.seq

    def press(self):
        r = self.script.pop(0) if self.script else None
        if r == "fail":
            self.add("equip.carving_enhance_fail", {})
        elif r is not None:
            self.add("equip.update", {"id": 7, "carving_level": r, "carving_exp": 0})  # 갱신이 응답보다 먼저 온다
            self.add("equip.carving_enhance_ok", {})

    def add(self, key, vals):
        self.seq += 1
        self.recent.append(types.SimpleNamespace(seq=self.seq, key=key, vals=vals))

    def wait(self, keys, timeout, after=None, check=None, stop=None):
        keys = {keys} if isinstance(keys, str) else set(keys)
        return next((s for s in self.recent if s.seq > after and s.key in keys and (check is None or check(s.vals))), None)


class FakeBot:
    def __init__(self, script):
        self.packets, self.pressed = FakePackets(script), 0
        self.log = types.SimpleNamespace(info=lambda m: None)

    def key(self, k):
        self.pressed += 1
        self.packets.press()

    def snapshot(self, tag):
        return types.SimpleNamespace(name=tag)


class RepeatTest(unittest.TestCase):
    def run_it(self, script, target=15, quiet=None):
        bot, tries = FakeBot(script), []
        with mock.patch.object(enhance, "next_level", return_value=target), \
                mock.patch.object(enhance, "QUIET", 0 if quiet else enhance.QUIET):
            try:
                return enhance.repeat(bot, lambda n, t: tries.append(n)), bot, tries
            except CannotProceed as e:
                return str(e), bot, tries

    def test_until_success(self):
        # 연출 중에 누른 것(None)은 세지 않는다
        got, bot, tries = self.run_it([14, None, 14, None, 15, 15])
        self.assertEqual(got, {"tries": 3, "level": 15})
        self.assertEqual(tries, [1, 2])
        self.assertEqual(bot.pressed, 5)  # 성공한 뒤로는 누르지 않는다

    def test_first_try_success(self):
        self.assertEqual(self.run_it([15])[0], {"tries": 1, "level": 15})

    def test_rejected_stops(self):
        got, bot, _ = self.run_it([14, "fail", 14])
        self.assertIn("골드·재료 부족", got)
        self.assertEqual(bot.pressed, 2)

    def test_level_not_matching_screen_stops(self):
        # 패킷 단계가 화면 목표와 안 맞으면 (칸 위치가 바뀜 등) 더 누르지 않는다
        got, bot, _ = self.run_it([12, 14])
        self.assertIn("알 수 없음", got)
        self.assertEqual(bot.pressed, 1)

    def test_nothing_happens_stops(self):
        got, _, _ = self.run_it([None, None], quiet=True)
        self.assertIn("강화되지 않음", got)

    def test_no_window_no_press(self):
        got, bot, _ = self.run_it([15], target=None)
        self.assertIn("열려 있지 않음", got)
        self.assertEqual(bot.pressed, 0)

    def test_no_packets_no_press(self):
        bot = FakeBot([15])
        bot.packets.ok = False
        with mock.patch.object(enhance, "next_level", return_value=15):
            self.assertRaises(CannotProceed, enhance.repeat, bot)
        self.assertEqual(bot.pressed, 0)


if __name__ == "__main__":
    unittest.main()
