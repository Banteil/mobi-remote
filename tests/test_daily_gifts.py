"""일일 미션 '선물 받기' — 목록을 조금씩 내려가며 못 받은 선물이 없어질 때까지 받는다 (mabi.tasks.daily_mission)."""
import logging
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from mabi.tasks import daily_mission

CFG = tomllib.loads((Path(__file__).resolve().parent.parent / "config.default.toml").read_text(encoding="utf-8"))


class FakePackets:
    ok = True

    def __init__(self):
        self.seq = 0
        self.got = []

    def mark(self):
        return self.seq

    def wait(self, keys, timeout, after=None, check=None):
        return self.got[-1] if self.got and self.got[-1].seq > after else None


class FakeBot:
    """미션 11개가 두 칸씩 6줄. 화면에는 3줄이 보이고 휠 3칸에 한 줄씩 내려간다."""

    def __init__(self, gifts):
        self.gifts = set(gifts)  # 선물을 못 받은 미션 번호 (0~10)
        self.top = 0
        self.hidden = False  # 지금 창에서 버튼이 안 잡힘 (연금술에서 ESC 로 돌아온 창 — 2026-10-25)
        self.opened = 0
        self.packets = FakePackets()
        self.log = logging.getLogger("test")
        self.state = SimpleNamespace(query=lambda name: [
            {"Title": str(i), "IsCompleted": True, "IsRewardReceived": i not in self.gifts} for i in range(11)])

    def scroll(self, x, y, notches):
        self.top = 0 if notches > 0 else min(self.top + 1, 3)

    def sleep(self, a, b=None):
        pass

    def frame(self):
        return np.full((1080, 1920, 3), self.top * 40, dtype=np.uint8)

    def exists(self, name):
        return True

    def to_main(self):
        self.opened += 1

    def key(self, k):
        pass

    def wait(self, name, timeout=None):
        self.hidden = False  # 창을 새로 열면 받을 카드가 보인다

    def snapshot(self, name):
        return SimpleNamespace(name=name)

    def find_all(self, name):
        if self.hidden:
            return []
        rows = range(self.top, self.top + 3)
        return [SimpleNamespace(i=i) for i in sorted(self.gifts) if i // 2 in rows]

    def click(self, b):
        self.gifts.discard(b.i)
        self.packets.seq += 1
        self.packets.got.append(SimpleNamespace(seq=self.packets.seq, key="dm.reward_ok"))


class GiftTest(unittest.TestCase):
    def test_middle_rows_are_not_skipped(self):
        bot = FakeBot([1, 2, 5, 6, 7, 9, 10])
        self.assertEqual(daily_mission.claim_gifts(bot, CFG["daily_mission"]), 7)
        self.assertFalse(bot.gifts)

    def test_reopens_window_when_buttons_not_found(self):
        bot = FakeBot([0, 1])
        bot.hidden = True
        self.assertEqual(daily_mission.claim_gifts(bot, CFG["daily_mission"]), 2)
        self.assertEqual(bot.opened, 1)

    def test_nothing_to_claim_never_clicks(self):
        bot = FakeBot([])
        self.assertEqual(daily_mission.claim_gifts(bot, CFG["daily_mission"]), 0)


if __name__ == "__main__":
    unittest.main()
