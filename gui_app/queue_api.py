"""작업 큐 화면(web/queue.js)이 부르는 파이썬 쪽 (mm.queue.*). Api 가 이 클래스를 섞어 쓴다.

큐의 주인은 mabi.workqueue.WorkQueue 다. 여기는 카드 종류의 실행기와 화면 연결만 둔다.
  daily · abyss : 숙제·어비스 (DailyApi 의 _daily_launch · _abyss_launch 를 기다린다)
  goal          : 제작·채집·가공 목표 (판단 엔진 mabi.craft.goal 의 걸음을 하나씩 실행)
  action        : 한 번 하는 행동 (버튼 하나 = 명령 하나, 전체 수령)
실행 중 사람에게 물어야 하면(재료를 직접 구해 와야 함) 'mm:queue-ask' 로 묻고 queue.answer 를 기다린다.
화면 설정 맞추기는 큐 한 번에 한 번 (q.session), 큐가 다 끝나면 한 번 되돌린다.
변화는 'mm:queue' {items, running} 로 화면에 보낸다.
"""
import logging
import math
import threading
import time

from mabi import gamedata as gd
from mabi.runner import RunOptions, load_config
from mabi.workqueue import Kind, WorkQueue

log = logging.getLogger("mabi")


def _num(n) -> str:
    return f"{int(n or 0):,}"


class DailyKind(Kind):
    def __init__(self, api):
        self.api = api

    @staticmethod
    def detail(it) -> str:
        only = it.get("only")
        return f"{len(it.get('chars') or [])}명 · " + (f"숙제 {len(only)}개" if only else "전체") + (" · 다시" if it.get("force") else "")

    def run(self, q, it):
        api = self.api
        if not api._q_display(q, it):
            return False
        if (err := api._busy_reason()):
            q.note(it, f"시작 못 함 — {err}")
            return False
        fit = it.get("fit") is not False
        opts = RunOptions(chars=it.get("chars") or None, only=it.get("only") or None, force=bool(it.get("force")),
                          display=fit, interface_ready=bool(q.session.get("iface")),
                          restore=False,  # 되돌리기는 큐가 다 끝날 때 한 번 (_q_drained)
                          extra={"from": "queue"})

        def on_event(e):
            if e.get("type") == "task_start" and e.get("label"):
                q.note(it, e["label"])
        t = api._daily_launch(opts, on_event=on_event)
        if fit:
            q.session["iface"] = True
        t.join()
        kind, val = api._daily_result
        if kind == "failed":
            q.note(it, f"실패 — {val}")
            return False
        if any(s == "STOP" for _, s, _ in val or []):  # F12·멈추기 → 일시정지 (F12 나 ▶ 로 이어 함)
            q.set_stop("stopped")
            return False
        return True  # 끝까지 돌았다 (실패한 숙제가 있어도 — 결과는 보고서로 본다)

    def stop(self, reason):
        # 카드를 뺐으면 종료, 아니면 일시정지 (진행 기록으로 끊긴 자리부터 이어 한다)
        self.api.daily_stop(reason == "remove")


class AbyssKind(Kind):
    STAGE = {"match": "매칭 중", "play": "진행 중", "clear": "클리어"}

    def __init__(self, api):
        self.api = api

    @staticmethod
    def detail(x) -> str:
        lim = " · ".join(s for s in [
            (f"{x['runs']}판" + (f" ({x['doneRuns']}판 함)" if x.get("doneRuns") else "")) if x.get("runs") else "",
            f"{x['minutes']}분" if x.get("minutes") else ""] if s)
        return (f"{x.get('dungeon')} {x.get('difficulty')} · {lim or '멈출 때까지'}" + (" · 쓰러지면 나감" if x.get("revive") is False else "")
                + (" · 화면 맞춤" if x.get("fit") else ""))

    def run(self, q, it):
        api = self.api
        # 멈췄다 다시 돌 때는 이미 돈 판·시간을 빼고 남은 만큼만
        runs = max(1, int(it["runs"]) - int(it.get("doneRuns") or 0)) if it.get("runs") else 0
        minutes = max(1, math.ceil(float(it["minutes"]) - float(it.get("doneSecs") or 0) / 60)) if it.get("minutes") else 0
        fit = bool(it.get("fit"))
        if fit and not api._q_display(q, it):
            return False
        if (err := api._busy_reason()):
            q.note(it, f"시작 못 함 — {err}")
            return False
        last = {"clears": 0, "secs": 0}

        def on_event(e):
            if e.get("clears") is not None:
                last.update(clears=e["clears"], secs=e.get("seconds") or 0)
            if e.get("type") == "abyss":
                stat = (f"클리어 {e['clears']}" + (f" · 부활 {e['revives']}" if e.get("revives") else "")
                        + f" · 사망으로 나감 {e.get('deaths', 0)}"
                        + (f" · {int(e['seconds']) // 60}분" if e.get("seconds") is not None else "")) if e.get("clears") is not None else ""
                q.note(it, self.STAGE.get(e.get("stage"), "") + (f" · {stat}" if stat else ""))
        t = api._abyss_launch({"slot": it.get("slot"), "dungeon": it.get("dungeon"), "difficulty": it.get("difficulty"),
                               "runs": runs, "minutes": minutes, "revive": it.get("revive") is not False,
                               "fit_display": fit, "interface": fit and not q.session.get("iface")}, on_event)
        if fit:
            q.session["iface"] = True
        t.join()
        q.patch(it["id"], {"doneRuns": int(it.get("doneRuns") or 0) + last["clears"],
                           "doneSecs": float(it.get("doneSecs") or 0) + last["secs"]})
        r = api._abyss_result
        if r.get("type") == "failed":
            q.note(it, f"실패 — {r.get('message', '')}")
            return False
        if r.get("stopped"):  # F12·멈추기 → 일시정지 (▶ 로 다시)
            q.set_stop("stopped")
            return False
        return True

    def stop(self, reason):
        self.api.daily_abyssStop()


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
                q.note(it, f"중단 — {r.get('message') or r.get('error')}")
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
                               {"daily": DailyKind(self), "abyss": AbyssKind(self), "goal": GoalKind(self),
                                "action": ActionKind(self)},
                               on_drained=self._q_drained, pause_note=self._q_pause_note)
        threading.Thread(target=self._q_hotkey, name="queue-f12", daemon=True).start()

    def _q_pause_note(self) -> str:
        key = str(load_config(self.paths)["game"].get("stop_key", "f12")).upper()
        return f"일시정지 · {key} 나 ▶ 로 재개"

    def _q_stop_key(self) -> None:
        """일시정지 키를 눌렀다: 돌고 있으면 일시정지, 쉬고 있으면 맨 위 일시정지 카드 이어 하기."""
        q = self.queue
        if q.running:
            log.info("F12 → 작업 큐 일시정지")
            q.request_stop("pause")
            self.cli.cancel()
        elif q.top_paused():
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

    def _q_display(self, q: WorkQueue, it: dict) -> bool:
        """숙제·어비스를 시작하기 전 게임 화면 설정 확인. 기준과 다르면 묻지 않고 맞춘다 (큐가 다 끝나면 되돌림).
        큐 한 번에 한 번만 (q.session['screen']). 맞추지 못하면 False."""
        if it.get("fit") is False:
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

