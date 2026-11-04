"""캐릭터 선택 — 슬롯 자리는 고정 좌표, 누른 뒤 선택 테두리·카드 이름 확인 (11-04)."""
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from mabi.tasks import login

CS = tomllib.loads((Path(__file__).parent.parent / "config.default.toml").read_text(encoding="utf-8"))["charselect"]


class FakeBot:
    def __init__(self):
        self.clicks = []
        self.log = mock.MagicMock()

    def click(self, xy):
        self.clicks.append(xy)

    def sleep(self, *a):
        pass

    def frame(self):
        return None

    def snapshot(self, tag):
        return Path(tag + ".png")


class SelectTest(unittest.TestCase):
    def test_slot_positions_fixed(self):
        """'•••' 를 못 찾는 카드가 있어도 칸이 밀리지 않는다 — 1번 카드 '•••' 가 장식에 가려 옆 캐릭터로 접속했다."""
        self.assertEqual([(m.x, m.y) for m in (login.slot_menu(CS, s) for s in (1, 2, 4, 5, 6))],
                         [(564, 203), (898, 203), (1566, 203), (564, 742), (898, 742)])

    def select(self, name, read, selected=True):
        bot = FakeBot()
        with mock.patch.object(login, "_scrolled_rows", return_value=[[]]), \
                mock.patch.object(login, "_is_selected", return_value=selected), \
                mock.patch("mabi.tasks.charscan._read_card", return_value=read):
            login.select_character(bot, {"charselect": CS}, {"slot": 5, "name": name})
        return bot

    def test_second_row_clicks_upper_part(self):
        bot = self.select("가나다", {"name": "가나다", "name_score": 0.99})
        self.assertEqual(bot.clicks, [(458, CS["max_click_y"])])

    def test_other_name_on_card_refuses(self):
        with self.assertRaises(login.SelectFailed):
            self.select("가나다", {"name": "라마바사", "name_score": 0.99})

    def test_unsure_name_goes_on(self):
        """이름을 확실히 못 읽으면(선택된 카드 금색 배경 등) 넘어가고 접속 뒤 이름으로 본다."""
        self.select("가나다", {"name": "라마", "name_score": 0.65})
        self.select("가나다", {"name": "", "name_score": 0.0})

    def test_no_border_fails(self):
        with self.assertRaises(login.SelectFailed):
            self.select("가나다", {}, selected=False)


if __name__ == "__main__":
    unittest.main()
