"""패킷 감시 테스트 — 캡처 없이 만든 TCP 조각으로 스트림 재조립과 상태 대기를 본다."""
import socket
import struct
import threading
import time
import unittest

from mabi.bot import Bot
from mabi.packet_monitor import PacketMonitor, Stream, appearing_name, parse_tcp
from mabi.tasks.content import wait_dungeon

KNOWN = frozenset({0x4f6e, 0x5026, 0x272fa, 0x30d4b})


def msg(proto: int, body: bytes, flag: int = 0) -> bytes:
    return struct.pack("<IIB", proto, len(body), flag) + body


def chop(data: bytes, size: int, seq: int = 1000) -> list[tuple[int, bytes]]:
    return [(seq + i, data[i:i + size]) for i in range(0, len(data), size)]


class StreamTest(unittest.TestCase):
    def setUp(self):
        self.desync = []
        self.s = Stream(KNOWN, self.desync.append)
        self.s.feed(999, 0x02, b"")  # SYN — 처음부터 받음

    def feed_all(self, parts) -> list:
        out = []
        for seq, p in parts:
            out += self.s.feed(seq, 0x18, p)
        return out

    def test_split_across_segments(self):
        data = msg(0x4f6e, b"\x01\x02\x03\x04") + msg(0x272fa, b"\x02\x00\x00\x00")
        got = self.feed_all(chop(data, 5))
        self.assertEqual(got, [(0x4f6e, 0, b"\x01\x02\x03\x04"), (0x272fa, 0, b"\x02\x00\x00\x00")])

    def test_hello_block_skipped(self):
        # 새 연결은 'MMCG' + 길이 + 내용으로 시작한다 (실제 캡처에서 4·4·296 바이트로 나뉘어 옴)
        hello = b"MMCG" + struct.pack("<I", 296) + bytes(range(256)) + b"\x00" * 40
        data = hello + msg(0x4f6e, b"abcd")
        got = self.feed_all([(1000, data[:4]), (1004, data[4:8]), (1008, data[8:304]), (1304, data[304:])])
        self.assertEqual(got, [(0x4f6e, 0, b"abcd")])
        self.assertEqual(self.desync, [])

    def test_retransmit_and_out_of_order(self):
        data = msg(0x4f6e, b"abcd") + msg(0x5026, b"") + msg(0x272fa, b"\x03\x00\x00\x00")
        parts = chop(data, 7)
        # 순서 뒤바꿈 + 앞 조각 재전송 + 겹치는 재전송
        order = [parts[0], parts[2], parts[1], parts[0], (parts[1][0] + 3, data[10:20]), *parts[3:]]
        got = self.feed_all(order)
        self.assertEqual([p for p, _, _ in got], [0x4f6e, 0x5026, 0x272fa])
        self.assertEqual(self.desync, [])

    def test_mid_stream_sync(self):
        s = Stream(KNOWN)  # SYN 없이 중간부터
        junk = b"\x99" * 13  # 앞 메시지의 꼬리
        data = junk + msg(0x30d4b, b"") + msg(0x30d4b, b"x") + msg(0x4f6e, b"abcd")
        got = s.feed(5000, 0x18, data)
        self.assertEqual([p for p, _, _ in got], [0x30d4b, 0x30d4b, 0x4f6e])

    def test_bad_header_resyncs(self):
        good = msg(0x4f6e, b"abcd")
        self.feed_all([(1000, good + struct.pack("<IIB", 0x4f6e, 4, 7) + b"zzzz")])
        self.assertEqual(self.desync, ["header"])
        self.assertFalse(self.s.synced)

    def test_lost_segment_gives_up(self):
        for i in range(600):
            self.s.feed(2000 + i * 10, 0x18, b"x" * 10)  # 1000~2000 이 끝내 안 옴
        self.assertIn("gap", self.desync)


class ParseTest(unittest.TestCase):
    def test_ethernet_ipv4_tcp(self):
        payload = b"hello"
        tcp = struct.pack("!HHIIBBHHH", 16000, 50123, 77, 0, 5 << 4, 0x18, 1024, 0, 0)
        ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp) + len(payload), 0, 0, 64, 6, 0,
                         socket.inet_aton("3.34.1.2"), socket.inet_aton("192.168.0.5"))
        frame = b"\x00" * 12 + b"\x08\x00" + ip + tcp + payload + b"\x00" * 6  # 이더넷 패딩
        self.assertEqual(parse_tcp(frame), ("3.34.1.2", 16000, 50123, 77, 0x18, b"hello"))

    def test_not_tcp(self):
        self.assertIsNone(parse_tcp(b"\x00" * 12 + b"\x86\xdd" + b"\x00" * 60))


class WaitTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.status = "running"

    def test_wait_after_mark(self):
        self.m.apply("dungeon.state", {"state_name": "InProgress"})
        mark = self.m.mark()
        self.assertIsNone(self.m.wait("dungeon.state", 0.05, after=mark))  # 앞의 것은 안 센다
        threading.Timer(0.05, self.m.apply, ("dungeon.state", {"state_name": "Cleared"})).start()
        got = self.m.wait("dungeon.state", 2, after=mark, check=lambda v: v["state_name"] == "Cleared")
        self.assertEqual(got.vals["state_name"], "Cleared")
        self.assertEqual(self.m.state.dungeon_state, "Cleared")

    def test_channel_state(self):
        self.m.apply("channel.leaving", {})
        self.assertTrue(self.m.state.loading)
        self.m.apply("channel.entering", {"channel": 5, "channel_type": "InstanceDungeon", "channel_name": "던전"})
        self.assertFalse(self.m.state.loading)
        self.assertEqual((self.m.state.channel, self.m.state.channel_type), (5, "InstanceDungeon"))
        self.assertEqual(self.m.last("channel.leaving").key, "channel.leaving")

    def test_dungeon_state_cleared_on_field(self):
        """던전을 나가는 패킷을 놓쳐도 마을에 들어오면 던전 밖 (2026-10-30: 지난밤 Cleared 가 남아 접속이 헛돎)."""
        self.m.apply("dungeon.state", {"state_name": "Cleared"})
        self.m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceDungeon", "channel_name": ""})
        self.assertEqual(self.m.state.dungeon_state, "Cleared")  # 던전 맵이면 그대로
        self.m.apply("channel.entering", {"channel": 2, "channel_type": "Field", "channel_name": ""})
        self.assertEqual(self.m.state.dungeon_state, "NotInDungeon")

    def test_dialogue(self):
        # 실제 캡처 순서: 대상 지정 → 진행 … → active 0 + 대상 없음 → 닫힘
        self.m.apply("dialogue.target", {"target": 0xA2A9})
        self.assertTrue(self.m.state.in_dialogue)
        self.m.apply("dialogue.update", {"active": True, "step": 4})
        self.assertTrue(self.m.state.in_dialogue)
        self.m.apply("dialogue.update", {"active": False, "step": 5})
        self.assertFalse(self.m.state.in_dialogue)
        self.m.apply("dialogue.target", {"target": 0xA2A9})
        self.m.apply("dialogue.target", {"target": 0xFFFFFFFFFFFFFFFF})
        self.assertFalse(self.m.state.in_dialogue)

    def test_saw_passing_state(self):
        """금방 지나간 로딩도 '누른 뒤 한 번이라도' 로는 보인다 — 지금 값만 보면 놓친다 (2026-10-28)."""
        self.m.apply("channel.leaving", {})  # 누르기 전의 로딩은 세지 않는다
        self.m.apply("channel.entering", {"channel": 1, "channel_type": "Field"})
        mark = self.m.mark()
        self.assertFalse(self.m.saw(lambda s: s.loading, mark))
        self.m.apply("channel.leaving", {})
        self.m.apply("channel.entering", {"channel": 2, "channel_type": "Field"})
        self.assertFalse(self.m.state.loading)
        self.assertTrue(self.m.saw(lambda s: s.loading, mark))

    def test_off_returns_at_once(self):
        self.m.status = "no_npcap"
        t = time.monotonic()
        self.assertIsNone(self.m.wait("dungeon.state", 5))
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertFalse(self.m.ok)


class FakeCli:
    def __init__(self, states):
        self.states = list(states)

    def available(self):
        return bool(self.states)

    def activity(self):
        return {"Dungeon": {"State": self.states.pop(0)}} if self.states else None


class FakeBot:
    wait_packet = Bot.wait_packet
    map_loading = Bot.map_loading
    is_loading = Bot.is_loading
    wait_loaded = Bot.wait_loaded

    def __init__(self, packets, cli=()):
        self.packets, self.state = packets, FakeCli(cli)

    def check_stop(self):
        pass

    def sleep(self, a, b=None):
        pass


class WaitDungeonTest(unittest.TestCase):
    def running(self) -> PacketMonitor:
        m = PacketMonitor(None)
        m.status, m.last_rx = "running", time.monotonic()
        return m

    def test_packet_first(self):
        m = self.running()
        m.apply("dungeon.state", {"state_name": "Entering"})
        threading.Timer(0.1, m.apply, ("dungeon.state", {"state_name": "InProgress"})).start()
        bot = FakeBot(m, cli=["Entering"] * 100)  # CLI 는 아직 모름 — 패킷이 먼저
        self.assertEqual(wait_dungeon(bot, lambda s: s == "InProgress", 3), "InProgress")
        self.assertEqual(len(bot.state.states), 100)

    def test_unknown_packet_state_uses_cli(self):
        bot = FakeBot(self.running(), cli=["Entering", "InProgress"])  # 감시가 던전 안에서 시작됨
        self.assertEqual(wait_dungeon(bot, lambda s: s == "InProgress", 3), "InProgress")

    def test_timeout_and_nothing(self):
        m = self.running()
        m.apply("dungeon.state", {"state_name": "InProgress"})
        self.assertEqual(wait_dungeon(FakeBot(m), lambda s: s != "InProgress", 0.2), "")
        self.assertIsNone(wait_dungeon(FakeBot(PacketMonitor(None)), lambda s: True, 1))



class MapWaitTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.status, self.m.last_rx = "running", time.monotonic()
        self.bot = FakeBot(self.m)

    def later(self, key, vals, after=0.1):
        threading.Timer(after, self.m.apply, (key, vals)).start()

    def test_unknown_until_first_map_change(self):
        self.assertIsNone(self.bot.map_loading())  # 감시를 켠 뒤 아직 맵을 옮긴 적이 없다
        self.assertIsNone(self.bot.wait_loaded(1))
        self.assertFalse(self.bot.is_loading())   # CLI 도 없으면 로딩 아님으로

    def test_wait_loaded(self):
        self.m.apply("channel.leaving", {})
        self.assertTrue(self.bot.map_loading())
        self.later("channel.entering", {"channel": 1, "channel_type": "Field"})
        t = time.monotonic()
        self.assertTrue(self.bot.wait_loaded(3))
        self.assertLess(time.monotonic() - t, 1)
        self.assertIs(self.bot.map_loading(), False)

    def test_find_after_mark(self):
        self.m.apply("channel.entering", {"channel": 1, "channel_type": "Field"})
        mark = self.m.mark()
        self.assertIsNone(self.m.find("channel.entering", mark))
        self.m.apply("channel.entering", {"channel": 2, "channel_type": "InstanceAbyssDungeon"})
        self.m.apply("channel.entering", {"channel": 3, "channel_type": "Field"})
        got = self.m.find("channel.entering", mark, lambda v: v["channel_type"] == "Field")
        self.assertEqual(got.vals["channel"], 3)

    def test_stale_signal_is_unknown(self):
        self.m.apply("channel.leaving", {})
        self.m.last_rx = time.monotonic() - 60  # 서버 패킷이 끊김
        self.assertIsNone(self.bot.map_loading())
        self.assertIsNone(self.bot.wait_packet(lambda s: True, 1))


def _s16(t: str) -> bytes:
    e = t.encode("utf-16le")
    return struct.pack("<I", len(e)) + e


class AppearingNameTest(unittest.TestCase):
    """등장 캐릭터 메시지 모양 (실제 캡처에서 본 배치, 이름은 지어낸 것)."""

    def body(self, name="시험이름"):
        tools = (_s16("Weapon") + struct.pack("<IIII", 1, 1, 0x1234, 0)
                 + _s16("Instrument") + struct.pack("<III", 9, 2, 7) + struct.pack("<I", 8)
                 + struct.pack("<II", 1, 0xFF112233))  # 칸 9, n=2 (7, 8), 색 1개
        return (b"\x01" * 40 + tools + struct.pack("<II", 100, 0) + b"\x5f" * 21
                + bytes.fromhex("0000803f00000000") + _s16(name) + b"\x00" * 30)

    def test_reads_name_after_tool_list(self):
        self.assertEqual(appearing_name(self.body()), "시험이름")

    def test_other_shapes_are_none(self):
        self.assertIsNone(appearing_name(b"\x00" * 200))
        self.assertIsNone(appearing_name(self.body()[:-60]))  # 잘림


class SessionTest(unittest.TestCase):
    def test_charselect_and_back(self):
        m = PacketMonitor(None)
        m.status = "running"
        self.assertIsNone(m.at_charselect())  # 감시를 켠 뒤 아직 모름
        m.apply("char.appearing", {"actor": 9, "mine": True, "name": "A"})
        m.apply("channel.leaving", {})
        m.apply("session.logout_ok", {})
        self.assertTrue(m.at_charselect())
        self.assertFalse(m.state.loading)
        self.assertIsNone(m.state.my_name)
        m.apply("session.entered", {})
        self.assertFalse(m.at_charselect())
        self.assertTrue(m.state.loading)  # 맵 진입은 몇 초 뒤
        m.apply("channel.entering", {"channel": 1, "channel_type": "Field"})
        self.assertFalse(m.state.loading)


class DeathTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)

    def test_my_actor_from_appearing(self):
        self.m.apply("char.personal_data", {"char_id": 77})
        self.m.apply("char.appearing", {"actor": 5, "mine": False})  # 다른 사람
        self.assertIsNone(self.m.state.me)
        self.m.apply("char.appearing", {"actor": 9, "mine": True})
        self.assertEqual(self.m.state.me, 9)

    def test_party_death_by_my_actor(self):
        # 파티 판에서는 부활 창 신호 없이 내 액터 사망만 온다 (death1 03:10:24)
        self.m.apply("char.appearing", {"actor": 9, "mine": True})
        self.m.apply("actor.dead", {"actor": 5, "dead": True, "reason": 2})  # 몬스터
        self.assertIsNone(self.m.state.dead)
        self.m.apply("actor.dead", {"actor": 9, "dead": True, "reason": 2})
        self.assertTrue(self.m.state.dead)
        self.m.apply("revive.item_ok", {})
        self.assertFalse(self.m.state.dead)

    def test_solo_death_and_revive_count(self):
        self.m.apply("revive.availability", {"available": True})
        self.assertTrue(self.m.state.dead)
        self.m.apply("revive.count", {"used": 1, "max": 3})
        self.m.apply("revive.availability", {"available": False})
        self.assertFalse(self.m.state.dead)
        self.assertEqual((self.m.state.revives_used, self.m.state.revives_max), (1, 3))

    def test_durability_lowest_until_repair(self):
        # 깎임 알림은 깎인 장비의 현재/최대 비율뿐 (무기 153/175 → 0.87429) — 어느 장비인지 몰라 가장 낮은 것을 쓴다
        self.assertIsNone(self.m.state.durability)
        self.m.apply("equip.durability", {"ratio": 153 / 175})
        self.m.apply("equip.durability", {"ratio": 0.95})
        self.assertAlmostEqual(self.m.state.durability, 153 / 175)
        self.m.apply("equip.repair_ok", {})
        self.assertIsNone(self.m.state.durability)
        self.m.apply("equip.durability", {"ratio": 0.99})
        self.m.apply("char.personal_data", {"char_id": 77})  # 다른 캐릭터
        self.assertIsNone(self.m.state.durability)

    def test_dialogue_action_and_menu(self):
        # 대장간: 메뉴(SelectKeyword + 선택지) → '수리' 뒤 대사(OpenNPCRepair) → 작별 인사(EndDialogue) → 끝 (repair2)
        self.m.apply("dialogue.update", {"active": True, "step": 7, "action": "SelectKeyword"})
        self.m.apply("dialogue.prompt", {"step": 7, "open": 1, "choices": 9})
        self.m.apply("dialogue.target", {"target": 36280})
        s = self.m.state
        self.assertEqual((s.dialogue_action, s.dialogue_step, s.dialogue_menu), ("SelectKeyword", 7, True))
        self.m.apply("dialogue.prompt", {"step": 8, "open": 0, "choices": 0})
        self.m.apply("dialogue.update", {"active": True, "step": 8, "action": "OpenNPCRepair"})
        self.assertEqual((s.dialogue_action, s.dialogue_step, s.dialogue_menu), ("OpenNPCRepair", 8, False))
        self.m.apply("dialogue.update", {"active": False, "step": 8, "action": ""})
        self.assertEqual((s.dialogue_action, s.dialogue_menu, s.in_dialogue), ("", False, False))


if __name__ == "__main__":
    unittest.main()
