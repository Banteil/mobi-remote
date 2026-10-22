"""설정 탭: 캐릭터(슬롯), 은동전 배분(기본값 + 캐릭터별), 가방 무게 기준, 저장 경로.

캐릭터는 profile.json, 숙제 설정은 config.toml 에 저장한다. config.toml 은 주석을 살려야 해서 tomlkit 으로 고친다.
"""
import os

import tomlkit
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from mabi import paths as mpaths
from mabi import profile as prof

INHERIT = "(기본값)"


class SettingsTab(QWidget):
    profile_changed = Signal()

    def __init__(self, paths: mpaths.Paths):
        super().__init__()
        self.paths = paths

        # ---- 캐릭터 ----
        self.chars = QTableWidget(0, 5)
        self.chars.setHorizontalHeaderLabels(["슬롯", "이름", "사냥터 횟수", "던전", "층"])
        self.chars.verticalHeader().setVisible(False)
        self.chars.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        add = QPushButton("캐릭터 추가")
        add.clicked.connect(lambda: self.add_row({"slot": self.chars.rowCount() + 1, "name": ""}, {}))
        remove = QPushButton("선택 삭제")
        remove.clicked.connect(lambda: self.chars.removeRow(self.chars.currentRow()))
        hint = QLabel("슬롯 = 캐릭터 선택 화면(캐릭터 생성 순)의 순서. 왼쪽 위부터 1, 2, 3, 4 / 다음 줄 5, 6 …")
        hint.setObjectName("muted")
        cbox = QGroupBox("캐릭터")
        cl = QVBoxLayout(cbox)
        cl.addWidget(hint)
        cl.addWidget(self.chars)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        cl.addLayout(row)

        # ---- 은동전 기본값 ----
        self.field_runs = QSpinBox()
        self.field_runs.setRange(0, 5)
        self.dungeon = QComboBox()
        self.floor = QSpinBox()
        self.floor.setRange(1, 2)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0.5, 1.0)
        self.weight.setSingleStep(0.01)
        sbox = QGroupBox("은동전 기본값")
        sf = QFormLayout(sbox)
        sf.addRow("사냥터 횟수", self.field_runs)
        sf.addRow("남은 은동전 던전", self.dungeon)
        sf.addRow("던전 층 (3구역)", self.floor)
        sf.addRow("가방 무게 한도 (비율)", self.weight)

        # ---- 경로 ----
        self.path_edits = {}
        pbox = QGroupBox("저장 경로 (비우면 기본값, 다음 실행부터 적용)")
        pf = QFormLayout(pbox)
        for key, label in (("data", "데이터 폴더"), ("logs", "로그 폴더"), ("shots", "스크린샷 폴더")):
            edit = QLineEdit()
            browse = QPushButton("찾기")
            browse.clicked.connect(lambda _=False, e=edit: self._browse(e))
            h = QHBoxLayout()
            h.addWidget(edit, 1)
            h.addWidget(browse)
            pf.addRow(label, h)
            self.path_edits[key] = edit
        cur = QLabel(f"지금: {paths.data}")
        cur.setObjectName("muted")
        pf.addRow("", cur)

        save = QPushButton("저장")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        self.msg = QLabel("")
        self.msg.setObjectName("muted")
        open_cfg = QPushButton("config.toml 열기")
        open_cfg.clicked.connect(lambda: os.startfile(self.paths.config))

        right = QVBoxLayout()
        right.addWidget(sbox)
        right.addWidget(pbox)
        right.addStretch(1)
        body = QHBoxLayout()
        body.addWidget(cbox, 3)
        body.addLayout(right, 2)
        bar = QHBoxLayout()
        bar.addWidget(open_cfg)
        bar.addStretch(1)
        bar.addWidget(self.msg)
        bar.addWidget(save)
        lay = QVBoxLayout(self)
        lay.addLayout(body, 1)
        lay.addLayout(bar)
        self.refresh()

    def _browse(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "폴더 선택", edit.text() or str(self.paths.data))
        if d:
            edit.setText(d)

    def _doc(self):
        return tomlkit.parse(self.paths.config.read_text(encoding="utf-8"))

    def _dungeons(self, doc) -> list[str]:
        return [n for n, p in doc["places"].items() if int(p["index"]) < 2]

    def refresh(self) -> None:
        doc = self._doc()
        s = doc["silver"]
        self.dungeon_names = self._dungeons(doc)
        self.dungeon.clear()
        self.dungeon.addItems(self.dungeon_names)
        self.dungeon.setCurrentText(str(s["dungeon"]))
        self.field_runs.setValue(int(s["field_runs"]))
        self.floor.setValue(int(s["floor"]))
        self.weight.setValue(float(doc["run"].get("max_weight_ratio", 1.0)))
        by_slot = s.get("by_slot", {})
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        self.chars.setRowCount(0)
        for ch in prof.characters(profile):
            self.add_row(ch, by_slot.get(str(ch["slot"]), {}))
        over = {}
        try:
            import json
            f = mpaths.default_data_dir() / "paths.json"
            over = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except ValueError:
            pass
        for k, e in self.path_edits.items():
            e.setText(over.get(k, ""))

    def add_row(self, ch: dict, over: dict) -> None:
        r = self.chars.rowCount()
        self.chars.insertRow(r)
        slot = QSpinBox()
        slot.setRange(1, 8)
        slot.setValue(int(ch["slot"]))
        self.chars.setCellWidget(r, 0, slot)
        self.chars.setItem(r, 1, QTableWidgetItem(ch.get("name", "")))
        fr = QComboBox()
        fr.addItems([INHERIT, "0", "1", "2", "3", "4", "5"])
        fr.setCurrentText(str(over["field_runs"]) if "field_runs" in over else INHERIT)
        self.chars.setCellWidget(r, 2, fr)
        dg = QComboBox()
        dg.addItems([INHERIT, "(던전 안 감)", *self.dungeon_names])
        dg.setCurrentText(INHERIT if "dungeon" not in over else (over["dungeon"] or "(던전 안 감)"))
        self.chars.setCellWidget(r, 3, dg)
        fl = QComboBox()
        fl.addItems([INHERIT, "1", "2"])
        fl.setCurrentText(str(over["floor"]) if "floor" in over else INHERIT)
        self.chars.setCellWidget(r, 4, fl)

    def save(self) -> None:
        # 캐릭터 → profile.json
        slots, names, overs = [], {}, {}
        for r in range(self.chars.rowCount()):
            slot = self.chars.cellWidget(r, 0).value()
            if slot in slots:
                self.msg.setText(f"슬롯 {slot} 이 두 번 있습니다")
                return
            slots.append(slot)
            item = self.chars.item(r, 1)
            names[str(slot)] = (item.text().strip() if item else "") or f"슬롯 {slot}"
            o = {}
            fr, dg, fl = (self.chars.cellWidget(r, c).currentText() for c in (2, 3, 4))
            if fr != INHERIT:
                o["field_runs"] = int(fr)
            if dg != INHERIT:
                o["dungeon"] = "" if dg == "(던전 안 감)" else dg
            if fl != INHERIT:
                o["floor"] = int(fl)
            if o:
                overs[str(slot)] = o
        prof.save_profile(self.paths.profile, {"slots": sorted(slots), "names": names})

        # 은동전·무게 → config.toml (주석 유지)
        doc = self._doc()
        s = doc["silver"]
        s["field_runs"] = self.field_runs.value()
        s["dungeon"] = self.dungeon.currentText()
        s["floor"] = self.floor.value()
        doc["run"]["max_weight_ratio"] = round(self.weight.value(), 2)
        # 기존 표를 지우고 새로 만들면 표에 붙은 주석(다음 섹션 머리 주석 포함)이 같이 사라지므로 제자리에서 고친다
        if "by_slot" not in s:
            s["by_slot"] = tomlkit.table(is_super_table=True)
        by = s["by_slot"]
        for slot in [k for k in by if k not in overs]:
            del by[slot]
        for slot, o in sorted(overs.items(), key=lambda kv: int(kv[0])):
            if slot not in by:
                by[slot] = tomlkit.table()
            t = by[slot]
            for k in [k for k in t if k not in o]:
                del t[k]
            for k, v in o.items():
                t[k] = v
        self.paths.config.write_text(tomlkit.dumps(doc), encoding="utf-8")

        mpaths.save_overrides(**{k: e.text().strip() for k, e in self.path_edits.items()})
        self.msg.setText("저장했습니다")
        self.profile_changed.emit()
