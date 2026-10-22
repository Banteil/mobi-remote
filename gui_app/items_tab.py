"""소지품: 검색 · 분류 · 보관처 · 정렬. 보관처별로 칸을 나눈다 (무게는 가방만 차지한다).

이름에 색 태그(★ 등급)가 있으면 색을 살려 그린다. 표에는 태그를 벗긴 이름, 원문은 툴팁에.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mabi import richtext

from .services import Services

WHERE = [("전체", None), ("가방", "bag"), ("캐릭터 창고", "char"), ("계정 창고", "acc"), ("창고에만", "store_only")]
SORTS = [("많은 순", lambda e: -e["total"]), ("이름 순", lambda e: e["name"]), ("분류 순", lambda e: (e["category"] or "", e["name"]))]


class _NumItem(QTableWidgetItem):
    """숫자 열이 글자 순(10 < 9)이 아니라 숫자 순으로 정렬되게."""
    def __lt__(self, other):
        return (self.data(Qt.UserRole) or 0) < (other.data(Qt.UserRole) or 0)


class ItemsTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.data = None
        self.search = QLineEdit()
        self.search.setPlaceholderText("검색")
        self.search.textChanged.connect(self.render)
        self.cat = QComboBox()
        self.cat.currentIndexChanged.connect(self.render)
        self.where = QComboBox()
        for label, key in WHERE:
            self.where.addItem(label, key)
        self.where.currentIndexChanged.connect(self.render)
        self.sort = QComboBox()
        for label, _ in SORTS:
            self.sort.addItem(label)
        self.sort.currentIndexChanged.connect(self.render)
        self.sums = QLabel("")
        self.sums.setObjectName("muted")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["이름", "분류", "합계", "가방", "캐릭터 창고", "계정 창고"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 2)
        bar.addWidget(self.cat, 1)
        bar.addWidget(self.where, 1)
        bar.addWidget(self.sort, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.sums)
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        q, o = self.svc.query, self.svc.opts()
        self.svc.run_bg(lambda: q.items(**o), self._loaded)

    def _loaded(self, r, err) -> None:
        if not r or "error" in r:
            self.sums.setText("소지품을 불러오지 못했습니다")
            return
        self.data = r
        cur = self.cat.currentText()
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem("모든 분류")
        self.cat.addItems(r["categories"])  # 필터 전 전체 기준이라 고른 분류가 메뉴에서 사라지지 않는다
        if cur:
            self.cat.setCurrentText(cur)
        self.cat.blockSignals(False)
        self.render()

    def render(self) -> None:
        if not self.data:
            return
        from mabi.query import matches
        s, cat, where = self.search.text(), self.cat.currentText(), self.where.currentData()
        rows = [e for e in self.data["items"] if matches(e["name_raw"], s)
                and (self.cat.currentIndex() <= 0 or e["category"] == cat)
                and (where is None or (where == "store_only" and e["at"]["bag"] == 0)
                     or (where != "store_only" and e["at"][where] > 0))]
        rows.sort(key=SORTS[self.sort.currentIndex()][1])
        tot = {k: sum(e["at"][k] for e in rows) for k in ("bag", "char", "acc")}
        self.sums.setText(f"{len(rows)}종 · 가방 {tot['bag']:,} · 캐릭터 창고 {tot['char']:,} · 계정 창고 {tot['acc']:,}")
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            name = QTableWidgetItem(("🔒 " if e["locked"] else "") + e["name"])
            segs = [c for _, c in richtext.segments(e["name_raw"]) if c]
            if segs:  # 등급 색 (QTableWidgetItem 은 부분 색을 못 그려 첫 색으로 칠한다)
                name.setForeground(QColor(segs[0]))
                name.setToolTip(e["name_raw"])
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem(e["category"] or ""))
            for c, v in enumerate([e["total"], e["at"]["bag"], e["at"]["char"], e["at"]["acc"]], start=2):
                it = _NumItem(f"{v:,}" if v else "·")
                it.setData(Qt.UserRole, v)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, it)
