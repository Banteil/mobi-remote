"""작업 큐 화면(web/queue.js)이 부르는 파이썬 쪽 (mm.queue.*). Api 가 이 클래스를 섞어 쓴다.

큐의 주인은 mabi.workqueue.WorkQueue 다. 여기는 카드 종류의 실행기와 화면 연결만 둔다.
  daily · abyss · raid : 숙제·어비스·레이드 (DailyApi 의 _daily_launch · _abyss_launch · _raid_launch 를 기다린다)
  goal          : 제작·채집·가공 목표 (판단 엔진 mabi.craft.goal 의 걸음을 하나씩 실행)
  action        : 한 번 하는 행동 (버튼 하나 = 명령 하나, 전체 수령)
실행 중 사람에게 물어야 하면(재료를 직접 구해 와야 함) 'mm:queue-ask' 로 묻고 queue.answer 를 기다린다.
화면 설정 맞추기는 큐 한 번에 한 번 (q.session), 큐가 다 끝나면 한 번 되돌린다.
변화는 'mm:queue' {items, running} 로 화면에 보낸다.
"""
import json
import logging
import math
import threading
import time

from mabi import gamedata as gd
from mabi import queue_report
from mabi.runner import RunOptions, load_config
from mabi.workqueue import Kind, WorkQueue

log = logging.getLogger("mabi")


def _num(n) -> str:
    return f"{int(n or 0):,}"


FAILED = ("FAIL", "ERROR", "CHECK", "HEAVY", "SKIP")


def daily_progress(p: dict | None, e: dict) -> dict | None:
    """숙제 실행기 이벤트(runner._emit)로 카드의 진행 기록(it['prog'])을 고친다. 바뀐 게 없으면 None.
    n: 캐릭터 수 · i: 지금 몇 번째 · tasks: 캐릭터당 숙제 수 · ci: 이 캐릭터에서 몇 번째 숙제
    done: 끝난 숙제 칸 (이미 끝나 건너뛴 것 포함 — 막대가 끝까지 찬다) · fail: 실패 칸 · seen: 나온 슬롯"""
    t = e.get("type")
    if t == "start":
        return {"n": len(e.get("characters") or []), "tasks": len(e.get("order") or []), "labels": e.get("labels") or {},
                "i": 0, "name": "", "task": "", "ci": 0, "step": "", "done": 0, "fail": 0, "seen": []}
    if not p:
        return None
    p = {**p, "seen": list(p.get("seen") or [])}
    slot = e.get("slot")
    if slot is not None and slot not in p["seen"] and t in ("character", "task_end"):
        p["seen"].append(slot)
    if t == "character":
        p.update(i=len(p["seen"]) if slot is not None else p["i"] + 1, name=e.get("name") or "", task="", ci=0, step="")
    elif t == "task_start":
        tid = e.get("task")
        p.update(task="접속" if tid == "login" else p["labels"].get(tid) or e.get("label") or tid, step="")
        if tid != "login":
            p["ci"] += 1
    elif t == "step":
        p["step"] = e.get("text") or e.get("step") or ""
    elif t == "task_end":
        if e.get("task") == "login":
            return None if e.get("status") == "OK" else {**p, "fail": p["fail"] + 1}
        p["done"] += 1
        if e.get("status") in FAILED:
            p["fail"] += 1
    else:
        return None
    return p


class DailyKind(Kind):
    own_loot = True  # 캐릭터마다 runner 가 잰다 ('loot' 이벤트)

    def __init__(self, api):
        self.api = api
        self._results: list | None = None  # 이번 실행의 숙제별 결과 (결과 창)

    def tasks(self, it):
        # DONE = 이 큐가 돌기 전에 오늘 이미 끝나 있어 건너뛴 캐릭터 — 이번 큐가 한 일이 아니라 결과 창에서 뺀다
        r, self._results = self._results, None
        return [list(x) for x in r if x[1] != "DONE"] if r else None

    @staticmethod
    def detail(it) -> str:
        only = it.get("only")
        return f"{len(it.get('chars') or [])}명 · " + (f"숙제 {len(only)}개" if only else "전체") + (" · 다시" if it.get("force") else "")

    def view(self, it):
        v = super().view(it)
        p = it.get("prog")
        if not p:
            return v
        if p.get("name"):
            v["now"] = f"[{p['i']}/{p['n']}] {p['name']}" + (f" · {p['task']}" if p.get("task") else "") + \
                (f" ({p['ci']}/{p['tasks']})" if p.get("ci") and p.get("task") != "접속" else "")
        v["step"] = p.get("step") or ""
        v["stat"] = f"실패 {p['fail']}" if p.get("fail") else ""
        if p.get("n") and p.get("tasks"):
            v["bar"] = [p["done"], p["n"] * p["tasks"]]
        return v

    def run(self, q, it):
        api = self.api
        if not api._q_display(q, it):
            return False
        if (err := api._busy_reason()):
            q.note(it, f"시작 못 함 — {err}")
            return False
        fit = api._q_fit()
        opts = RunOptions(chars=it.get("chars") or None, only=it.get("only") or None, force=bool(it.get("force")),
                          display=fit, interface_ready=bool(q.session.get("iface")),
                          restore=False,  # 되돌리기는 큐가 다 끝날 때 한 번 (_q_drained)
                          extra={"from": "queue"})

        def on_event(e):
            fields = {}
            if (p := daily_progress(it.get("prog"), e)) is not None:
                fields["prog"] = p
            if e.get("type") == "start":
                fields["note"] = ""  # 진행은 카드의 진행 줄(view)로 보인다
            if e.get("type") == "task_start" and e.get("label"):
                fields["at"] = e["label"]  # 멈추면 '… 에서 멈춤' 으로 쓴다
            if fields:
                q.patch(it["id"], fields)
            if e.get("type") == "loot" and q.report:
                q.report.add_loot(it, {k: e.get(k) for k in ("who", "gained", "used", "cur")})
        self._results = None
        t = api._daily_launch(opts, on_event=on_event)
        if fit:
            q.session["iface"] = True
        t.join()
        kind, val = api._daily_result
        self._results = val if kind == "done" else None
        if kind == "failed":
            q.note(it, f"실패 — {val}")
            return False
        if any(s == "STOP" for _, s, _ in val or []):  # F12·멈추기 → 일시정지 (F12 나 ▶ 로 이어 함)
            q.set_stop("stopped")
            return False
        # 끝까지 돌았어도 끝나지 않은 숙제가 있으면 '완료' 로 치우지 않는다 — 6명 모두 접속에 실패했는데 카드가
        # 완료로 사라져 다 된 줄 알았다 (2026-10-30). 실패 카드로 남겨 ▶ 로 다시 걸면 오늘 끝난 숙제는 넘기고 남은 것만 한다
        bad = [label for label, s, _ in val or [] if s in FAILED]
        if bad:
            q.note(it, f"끝까지 돌았지만 {len(bad)}건이 끝나지 않음 ({', '.join(bad[:3])}{' …' if len(bad) > 3 else ''})"
                       " — 결과 창 확인 · ▶ 로 남은 것만 다시")
            return False
        return True

    def stop(self, reason):
        # 카드를 뺐으면 종료, 아니면 일시정지 (진행 기록으로 끊긴 자리부터 이어 한다)
        self.api.daily_stop(reason in ("remove", "skip"))


class AbyssKind(Kind):
    # 카드 앞에서 재면 아직 앞 카드의 캐릭터라 다른 캐릭터 가방끼리 뺀다 (2026-10-30 결과 창에 룬의 파편 +16만 등)
    # → 이 캐릭터로 접속을 마친 뒤('ready')부터 카드 끝까지 잰다
    own_loot = True
    STAGE = {"match": "매칭 중", "play": "진행 중", "clear": "클리어", "repair": "장비 수리"}
    KIND, PLACE = "abyss", "dungeon"  # 반복 종류 (DailyApi._<KIND>_launch · 진행 이벤트 type), 카드의 장소 칸

    def __init__(self, api):
        self.api = api

    @classmethod
    def detail(cls, x) -> str:
        lim = " · ".join(s for s in [
            (f"{x['runs']}판" + (f" ({x['doneRuns']}판 함)" if x.get("doneRuns") else "")) if x.get("runs") else "",
            f"{x['minutes']}분" if x.get("minutes") else ""] if s)
        return f"{x.get(cls.PLACE)} {x.get('difficulty')} · {lim or '멈출 때까지'}" + (" · 쓰러지면 나감" if x.get("revive") is False else "")

    def where(self, it) -> str:
        return f"{it['doneRuns']}판 한 뒤" if it.get("doneRuns") else ""

    def view(self, it):
        v = super().view(it)
        p = it.get("prog") or {}
        clears = int(it.get("doneRuns") or 0) + int(p.get("clears") or 0)
        secs = float(it.get("doneSecs") or 0) + float(p.get("secs") or 0)
        runs, minutes = int(it.get("runs") or 0), float(it.get("minutes") or 0)
        if not p and not clears:
            return v
        v["now"] = " · ".join(s for s in [
            self.STAGE.get(p.get("stage"), ""),
            f"{clears}/{runs}판" if runs else f"클리어 {clears}",
            f"{int(secs) // 60}분" + (f"/{minutes:g}분" if minutes else "")] if s)
        v["stat"] = " · ".join(s for s in [f"부활 {p['revives']}" if p.get("revives") else "",
                                           f"사망으로 나감 {p['deaths']}" if p.get("deaths") else ""] if s)
        v["bar"] = [clears, runs] if runs else [int(secs), int(minutes * 60)] if minutes else None
        return v

    def run(self, q, it):
        api = self.api
        # 멈췄다 다시 돌 때는 이미 돈 판·시간을 빼고 남은 만큼만
        runs = max(1, int(it["runs"]) - int(it.get("doneRuns") or 0)) if it.get("runs") else 0
        minutes = max(1, math.ceil(float(it["minutes"]) - float(it.get("doneSecs") or 0) / 60)) if it.get("minutes") else 0
        fit = api._q_fit()
        if fit and not api._q_display(q, it):
            return False
        if (err := api._busy_reason()):
            q.note(it, f"시작 못 함 — {err}")
            return False
        last = {"clears": 0, "secs": 0}
        before = []

        q.patch(it["id"], {"prog": {}, "note": ""})  # 이번에 돈 몫만 (앞서 돈 판·시간은 doneRuns·doneSecs)

        def on_event(e):
            if e.get("type") == "ready" and not before:
                before.append(q._snap())
            if e.get("clears") is not None:
                last.update(clears=e["clears"], secs=e.get("seconds") or 0)
            if e.get("type") == self.KIND:  # 진행은 카드의 진행 줄(view)로 보인다
                p = dict(it.get("prog") or {})
                p["stage"] = e.get("stage") or p.get("stage")
                if e.get("clears") is not None:
                    p.update(clears=e["clears"], revives=e.get("revives") or 0, deaths=e.get("deaths") or 0,
                             secs=e.get("seconds") or 0)
                q.patch(it["id"], {"prog": p})
        launch = getattr(api, f"_{self.KIND}_launch")
        t = launch({"slot": it.get("slot"), self.PLACE: it.get(self.PLACE), "difficulty": it.get("difficulty"),
                    "runs": runs, "minutes": minutes, "revive": it.get("revive") is not False,
                    "interface": fit and not q.session.get("iface")}, on_event)
        if fit:
            q.session["iface"] = True
        t.join()
        if before and q.report:
            q.report.add_loot(it, queue_report.loot(before[0], q._snap()))
        q.patch(it["id"], {"doneRuns": int(it.get("doneRuns") or 0) + last["clears"],
                           "doneSecs": float(it.get("doneSecs") or 0) + last["secs"], "prog": {}})
        r = getattr(api, f"_{self.KIND}_result")
        if r.get("type") == "failed":
            q.note(it, f"실패 — {r.get('message', '')}")
            return False
        if r.get("stopped"):  # F12·멈추기 → 일시정지 (▶ 로 다시)
            q.set_stop("stopped")
            return False
        return True

    def stop(self, reason):
        getattr(self.api, f"daily_{self.KIND}Stop")()


class RaidKind(AbyssKind):
    """레이드 반복 (혼자하기) — 어비스 카드와 같은 틀, 장소 칸이 raid."""
    STAGE = {"entry": "입장", "sail": "출항", "play": "진행 중", "clear": "클리어", "repair": "장비 수리"}
    KIND, PLACE = "raid", "raid"


class GoalKind(Kind):
    """제작·채집·가공 목표 — "이걸 새로 N개" 를 끝까지 민다 (예전 web/queue.js 의 runGoalItem·goalExecute 를 옮김).

    무엇을 할지는 판단 엔진(mabi.craft.goal)이 한 걸음씩 정하고, 여기서는 그 걸음을 실행하고 사람이 개입해야 하는
    순간만 처리한다. 매 걸음마다 상태를 새로 읽으므로 채집이 예상보다 많이 들어오든, 가공이 늦게 끝나든 따라간다.
    멈추는 조건은 셋 — 목표 달성, 사람이 멈춤, 그리고 진전이 없을 때. 헛돌면서 날개를 태우는 것이 가장 나쁜 실패다.

    target 은 새로 만들 개수다. 엔진은 "몇 개를 들고 있으면 끝인가" 로 보므로 시작할 때의 보유량(base)을 더해 넘긴다.
    base 는 큐가 이 카드를 처음 집어 들 때 잡고, 일시정지했다 이어 갈 때는 그대로 둔다 (다시 잡으면 한 일이 없던 것이 된다).
    """
    MAX_STEPS = 300
    STUCK_LIMIT = 4  # 같은 걸음이 이만큼 연달아 나오면 헛도는 것으로 본다

    def __init__(self, api):
        self.api = api

    @staticmethod
    def detail(x) -> str:
        return (f"목표 {_num(x.get('target'))}개" + (f" · 만든 {_num(x['made'])}" if x.get("made") else "")
                + (f" · 날개 {_num(x['spent'])}" if x.get("spent") else "") + (f" · {x['via']}" if x.get("via") else ""))

    def view(self, it):
        v = super().view(it)
        if it.get("target"):
            v["bar"] = [min(int(it.get("made") or 0), int(it["target"])), int(it["target"])]
        return v

    def run(self, q, it):
        api, name = self.api, it.get("name")
        if it.get("base") is None:
            try:
                base = int(api.goal_next(name, 0).get("have") or 0)
            except Exception:  # noqa: BLE001 — 못 읽으면 0 부터 센다
                base = 0
            q.patch(it["id"], {"base": base})
        spent, done, last_key, repeat, ok = 0, 0, "", 0, False
        for _ in range(self.MAX_STEPS):
            if q.stop:
                break
            r = api.goal_next(name, (it.get("base") or 0) + int(it.get("target") or 0))  # 수량은 도중에 바뀔 수 있다 (✎)
            if r.get("error"):
                q.note(it, f"실패 — {r.get('message') or r.get('error')}")
                break
            st = r.get("step") or {}
            have = r.get("have") or 0
            q.patch(it["id"], {"have": have, "made": max(0, have - (it.get("base") or 0))}, quiet=True)
            kind = st.get("kind")
            if kind == "done":
                q.note(it, f"달성 — 새로 {_num(it.get('made'))}개 (날개 {_num(spent)})")
                ok = True
                break
            if kind == "blocked":
                q.note(it, f"막힘 — {st.get('message') or st.get('reason') or ''}")
                # 상점·거래는 커넥터에 명령이 없어 대신 구해 올 수 없다 → 사람에게 묻는다
                if not api._q_ask(q, it, {"kind": "goal_blocked", "step": st, "label": it.get("label") or name}):
                    break
                continue  # 구해 왔다니 다시 판단해 본다
            # 같은 걸음만 반복되면 헛도는 것이다. 기다림은 원래 반복되므로 제외한다.
            key = f"{kind}:{st.get('name') or ''}:{st.get('batch') or st.get('runs') or ''}"
            repeat = repeat + 1 if key == last_key and kind != "wait" else 0
            last_key = key
            # 학습은 한 번 해 보고 안 되면 더 해도 안 된다
            if repeat >= (1 if kind == "learn" else self.STUCK_LIMIT):
                q.note(it, f"진전이 없어 멈춤 — {st.get('name') or kind} {repeat + 1}회 반복")
                break
            q.note(it, f"[{done + 1}] {st.get('why') or kind}")
            if kind == "wait":
                if not self._wait(q, it, st):
                    break
                continue
            got = self._execute(q, it, st, done + 1)
            if got is None:
                break  # 실패했고 이어갈 수 없다
            spent += got
            done += 1
            q.patch(it["id"], {"spent": (it.get("spent") or 0) + got, "steps": (it.get("steps") or 0) + 1})
        return ok

    def _wait(self, q, it, st) -> bool:
        """가공이 끝나기를 기다린다. 남은 시간을 카드에 적고, 큐가 서면 그만."""
        until = time.monotonic() + max(5, float(st.get("seconds") or 0))
        while time.monotonic() < until:
            if q.stop:
                return False
            left = int(until - time.monotonic())
            q.note(it, f"가공 완료까지 {left // 60}분 {left % 60}초 대기" if left >= 60 else f"가공 완료까지 {left}초 대기")
            time.sleep(min(5, max(0.1, until - time.monotonic())))
        return True

    def _execute(self, q, it, st, n) -> int | None:
        """한 걸음을 실제로 실행한다. 쓴 날개를 돌려주고, 이어갈 수 없으면 None."""
        api, kind, tag = self.api, st.get("kind"), f"({n}) "
        if kind == "collect":
            label = f"{tag}{st.get('facility')} 수령"
            cmd, body, act = "complete_altering_work", {"displayName": st.get("name")}, "collect"
        else:
            is_alter = kind == "alter" or (kind == "learn" and st.get("via") == "가공")
            cmd = "execute_gathering" if kind == "gather" else "execute_altering" if is_alter else "execute_crafting"
            body = ({"displayName": st.get("name"), "craftCount": 1 if kind == "learn" else (st.get("batch") or 1)}
                    if cmd == "execute_crafting" else {"displayName": st.get("name")})
            label, act = tag + (st.get("why") or st.get("name") or ""), ("alter" if is_alter else "craft")
        r = api.exec(cmd, body, origin={"label": label, "act": act})
        # 게임 쪽 확인 창에 막혔으면 닫히길 기다렸다가 한 번 더. 가공은 막혀도 날개가 이미 나가므로(실측) 한 번만
        if not r.get("ok") and r.get("error") == "blocked" and api._q_wait_dialog_closed(q, st.get("facility") or st.get("name") or ""):
            r = api.exec(cmd, body, origin={"label": label + " (재시도)", "act": act})
        if r.get("ok"):
            return int(r.get("wingsSpent") or 0)
        if kind == "collect":
            return None
        if r.get("error") == "invalid_count":
            return 0  # 상한을 넘겼다 — 엔진이 maxCount 를 배웠으니 다음 걸음에서 맞춰 부른다
        if r.get("error") == "insufficient_living_skill_level":
            # 기다린다고 풀리지 않는다 (같은 거절만 온다) → 카드를 접고 큐 전체를 세운다. 시작 전 거절이라 날개는 안 나간다
            data = r.get("data") if isinstance(r.get("data"), dict) else {}
            q.set_stop("skill", {"what": st.get("name"), "level": r.get("requiredLevel") or data.get("requiredLevel")})
            api._q_toast("생활 스킬 레벨이 모자랍니다",
                         f"{st.get('name')} 을(를) 캘 수 없어 작업 큐를 세웠습니다."
                         + (f" 필요 레벨 {data['requiredLevel']}." if data.get("requiredLevel") else ""), "bad")
        if r.get("error") == "insufficient_transfer_cost":
            # 계획은 보관함 반출 비용(분해된 장비 부품)이 늘 있다고 보고 세운다. 게임이 모자란다고 하면 여기서 멈춘다 —
            # 장비 부품은 기다린다고 생기지 않고, 다음 카드도 같은 보관함 재료를 쓸 가능성이 크다
            q.set_stop("transfer", {"what": st.get("name")})
            api._q_toast("분해된 장비 부품이 모자랍니다",
                         f"{st.get('name')} 의 재료를 보관함에서 꺼낼 수 없어 작업 큐를 세웠습니다.", "bad")
        return None


class ActionKind(Kind):
    """한 번 하는 행동 (제작·채집·가공·수령·연주 버튼). 비용 확인은 화면이 카드를 넣기 전에 받았다."""

    def __init__(self, api):
        self.api = api

    @staticmethod
    def detail(x) -> str:
        return x.get("detail") or ""

    def run(self, q, it):
        if it.get("act") == "collectAll":
            return self.api._q_collect_all(q, it)
        r = self.api.exec(it.get("command"), it.get("body"), origin={"label": it.get("label"), "act": it.get("act")})
        if not r.get("ok"):
            ko = r.get("ko") or {}
            q.note(it, "실패 — " + (ko.get("text") or r.get("message") or r.get("error") or "알 수 없음"))
        return bool(r.get("ok"))


class QueueApi:
    """self.paths, self.cd, self._emit, DailyApi 가 있는 클래스에 섞는다. _init_queue() 를 __init__ 에서 부른다."""

    queue: WorkQueue | None = None

    def _init_queue(self) -> None:
        emit = lambda ch, v: self._emit(ch, v)  # noqa: E731 — 창은 나중에 붙는다
        self._q_pending_ask: dict | None = None
        self.queue = WorkQueue(self.cd.queue_file, self.cd.history_file, emit,
                               {"daily": DailyKind(self), "abyss": AbyssKind(self), "raid": RaidKind(self), "goal": GoalKind(self),
                                "action": ActionKind(self)},
                               on_drained=self._q_drained, pause_note=self._q_pause_note,
                               snap=self._q_snap, on_report=self._q_report)
        threading.Thread(target=self._q_hotkey, name="queue-f12", daemon=True).start()

    # ---- 결과 창: 큐가 다 비면 (다 끝남·전체 중단·마지막 카드 뺌) mabi/workqueue 가 보고서를 넘긴다
    def _q_snap(self):
        def query(cmd):
            r = self.cli.run(cmd, timeout=15)
            return r.data if r.ok else None
        return queue_report.snapshot(query)

    @property
    def _q_report_file(self):
        return self.paths.data / "queue-report.json"

    def _q_report(self, rep: dict) -> None:
        try:
            self._q_report_file.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            log.exception("작업 큐 결과 저장 실패")
        log.info(f"작업 큐 끝 — 결과 창 ({len(rep['cards'])}건)")
        self._emit("mm:queue-report", rep)
        self._bring_front()  # 결과 창이 게임 위로 보이게

    def queue_lastReport(self) -> dict | None:  # noqa: N802
        """지난 결과 창 다시 보기."""
        try:
            return json.loads(self._q_report_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _q_pause_note(self) -> str:
        key = str(load_config(self.paths)["game"].get("stop_key", "f12")).upper()
        return f"일시정지 · {key} 나 ▶ 로 재개"

    def _q_stop_key(self) -> None:
        """일시정지 키를 눌렀다: 돌고 있으면 일시정지, 쉬고 있으면 맨 위 일시정지 카드 이어 하기.
        Ctrl+키 = 전체 중단 (큐를 비운다 → 결과 창), Shift+키 = 지금 작업만 중단 (빼고 다음 카드로)."""
        from mabi.inputs import key_pressed
        q = self.queue
        if key_pressed(0x11):  # Ctrl
            if q.items:
                log.info("Ctrl+F12 → 작업 큐 전체 중단")
                q.clear()
                self.cli.cancel()
            return
        if key_pressed(0x10):  # Shift
            if q.current() or q.top_paused():
                log.info("Shift+F12 → 지금 작업 중단, 다음 카드로")
                q.skip_current()
                self.cli.cancel()
            return
        if q.running:
            log.info("F12 → 작업 큐 일시정지")
            q.request_stop("pause")
            self.cli.cancel()
        elif q.can_resume():
            log.info("F12 → 이어 하기")
            q.resume_top()

    def _q_hotkey(self) -> None:
        """일시정지 키(F12) 하나로 작업 큐 전체를 다룬다 — 앱이 켜져 있는 동안 늘 본다.
          큐가 돌고 있으면 → 무엇이 돌든 일시정지 (지금 명령도 끊는다 — ■ 와 같다)
          쉬고 있으면     → 맨 위 일시정지 카드를 이어 한다
        예전에는 숙제·어비스가 저마다 F12 를 봐서 행동·목표 카드는 F12 로 안 멈췄고, 이어 하기 감시는 숙제가
        멈출 때만 켜져 리모콘을 다시 켜면 안 들었다 (2026-10-24). 숙제·어비스 안의 중단 감시는 그대로 두지만,
        키 상태를 읽기만 하므로(GetAsyncKeyState 0x8000) 서로 눌림을 빼앗지 않는다."""
        from mabi.inputs import key_pressed, vk_of
        vk, checked, down = None, 0.0, False
        while True:
            try:
                if time.monotonic() - checked > 3:  # 설정에서 키를 바꿀 수 있다
                    vk, checked = vk_of(load_config(self.paths)["game"].get("stop_key", "f12")), time.monotonic()
                now = key_pressed(vk)
                if now and not down:
                    self._q_stop_key()
                down = now
            except Exception:  # noqa: BLE001 — 감시가 죽으면 F12 가 영영 안 든다
                log.exception("F12 감시 오류")
                time.sleep(1)
            time.sleep(0.03)

    def _q_toast(self, title: str, text: str = "", kind: str = "ok") -> None:
        self._emit("mm:queue-toast", {"title": title, "text": text, "kind": kind})

    def _q_fit(self) -> bool:
        """옵션 창 '화면 설정 맞추기' ([run] fit_display) — 숙제·어비스·레이드 카드가 시작할 때 모두 이 값을 따른다
        (예전엔 탭마다 체크박스가 있어 카드에 담겼다 — 2026-10-28 사용자: 옵션 창으로 완전히 옮김)."""
        return bool(load_config(self.paths)["run"].get("fit_display", True))

    def _q_display(self, q: WorkQueue, it: dict) -> bool:
        """숙제·어비스·레이드를 시작하기 전 게임 화면 설정 확인. 기준과 다르면 묻지 않고 맞춘다 (큐가 다 끝나면 되돌림).
        큐 한 번에 한 번만 (q.session['screen']). 맞추지 못하면 False."""
        if not self._q_fit():
            return True
        q.session["used"] = True
        if q.session.get("screen"):
            return True
        d = self.daily_displayCheck({"chars": it.get("chars"), "only": it.get("only"), "force": it.get("force")})
        if d.get("ok"):
            q.session["screen"] = not d.get("idle")  # 오늘 할 게 없어 안 본 것이면 다음 카드에서 다시 본다
            return True
        q.note(it, "화면 설정 맞추는 중")
        log.info("화면 설정 맞추는 중: " + ", ".join(d.get("problems") or ["확인 실패"]))
        m = self._display_fix_sync()
        if not m.get("ok"):
            self._q_toast("화면 설정을 맞추지 못했습니다", m.get("message", ""), "bad")
            q.note(it, f"화면 설정 실패 — {m.get('message', '')}")
            return False
        self._q_toast("화면 설정을 파일로 맞췄습니다" if m.get("running") is False else "화면 설정을 맞췄습니다", m.get("message", ""))
        q.session["screen"] = m.get("running") is not False
        return True

    def _q_ask(self, q: WorkQueue, it: dict, payload: dict) -> bool:
        """돌던 카드가 사람에게 묻는다 ('mm:queue-ask'). 화면이 queue.answer(True|False) 로 답할 때까지 기다린다.
        큐가 서면(F12·⏸) 그만 기다리고 False. 화면을 새로 띄우면 queue.state 가 이 질문을 다시 준다."""
        ask = {"id": it["id"], **payload}
        ev = threading.Event()
        self._q_pending_ask = {"ask": ask, "event": ev, "answer": False}
        self._emit("mm:queue-ask", ask)
        try:
            while not ev.wait(0.5):
                if q.stop:
                    return False
            return bool(self._q_pending_ask and self._q_pending_ask["answer"])
        finally:
            self._q_pending_ask = None
            self._emit("mm:queue-ask", None)  # 화면이 띄운 질문 창을 닫는다 (큐가 서서 그만 기다린 경우)

    def _q_wait_dialog_closed(self, q: WorkQueue, label: str, limit: float = 120) -> bool:
        """게임에 확인 창(대화)이 떠 있으면 사람이 닫을 때까지 기다린다 (처음 한 번 알림). 닫혔으면 True.
        큐가 서면(q.stop) 그만 기다린다."""
        end, told = time.monotonic() + limit, False
        while time.monotonic() < end:
            if q.stop:
                return False
            a = self.query("activity", {})
            if not (isinstance(a, dict) and a.get("dialogue")):
                return True
            if not told:
                told = True
                self._q_toast("게임에서 확인이 필요합니다", f"{label} — 게임 창에서 확인을 눌러 주세요. 닫히면 자동으로 이어갑니다.", "bad")
            time.sleep(2)
        return False

    def _q_collect_all(self, q: WorkQueue, it: dict) -> bool:
        """가공 완료분 전체 수령 — 완료분이 있는 시설마다 complete_altering_work 한 번.
        수령은 비용이 없고 되돌릴 것도 없어 묻지 않는다. 앞 시설의 보상 창이 남아 있으면 닫히길 기다린다."""
        w = self.query("alteringWorks", {"refresh": True})
        targets = [f["completed"][0]["name"] for f in (w.get("facilities") or []) if f.get("completed")]
        if not targets:
            q.note(it, "수령할 작업 없음")
            self._q_toast("수령할 작업 없음")
            return True
        done = failed = 0
        for i, name in enumerate(targets):
            if q.stop:
                break
            label = f"({i + 1}/{len(targets)}) {name} 시설"
            q.note(it, f"수령 중… {label}")
            if i > 0 and not self._q_wait_dialog_closed(q, label):
                q.note(it, "확인 창이 닫히지 않아 멈춤")
                break
            origin = {"label": f"{label} 수령", "act": "collect"}
            r = self.exec("complete_altering_work", {"displayName": name}, origin=origin)
            if not r.get("ok") and r.get("error") == "blocked" and self._q_wait_dialog_closed(q, label):
                r = self.exec("complete_altering_work", {"displayName": name}, origin={**origin, "label": f"{label} 수령(재시도)"})
            if r.get("ok"):
                done += 1
            else:
                failed += 1
        q.note(it, f"완료 {done}곳" + (f" · 실패 {failed}곳" if failed else ""))
        self._q_toast("전체 수령 종료", f"완료 {done}곳" + (f" · 실패 {failed}곳" if failed else ""), "bad" if failed else "ok")
        self._emit("mm:exec-done", {"command": "complete_altering_work", "ok": True, "origin": {"act": "collectAll", "quiet": True}})
        return failed == 0 and not q.stop

    def _q_drained(self, q: WorkQueue) -> None:
        """할 일이 다 끝났다 (일시정지 카드도 없음) → 이번 큐에서 맞춘 화면 설정을 되돌린다."""
        if q.session.get("used"):
            self.daily_displayRestore()

    # ---- 화면 (mm.queue.*) ----
    def queue_state(self) -> dict:
        """화면이 처음 뜰 때. 기다리는 질문이 있으면 같이 준다 (다시 띄운다)."""
        p = self._q_pending_ask
        return {**self.queue.snapshot(), "labels": gd.labels().get("queue_state", {}), "ask": p["ask"] if p else None}

    def queue_answer(self, item_id, yes) -> dict:
        """돌던 카드의 질문에 답한다."""
        p = self._q_pending_ask
        if not p or str(p["ask"]["id"]) != str(item_id):
            return {"ok": False}
        p["answer"] = bool(yes)
        p["event"].set()
        return {"ok": True}

    def queue_add(self, spec: dict, where: str = "end", replace_paused: bool = False) -> dict:
        return self.queue.add(spec if isinstance(spec, dict) else {}, where, bool(replace_paused))

    def queue_remove(self, item_id) -> dict:
        self.queue.remove(item_id)
        return {"ok": True}

    def queue_move(self, item_id, delta) -> dict:
        self.queue.move(item_id, int(delta))
        return {"ok": True}

    def queue_playOne(self, item_id) -> dict:  # noqa: N802
        self.queue.play_one(item_id)
        return {"ok": True}

    def queue_pauseOne(self, item_id) -> dict:  # noqa: N802
        self.queue.pause_one(item_id)
        return {"ok": True}

    def queue_pause(self) -> dict:
        self.queue.pause()
        return {"ok": True}

    def queue_halt(self) -> dict:
        """지금 명령까지 끊고 일시정지 (⏸ 는 이번 걸음을 마치고)."""
        self.queue.pause()
        self.cli.cancel()
        return {"ok": True}

    def queue_playAll(self) -> dict:  # noqa: N802
        self.queue.play_all()
        return {"ok": True}

    def queue_tidy(self) -> dict:
        self.queue.tidy()
        return {"ok": True}

    def queue_clear(self) -> dict:
        self.queue.clear()
        return {"ok": True}

    def queue_edit(self, item_id, target) -> dict:
        self.queue.edit(item_id, int(target))
        return {"ok": True}

    def queue_patch(self, item_id, fields) -> dict:
        self.queue.patch(item_id, fields if isinstance(fields, dict) else {})
        return {"ok": True}

