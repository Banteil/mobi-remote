"""Screen — mss 는 만든 스레드에서만 찍히므로, 카드마다 작업 스레드가 바뀌어도 스레드마다 따로 만든다."""
import threading
import unittest
from unittest import mock

from mabi import screen


class ScreenThreadTest(unittest.TestCase):
    def test_one_mss_per_thread(self):
        with mock.patch.object(screen.mss, "mss", side_effect=lambda: object()):
            s = screen.Screen(window=None)
            here = s._sct
            self.assertIs(s._sct, here)  # 같은 스레드에서는 다시 만들지 않는다
            other = []
            t = threading.Thread(target=lambda: other.append(s._sct))
            t.start()
            t.join()
            self.assertIsNot(other[0], here)


if __name__ == "__main__":
    unittest.main()
