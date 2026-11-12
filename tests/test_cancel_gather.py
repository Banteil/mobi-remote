"""명령을 끊을 때 — 채집처럼 게임 안에서 계속되는 행동이면 stop_action 도 보낸다. 작업 큐 카드의 기억한 캐릭터는 파일에 남는다."""
import unittest
from unittest import mock

from mabi import connector
from mabi.craft import queue as cq


class CancelTest(unittest.TestCase):
    def cancel(self, cmd):
        c = connector.Connector()
        c._proc = mock.Mock(**{"poll.return_value": None})
        c._proc_cmd = cmd
        with mock.patch.object(c, "_run", return_value=connector.Result(True, 0)) as run:
            c.cancel()
        c._proc.kill.assert_called_once()
        return run

    def test_gathering_also_stops_action(self):
        self.cancel("execute_gathering").assert_called_once_with("stop_action", None, 15, track=False)

    def test_other_commands_only_kill(self):
        self.cancel("execute_crafting").assert_not_called()


class PinSavedTest(unittest.TestCase):
    def test_pin_is_kept_in_file(self):
        pin = {"slot": 1, "name": "가"}
        text = cq.encode({"items": [{"id": 1, "name": "쌀", "pin": pin}]})
        self.assertIn('"pin"', text)


if __name__ == "__main__":
    unittest.main()
