"""기록 탭: 실행 목록 → 캐릭터·숙제별 결과와 경고 → 스크린샷. 진단 파일 내보내기."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from mabi import paths as mpaths
from mabi import report_tools as rt
from mabi.tasks import TASKS

LABELS = {"login": "접속", **{t: label for t, (label, _) in TASKS.items()}}

from .style import MUTED, STATUS_COLORS, STATUS_TEXT


def _shot_of(text: str) -> str | None:
    m = rt.SHOT_RE.search(text or "")
    return m.group(0) if m else None


class HistoryTab(QWidget):
    def __init__(self, paths: mpaths.Paths):
        super().__init__()
        self.paths = paths
        rt.use(paths)

        self.runs = QListWidget()
        self.runs.currentItemChanged.connect(self.show_run)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["항목", "결과", "시간", "내용"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 60)
        self.tree.currentItemChanged.connect(self.show_shot)
        self.tree.itemDoubleClicked.connect(self.open_shot)
        self.shot = QLabel("")
        self.shot.setAlignment(Qt.AlignCenter)
        self.shot.setMinimumHeight(220)
        self.env = QLabel("")
        self.env.setObjectName("muted")

        self.anon = QCheckBox("캐릭터 이름 숨기기")
        export = QPushButton("진단 파일 내보내기")
        export.clicked.connect(self.export)
        open_dir = QPushButton("로그 폴더 열기")
        open_dir.clicked.connect(lambda: os.startfile(self.paths.logs))
        self.msg = QLabel("")
        self.msg.setObjectName("muted")

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.tree)
        right.addWidget(self.shot)
        right.setSizes([480, 220])
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.runs)
        rbox = QWidget()
        rl = QVBoxLayout(rbox)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.env)
        rl.addWidget(right, 1)
        split.addWidget(rbox)
        split.setSizes([260, 900])

        bar = QHBoxLayout()
        bar.addWidget(open_dir)
        bar.addStretch(1)
        bar.addWidget(self.msg)
        bar.addWidget(self.anon)
        bar.addWidget(export)
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)
        lay.addLayout(bar)
        self.refresh()

    def refresh(self) -> None:
        self.data = list(reversed(rt.load_runs(None)))
        self.runs.clear()
        for r in self.data:
            tasks = [t for c in r["characters"] for t in c["tasks"]]
            bad = sum(1 for t in tasks if t.get("status") not in ("OK", "DONE"))
            names = ", ".join(c["name"] or "현재" for c in r["characters"])
            item = QListWidgetItem(f"{r['started'][5:16].replace('T', ' ')}  {names}\n"
                                   f"  {len(tasks) - bad}/{len(tasks)} 성공" + ("" if r.get("finished") else "  (중단됨)"))
            if bad:
                item.setForeground(QColor(STATUS_COLORS["CHECK"]))
            self.runs.addItem(item)
        if self.data:
            self.runs.setCurrentRow(0)

    def show_run(self, cur, _prev=None) -> None:
        self.tree.clear()
        self.shot.clear()
        row = self.runs.row(cur) if cur else -1
        if row < 0:
            return
        r = self.data[row]
        env = r.get("env", {})
        self.env.setText(f"v{r.get('version')}  창 {env.get('client_size')}  관리자 {env.get('admin')}  CLI {env.get('cli')}")
        for c in r["characters"]:
            ci = QTreeWidgetItem([f"{c['slot'] or '-'}. {c['name'] or '현재 캐릭터'}"])
            self.tree.addTopLevelItem(ci)
            for t in c["tasks"]:
                st = t.get("status") or "STOP"
                b, a = t.get("before") or {}, t.get("after") or {}
                delta = "  ".join(f"{k} {b.get(k)}→{a.get(k)}" for k in ("silver", "tribute")
                                  if b.get(k) is not None and b.get(k) != a.get(k))
                ti = QTreeWidgetItem([LABELS.get(t["id"], t["id"]), STATUS_TEXT.get(st, st), f"{t.get('seconds') or 0}s",
                                      (t.get("summary") or "") + (f"   ({delta})" if delta else "")])
                ti.setForeground(1, QColor(STATUS_COLORS.get(st, MUTED)))
                ti.setData(0, Qt.UserRole, _shot_of(t.get("summary")))
                for e in t.get("events", []):
                    ei = QTreeWidgetItem(["", e["kind"], e["time"], e["message"]])
                    ei.setForeground(3, QColor(MUTED))
                    ei.setData(0, Qt.UserRole, _shot_of(e["message"]))
                    ti.addChild(ei)
                ci.addChild(ti)
            ci.setExpanded(True)

    def _shot_path(self, item):
        name = item.data(0, Qt.UserRole) if item else None
        p = self.paths.shots / name if name else None
        return p if p and p.exists() else None

    def show_shot(self, cur, _prev=None) -> None:
        p = self._shot_path(cur)
        if not p:
            self.shot.clear()
            return
        pix = QPixmap(str(p))
        self.shot.setPixmap(pix.scaled(self.shot.width(), self.shot.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def open_shot(self, item, _col) -> None:
        p = self._shot_path(item)
        if p:
            os.startfile(p)

    def export(self) -> None:
        runs = rt.load_runs(None)[-5:]
        if not runs:
            self.msg.setText("기록이 없습니다")
            return
        out = rt.export(runs, self.anon.isChecked())
        self.msg.setText(f"저장: {out.name}")
        os.startfile(out.parent)
