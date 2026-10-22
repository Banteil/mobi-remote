"""미션: 일일·주간 (진행 중 / 받을 보상 / 끝) + 퀘스트 트래커.

커넥터에는 보상 받기 명령이 없다. 받을 보상은 일일 숙제의 일일 미션 단계가 화면 조작으로 받는다.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .services import Services
from .style import MUTED, STATUS_COLORS

STATE = {"open": ("·", "진행 중", None), "unclaimed": ("◆", "보상 받기 전", STATUS_COLORS["CHECK"]),
         "done": ("✔", "끝", STATUS_COLORS["DONE"])}


class MissionsTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.only_open = QCheckBox("진행 중·받을 보상만")
        self.only_open.setChecked(svc.settings.get("missions_only_open", False))
        self.only_open.toggled.connect(lambda v: (svc.save_settings(missions_only_open=v), self.refresh()))
        self.boxes = {}
        cols = QHBoxLayout()
        for key, title in (("daily", "일일 미션"), ("weekly", "주간 미션")):
            box = QGroupBox(title)
            head = QLabel("")
            head.setObjectName("muted")
            tree = QTreeWidget()
            tree.setHeaderLabels(["", "미션", "진행"])
            tree.setRootIsDecorated(False)
            tree.setColumnWidth(0, 30)
            tree.setColumnWidth(1, 330)
            v = QVBoxLayout(box)
            v.addWidget(head)
            v.addWidget(tree)
            cols.addWidget(box)
            self.boxes[key] = (head, tree)
        qbox = QGroupBox("퀘스트 트래커")
        self.quests = QTreeWidget()
        self.quests.setHeaderLabels(["퀘스트 · 목표", "진행"])
        self.quests.setColumnWidth(0, 520)
        qhint = QLabel("게임 퀘스트 트래커에서 지금 보고 있는 탭의 것만 옵니다. 비어 있어도 정상입니다.")
        qhint.setObjectName("muted")
        qv = QVBoxLayout(qbox)
        qv.addWidget(qhint)
        qv.addWidget(self.quests)

        lay = QVBoxLayout(self)
        lay.addWidget(self.only_open)
        lay.addLayout(cols, 3)
        lay.addWidget(qbox, 2)
        svc.tick.connect(lambda: self.isVisible() and self.refresh())

    def refresh(self) -> None:
        q, o, only = self.svc.query, self.svc.opts(), self.only_open.isChecked()

        def work():
            return q.daily(only_open=only, **o), q.weekly(only_open=only, **o), q.quests(**o)
        self.svc.run_bg(work, self._show)

    def _show(self, r, err) -> None:
        if not r:
            return
        for key, data in zip(("daily", "weekly"), r[:2]):
            head, tree = self.boxes[key]
            tree.clear()
            if "error" in data:
                head.setText("불러오지 못했습니다")
                continue
            parts = [f"{data['total']}개 중 진행 중 {data['open']}"]
            if data["unclaimed"]:
                parts.append(f"받을 보상 {data['unclaimed']}")
            head.setText(" · ".join(parts))
            for m in data["items"]:
                mark, tip, color = STATE[m["state"]]
                it = QTreeWidgetItem([mark, f"{m['title']} — {m['desc']}", f"{m['cur']}/{m['goal']}"])
                it.setToolTip(0, tip)
                if color:
                    for c in range(3):
                        it.setForeground(c, QColor(color))
                tree.addTopLevelItem(it)
        self.quests.clear()
        qs = r[2]
        for qd in qs.get("items", []):
            top = QTreeWidgetItem([qd["title"] + (f"   ({qd['source']})" if qd.get("source") else ""), ""])
            for ob in qd["objectives"]:
                ch = QTreeWidgetItem([("✔ " if ob["done"] else "· ") + ob["desc"], ob["progress"] or ""])
                if ob["done"]:
                    ch.setForeground(0, QColor(MUTED))
                top.addChild(ch)
            self.quests.addTopLevelItem(top)
            top.setExpanded(True)
