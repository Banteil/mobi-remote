"""작업 큐 화면(web/queue.js)이 부르는 파이썬 쪽 (mm.queue.*). Api 가 이 클래스를 섞어 쓴다.

큐의 주인은 mabi.workqueue.WorkQueue 다. 여기는 카드 종류의 실행기와 화면 연결만 둔다.
  daily · abyss : 파이썬이 돌린다 (DailyApi 의 _daily_launch · _abyss_launch 를 기다린다)
  goal · action : 아직 화면이 돌린다 (RemoteKind — 'mm:queue-run' 을 받고 queue.uiDone 으로 답한다)
화면 설정 맞추기는 큐 한 번에 한 번 (q.session), 큐가 다 끝나면 한 번 되돌린다.
변화는 'mm:queue' {items, running} 로 화면에 보낸다.
"""
import logging
import math

from mabi import gamedata as gd
from mabi.runner import RunOptions, load_config
from mabi.workqueue import Kind, RemoteKind, WorkQueue

log = logging.getLogger("mabi")


def _num(n) -> str:
    return f"{int(n or 0):,}"


class DailyKind(Kind):
    def __init__(self, api):
        self.api = api

    @property
    def pause_note(self) -> str:
        key = str(load_config(self.api.paths)["game"].get("stop_key", "f12")).upper()
        return f"일시정지 · {key} 나 ▶ 로 재개"

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
        t = api._daily_launch(opts, on_event=on_event, on_resume=lambda: q.resume_paused("daily"))
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
        # 카드를 뺐으면 종료 (F12 로 이어 하지 않음), 아니면 일시정지
        self.api.daily_stop(reason == "remove")

    def removed(self, it):
        self.api.daily_pauseCancel()  # 일시정지한 숙제 카드를 지우면 F12 이어 하기도 끈다


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


class GoalKind(RemoteKind):
    """제작·채집·가공 목표 (화면이 goal 판단 엔진과 함께 돌린다)."""

    @staticmethod
    def detail(x) -> str:
        return (f"목표 {_num(x.get('target'))}개" + (f" · 만든 {_num(x['made'])}" if x.get("made") else "")
                + (f" · 날개 {_num(x['spent'])}" if x.get("spent") else "") + (f" · {x['via']}" if x.get("via") else ""))


class ActionKind(RemoteKind):
    """한 번 하는 행동 (제작·채집·가공·수령·연주 버튼)."""

    @staticmethod
    def detail(x) -> str:
        return x.get("detail") or ""


class QueueApi:
    """self.paths, self.cd, self._emit, DailyApi 가 있는 클래스에 섞는다. _init_queue() 를 __init__ 에서 부른다."""

    queue: WorkQueue | None = None

    def _init_queue(self) -> None:
        emit = lambda ch, v: self._emit(ch, v)  # noqa: E731 — 창은 나중에 붙는다
        self.queue = WorkQueue(self.cd.queue_file, self.cd.history_file, emit,
                               {"daily": DailyKind(self), "abyss": AbyssKind(self), "goal": GoalKind(emit),
                                "action": ActionKind(emit)},
                               on_start=self.daily_pauseCancel,  # 다른 일이 돌면 F12 는 그 일의 것 — 숙제를 깨우지 않는다
                               on_drained=self._q_drained)

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

    def _q_drained(self, q: WorkQueue) -> None:
        """할 일이 다 끝났다 (일시정지 카드도 없음) → 이번 큐에서 맞춘 화면 설정을 되돌린다."""
        if q.session.get("used"):
            self.daily_displayRestore()

    # ---- 화면 (mm.queue.*) ----
    def queue_state(self) -> dict:
        """화면이 처음 뜰 때. 화면이 돌리던 카드가 있었다면 이어 갈 수 없으니 일시정지로 돌린다."""
        self.queue.ui_reset()
        return {**self.queue.snapshot(), "labels": gd.labels().get("queue_state", {})}

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

    def queue_uiDone(self, item_id, result) -> dict:  # noqa: N802
        return {"ok": self.queue.ui_done(item_id, result if isinstance(result, dict) else {})}
