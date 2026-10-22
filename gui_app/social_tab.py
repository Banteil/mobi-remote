"""소셜: 채팅, 표정, 행동.

2026-10-15 판부터 write_chat 은 보낼 때마다 게임 안에 확인 창을 띄우고, 사람이 '보내기'를 눌러야 전송된다.
그동안 명령이 몇 분까지 기다리므로 "게임에서 확인하세요"를 띄우고, 취소 버튼으로 기다림을 끊을 수 있게 한다.
표정은 EmojiText, 행동은 ChatCommands 첫 번째를 write_chat 으로 보낸다. 일어서기만 전용 명령(stand_up).
"""
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .services import Services
from .style import STATUS_COLORS

CONFIRM_WAIT = 300  # 게임 확인 창을 기다리는 최대 초


class SocialTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.chat = QLineEdit()
        self.chat.setMaxLength(50)
        self.chat.setPlaceholderText("채팅 (50자까지)")
        self.chat.returnPressed.connect(self.send_chat)
        send = QPushButton("보내기")
        send.clicked.connect(self.send_chat)
        self.hint = QLabel("보낼 때마다 게임 화면에 확인 창이 뜹니다. 게임에서 '보내기'를 눌러야 전송됩니다.")
        self.hint.setObjectName("muted")
        self.search = QLineEdit()
        self.search.setPlaceholderText("표정·행동 검색")
        self.search.textChanged.connect(self.render)
        self.grids = {}
        lay = QVBoxLayout(self)
        ch = QHBoxLayout()
        ch.addWidget(self.chat, 1)
        ch.addWidget(send)
        lay.addLayout(ch)
        lay.addWidget(self.hint)
        lay.addWidget(self.search)
        for key, title in (("facials", "표정"), ("behaviours", "행동")):
            box = QGroupBox(title)
            inner = QWidget()
            grid = QGridLayout(inner)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setWidget(inner)
            QVBoxLayout(box).addWidget(sc)
            lay.addWidget(box, 1 if key == "facials" else 3)
            self.grids[key] = grid
        self.data = None

    def refresh(self) -> None:
        q, o = self.svc.query, self.svc.opts()
        self.svc.run_bg(lambda: q.social(**o), lambda r, e: (setattr(self, "data", r), self.render()))

    def render(self) -> None:
        if not self.data or "error" in self.data:
            return
        from mabi.query import matches
        for key, grid in self.grids.items():
            while grid.count():
                grid.takeAt(0).widget().deleteLater()
            rows = [x for x in self.data[key] if matches(x["name"], self.search.text())]
            for i, x in enumerate(rows):
                b = QPushButton(x["name"] + (f" {x['send']}" if key == "facials" and x["send"] else ""))
                b.clicked.connect(lambda _=False, x=x: self.do(x))
                grid.addWidget(b, i // 8, i % 8)

    def send_chat(self) -> None:
        text = self.chat.text().strip()
        if text:
            self._write(text, f"채팅 '{text}'", clear=True)

    def do(self, x: dict) -> None:
        if x["command"] == "stand_up":
            self.svc.action("stand_up", None, label="일어서기")
        elif x["send"]:
            self._write(x["send"], x["name"])

    def _write(self, text: str, label: str, clear: bool = False) -> None:
        self.hint.setText("게임 화면의 확인 창에서 '보내기'를 눌러 주세요 (취소하려면 아래 상태바의 취소)")
        self.hint.setStyleSheet(f"color: {STATUS_COLORS['CHECK']}")

        def done(r):
            self.hint.setText("보낼 때마다 게임 화면에 확인 창이 뜹니다. 게임에서 '보내기'를 눌러야 전송됩니다.")
            self.hint.setStyleSheet("")
            if r is not None and r.ok and clear:
                self.chat.clear()
        self.svc.action("write_chat", text, done, label, timeout=CONFIRM_WAIT)
