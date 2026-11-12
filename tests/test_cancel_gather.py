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
        with mock.patch.object(connector.threading, "Thread") as th:
            c.cancel()
        c._proc.kill.assert_called_once()
        return th

    def test_gathering_also_stops_action(self):
        th = self.cancel("execute_gathering")
        th.assert_called_once()
        self.assertEqual(th.call_args.kwargs["args"], ("execute_gathering",))

    def test_other_commands_only_kill(self):
        self.cancel("execute_crafting").assert_not_called()

    def stop(self, results, new_proc_after=None):
        c = connector.Connector()
        seq = iter(results)

        def run(*a, **k):
            r = next(seq)
            if new_proc_after is not None and run.calls == new_proc_after:
                c._proc = object()
            run.calls += 1
            return r
        run.calls = 0
        with mock.patch.object(c, "_run", side_effect=run), mock.patch.object(connector.time, "sleep"):
            c._stop_action("execute_gathering")
        return run.calls

    def test_retries_through_success_motion(self):
        no = connector.Result(False, 1, error="no_action")
        self.assertEqual(self.stop([no, no, connector.Result(True, 0)]), 3)  # 성공 모션 동안 거절 → 다음 캐기에 멈춤

    def test_stops_retrying_when_new_action_starts(self):
        no = connector.Result(False, 1, error="no_action")
        self.assertEqual(self.stop([no, no, no], new_proc_after=0), 1)  # 이어 하기로 새 채집이 시작되면 그만


class PinSavedTest(unittest.TestCase):
    def test_pin_is_kept_in_file(self):
        pin = {"slot": 1, "name": "가"}
        text = cq.encode({"items": [{"id": 1, "name": "쌀", "pin": pin}]})
        self.assertIn('"pin"', text)


if __name__ == "__main__":
    unittest.main()
