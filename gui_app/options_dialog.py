"""옵션 창: 커넥터 위치, 호환성 검사, 명령 직접 호출, 호출 기록, 동작 설정."""
import json
import os

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from mabi.connector import ACTION_COMMANDS, EXE_NAME

from .services import Services
from .style import STATUS_COLORS

LEVEL_COLOR = {"ok": STATUS_COLORS["OK"], "info": STATUS_COLORS["OK"], "warn": STATUS_COLORS["CHECK"],
               "error": STATUS_COLORS["FAIL"]}


class OptionsDialog(QDialog):
    def __init__(self, svc: Services, parent=None):
        super().__init__(parent)
        self.svc = svc
        self.setWindowTitle("옵션")
        self.resize(900, 640)
        tabs = QTabWidget()
        tabs.addTab(self._connector_tab(), "커넥터")
        tabs.addTab(self._compat_tab(), "호환성")
        tabs.addTab(self._call_tab(), "명령 직접 호출")
        tabs.addTab(self._log_tab(), "호출 기록")
        tabs.addTab(self._behaviour_tab(), "동작")
        QVBoxLayout(self).addWidget(tabs)

    # ---- 커넥터 ----
    def _connector_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.loc = QLabel("")
        self.loc.setWordWrap(True)
        self.path = QLineEdit(self.svc.settings.get("cli_path", ""))
        self.path.setPlaceholderText("비우면 자동으로 찾습니다")
        pick = QPushButton("직접 지정")
        pick.clicked.connect(self._pick)
        again = QPushButton("다시 찾기")
        again.clicked.connect(self._relocate)
        self.cands = QPlainTextEdit()
        self.cands.setReadOnly(True)
        h = QHBoxLayout()
        h.addWidget(self.path, 1)
        h.addWidget(pick)
        h.addWidget(again)
        f.addRow("지금 쓰는 위치", self.loc)
        f.addRow("직접 지정", h)
        f.addRow("찾아본 위치", self.cands)
        self._show_loc()
        return w

    def _show_loc(self) -> None:
        loc = self.svc.cli.locate()
        self.loc.setText(f"{loc.path}\n({loc.source})" if loc.found else "찾지 못했습니다 — 마비노기 모바일이 이 PC 에 설치되어 있는지 확인하세요")
        self.svc.run_bg(self.svc.cli.candidate_report, lambda r, e: self.cands.setPlainText(
            "\n".join(f"{'✔' if ok else '·'} {p}   [{s}]" for p, s, ok in (r or [])[:300])))

    def _pick(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "커넥터 선택", "", f"{EXE_NAME} ({EXE_NAME})")
        if f:
            if os.path.basename(f).lower() != EXE_NAME.lower():
                self.loc.setText(f"{EXE_NAME} 파일을 골라 주세요")
                return
            self.path.setText(f)
            self._relocate()

    def _relocate(self) -> None:
        self.svc.save_settings(cli_path=self.path.text().strip())
        self.svc.cli.locate(force=True)
        self._show_loc()
        self.svc.check_status()

    # ---- 호환성 ----
    def _compat_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.compat_head = QLabel("")
        self.compat_out = QPlainTextEdit()
        self.compat_out.setReadOnly(True)
        run, save = QPushButton("다시 검사"), QPushButton("지금 상태를 기준선으로 저장")
        run.clicked.connect(self._compat_run)
        save.clicked.connect(self._compat_save)
        h = QHBoxLayout()
        h.addWidget(run)
        h.addWidget(save)
        h.addStretch(1)
        v.addLayout(h)
        v.addWidget(self.compat_head)
        v.addWidget(self.compat_out, 1)
        hint = QLabel("게임 업데이트 뒤 정상 동작을 확인했으면 기준선을 저장하세요. 다음부터 바뀐 점을 알려 줍니다.")
        hint.setObjectName("muted")
        v.addWidget(hint)
        self._compat_run()
        return w

    def _compat_run(self) -> None:
        self.compat_head.setText("검사 중…")
        self.svc.run_bg(lambda: self.svc.compat.check(refresh=self.svc.online is not False), self._compat_show)

    def _compat_show(self, r, e) -> None:
        if not r:
            self.compat_head.setText(f"검사 실패: {e}")
            return
        cli = r["current"]["cli"]
        self.compat_head.setText(f"커넥터 {cli.get('productVersion')} — "
                                 + {"ok": "기준선과 같습니다", "info": "참고할 변경", "warn": "확인이 필요한 변경",
                                    "error": "기능이 깨질 수 있는 변경"}[r["level"]])
        self.compat_head.setStyleSheet(f"color: {LEVEL_COLOR[r['level']]}")
        self.compat_out.setPlainText("\n\n".join(f"[{c['level']}] {c['title']}\n{c['detail']}" for c in r["changes"]))

    def _compat_save(self) -> None:
        self.svc.run_bg(lambda: self.svc.compat.save(note="옵션 창에서 저장"), lambda r, e: self._compat_run())

    # ---- 명령 직접 호출 ----
    def _call_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.cmd = QComboBox()
        costs = self.svc.cli.costs()
        for c in sorted(self.svc.cli.capabilities(), key=lambda c: c["Command"]):
            n = c["Command"]
            tag = f"  [날개 {costs[n]['amount']}]" if n in costs else ("  [실행]" if n in ACTION_COMMANDS else "")
            self.cmd.addItem(n + tag, c)
        self.cmd.currentIndexChanged.connect(self._fill_example)
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setObjectName("muted")
        self.body = QLineEdit()
        self.body.setPlaceholderText("본문 (JSON 또는 평문, 없으면 비움)")
        go = QPushButton("호출")
        go.clicked.connect(self._call)
        self.resp = QPlainTextEdit()
        self.resp.setReadOnly(True)
        h = QHBoxLayout()
        h.addWidget(self.cmd, 1)
        h.addWidget(go)
        v.addLayout(h)
        v.addWidget(self.desc)
        v.addWidget(self.body)
        v.addWidget(self.resp, 1)
        self._fill_example()
        return w

    def _fill_example(self) -> None:
        c = self.cmd.currentData() or {}
        self.body.setText(c.get("BodyExample") or "")
        self.desc.setText((c.get("Description") or "") + "\n" + (c.get("Note") or ""))

    def _call(self) -> None:
        c = self.cmd.currentData() or {}
        text = self.body.text().strip()
        try:
            body = json.loads(text) if text.startswith(("{", "[")) else (text or None)
        except ValueError:
            body = text
        name = c.get("Command")
        if not name:
            return
        if name in ACTION_COMMANDS:
            self.svc.action(name, body, lambda r: self._show_resp(r), name)
        else:
            self.svc.run_bg(lambda: self.svc.cli.run(name, body), lambda r, e: self._show_resp(r))

    def _show_resp(self, r) -> None:
        if r is None:
            return
        self.resp.setPlainText(f"ok={r.ok} code={r.code} {r.ms}ms\n" + json.dumps(r.data, ensure_ascii=False, indent=2)[:200000])

    # ---- 호출 기록 ----
    def _log_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.calls = QPlainTextEdit()
        self.calls.setReadOnly(True)
        refresh, open_dir = QPushButton("새로고침"), QPushButton("로그 폴더 열기")
        refresh.clicked.connect(self._show_calls)
        open_dir.clicked.connect(lambda: os.startfile(self.svc.paths.logs))
        h = QHBoxLayout()
        h.addWidget(refresh)
        h.addWidget(open_dir)
        h.addStretch(1)
        v.addLayout(h)
        v.addWidget(self.calls, 1)
        self._show_calls()
        return w

    def _show_calls(self) -> None:
        self.calls.setPlainText("\n".join(self.svc.calllog.tail(300)))
        self.calls.verticalScrollBar().setValue(self.calls.verticalScrollBar().maximum())

    # ---- 동작 ----
    def _behaviour_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        tray = QCheckBox("창을 닫으면 트레이로 숨기기 (종료는 트레이 메뉴에서)")
        tray.setChecked(bool(self.svc.settings.get("close_to_tray")))
        tray.toggled.connect(lambda on: self.svc.save_settings(close_to_tray=on))
        v.addWidget(tray)
        v.addStretch(1)
        return w
