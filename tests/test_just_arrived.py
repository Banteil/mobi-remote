"""Bot.just_arrived — 맵에 막 들어왔으면 to_main 이 맹목 ESC(→ ESC 메뉴가 열림)를 누르지 않고 기다린다."""
import time
import unittest
from types import SimpleNamespace

from mabi.bot import Bot


def bot(ok=True, loading=False, ago=None):
    entered = time.monotonic() - ago if ago is not None else 0.0
    b = SimpleNamespace(cfg={"timing": {"after_map": 15}},
                        packets=SimpleNamespace(ok=ok, state=SimpleNamespace(loading=loading, entered_at=entered)))
    b.just_arrived = lambda: Bot.just_arrived(b)
    return b


class JustArrivedTest(unittest.TestCase):
    def test_right_after_map_entry(self):
        self.assertTrue(bot(ago=3).just_arrived())

    def test_after_window(self):
        self.assertFalse(bot(ago=30).just_arrived())

    def test_loading_or_no_packets(self):
        self.assertFalse(bot(ago=3, loading=True).just_arrived())
        self.assertFalse(bot(ago=3, ok=False).just_arrived())
        self.assertFalse(bot().just_arrived())  # 감시를 켠 뒤 맵을 옮긴 적이 없음


if __name__ == "__main__":
    unittest.main()
