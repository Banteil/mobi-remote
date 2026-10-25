"""숙제 완료 확인을 패킷으로 먼저 — 검은 구멍 깬 목록, 요일 던전 추천 항목, 지금 마을 (화면은 최후)."""
import logging
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor import PacketState
from mabi.profile import game_day_start
from mabi.tasks import black_hole, content, weekday

CFG = {"black_hole": {"achieved": "x"}, "weekday_dungeon": {"achieved": "y"}}


def bot_with(**state):
    st = PacketState(**state)
    return SimpleNamespace(packets=SimpleNamespace(ok=True, state=st), log=logging.getLogger("test"))


class DayStartTest(unittest.TestCase):
    def test_before_six_is_yesterday(self):
        self.assertEqual(game_day_start(datetime(2026, 10, 25, 5, 59)), datetime(2026, 10, 24, 6, 0))
        self.assertEqual(game_day_start(datetime(2026, 10, 25, 13, 0)), datetime(2026, 10, 25, 6, 0))


class BlackHoleTest(unittest.TestCase):
    def ms(self, *a):
        return int(datetime(*a).timestamp() * 1000)

    def test_cleared_today_skips_screen(self):
        bot = bot_with(dimensions_cleared=[self.ms(2026, 10, 25, 13, 10)])
        with mock.patch.object(black_hole, "game_day_start", lambda: datetime(2026, 10, 25, 6)), \
                mock.patch.object(black_hole, "daily_achieved", side_effect=AssertionError("화면을 열면 안 됨")):
            self.assertTrue(black_hole.verify(bot, CFG))

    def test_yesterday_or_empty_falls_back_to_screen(self):
        for times in ([self.ms(2026, 10, 25, 5, 50)], [], None):
            bot = bot_with(dimensions_cleared=times)
            with mock.patch.object(black_hole, "game_day_start", lambda: datetime(2026, 10, 25, 6)), \
                    mock.patch.object(black_hole, "daily_achieved", return_value=False) as screen:
                self.assertFalse(black_hole.verify(bot, CFG))
                screen.assert_called_once()


    def test_run_opens_guide_once(self):
        # 일일 달성 체크로 먼저 확인하지 않고 바로 가기만 연다 — 카드가 없으면 끝 (실행기가 확인)
        bot = bot_with(dimensions_cleared=[])
        bot.state = SimpleNamespace(available=lambda: True)
        bot.resumed_at = lambda *a: False
        bot.step = lambda *a, **k: None
        with mock.patch.object(black_hole, "game_space", return_value="이멘 마하"),                 mock.patch.object(black_hole, "daily_achieved", side_effect=AssertionError("일일 달성 체크를 열면 안 됨")),                 mock.patch.object(black_hole, "open_guide_card", return_value=False) as guide:
            self.assertEqual(black_hole.run(bot, {"black_hole": {"space_keyword": "검은 구멍", "card": "c"}}), "검은 구멍 카드 없음")
            guide.assert_called_once()


class WeekdayTest(unittest.TestCase):
    def test_recommend_weekday_means_not_done(self):
        with mock.patch.object(weekday, "daily_achieved", side_effect=AssertionError("화면을 열면 안 됨")):
            self.assertFalse(weekday.verify(bot_with(recommend=2), CFG))

    def test_other_recommend_uses_screen(self):
        # 5(가방 정리)가 2 를 가린 것일 수도 있다
        with mock.patch.object(weekday, "daily_achieved", return_value=True) as screen:
            self.assertTrue(weekday.verify(bot_with(recommend=5), CFG))
            screen.assert_called_once()


class TownTest(unittest.TestCase):
    def test_other_town(self):
        self.assertTrue(content.other_town(bot_with(channel=1, channel_type="Field", channel_name="콜헨"), "이멘마하"))
        self.assertFalse(content.other_town(bot_with(channel=1, channel_type="Field", channel_name="이멘 마하"), "이멘마하"))

    def test_unknown_or_not_town(self):
        self.assertFalse(content.other_town(bot_with(channel=1, channel_type="BattleField", channel_name="창백한 산"), "이멘마하"))
        self.assertFalse(content.other_town(bot_with(), "이멘마하"))
        self.assertFalse(content.other_town(bot_with(channel=1, channel_type="Field", channel_name="콜헨", loading=True), "이멘마하"))


if __name__ == "__main__":
    unittest.main()
