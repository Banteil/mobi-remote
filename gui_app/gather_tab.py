"""채집: 목록(도구 보유만), 즐겨찾기, 채집 실행 (1회 호출 = 최대 100개, 정령의 날개 5).

채집 장소는 커넥터가 가장 가까운 곳으로 알아서 고른다. 낚시 전용 품목은 자동 낚시를 켜고 바로 돌아오며,
그만두려면 상단 '정지'(stop_action). 소모품(빈 병 등)이 중간에 떨어지거나 공격받으면 멈춘다.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from mabi.query import matches

from .services import Services

FAV = "gather"


def confirm_cost(parent, svc: Services, command: str, what: str) -> bool:
    """비용이 드는 명령 전에 '소모 N / 보유 → 실행 후'를 묻는다. 모자라면 실행하지 않는다."""
    cost = svc.cli.cost_of(command)
    if not cost:
        return True
    have = svc.query.wings(refresh=True, **svc.opts()) if cost["currency"] == "정령의 날개" else None
    if have is not None and have < cost["amount"]:
        QMessageBox.warning(parent, "재화 부족", f"{cost['currency']} {cost['amount']}개가 필요한데 {have}개 있습니다.")
        return False
    tail = f"\n보유 {have:,} → 실행 후 {have - cost['amount']:,}" if have is not None else ""
    return QMessageBox.question(parent, "실행 확인", f"{what}\n\n{cost['currency']} {cost['amount']} 소모{tail}") == QMessageBox.Yes


class GatherTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.data = None
        self.search = QLineEdit()
        self.search.setPlaceholderText("검색")
        self.search.textChanged.connect(self.render)
        self.only_ok = QCheckBox("도구 있는 것만")
        self.only_ok.setChecked(True)
        self.only_ok.toggled.connect(self.render)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["☆", "이름", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.cellClicked.connect(self._cell)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.only_ok)
        bar.addWidget(self.count)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        q, o = self.svc.query, self.svc.opts()
        self.svc.run_bg(lambda: q.gather(**o), lambda r, e: (setattr(self, "data", r), self.render()))

    def render(self) -> None:
        if not self.data or "error" in self.data:
            return
        favs = self.svc.favorites.get(FAV)
        rows = [r for r in self.data["items"] if matches(r["name_raw"], self.search.text())
                and (not self.only_ok.isChecked() or r["tool"])]
        rows.sort(key=lambda r: (r["name_raw"] not in favs,))  # 즐겨찾기 먼저, 그 안은 게임 순서
        self.count.setText(f"{len(rows)} / {self.data['total']}종")
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            star = QTableWidgetItem("★" if r["name_raw"] in favs else "☆")
            star.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, star)
            name = QTableWidgetItem(r["name"] + ("" if r["tool"] else "   (도구 없음)"))
            self.table.setItem(i, 1, name)
            b = QPushButton("채집")
            b.setEnabled(r["tool"])
            b.clicked.connect(lambda _=False, r=r: self.gather(r))
            self.table.setCellWidget(i, 2, b)

    def _cell(self, row: int, col: int) -> None:
        if col == 0:
            self.svc.favorites.toggle(FAV, self.rows[row]["name_raw"])
            self.render()

    def gather(self, r: dict) -> None:
        if not confirm_cost(self, self.svc, "execute_gathering", f"'{r['name']}' 채집 (최대 100개)"):
            return

        def done(res):
            if res is not None and res.ok and isinstance(res.data, dict) and res.data.get("gained") is not None:
                self.svc.notice.emit("ok", f"{r['name']} {res.data['gained']}/{res.data.get('target')}개 채집")
        self.svc.action("execute_gathering", {"displayName": r["name_raw"]}, done, f"{r['name']} 채집")
