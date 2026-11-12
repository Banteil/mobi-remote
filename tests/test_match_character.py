"""읽은 이름으로 캐릭터 고르기 (mabi.tasks.login.match_character) — 확실할 때만 고른다."""
import unittest

from mabi.tasks.login import match_character

CHARS = [{"slot": 1, "name": "하늘바다"}, {"slot": 2, "name": "구름언덕"}]


class MatchCharacterTest(unittest.TestCase):
    def test_exact(self):
        self.assertIs(match_character("구름언덕", CHARS), CHARS[1])

    def test_ocr_one_letter_off(self):
        self.assertIs(match_character("하늘바디", CHARS), CHARS[0])

    def test_unknown_or_empty(self):
        self.assertIsNone(match_character("전혀다른", CHARS))
        self.assertIsNone(match_character("", CHARS))

    def test_two_close_names_is_not_sure(self):
        # 비슷한 이름이 둘이면 고르지 않는다 (처음 것을 고르면 엉뚱한 캐릭터로 판단한다)
        twins = [{"slot": 1, "name": "별빛하나"}, {"slot": 2, "name": "별빛하노"}]
        self.assertIsNone(match_character("별빛하니", twins))


if __name__ == "__main__":
    unittest.main()
