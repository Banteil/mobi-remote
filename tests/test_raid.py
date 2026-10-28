"""레이드 반복 (mabi.tasks.raid) — 패킷 상태로 어디인지 가르기, 원격 명령, 큐 카드 표시."""
import time
import unittest
from types import SimpleNamespace

from mabi.bot import Bot
from mabi.packet_monitor import PacketMonitor
from mabi.tasks import raid


class FakeBot:
    """패킷만 진짜 (PacketMonitor). 화면·CLI 는 없다고 본다."""
    map_loading = Bot.map_loading

    def __init__(self, quests=None):
        self.packets = PacketMonitor(None)
        self.packets.status = "running"
        self.packets.last_rx = time.monotonic()  # 방금 받음 (ok)
        self.state = SimpleNamespace(available=lambda: quests is not None, query=lambda cmd: quests)

    def enter(self, kind):
        self.packets.apply("channel.leaving", {})
        self.packets.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": ""})


class PacketStateTest(unittest.TestCase):
    """caps/raid1 순서: 배 진입 → 출항 → 레이드 맵 → 보스전 → 결과 → 출항선."""

    def test_flow(self):
        bot = FakeBot()
        bot.enter(raid.LOBBY_MAP)
        bot.packets.apply("raid.state", {"state_name": "Lobby"})
        self.assertEqual(raid.where(bot, "카브락"), "ship")
        bot.packets.apply("raid.depart", {})
        bot.packets.apply("raid.state", {"state_name": "InProgress"})
        bot.packets.apply("channel.leaving", {})
        self.assertEqual(raid.where(bot, "카브락"), "loading")
        bot.packets.apply("channel.entering", {"channel": 2, "channel_type": raid.RAID_MAP, "channel_name": ""})
        self.assertEqual(raid.where(bot, "카브락"), "play")
        bot.packets.apply("raid.boss_begin", {})
        self.assertTrue(bot.packets.state.raid_boss)
        bot.packets.apply("raid.state", {"state_name": "Cleared"})
        bot.packets.apply("raid.result", {"raid": 1093425028})
        self.assertEqual(raid.where(bot, "카브락"), "cleared")
        bot.enter(raid.LOBBY_MAP)  # 출항선으로 — 결과는 지운다
        self.assertEqual(bot.packets.state.raid_result, 0)
        self.assertFalse(bot.packets.state.raid_boss)
        self.assertEqual(raid.where(bot, "카브락"), "ship")

    def test_result_cleared_on_new_raid_map(self):
        """지난 판 결과가 다음 판 레이드 맵에서 클리어로 보이면 안 된다."""
        bot = FakeBot()
        bot.enter(raid.RAID_MAP)
        bot.packets.apply("raid.result", {"raid": 7})
        self.assertTrue(raid.cleared(bot))
        bot.enter(raid.RAID_MAP)
        bot.packets.apply("raid.state", {"state_name": "InProgress"})
        self.assertFalse(raid.cleared(bot))


class QuestTitleTest(unittest.TestCase):
    def test_strips_color_tag(self):
        bot = FakeBot([{"QuestTitle": "<color=orange>카브락</color> 토벌 완료", "Source": "shortcut"}])
        self.assertEqual(raid._quest_title(bot), "카브락 토벌 완료")

    def test_only_shortcut(self):
        bot = FakeBot([{"QuestTitle": "출항하기", "Source": "main"}])
        self.assertEqual(raid._quest_title(bot), "")


class CommandTest(unittest.TestCase):
    def test_raid_command(self):
        from gui_app.web_main import _command
        self.assertEqual(_command(["gui.py", "--raid", "3", "카브락", "5", "어려움"]), "raid:3:카브락:5:어려움".encode())
        self.assertEqual(_command(["gui.py", "--abyss", "1", "광기의 동굴"]), "abyss:1:광기의 동굴".encode())


class CardTest(unittest.TestCase):
    def test_detail(self):
        from gui_app.queue_api import RaidKind
        self.assertEqual(RaidKind.detail({"raid": "카브락", "difficulty": "어려움", "runs": 3}), "카브락 어려움 · 3판")

    def test_difficulties_cover_raids(self):
        self.assertEqual(set(raid.DIFFICULTIES), set(raid.RAIDS))


if __name__ == "__main__":
    unittest.main()
