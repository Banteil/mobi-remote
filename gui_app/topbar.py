"""상단바: 연결 상태, 레벨·직업, 타이틀·서버, 정령의 날개, 가방 무게, 갱신 간격, 새로고침."""
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from . import style
from .services import Services

REASON_TEXT = {"game_off": "게임 꺼짐", "option_off": "AI 커넥터 꺼짐 (게임 설정)", "no_connector": "커넥터 없음",
               "error": "확인 실패"}
INTERVALS = [("자동 갱신 끔", 0), ("3초", 3), ("5초", 5), ("10초", 10), ("30초", 30)]


class TopBar(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.conn = QLabel("연결 확인 중")
        self.who = QLabel("")
        self.title = QLabel("")
        self.title.setObjectName("muted")
        self.wings = QLabel("")
        self.weight = QLabel("")
        self.interval = QComboBox()
        for label, sec in INTERVALS:
            self.interval.addItem(label, sec)
        cur = svc.settings.get("refresh_interval", 10)
        self.interval.setCurrentIndex(next((i for i, (_, s) in enumerate(INTERVALS) if s == cur), 3))
        self.interval.currentIndexChanged.connect(self._interval)
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(self.refresh_all)
        stop = QPushButton("정지")
        stop.setToolTip("게임에서 지금 하는 동작(연주·앉기·자동 진행 등)을 멈춥니다")
        stop.clicked.connect(lambda: svc.action("stop_action", None, label="정지"))
        opts = QPushButton("옵션")
        opts.clicked.connect(self.open_options)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        for w in (self.conn, self.who, self.title):
            lay.addWidget(w)
        lay.addStretch(1)
        for w in (self.wings, self.weight, self.interval, stop, refresh, opts):
            lay.addWidget(w)

        svc.connection.connect(self.on_connection)
        svc.tick.connect(self.refresh)

    def open_options(self) -> None:
        from .options_dialog import OptionsDialog
        OptionsDialog(self.svc, self.window()).exec()

    def _interval(self) -> None:
        sec = self.interval.currentData()
        self.svc.set_interval(sec)
        self.svc.save_settings(refresh_interval=sec)

    def on_connection(self, st: dict) -> None:
        if st.get("connected"):
            self.conn.setText("● 연결됨")
            self.conn.setStyleSheet(f"color: {style.STATUS_COLORS['OK']}")
            self.refresh()
        else:
            self.conn.setText("● " + REASON_TEXT.get(st.get("reason"), "연결 안 됨"))
            self.conn.setStyleSheet(f"color: {style.STATUS_COLORS['FAIL']}")

    def refresh_all(self) -> None:
        """새로고침 버튼: 연결부터 다시 보고, 보이는 화면을 캐시 무시로 다시 읽는다."""
        self.svc.check_status(lambda st, e: self.svc.tick.emit())

    def refresh(self) -> None:
        q, o = self.svc.query, self.svc.opts()

        def work():
            return q.me(**o), q.wings(**o)

        def done(r, e):
            if not r:
                return
            me, wings = r
            if "error" not in me:
                self.who.setText(f"Lv.{me['level']} {me['job'] or ''}")
                self.title.setText(f"「{me['title'] or ''}」 {me['realm'] or ''}")
                pct = me["weight_pct"]
                self.weight.setText(f"무게 {pct}%")
                self.weight.setStyleSheet(f"color: {style.STATUS_COLORS['FAIL'] if pct >= 100 else style.STATUS_COLORS['CHECK'] if pct >= 90 else style.TEXT}")
            if wings is not None:
                self.wings.setText(f"정령의 날개 {wings:,}")
        self.svc.run_bg(work, done)
