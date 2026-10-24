"""작업 큐 — 카드를 줄 세워 두고 위에서부터 하나씩 돌린다. 큐의 주인은 여기다 (화면은 보여 주고 버튼만 누른다).

캐릭터는 하나고 게임 조작도 한 번에 하나라 동시에 돌릴 수 없어서 큐다. 예전에는 웹 화면(JS)이 큐를 돌렸는데,
  - 화면을 다시 띄우면 돌던 카드가 끊기고,
  - F12 를 받는 곳이 둘(숙제는 파이썬, 큐는 JS)이라 어비스를 멈춘 F12 가 일시정지한 숙제까지 깨웠고 (2026-10-24),
  - 예약·루틴처럼 화면을 누르지 않고 도는 일을 붙일 수 없었다.
그래서 상태·순서·멈춤·저장은 모두 이 클래스가 한다.

카드 종류(kind)마다 실행기(Kind)가 있다 (gui_app/queue_api.py — 숙제·어비스·제작 목표·한 번 하는 행동).

멈추는 이유는 하나만 둔다 (stop). 돌고 있는 카드가 끝나면 그 이유를 보고 카드를 어떻게 둘지 정한다.
  stopped : 작업이 스스로 멈춤 (숙제 F12·어비스 멈추기) → 일시정지
  preempt : '지금 바로' 에 밀림 → 대기로 돌리고 큐를 곧바로 다시 돌린다
  pause   : 사람이 멈춤 (⏸·■·취소) → 일시정지
  remove  : 돌던 카드를 뺐거나 큐를 비움
  skill   : 생활 스킬 레벨 부족 {what, level} → 중단 (기다려도 안 풀린다)
둘이 겹치면 센 쪽 (뒤로 갈수록 셈). 예: 밀리던 숙제가 STOP 으로 끝나도 '밀림' 그대로.

상태: wait(대기) · run(진행 중) · pause(일시정지) · done(완료 — 바로 빠진다) · fail(중단)

일시정지는 '큐가 거기서 멈춰 있다' 는 뜻이라 맨 위 한 장만 둔다 (_one_pause). 큐는 위에서부터 돌다가 일시정지 카드를
만나면 선다 — 예전에는 건너뛰고 아래 대기 카드로 넘어가, 숙제를 일시정지한 채 수령 버튼(지금 바로)을 누르면
수령 뒤에 어비스가 저절로 시작됐다 (2026-10-24 20:04). 이어 하기(▶·F12)는 맨 위 일시정지 카드부터.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from .craft import queue as store

log = logging.getLogger("mabi")

STOP_RANK = {"stopped": 0, "preempt": 1, "pause": 2, "remove": 3, "skill": 4}


class Kind:
    """카드 종류 하나의 실행기."""

    def run(self, q: "WorkQueue", it: dict) -> bool:
        """카드 하나를 끝까지 (막는다). 끝까지 갔으면 True. 멈췄으면 q.set_stop('stopped') 후 False."""
        raise NotImplementedError

    def stop(self, reason: str) -> None:
        """큐가 선다 — 돌고 있는 일을 멈춰 달라."""

    def removed(self, it: dict) -> None:
        """돌지 않는 이 카드가 큐에서 빠졌다 (일시정지한 숙제의 F12 이어 하기 감시를 끄는 등)."""


class WorkQueue:
    def __init__(self, file: Path, history_file: Path, emit: Callable[[str, object], None],
                 kinds: dict[str, Kind], default_kind: str = "goal",
                 on_drained: Callable[["WorkQueue"], None] | None = None, pause_note: Callable[[], str] | None = None):
        """on_drained(q) 할 일이 다 끝났을 때 (일시정지 카드도 없음) · pause_note() 일시정지 카드 메모."""
        self.file, self.history_file, self.emit = file, history_file, emit
        self.kinds, self.default_kind = kinds, default_kind
        self.on_drained = on_drained or (lambda q: None)
        self.pause_note = pause_note or (lambda: "일시정지 · ▶ 로 재개")
        self.lock = threading.RLock()
        self.items: list[dict] = []
        self.running = False
        self.stop: dict | None = None
        self.session: dict = {}  # 큐 한 번 도는 동안 종류들이 같이 쓰는 값 (화면 설정을 맞췄나 등). 다 끝나면 비운다
        self._thread: threading.Thread | None = None
        self._seq = 1
        self._load()

    # ---------------------------------------------------------------- 저장·알림
    def _load(self) -> None:
        items = store.load(self.file)["items"]
        for x in items:
            if x.get("status") == "run":  # 앱이 꺼진 동안 진행됐을 리가 없다
                x["status"] = "wait"
            elif x.get("status") == "pause":
                # 일시정지는 '돌던 동작을 잠깐 멈춤' — 껐다 켜면 돌던 동작이 없으니 차례를 기다리는 카드다.
                # 하던 자리(숙제 진행 기록·어비스 한 판 수·목표 기준점)는 그대로라 ▶ 로 이어 한다 (2026-10-24 사용자 결정)
                x["status"] = "wait"
                x["note"] = "대기 — 하던 자리에서 이어서"
            self._seq = max(self._seq, int(x.get("id") or 0) + 1)
        self.items = items

    def _one_pause(self) -> None:
        """일시정지는 맨 위 한 장만. 그 아래 일시정지 카드는 대기로 (하던 자리 기록은 그대로라 이어서 한다)."""
        seen = False
        for x in self.items:
            if x.get("status") != "pause":
                continue
            if seen:
                x["status"] = "wait"
                x["note"] = "대기 — 하던 자리에서 이어서"
            seen = True

    def top_paused(self) -> dict | None:
        return next((x for x in self.items if x.get("status") == "pause"), None)

    def snapshot(self) -> dict:
        with self.lock:
            return {"items": [dict(x) for x in self.items], "running": self.running}

    def _changed(self) -> None:
        with self.lock:
            self._one_pause()
            store.save(self.file, {"items": self.items})
            snap = self.snapshot()
        self.emit("mm:queue", snap)

    def _record(self, it: dict, result: str) -> None:
        k = self.kinds.get(it.get("kind") or self.default_kind)
        store.record(self.history_file, {
            "start": it.get("startedAt") or int(time.time() * 1000), "end": int(time.time() * 1000),
            "kind": it.get("kind") or self.default_kind, "label": it.get("label"), "result": result,
            "detail": it.get("detail") or (k.detail(it) if hasattr(k, "detail") else ""), "note": it.get("note") or ""})

    def find(self, item_id) -> dict | None:
        return next((x for x in self.items if str(x.get("id")) == str(item_id)), None)

    def current(self) -> dict | None:
        return next((x for x in self.items if x.get("status") == "run"), None)

    def kind_of(self, it: dict) -> Kind:
        return self.kinds.get(it.get("kind") or self.default_kind) or self.kinds[self.default_kind]

    # ---------------------------------------------------------------- 멈춤
    def set_stop(self, reason: str, extra: dict | None = None) -> None:
        """세우는 이유를 적어 둔다 (돌고 있는 일에는 알리지 않음 — 일이 스스로 멈췄을 때)."""
        with self.lock:
            if not self.stop or STOP_RANK.get(reason, 2) > STOP_RANK.get(self.stop["reason"], 2):
                self.stop = {"reason": reason, **(extra or {})}

    def request_stop(self, reason: str, extra: dict | None = None) -> None:
        """큐를 세운다: 이유를 적고 돌고 있는 일에 알린다."""
        self.set_stop(reason, extra)
        cur = self.current()
        if cur:
            self.kind_of(cur).stop(reason)

    # ---------------------------------------------------------------- 카드 다루기 (화면 버튼)
    def add(self, spec: dict, where: str = "end", replace_paused: bool = False) -> dict:
        """카드를 넣는다. where='end' 맨 아래에 담기만, 'now' 맨 위에 넣고 바로 (돌던 일은 밀렸다가 이어서).
        replace_paused: 같은 종류의 아직 안 돈 카드(일시정지·대기)를 이걸로 바꾼다 (숙제 시작 = 새 숙제.
        숙제는 진행 기록이 따로 있어 새 카드도 끊긴 자리부터 한다)."""
        with self.lock:
            it = {k: v for k, v in (spec or {}).items() if k != "id"}
            it.update(id=self._seq, status="wait")
            it.setdefault("note", "")
            self._seq += 1
            if replace_paused:
                for x in [x for x in self.items if x.get("kind") == it.get("kind") and x.get("status") in ("pause", "wait")]:
                    self.items.remove(x)
                    self.kind_of(x).removed(x)
            if where == "now":
                self.items.insert(0, it)
            else:
                self.items.append(it)
            cur = self.current()
        self._changed()
        if where == "now":
            if cur:
                self.patch(cur["id"], {"note": "뒤로 미루는 중…"})
                self.request_stop("preempt")
            else:
                self.tick()
        return dict(it)

    def remove(self, item_id) -> None:
        with self.lock:
            it = self.find(item_id)
            if not it:
                return
            running = it.get("status") == "run"
            if running:
                self.request_stop("remove")
            self.items.remove(it)
        if not running:
            self.kind_of(it).removed(it)
        self._changed()

    def move(self, item_id, delta: int) -> None:
        with self.lock:
            i = next((n for n, x in enumerate(self.items) if str(x.get("id")) == str(item_id)), -1)
            j = i + int(delta)
            if i < 0 or not 0 <= j < len(self.items):
                return
            self.items[i], self.items[j] = self.items[j], self.items[i]
        self._changed()

    def play_one(self, item_id) -> None:
        """이 카드부터. 대기 줄의 맨 앞(돌고 있는 카드 바로 뒤)으로 올리고 큐를 깨운다.
        끝난 카드를 다시 거는 것이면 진행 기록을 지운다 (일시정지였다면 하던 자리에서 이어 간다)."""
        with self.lock:
            it = self.find(item_id)
            if not it or it.get("status") == "run":
                return
            if it.get("status") in ("done", "fail"):
                for k in ("base", "made", "doneRuns", "doneSecs"):
                    it.pop(k, None)
                it.update(spent=0, steps=0, note="")
            it["status"] = "wait"
            self.items.remove(it)
            at = next((n for n, x in enumerate(self.items) if x.get("status") == "run"), -1)
            self.items.insert(at + 1, it)
        self._changed()
        self.tick()

    def pause_one(self, item_id) -> None:
        """돌고 있는 이 카드에서 일시정지 (이번 걸음을 마치고)."""
        it = self.find(item_id)
        if it and it.get("status") == "run":
            self.patch(item_id, {"note": "이번 걸음을 마치고 멈춥니다…"})
            self.request_stop("pause")

    def pause(self) -> None:
        if self.running:
            self.request_stop("pause")

    def resume_top(self) -> None:
        """맨 위 일시정지 카드를 이어 한다 (F12). 다른 일이 돌고 있으면 그 F12 는 그 일의 것이다."""
        if self.running:
            return
        it = self.top_paused()
        if it:
            self.play_one(it["id"])

    def play_all(self) -> None:
        """▶ 전체 시작. 일시정지한 카드도 대기로 되돌려 위에서부터 차례로."""
        with self.lock:
            for x in self.items:
                if x.get("status") == "pause":
                    x["status"] = "wait"
        self._changed()
        self.tick()

    def tidy(self) -> None:
        with self.lock:
            self.items = [x for x in self.items if x.get("status") in ("wait", "run", "pause")]
        self._changed()

    def clear(self) -> None:
        with self.lock:
            if self.current():
                self.request_stop("remove")
            gone, self.items = self.items, []
        for x in gone:
            if x.get("status") != "run":
                self.kind_of(x).removed(x)
        self._changed()

    def edit(self, item_id, target: int) -> None:
        """목표 수량 바꾸기. 끝난 카드면 다시 대기로."""
        with self.lock:
            it = self.find(item_id)
            if not it:
                return
            it["target"] = int(target)
            if it.get("status") in ("done", "fail"):
                it["status"] = "wait"
        self._changed()
        self.tick()

    def patch(self, item_id, fields: dict, quiet: bool = False) -> None:
        """카드 값 고치기 (메모·예상 비용·진행 수량). id·status 는 못 바꾼다."""
        with self.lock:
            it = self.find(item_id)
            if not it:
                return
            it.update({k: v for k, v in (fields or {}).items() if k not in ("id", "status")})
        if not quiet:
            self._changed()

    def note(self, it: dict, text: str) -> None:
        self.patch(it["id"], {"note": text})

    # ---------------------------------------------------------------- 돌리기
    def tick(self) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.stop = None
            self._thread = threading.Thread(target=self._loop, name="work-queue", daemon=True)
        self._changed()
        self._thread.start()

    def _loop(self) -> None:
        drained = restart = False
        try:
            while True:
                with self.lock:
                    if self.stop:
                        break
                    # 위에서부터: 일시정지 카드를 만나면 거기서 선다 (건너뛰고 아래 카드를 돌리지 않는다)
                    it = next((x for x in self.items if x.get("status") in ("wait", "pause")), None)
                    if not it or it.get("status") == "pause":
                        drained = not it
                        break
                    it["status"] = "run"
                    it["startedAt"] = int(time.time() * 1000)
                    it["note"] = "시작"
                self._changed()
                kind = self.kind_of(it)
                ok = False
                try:
                    ok = bool(kind.run(self, it))
                except Exception as e:  # noqa: BLE001 — 한 카드의 오류로 큐가 죽으면 안 된다
                    log.exception(f"작업 큐: '{it.get('label')}' 오류")
                    it["note"] = f"오류 — {e}"
                with self.lock:
                    if it not in self.items:  # 도중에 지워졌다
                        gone = True
                    else:
                        gone = False
                if gone:
                    self._record(it, "removed")
                    continue
                if ok:
                    # 다 한 카드는 치운다. 남겨 두면 다음에 뭘 할 차례인지가 안 보인다. 기록은 작업 기록 창에
                    self._record(it, "done")
                    with self.lock:
                        self.items.remove(it)
                    self.emit("mm:queue-done", {"item": dict(it)})
                    self._changed()
                    continue
                why = self.stop and self.stop["reason"]
                if not why:
                    it["status"] = "fail"
                elif why == "preempt":
                    it["status"] = "wait"
                    restart = True
                    it["note"] = "뒤로 밀림 — 앞 작업이 끝나면 이어서"
                elif why == "skill":
                    # 스킬 레벨은 시간이 지난다고 오르지 않는다. 대기로 되돌리면 재생을 누를 때마다 같은 거절을 받는다
                    s = self.stop
                    it["status"] = "fail"
                    it["note"] = (f"생활 스킬 레벨 부족 — {s.get('what')}" + (f" (필요 Lv.{s['level']})" if s.get("level") else "")
                                  + " · 날개는 쓰이지 않았습니다.")
                else:  # 사람이 멈춘 것(⏸·■·F12)은 실패가 아니다 — 일시정지로 두고 ▶ 로 하던 자리에서 이어 간다
                    it["status"] = "pause"
                    it["note"] = self.pause_note()
                self._record(it, {"fail": "fail", "pause": "pause"}.get(it["status"], "stop"))
                self._changed()
        finally:
            with self.lock:
                self.running = False
                self.stop = None
            self._changed()
            if restart:
                self.tick()  # 지금 바로 시작한 작업으로
            elif drained:
                try:
                    self.on_drained(self)
                except Exception:  # noqa: BLE001
                    log.exception("작업 큐 끝 처리 실패")
                self.session = {}
