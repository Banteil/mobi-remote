"""지금 어디인가 (mabi.place) — 패킷이 맵을 알면 패킷, 모르면 CLI 로 짐작."""
import time
import unittest
from types import SimpleNamespace

from mabi import gamedata as gd
from mabi.bot import Bot
from mabi.packet_monitor import PacketMonitor
from mabi.place import ABYSS, DUNGEON, FIELD, RAID_LOBBY, place


class FakeBot:
    map_loading = Bot.map_loading

    def __init__(self, act=None, name=""):
        self.packets = PacketMonitor(None)
        self.packets.status, self.packets.last_rx = "running", time.monotonic()
        self._act, self._name = act, name

    def activity(self, max_age=1.0):
        return self._act

    def environment(self, max_age=3.0):
        return {"ChannelDisplayName": self._name} if self._name else None


class PlaceTest(unittest.TestCase):
    def test_packet_knows_map(self):
        bot = FakeBot()
        bot.packets.apply("channel.entering", {"channel": 1, "channel_type": ABYSS, "channel_name": "허상의 정박지"})
        pl = place(bot)
        self.assertEqual((pl.src, pl.kind, pl.loading), ("packet", ABYSS, False))
        bot.packets.apply("channel.leaving", {})
        self.assertEqual((place(bot).loading, place(bot).kind), (True, None))

    def test_cli_guesses(self):
        act = {"Dungeon": {"State": "NotInDungeon"}, "Battlefield": {"IsInBattleField": False}}
        self.assertEqual(place(FakeBot(act, "허상의 정박지")).kind, ABYSS)
        self.assertEqual(place(FakeBot(act, gd.text("raid_ship"))).kind, RAID_LOBBY)
        self.assertIsNone(place(FakeBot(act, "던바튼")).kind)  # 마을은 짐작하지 않는다
        field = {"Dungeon": {"State": "NotInDungeon"}, "Battlefield": {"IsInBattleField": True}}
        self.assertEqual((place(FakeBot(field, "센마이 평원")).kind, place(FakeBot(field)).in_field), (FIELD, True))
        dun = {"Dungeon": {"State": "InProgress"}, "Battlefield": {"IsInBattleField": False}}
        self.assertEqual(place(FakeBot(dun, "마스 심층 던전 1층 2구역")).kind, DUNGEON)

    def test_nothing_known(self):
        pl = place(FakeBot())
        self.assertEqual((pl.loading, pl.kind, pl.src), (None, None, ""))


if __name__ == "__main__":
    unittest.main()
