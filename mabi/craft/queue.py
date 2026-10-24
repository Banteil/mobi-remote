"""작업 큐 — 목표를 줄 세워 두고 하나씩 민다 (리모콘 src/queue.js + app.js 의 큐 처리).

캐릭터는 하나고 CLI 호출도 하나씩이라 동시에 돌릴 수가 없어서 큐다. 걸어 두면 순서대로 진행되고,
진행 중에도 뒤에 붙이거나 순서를 바꿀 수 있다. 껐다 켜도 목록이 남게 queue.json 에 저장하고,
진행 중이던 항목은 다시 켤 때 대기로 되돌린다 — 앱이 꺼진 동안 진행됐을 리가 없다.

상태: wait(대기) · run(진행 중) · pause(일시정지) · done(완료) · fail(중단)
"""
import json
import threading
from pathlib import Path
from typing import Callable

from .. import gamedata as gd
from .runner import GoalRunner

# 한 항목이 가질 수 있는 필드. 화면이 주는 값을 그대로 믿지 않고 걸러 담는다
FIELDS = ["id", "via", "name", "label", "recipe", "target", "status", "note",
          "spent", "steps", "have", "startHave", "per", "runs", "wings", "partial", "base", "made",
          # 일일 숙제 카드 (kind='daily'). 빠지면 다시 켰을 때 숙제 카드인 줄 몰라 새 숙제가 바꿔 끼우지 못하고 쌓인다
          "kind", "chars", "only", "force",
          # 어비스 반복 카드 (kind='abyss'; runs 는 위 runs 를 같이 쓴다 — 판 수)
          "slot", "dungeon", "difficulty", "minutes", "revive",
          # 한 번 하는 행동 카드 (kind='action' — 제작·채집·가공·수령·연주 버튼)
          "act", "command", "body", "detail", "skipConfirm",
          "doneRuns", "doneSecs", "fit"]  # 어비스 카드가 멈췄다 다시 돌 때 이미 한 판·초

STATE_LABEL = gd.labels()["queue_state"]

# 작업 기록 (끝난 항목 한 줄씩, queue-history.jsonl). 화면의 '기록' 창이 읽는다
HISTORY_FIELDS = ["start", "end", "kind", "label", "result", "detail", "note"]
HISTORY_KEEP = 1000


def record(file: Path, entry: dict) -> None:
    """끝난 항목 하나를 기록 끝에 붙인다. 오래된 것은 HISTORY_KEEP 줄만 남기고 버린다."""
    row = {k: entry[k] for k in HISTORY_FIELDS if isinstance(entry, dict) and k in entry}
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        lines = file.read_text(encoding="utf-8").splitlines() if file.exists() else []
        lines = (lines + [json.dumps(row, ensure_ascii=False)])[-HISTORY_KEEP:]
        file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # 기록에 실패해도 큐는 계속 돈다


def history(file: Path, limit: int = 300) -> list[dict]:
    """최근 기록부터 limit 개."""
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def load(file: Path) -> dict:
    try:
        d = json.loads(file.read_text(encoding="utf-8"))
        return {"items": d["items"] if isinstance(d.get("items"), list) else []}
    except (OSError, ValueError, AttributeError):
        return {"items": []}


def save(file: Path, state: dict) -> dict:
    items = [{k: x[k] for k in FIELDS if k in x}
             for x in (state.get("items") if isinstance(state, dict) and isinstance(state.get("items"), list) else [])]
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 저장에 실패해도 진행 중인 큐는 계속 돌아야 한다
    return {"items": items}


class WorkQueue:
    def __init__(self, file: Path, on_change: Callable[[], None] | None = None,
                 on_notice: Callable[[str, str, str], None] | None = None,
                 kick: Callable[[], None] | None = None):
        """on_change() 다시 그리기 · on_notice(제목, 글, 'ok'|'bad') · kick() 큐를 깨워 달라 (GUI 가 스레드로 tick 을 부른다)."""
        self.file = file
        self.on_change = on_change or (lambda: None)
        self.on_notice = on_notice or (lambda *_: None)
        self.kick = kick or (lambda: None)
        self.lock = threading.RLock()
        self.items: list[dict] = []
        self.running = False
        self.runner: GoalRunner | None = None  # 돌고 있는 실행기 (멈춤 신호를 보낼 곳)
        self._abort = threading.Event()
        self.seq = 1
        self.reload()

    # ---------------------------------------------------------------- 저장
    def reload(self) -> None:
        with self.lock:
            self.items = [{**x, "status": "wait" if x.get("status") == "run" else x.get("status", "wait")}
                          for x in load(self.file)["items"]]
            for x in self.items:
                try:
                    self.seq = max(self.seq, int(x.get("id") or 0) + 1)
                except (TypeError, ValueError):
                    pass
        self.on_change()

    def save(self) -> None:
        with self.lock:
            save(self.file, {"items": self.items})

    def _changed(self) -> None:
        self.save()
        self.on_change()

    # ---------------------------------------------------------------- CRUD
    def add(self, spec: dict) -> dict:
        """spec: {via, name, label, target(새로 만들 개수), wings?, partial?, recipe?}. 담기만 하고 돌리지 않는다 —
        날개가 나가는 일은 사람이 재생을 누른 뒤에 시작해야 한다."""
        with self.lock:
            it = {"id": self.seq, "status": "wait", "note": "", "spent": 0, "steps": 0, **spec}
            self.seq += 1
            self.items.append(it)
        self._changed()
        self.on_notice("큐에 담았습니다", f"{it.get('label') or it['name']} 새로 {it['target']:,}개 — 재생을 누르면 진행합니다.", "ok")
        return it

    def find(self, item_id) -> dict | None:
        return next((x for x in self.items if str(x.get("id")) == str(item_id)), None)

    def note(self, it: dict, text: str) -> None:
        it["note"] = text
        self.on_change()

    def remove(self, item_id) -> None:
        with self.lock:
            it = self.find(item_id)
            if not it:
                return
            if it["status"] == "run":
                self._abort.set()
                it["note"] = "멈추는 중…"
            self.items = [x for x in self.items if x is not it]
        self._changed()

    def play_one(self, item_id) -> None:
        """이 항목부터 돌린다. 끝난 것을 다시 거는 것이면 기준점을 새로 잡고, 보류였다면 하던 자리에서 이어간다."""
        with self.lock:
            it = self.find(item_id)
            if not it or it["status"] == "run":
                return
            if it["status"] in ("done", "fail"):
                for k in ("base", "made"):
                    it.pop(k, None)
                it.update(spent=0, steps=0, note="")
            it["status"] = "wait"
            # 진행 중인 항목 바로 뒤, 다른 대기 항목보다는 앞
            self.items = [x for x in self.items if x is not it]
            at = next((i for i, x in enumerate(self.items) if x["status"] == "run"), -1)
            self.items.insert(0 if at < 0 else at + 1, it)
        self._changed()
        self.kick()

    def pause_one(self, item_id) -> None:
        """보류. 진행 중이면 이번 걸음을 마치고 빠진다. 보류된 항목은 지나칠 뿐 지워지지 않는다."""
        with self.lock:
            it = self.find(item_id)
            if not it:
                return
            if it["status"] == "run":
                it["pauseAfter"] = True
                self._abort.set()
                self.note(it, "이번 걸음을 마치고 멈춥니다…")
                return
            if it["status"] == "wait":
                it["status"] = "pause"
        self._changed()

    def move(self, item_id, delta: int) -> None:
        with self.lock:
            i = next((k for k, x in enumerate(self.items) if str(x.get("id")) == str(item_id)), -1)
            j = i + delta
            if i < 0 or j < 0 or j >= len(self.items):
                return
            self.items[i], self.items[j] = self.items[j], self.items[i]
        self._changed()

    def edit(self, item_id, target: int) -> None:
        """목표 수량 바꾸기. 진행 중이어도 다음 걸음부터 새 수량으로 판단하고, 이미 만든 만큼은 인정한다."""
        if not target:
            return
        with self.lock:
            it = self.find(item_id)
            if not it:
                return
            it["target"] = target
            if it["status"] in ("done", "fail"):
                it["status"] = "wait"
        self._changed()
        self.kick()

    def tidy(self) -> None:
        """중단된 항목을 치운다 (완료는 끝나는 즉시 스스로 빠진다)."""
        with self.lock:
            self.items = [x for x in self.items if x["status"] in ("wait", "run", "pause")]
        self._changed()

    def clear(self) -> None:
        """전부 지운다 (확인은 부르는 쪽이). 진행 중이면 이번 걸음을 마치고 멈춘다."""
        with self.lock:
            self._abort.set()
            self.items = []
        self._changed()

    # ---------------------------------------------------------------- 진행
    def pause(self) -> None:
        """부드럽게 멈춘다. 항목 상태는 그대로라 재생을 누르면 이어진다."""
        if self.running:
            self._abort.set()

    def halt(self) -> None:
        """지금 명령까지 끊고 멈춘다. 진행하던 항목은 보류가 되어 재생해도 건너뛴다."""
        with self.lock:
            it = next((x for x in self.items if x["status"] == "run"), None)
            if it:
                it["pauseAfter"] = True
        self._abort.set()
        if self.runner:
            self.runner.halt()

    def tick(self, make_runner: Callable[[threading.Event], GoalRunner]) -> None:
        """대기 중인 것을 위에서부터 하나씩 민다 (막히는 호출이라 작업 스레드에서 부를 것).
        make_runner(cancel) 은 이 큐의 멈춤 신호를 받는 GoalRunner 를 만들어 준다.
        한 항목이 실패해도 큐를 통째로 세우지 않는다 — 실패한 카드는 이유를 달고 남는다."""
        with self.lock:
            if self.running:
                return
            self.running = True
            self._abort.clear()
        runner = make_runner(self._abort)
        self.runner = runner
        runner.skill_halt = None
        self.on_change()
        try:
            while not self._abort.is_set():
                with self.lock:
                    it = next((x for x in self.items if x["status"] == "wait"), None)
                    if not it:
                        break  # 보류(pause)는 여기서 안 걸리니 자연히 건너뛴다
                    it["status"] = "run"
                self.note(it, "시작")
                self.save()

                ok = False
                try:
                    ok = runner.run_item(it)
                except Exception as e:
                    self.note(it, f"오류 — {e}")

                with self.lock:
                    if not any(x is it for x in self.items):
                        continue  # 도중에 지워졌으면 상태를 되살리지 않는다
                    if ok:
                        # 다 만든 카드는 치운다. 남겨 두면 다음에 뭘 할 차례인지가 안 보인다
                        self.items = [x for x in self.items if x is not it]
                        self.on_notice("목표 달성", f"{it.get('label')} 새로 {it['target']:,}개"
                                       + (f" · 날개 {it['spent']:,}" if it.get("spent") else ""), "ok")
                    elif runner.skill_halt:
                        # 스킬 레벨은 시간이 지난다고 안 오른다. 대기로 되돌리면 같은 거절만 반복하므로 중단으로 못 박는다
                        h = runner.skill_halt
                        it["status"] = "fail"
                        it["note"] = (f"생활 스킬 레벨 부족 — {h['what']}" + (f" (필요 Lv.{h['level']})" if h.get("level") else "")
                                      + " · 날개는 쓰이지 않았습니다.")
                        self.on_notice("생활 스킬 레벨이 모자랍니다",
                                       f"{h['what']} 을(를) 캘 수 없어 작업 큐를 세웠습니다."
                                       + (f" 필요 레벨 {h['level']}." if h.get("level") else ""), "bad")
                    elif it.get("pauseAfter"):
                        it["status"] = "pause"
                        it["note"] = "보류 — ▶ 를 누르면 이어서 진행합니다."
                    elif self._abort.is_set():
                        it["status"] = "wait"
                        it["note"] = "멈춤 — 재생을 누르면 이어서 진행합니다."
                    else:
                        it["status"] = "fail"
                    it.pop("pauseAfter", None)
                self._changed()
        finally:
            with self.lock:
                self.running = False
                self.runner = None
                self._abort.clear()
            self.on_change()
