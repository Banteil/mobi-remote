"""일일 숙제 탭: 캐릭터·숙제 선택, 시작/중단, 캐릭터 × 숙제 진행 표, 로그."""
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from mabi import paths as mpaths
from mabi import profile as prof
from mabi import tasks
from mabi.runner import RunOptions, Runner, load_config

from .style import MUTED, STATUS_COLORS, STATUS_TEXT

LOGIN = "login"


class RunWorker(QThread):
    event = Signal(dict)
    failed = Signal(str)

    def __init__(self, paths: mpaths.Paths, opts: RunOptions):
        super().__init__()
        self.runner = Runner(paths, on_event=self.event.emit, force_exit=False)
        self.opts = opts

    def run(self) -> None:
        try:
            self.runner.run(self.opts)
        except Exception as e:  # 설정 오류, 게임 창 없음 등
            self.failed.emit(f"{type(e).__name__}: {e}")


class DailyTab(QWidget):
    finished = Signal()

    def __init__(self, paths: mpaths.Paths, bridge):
        super().__init__()
        self.paths = paths
        self.worker: RunWorker | None = None
        self.rows: dict = {}   # slot → 행
        self.cols: dict = {}   # 숙제 id → 열

        # ---- 위: 선택과 버튼 ----
        self.char_box = QGroupBox("캐릭터")
        self.char_layout = QHBoxLayout(self.char_box)
        self.task_box = QGroupBox("숙제")
        self.task_layout = QHBoxLayout(self.task_box)
        self.force = QCheckBox("오늘 끝낸 숙제도 다시")
        self.start_btn = QPushButton("시작")
        self.start_btn.setObjectName("primary")
        self.stop_btn = QPushButton("중단 (F12)")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.status = QLabel("")
        self.status.setObjectName("muted")

        top = QHBoxLayout()
        top.addWidget(self.char_box, 3)
        top.addWidget(self.task_box, 3)
        side = QVBoxLayout()
        side.addWidget(self.force)
        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        side.addLayout(btns)
        top.addLayout(side, 1)

        # ---- 가운데: 진행 표 ----
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setWordWrap(False)

        # ---- 아래: 로그 ----
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        bridge.line.connect(self.append_log)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.log)
        split.setSizes([330, 300])

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.status)
        lay.addWidget(split, 1)
        self.refresh()

    # ---- 화면 구성 ----
    def refresh(self) -> None:
        if self.running():
            return
        cfg = load_config(self.paths)
        self.labels = {t: l for t, (l, _) in tasks.build(cfg).items()}
        self.order = list(cfg["run"]["order"])
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        self.chars = prof.characters(profile)

        for lay in (self.char_layout, self.task_layout):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w:
                    w.deleteLater()
        self.char_checks = {}
        for ch in self.chars:
            cb = QCheckBox(f"{ch['slot']}. {ch['name']}")
            cb.setChecked(True)
            self.char_layout.addWidget(cb)
            self.char_checks[ch["slot"]] = cb
        if not self.chars:
            self.char_layout.addWidget(QLabel("설정 탭에서 캐릭터를 추가하세요"))
        self.task_checks = {}
        for t in self.order:
            cb = QCheckBox(self.labels.get(t, t))
            cb.setChecked(True)
            self.task_layout.addWidget(cb)
            self.task_checks[t] = cb
        self.build_table(self.chars, self.order)
        self.show_today()

    def build_table(self, chars: list, order: list) -> None:
        cols = [LOGIN, *order]
        self.cols = {t: i + 1 for i, t in enumerate(cols)}
        self.rows = {c["slot"]: i for i, c in enumerate(chars)}
        self.table.clear()
        self.table.setColumnCount(len(cols) + 1)
        self.table.setRowCount(len(chars))
        self.table.setHorizontalHeaderLabels(["캐릭터", "접속", *[self.labels.get(t, t) for t in order]])
        for c in chars:
            self.table.setItem(self.rows[c["slot"]], 0, QTableWidgetItem(f"{c['slot'] or '-'}. {c['name']}"))

    def show_today(self) -> None:
        """오늘 기록(state)을 표에 미리 보여 준다."""
        state = prof.DailyState(self.paths.state)
        for slot in self.rows:
            for t in self.cols:
                v = state.get(slot, t)
                if v:
                    st = "DONE" if v == "done" else v.split(":", 1)[0]
                    self.set_cell(slot, t, st, v)

    def set_cell(self, slot, task: str, status: str, tip: str = "") -> None:
        r, c = self.rows.get(slot), self.cols.get(task)
        if r is None or c is None:
            return
        item = QTableWidgetItem(STATUS_TEXT.get(status, status))
        item.setTextAlignment(Qt.AlignCenter)
        item.setForeground(QColor(STATUS_COLORS.get(status, MUTED)))
        item.setToolTip(tip)
        self.table.setItem(r, c, item)

    def append_log(self, level: str, text: str) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor({"WARNING": STATUS_COLORS["CHECK"], "ERROR": STATUS_COLORS["FAIL"]}.get(level, "#d0d0d4")))
        cur = self.log.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text + "\n", fmt)
        self.log.setTextCursor(cur)
        self.log.ensureCursorVisible()

    # ---- 실행 ----
    def running(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def start(self) -> None:
        chars = [s for s, cb in self.char_checks.items() if cb.isChecked()]
        only = [t for t, cb in self.task_checks.items() if cb.isChecked()]
        if not chars or not only:
            self.status.setText("캐릭터와 숙제를 하나 이상 고르세요")
            return
        opts = RunOptions(chars=chars, only=None if only == self.order else only, force=self.force.isChecked(),
                          extra={"from": "gui"})
        sel = [c for c in self.chars if c["slot"] in chars]
        self.build_table(sel, only)
        self.show_today()
        self.worker = RunWorker(self.paths, opts)
        self.worker.event.connect(self.on_event)
        self.worker.failed.connect(lambda m: self.status.setText(f"실행 실패: {m}"))
        self.worker.finished.connect(self.on_finished)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("실행 중")
        self.worker.start()

    def stop(self) -> None:
        if self.worker:
            self.worker.runner.stop()
            self.status.setText("중단 요청 — 지금 동작이 끝나면 멈춥니다")

    def wait(self, ms: int) -> None:
        if self.worker:
            self.worker.wait(ms)

    def on_event(self, e: dict) -> None:
        t = e["type"]
        if t == "task_start":
            self.set_cell(e["slot"], e["task"], "RUN", e["label"])
            self.status.setText(f"진행 중: {e['label']}")
        elif t == "task_end":
            self.set_cell(e["slot"], e["task"], e["status"], f"{e['summary']} ({e['seconds']}초)")
        elif t == "done":
            bad = [r for r in e["results"] if r[1] not in ("OK", "DONE")]
            self.status.setText("완료" if not bad else f"완료 — 확인 필요 {len(bad)}건")

    def on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.finished.emit()
