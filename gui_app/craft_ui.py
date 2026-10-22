"""제작 · 가공 탭과 작업 큐(목표 루프).

판단은 mabi/craft (리모콘 이식), 여기는 화면과 스레드 연결만 한다.
- 단건 실행은 craft.execute.execute (실행 전 시설 칸 차단, 실행 전후 인벤 비교로 레시피 학습)
- 목표는 큐에 담기만 하고, 재생을 눌러야 돈다 (날개가 나가는 일은 사람이 시작해야 한다)
- 큐는 작업 스레드에서 돈다. 막혔을 때 "구해 왔으면 계속" 물음은 화면 스레드로 넘겨 답을 기다린다
"""
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from mabi.craft import execute as cexec
from mabi.craft import goal, lists
from mabi.craft.queue import WorkQueue
from mabi.craft.runner import GoalRunner
from mabi.query import matches

from .gather_tab import confirm_cost
from .services import Services
from .style import MUTED, STATUS_COLORS

PAGE = 200  # 제작 1,834줄을 한 번에 그리면 느리다. 검색으로 좁히거나 다음 쪽으로


def run_exec(svc: Services, command: str, body, label: str, done=None) -> None:
    """학습이 붙은 단건 실행 (상태바 진행 표시·알림 포함)."""
    if svc.cli.busy():
        svc.notice.emit("bad", "다른 명령이 진행 중입니다")
        return
    svc.action_state.emit(True, label)

    def fin(r, e):
        svc.action_state.emit(False, "")
        if r is None:
            svc.notice.emit("bad", f"{label}: 실행 실패 ({e})")
        elif r.ok:
            svc.notice.emit("ok", f"{label} 완료" + (f" — 날개 {r.wings_spent} 사용" if r.wings_spent else ""))
        else:
            ko = r.ko or {}
            svc.notice.emit("bad", f"{label}: {ko.get('text') or r.error}" + (f" — {ko['hint']}" if ko.get("hint") else ""))
        for c in ("get_currencies", "get_items", "get_altering_works", "get_alterable_items", "get_craftable_items"):
            svc.cache.clear(c)
        if done:
            done(r)
    svc.run_bg(lambda: cexec.execute(svc.cd, svc.cli, svc.cache, command, body), fin)


def ask_count(parent, title: str, label: str, maximum: int = 9999) -> int:
    n, ok = QInputDialog.getInt(parent, title, label, 1, 1, maximum)
    return n if ok else 0


# ------------------------------------------------------------------ 큐
class QueueBridge(QObject):
    changed = Signal()
    notice = Signal(str, str, str)
    busy = Signal(str)
    ask = Signal(str, str)  # (라벨, 막힌 이유) → 화면이 답을 bridge.answer 에 넣는다


class QueuePanel(QWidget):
    """오른쪽 작업 큐. 카드: 대기/진행/보류/중단, 카드별 ▶ ⏸ ✎ ✕ ↑↓."""
    STATUS = {"wait": ("대기", MUTED), "run": ("진행 중", STATUS_COLORS["RUN"]), "pause": ("보류", STATUS_COLORS["CHECK"]),
              "fail": ("중단", STATUS_COLORS["FAIL"]), "done": ("완료", STATUS_COLORS["OK"])}

    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.setMinimumWidth(300)
        self.bridge = QueueBridge()
        self.bridge.changed.connect(self.render)
        self.bridge.notice.connect(lambda t, b, k: svc.notice.emit("ok" if k == "ok" else "bad", f"{t} — {b}" if b else t))
        self.bridge.busy.connect(lambda s: svc.action_state.emit(bool(s), s or ""))
        self.bridge.ask.connect(self._ask)
        self._answer, self._answered = False, threading.Event()
        self.queue = WorkQueue(svc.cd.queue_file, on_change=self.bridge.changed.emit,
                               on_notice=lambda t, b, k: self.bridge.notice.emit(t, b, k), kick=self.play)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        title = QLabel("작업 큐")
        title.setObjectName("title")
        play, pause, halt = QPushButton("▶ 진행"), QPushButton("‖ 멈춤"), QPushButton("■ 정지")
        play.setObjectName("primary")
        pause.setToolTip("이번 걸음을 마치고 멈춤 (항목은 그대로)")
        halt.setToolTip("지금 명령까지 끊고 멈춤 (진행 항목은 보류)")
        play.clicked.connect(self.play)
        pause.clicked.connect(self.queue.pause)
        halt.clicked.connect(self.queue.halt)
        tidy, clear = QPushButton("정리"), QPushButton("비우기")
        tidy.clicked.connect(self.queue.tidy)
        clear.clicked.connect(lambda: QMessageBox.question(self, "작업 큐", "큐를 모두 지울까요?") == QMessageBox.Yes
                              and self.queue.clear())
        card = QHBoxLayout()
        for txt, fn, tip in (("▶", self.queue.play_one, "이 항목부터"), ("‖", self.queue.pause_one, "보류"),
                             ("✎", self._edit, "수량 바꾸기"), ("↑", lambda i: self.queue.move(i, -1), ""),
                             ("↓", lambda i: self.queue.move(i, 1), ""), ("✕", self.queue.remove, "빼기")):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setMaximumWidth(40)
            b.clicked.connect(lambda _=False, fn=fn: self._sel() and fn(self._sel()))
            card.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.addWidget(title)
        lay.addWidget(self.list, 1)
        lay.addLayout(card)
        row = QHBoxLayout()
        for w in (play, pause, halt, tidy, clear):
            row.addWidget(w)
        lay.addLayout(row)
        self.render()

    def _sel(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _edit(self, item_id) -> None:
        it = self.queue.find(item_id)
        if it:
            n, ok = QInputDialog.getInt(self, "수량", f"{it.get('label') or it['name']} 새로 만들 개수", it["target"], 1, 99999)
            if ok:
                self.queue.edit(item_id, n)

    def render(self) -> None:
        if not hasattr(self, "list"):  # 큐를 읽는 중(생성자 안)에도 불린다
            return
        sel = self._sel()
        self.list.clear()
        for it in self.queue.items:
            st, color = self.STATUS.get(it.get("status"), ("?", MUTED))
            made = f"  {it.get('made', 0):,}/{it['target']:,}" if it.get("made") is not None else f"  0/{it['target']:,}"
            wings = f" · 날개 {it['spent']:,}" if it.get("spent") else ""
            li = QListWidgetItem(f"[{st}] {it.get('label') or it['name']}{made}{wings}\n{it.get('note') or ''}")
            li.setForeground(QColor(color))
            li.setData(Qt.UserRole, it["id"])
            self.list.addItem(li)
            if it["id"] == sel:
                self.list.setCurrentItem(li)

    def add(self, via: str, name: str, label: str, target: int) -> None:
        est = goal.next_for(self.svc.cd, self.svc.cache, name, target, refresh=False, offline=True)
        spec = {"via": via, "name": name, "label": label, "target": target}
        if est.get("estimate"):
            spec["wings"] = est["estimate"].get("wings")
        self.queue.add(spec)

    # ---- 진행 (작업 스레드) ----
    def play(self) -> None:
        if self.queue.running:
            return
        if self.svc.online is not True:
            self.svc.notice.emit("bad", "게임에 연결되어 있을 때만 진행할 수 있습니다")
            return

        def make_runner(cancel):
            return GoalRunner(self.svc.cd, self.svc.cli, self.svc.cache, cancel=cancel,
                              on_note=lambda it, t: self.bridge.changed.emit(),
                              on_notice=lambda t, b, k: self.bridge.notice.emit(t, b, k),
                              on_busy=lambda s: self.bridge.busy.emit(s or ""),
                              on_change=lambda it: self.bridge.changed.emit(),
                              on_blocked=self._blocked)
        self.svc.run_bg(lambda: self.queue.tick(make_runner), lambda r, e: self.bridge.changed.emit())

    def _blocked(self, step: dict, label: str) -> bool:
        """작업 스레드: 막혔을 때 화면에 묻고 답을 기다린다."""
        self._answered.clear()
        self.bridge.ask.emit(label, step.get("message") or step.get("reason") or "")
        self._answered.wait()
        return self._answer

    def _ask(self, label: str, why: str) -> None:
        r = QMessageBox.question(self, "자동으로 구할 수 없는 재료",
                                 f"{label}\n\n{why}\n\n게임에서 직접 구해 왔으면 '예'를 누르면 이어서 진행합니다.")
        self._answer = r == QMessageBox.Yes
        self._answered.set()


# ------------------------------------------------------------------ 목록 공통
class _ListTab(QWidget):
    FAV = ""
    HEAD: list[str] = []

    def __init__(self, svc: Services, queue: QueuePanel):
        super().__init__()
        self.svc, self.queue = svc, queue
        self.data, self.page = None, 0
        self.search = QLineEdit()
        self.search.setPlaceholderText("검색")
        self.search.textChanged.connect(lambda: (setattr(self, "page", 0), self.render()))
        self.only_ok = QCheckBox("가능한 것만")
        self.only_ok.toggled.connect(lambda: (setattr(self, "page", 0), self.render()))
        self.count = QLabel("")
        self.count.setObjectName("muted")
        self.prev, self.next = QPushButton("◀"), QPushButton("▶")
        self.prev.clicked.connect(lambda: (setattr(self, "page", max(0, self.page - 1)), self.render()))
        self.next.clicked.connect(lambda: (setattr(self, "page", self.page + 1), self.render()))
        self.table = QTableWidget(0, len(self.HEAD))
        self.table.setHorizontalHeaderLabels(self.HEAD)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 30)
        self.table.cellClicked.connect(self._cell)
        self.bar = QHBoxLayout()
        self.bar.addWidget(self.search, 1)
        self.bar.addWidget(self.only_ok)
        self.bar.addWidget(self.count)
        self.bar.addWidget(self.prev)
        self.bar.addWidget(self.next)

    def _cell(self, row, col):
        if col == 0 and row < len(self.rows):
            self.svc.favorites.toggle(self.FAV, self.rows[row]["name_raw"])
            self.render()

    def filtered(self) -> list:
        favs = self.svc.favorites.get(self.FAV)
        rows = [r for r in self.data["items"] if matches(r["name_raw"], self.search.text())
                and (not self.only_ok.isChecked() or r["ok"])]
        return sorted(rows, key=lambda r: r["name_raw"] not in favs)  # 즐겨찾기 먼저, 그 안은 게임 순서

    def render(self) -> None:
        if not self.data or "error" in self.data:
            return
        rows = self.filtered()
        pages = max(1, -(-len(rows) // PAGE))
        self.page = min(self.page, pages - 1)
        self.rows = rows[self.page * PAGE:(self.page + 1) * PAGE]
        self.count.setText(f"{len(rows):,}개" + (f" · {self.page + 1}/{pages}쪽" if pages > 1 else ""))
        self.prev.setEnabled(self.page > 0)
        self.next.setEnabled(self.page < pages - 1)
        favs = self.svc.favorites.get(self.FAV)
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            star = QTableWidgetItem("★" if r["name_raw"] in favs else "☆")
            mark = QTableWidgetItem("✔" if r["ok"] else "✘")
            mark.setForeground(QColor(STATUS_COLORS["OK"] if r["ok"] else MUTED))
            for c, it in enumerate((star, mark)):
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, c, it)
            self.fill_row(i, r)
        self.table.resizeRowsToContents()

    @staticmethod
    def status_text(r: dict) -> str:
        if r["ok"]:
            return ""
        parts = [r.get("reason") or ""]
        if r.get("missing"):
            parts.append("부족: " + ", ".join(r["missing"]))
        if r.get("covered"):
            parts.append("창고에서 충당: " + ", ".join(r["covered"]))
        return "  ".join(p for p in parts if p)


class CraftTab(_ListTab):
    FAV = "craft"
    HEAD = ["☆", "", "이름", "산출", "상태", "", ""]

    def __init__(self, svc, queue):
        super().__init__(svc, queue)
        lay = QVBoxLayout(self)
        lay.addLayout(self.bar)
        lay.addWidget(self.table, 1)
        self.table.setColumnWidth(4, 420)

    def refresh(self) -> None:
        cd, qc, o = self.svc.cd, self.svc.cache, self.svc.opts()
        self.svc.run_bg(lambda: lists.craft(cd, qc, detail=True, **o), lambda r, e: (setattr(self, "data", r), self.render()))

    def fill_row(self, i, r) -> None:
        self.table.setItem(i, 2, QTableWidgetItem(r["name"]))
        self.table.setItem(i, 3, QTableWidgetItem(f"×{r['per']}" if r.get("per") else ""))
        st = QTableWidgetItem(self.status_text(r))
        st.setForeground(QColor(MUTED))
        self.table.setItem(i, 4, st)
        b = QPushButton("제작")
        b.setEnabled(r["ok"])
        b.clicked.connect(lambda _=False, r=r: self.craft(r))
        self.table.setCellWidget(i, 5, b)
        g = QPushButton("목표")
        g.clicked.connect(lambda _=False, r=r: self.goal(r))
        self.table.setCellWidget(i, 6, g)

    def craft(self, r) -> None:
        limit = self.svc.cd.knowledge.craft_limit(r["name_raw"])
        n = ask_count(self, "제작", f"{r['name']} — 몇 회 제작할까요? (한 번에 {limit}회까지, 호출 1번에 날개 5)", limit)
        if n and confirm_cost(self, self.svc, "execute_crafting", f"'{r['name']}' {n}회 제작"):
            run_exec(self.svc, "execute_crafting", {"displayName": r["name_raw"], "craftCount": n},
                     f"{r['name']} {n}회 제작", lambda res: self.refresh())

    def goal(self, r) -> None:
        n = ask_count(self, "목표", f"{r['name']} — 새로 몇 개 만들까요? (재료 채집·가공부터 알아서 진행합니다)", 99999)
        if n:
            self.queue.add("제작", r["name_raw"], r["name"], n)


class AlterTab(_ListTab):
    FAV = "alter"
    HEAD = ["☆", "", "이름", "산출", "시설·레벨", "상태", "", "", ""]

    def __init__(self, svc, queue):
        super().__init__(svc, queue)
        self.works_box = QGroupBox("가공 시설")
        self.works = QGridLayout(self.works_box)
        collect_all = QPushButton("완료분 전체 수령")
        collect_all.clicked.connect(self.collect_all)
        self.bar.insertWidget(0, collect_all)
        lay = QVBoxLayout(self)
        lay.addWidget(self.works_box)
        lay.addLayout(self.bar)
        lay.addWidget(self.table, 1)
        self.table.setColumnWidth(5, 330)
        self.room = {}

    def refresh(self) -> None:
        cd, qc, o = self.svc.cd, self.svc.cache, self.svc.opts()
        self.svc.run_bg(lambda: (lists.altering_works(cd, qc, **o), lists.alter(cd, qc, **o)), self._loaded)

    def _loaded(self, r, e) -> None:
        if not r:
            return
        works, self.data = r
        self.render_works(works)
        self.render()

    def render_works(self, w: dict) -> None:
        while self.works.count():
            self.works.takeAt(0).widget().deleteLater()
        if "error" in w:
            self.works.addWidget(QLabel("가공 현황을 불러오지 못했습니다"), 0, 0)
            return
        by = {f["facility"]: f for f in w["facilities"]}
        self.room = {x["facility"]: x for x in w["room"]}
        top = self.svc.cd.rules.altering_facility()["maxLevel"]
        for i, x in enumerate(sorted(w["room"], key=lambda x: x["facility"])):
            f = by.get(x["facility"], {"completed": [], "inProgress": []})
            lv = f"Lv{x['level']}" + ("" if x.get("levelSet") else "?") if x.get("level") else "Lv?"
            text = (f"{x['facility']}  {lv}  {x['used']}/{x['slots']}칸"
                    + (f"  완료 {len(f['completed'])}" if f["completed"] else ""))
            lab = QLabel(text)
            lab.setToolTip("\n".join([f"✔ {c['name']}" for c in f["completed"]]
                                     + [f"· {p['name']} ({(p.get('remainingSec') or 0) // 60}분 남음)" for p in f["inProgress"]])
                           + f"\n칸 수 근거: {x['source']}")
            if x["free"] == 0:
                lab.setStyleSheet(f"color: {STATUS_COLORS['CHECK']}")
            lvbox = QComboBox()
            lvbox.addItem("레벨 모름", 0)
            for n in range(1, top + 1):
                lvbox.addItem(f"Lv{n} ({self.svc.cd.rules.slots_for_level(n)}칸)", n)
            lvbox.setCurrentIndex(x["level"] if x.get("levelSet") and x.get("level") else 0)
            lvbox.setToolTip("게임 화면의 시설 레벨. 정해 두면 칸이 꽉 찼을 때 날개를 쓰기 전에 막습니다")
            lvbox.currentIndexChanged.connect(lambda _=0, fac=x["facility"], box=lvbox: (
                self.svc.cd.knowledge.set_facility_level(fac, box.currentData()), self.refresh()))
            get = QPushButton("수령")
            get.setEnabled(bool(f["completed"]))
            get.clicked.connect(lambda _=False, f=f: self.collect(f))
            r, c = divmod(i, 2)
            self.works.addWidget(lab, r, c * 3)
            self.works.addWidget(lvbox, r, c * 3 + 1)
            self.works.addWidget(get, r, c * 3 + 2)

    def fill_row(self, i, r) -> None:
        self.table.setItem(i, 2, QTableWidgetItem(r["name"]))
        self.table.setItem(i, 3, QTableWidgetItem(f"×{r['per']}" if r.get("per") else ""))
        fac = r.get("facility") or "시설 모름"
        self.table.setItem(i, 4, QTableWidgetItem(fac + (f" Lv.{r['level']}" if r.get("level") else "")
                                                  + (f" · {r['sec'] // 60}분" if r.get("sec") else "")))
        st = QTableWidgetItem("칸 없음" if r.get("no_slot") else self.status_text(r))
        st.setForeground(QColor(MUTED))
        self.table.setItem(i, 5, st)
        room = self.room.get(r.get("facility"))
        full = bool(room and room["free"] == 0) or bool(r.get("no_slot"))
        b = QPushButton("칸 없음" if full else "가공")
        b.setEnabled(r["ok"] and not full)
        b.clicked.connect(lambda _=False, r=r: self.alter(r))
        self.table.setCellWidget(i, 6, b)
        fill = QPushButton("채우기")
        fill.setToolTip("이 시설의 남은 칸만큼 이 가공을 등록합니다")
        fill.setEnabled(bool(r["ok"] and room and room["free"] > 0))
        fill.clicked.connect(lambda _=False, r=r: self.fill(r))
        self.table.setCellWidget(i, 7, fill)
        g = QPushButton("목표")
        g.clicked.connect(lambda _=False, r=r: self.goal(r))
        self.table.setCellWidget(i, 8, g)

    def alter(self, r) -> None:
        if confirm_cost(self, self.svc, "execute_altering", f"'{r['name']}' 가공 1건 등록"):
            run_exec(self.svc, "execute_altering", {"displayName": r["name_raw"]}, f"{r['name']} 가공", lambda res: self.refresh())

    def fill(self, r) -> None:
        """남은 칸만큼 하나씩 등록하고, 매번 큐가 실제로 늘었는지 확인한다 (꽉 찬 뒤의 시도가 날개를 태운다)."""
        room = self.room.get(r.get("facility"))
        if not room or room["free"] <= 0:
            return
        n = room["free"]
        if not confirm_cost(self, self.svc, "execute_altering", f"'{r['name']}' 가공 {n}건 등록 (호출 {n}번)"):
            return
        left = [n]

        def one(res=None):
            if res is not None and not res.ok:
                self.refresh()
                return
            if left[0] <= 0:
                self.refresh()
                return
            left[0] -= 1
            run_exec(self.svc, "execute_altering", {"displayName": r["name_raw"]},
                     f"{r['name']} 가공 ({n - left[0]}/{n})", one)
        one()

    def collect(self, f: dict) -> None:
        if f["completed"]:
            run_exec(self.svc, "complete_altering_work", {"displayName": f["completed"][0]["name"]},
                     f"{f['facility']} 수령", lambda res: self.refresh())

    def collect_all(self) -> None:
        """완료분이 있는 시설마다 한 번씩 (수령은 무료)."""
        cd, qc = self.svc.cd, self.svc.cache

        def work():
            w = lists.altering_works(cd, qc, refresh=True)
            out = []
            for f in w.get("facilities", []):
                if f["completed"]:
                    r = cexec.execute(cd, self.svc.cli, qc, "complete_altering_work", {"displayName": f["completed"][0]["name"]})
                    out.append((f["facility"], r.ok))
            return out
        self.svc.action_state.emit(True, "완료분 전체 수령")
        self.svc.run_bg(work, lambda r, e: (self.svc.action_state.emit(False, ""),
                                            self.svc.notice.emit("ok", f"수령 {sum(1 for _, ok in r or [] if ok)}곳"),
                                            self.refresh()))

    def goal(self, r) -> None:
        n = ask_count(self, "목표", f"{r['name']} — 새로 몇 개 만들까요?", 99999)
        if n:
            self.queue.add("가공", self.svc.cd.knowledge.product_of(r["name_raw"]), r["name"], n)
