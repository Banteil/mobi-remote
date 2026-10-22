"""목표 하나를 끝까지 미는 실행기 (리모콘 app/renderer/app.js 의 runGoalItem·goalExecute·goalWait·waitForUserInput).

무엇을 할지는 goal.next_step 이 한 걸음씩 정하고, 여기서는 그 걸음을 실행하고 사람이 개입할 순간만 처리한다.
화면과 무관하게 콜백으로만 알린다 — Qt 스레드가 그대로 돌릴 수 있게.

멈추는 조건: 목표 달성 · 취소 · 진전 없음(같은 걸음 4회 연속, 학습은 1회, 기다림은 제외) · 300걸음 ·
생활 스킬 레벨 부족(기다린다고 안 풀린다). 헛돌면서 날개를 태우는 것이 가장 나쁜 실패다.
"""
import threading
import time
from typing import Callable

from ..cache import QueryCache
from ..connector import Connector
from ..query import Query
from . import goal
from .execute import ExecResult, execute

GOAL_MAX_STEPS = 300
GOAL_STUCK_LIMIT = 4    # 같은 걸음이 이만큼 연달아 나오면 헛도는 것으로 본다
USER_INPUT_TIMEOUT = 120


def _noop(*_a, **_k):
    return None


class GoalRunner:
    def __init__(self, cd, cli: Connector, qc: QueryCache, *,
                 on_note: Callable[[dict, str], None] | None = None,
                 on_notice: Callable[[str, str, str], None] | None = None,
                 on_busy: Callable[[str | None], None] | None = None,
                 on_blocked: Callable[[dict, str], bool] | None = None,
                 on_change: Callable[[dict], None] | None = None,
                 on_exec: Callable[[str, object, ExecResult], None] | None = None,
                 cancel: threading.Event | None = None):
        """on_note(항목, 글) 카드 메모 · on_notice(제목, 글, 'ok'|'bad') 토스트 · on_busy(상태바 글 또는 None) ·
        on_blocked(걸음, 라벨) → True 면 "구해 왔습니다 — 계속" · on_change(항목) 저장·다시 그리기 ·
        on_exec(명령, 본문, 결과) 호출 기록 · cancel 이 켜지면 이번 걸음을 마치고 멈춘다."""
        self.cd, self.cli, self.qc = cd, cli, qc
        self.query = Query(qc)
        self.on_note = on_note or _noop
        self.on_notice = on_notice or _noop
        self.on_busy = on_busy or _noop
        self.on_blocked = on_blocked or (lambda _st, _label: False)  # 물을 곳이 없으면 멈춘다
        self.on_change = on_change or _noop
        self.on_exec = on_exec or _noop
        self.abort = cancel or threading.Event()
        self.skill_halt: dict | None = None  # 생활 스킬 레벨이 모자라 멈춘 것 {what, level, message}

    # ---------------------------------------------------------------- 제어
    def halt(self) -> None:
        """지금 명령까지 끊고 멈춘다 (CLI 프로세스 종료 → 게임도 그 행동을 멈춘다)."""
        self.abort.set()
        try:
            self.cli.cancel()
        except Exception:
            pass

    def next(self, name: str, target: int) -> dict:
        """{step, estimate, have} 또는 {error, message}. 매번 새로 읽는다 — 한 걸음 뒤의 캐시는 이미 옛것이다."""
        return goal.next_for(self.cd, self.qc, name, target, refresh=True)

    def _note(self, it: dict, text: str) -> None:
        it["note"] = text
        self.on_note(it, text)

    # ---------------------------------------------------------------- 목표 하나
    def run_item(self, it: dict) -> bool:
        """큐 항목 하나를 끝까지 민다. it: {name, label, target(새로 만들 개수), base?, ...}. 끝까지 갔으면 True.
        기준점(base)은 실제로 시작할 때 잡는다 — 이미 잡혀 있으면(보류 후 이어가기) 그대로 둔다."""
        name, label = it["name"], it.get("label") or it["name"]
        if it.get("base") is None:
            try:
                r0 = self.next(name, 0)
                it["base"] = r0.get("have", 0) if r0 and r0.get("have") is not None else 0
            except Exception:
                it["base"] = 0
            self.on_change(it)

        spent = done = repeat = 0
        last_key = ""
        ok_end = False
        for _ in range(GOAL_MAX_STEPS):
            if self.abort.is_set():
                break
            r = self.next(name, (it.get("base") or 0) + it["target"])
            if r.get("error"):
                self._note(it, "중단 — " + (r.get("message") or r["error"]))
                break
            st = r["step"]
            it["have"] = r["have"]
            it["made"] = max(0, r["have"] - (it.get("base") or 0))

            if st["kind"] == "done":
                self._note(it, f"달성 — 새로 {it['made']:,}개 (날개 {spent:,})")
                ok_end = True
                break
            if st["kind"] == "blocked":
                self._note(it, "막힘 — " + (st.get("message") or st.get("reason") or ""))
                if not self.on_blocked(st, label):
                    break
                continue  # 구해 왔다니 다시 판단해 본다

            # 같은 걸음만 반복되면 헛도는 것이다. 기다림은 원래 반복되므로 제외
            key = f"{st['kind']}:{st.get('name') or ''}:{st.get('batch') or st.get('runs') or ''}"
            repeat = repeat + 1 if key == last_key and st["kind"] != "wait" else 0
            last_key = key
            limit = 1 if st["kind"] == "learn" else GOAL_STUCK_LIMIT  # 학습은 한 번 해서 안 되면 더 해도 안 된다
            if repeat >= limit:
                self._note(it, f"진전이 없어 멈춤 — {st.get('name') or st['kind']} {repeat + 1}회 반복")
                break

            self._note(it, f"[{done + 1}] {st.get('why') or st['kind']}")
            if st["kind"] == "wait":
                if not self.wait(st):
                    break
                continue

            spent_now = self.execute_step(st, done + 1)
            if spent_now is None:
                break  # 실패했고 이어갈 수 없다
            spent += spent_now
            done += 1
            it["spent"], it["steps"] = spent, done
            self.on_change(it)

        self.on_busy(None)
        it["spent"], it["steps"] = spent, done
        return ok_end

    def run_goal(self, name: str, target: int, label: str | None = None) -> dict:
        """큐 없이 목표 하나만 돌린다 (target = 새로 만들 개수). 진행 기록이 담긴 항목을 돌려준다."""
        it = {"name": name, "label": label or name, "target": target, "note": "", "spent": 0, "steps": 0}
        self.abort.clear()
        self.skill_halt = None
        it["ok"] = self.run_item(it)
        return it

    # ---------------------------------------------------------------- 걸음 실행
    def _run(self, command: str, body, label: str) -> ExecResult:
        self.on_busy(f"{label} 실행 중…")
        try:
            r = execute(self.cd, self.cli, self.qc, command, body)
        finally:
            self.on_busy(None)
        self.on_exec(command, body, r)
        if not r.ok:
            ko = r.ko or {}
            self.on_notice(f"실패 — {label}" + (f": {ko['text']}" if ko.get("text") else ""),
                           ko.get("hint") or (r.message or r.error or ""), "bad")
        return r

    def execute_step(self, st: dict, n: int) -> int | None:
        """한 걸음을 실제로 실행한다. 소모한 날개를 돌려주고, 이어갈 수 없으면 None."""
        tag = f"({n}) "
        if st["kind"] == "collect":
            body = {"displayName": st["name"]}
            r = self._run("complete_altering_work", body, f"{tag}{st['facility']} 수령")
            # 보상 창이 떠서 막혔으면 사람이 닫기를 기다렸다가 한 번 더
            if not r.ok and r.error == "blocked" and self.wait_for_user_input(st["facility"]):
                r = self._run("complete_altering_work", body, f"{tag}{st['facility']} 수령(재시도)")
            return (r.wings_spent or 0) if r.ok else None

        is_alter = st["kind"] == "alter" or (st["kind"] == "learn" and st.get("via") == goal.VIA["ALTER"])
        command = "execute_gathering" if st["kind"] == "gather" else \
            "execute_altering" if is_alter else "execute_crafting"
        body = {"displayName": st["name"],
                "craftCount": 1 if st["kind"] == "learn" else (st.get("batch") or 1)} \
            if command == "execute_crafting" else {"displayName": st["name"]}

        r = self._run(command, body, tag + (st.get("why") or st["name"]))
        # 게임 확인 창에 막혔으면 기다렸다가 한 번만 더 (가공은 막혀도 날개가 나가서 재시도가 공짜가 아니다)
        if not r.ok and r.error == "blocked" and self.wait_for_user_input(st["name"]):
            r = self._run(command, body, f"{tag}{st['name']} (재시도)")

        if not r.ok:
            if r.error == "invalid_count":
                return 0  # 상한을 배웠다. 다음 걸음에서 맞춰 부른다
            if r.error == "insufficient_living_skill_level":
                # 기다린다고 풀리지 않고 다시 불러도 같은 답이다. 시작 전 거절이라 날개는 안 나갔다
                self.skill_halt = {"what": st["name"], "level": r.required_level, "message": r.message}
                self.abort.set()
            return None
        return r.wings_spent or 0

    def wait(self, st: dict) -> bool:
        """가공이 끝나기를 기다린다. 취소를 받는다."""
        until = time.monotonic() + max(5, st.get("seconds") or 0)
        self.on_notice("대기", st.get("why") or "가공이 끝나기를 기다립니다.", "ok")
        while time.monotonic() < until:
            if self.abort.is_set():
                return False
            left = int(until - time.monotonic() + 0.999)
            self.on_busy(f"가공 완료까지 {left}초 대기 중… (취소 가능)")
            self.abort.wait(min(2.0, max(0.0, until - time.monotonic())))
        self.on_busy(None)
        return True

    def wait_for_user_input(self, label: str = "", timeout: float = USER_INPUT_TIMEOUT) -> bool:
        """게임에 사람이 눌러야 하는 창이 떠 있으면 닫힐 때까지 기다린다 (커넥터에는 팝업을 누르는 명령이 없다).
        IsReviving 은 살아 있어도 켜져 있어서 보지 않는다. True = 정리됨, False = 시간 초과·중단."""
        started = time.monotonic()
        notified = False
        while time.monotonic() - started < timeout:
            if self.abort.is_set():
                return False
            a = self.query.activity()
            if not a.get("dialogue"):
                return True
            if not notified:
                notified = True
                self.on_notice("게임에서 확인이 필요합니다",
                               (f"{label} — " if label else "") + "게임 창에서 확인을 눌러 주세요. 닫히면 자동으로 이어갑니다.",
                               "bad")
            left = round(timeout - (time.monotonic() - started))
            self.on_busy(f"게임에서 확인을 눌러 주세요… ({left}초 내)")
            self.abort.wait(2.0)
        return False
