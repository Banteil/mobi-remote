"""연주: 악기 교체, 악보 목록, 재생목록(반복·셔플), 지금 연주 중인 곡 진행바.

2026-10-15 판부터 커넥터는 게임이 준 악보(상점·보상)만 목록에 주고 연주하게 한다.
직접 만들거나 복사한 악보는 목록에서 빠지고, 재생목록에 남아 있으면 건너뛴다.
"""
import random
import time

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget, QComboBox)

from mabi import errors

from .services import Services
from .style import MUTED, STATUS_COLORS

STOP_ALL = {"not_available_on_combat", "not_available_on_dead", "not_available_on_riding", "no_instrument"}


def mmss(sec: float) -> str:
    n = max(0, round(sec))
    return f"{n // 60}:{n % 60:02d}"


class Player(QThread):
    """재생목록을 차례로 연주한다. 게임 '반복'이 켜져 있으면 곡이 끝나도 IsPlaying 이 안 내려오므로
    경과 시간이 총 길이에 닿으면 직접 멈추고 다음 곡으로 넘어간다."""
    status = Signal(str)

    def __init__(self, svc: Services, tracks: list[str], loop: bool):
        super().__init__()
        self.svc, self.tracks, self.loop = svc, tracks, loop
        self.stopping = False

    def run(self) -> None:
        cli, q = self.svc.cli, self.svc.query
        i, played, skipped = 0, 0, 0
        while not self.stopping and 0 <= i < len(self.tracks):
            title = self.tracks[i]
            label = title.removeprefix("악보: ")
            self.status.emit(f"({i + 1}/{len(self.tracks)}) {label}")
            r = cli.run("play_music_score", {"title": title})
            if not r.ok:
                skipped += 1
                self.status.emit(f"{label} 건너뜀 — {errors.describe('play_music_score', r.error)['text']}")
                if r.error in STOP_ALL:  # 전투·사망·탑승·악기 없음이면 뒤 곡도 마찬가지
                    break
            else:
                played += 1
                self._sleep(2)
                while not self.stopping:
                    a = q.activity()
                    p = a.get("perf") if "error" not in a else None
                    if not p or not p["playing"]:
                        break
                    if p["total"] and p["elapsed"] >= p["total"] - 0.5:
                        cli.run("stop_action")
                        break
                    self._sleep(3)
            i = i + 1 if i + 1 < len(self.tracks) else (0 if self.loop and played else -1)
        if self.stopping:
            cli.run("stop_action")
        self.status.emit(f"재생목록 끝 — {played}곡 연주" + (f", {skipped}곡 건너뜀" if skipped else ""))

    def _sleep(self, s: float) -> None:
        end = time.monotonic() + s
        while not self.stopping and time.monotonic() < end:
            time.sleep(0.1)


class MusicTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        self.player: Player | None = None
        self.owned: list[dict] = []
        self.last_perf, self.perf_at = None, 0.0

        # 악기
        ibox = QGroupBox("악기")
        self.inst_grid = QGridLayout(ibox)
        # 악보
        sbox = QGroupBox("악보 (게임이 준 악보만 연주할 수 있습니다)")
        self.search = QLineEdit()
        self.search.setPlaceholderText("검색")
        self.search.textChanged.connect(self.render_scores)
        self.scores = QListWidget()
        self.scores.itemDoubleClicked.connect(lambda it: self.play_one(it.data(256)))
        add = QPushButton("재생목록에 넣기")
        add.clicked.connect(self.add_selected)
        play = QPushButton("연주")
        play.clicked.connect(lambda: self.scores.currentItem() and self.play_one(self.scores.currentItem().data(256)))
        sv = QVBoxLayout(sbox)
        sv.addWidget(self.search)
        sv.addWidget(self.scores, 1)
        sh = QHBoxLayout()
        sh.addWidget(play)
        sh.addWidget(add)
        sv.addLayout(sh)
        # 재생목록
        pbox = QGroupBox("재생목록")
        self.pl_pick = QComboBox()
        self.pl_pick.currentIndexChanged.connect(self.render_playlist)
        new, ren, dele = QPushButton("새로"), QPushButton("이름"), QPushButton("삭제")
        new.clicked.connect(self.pl_new)
        ren.clicked.connect(self.pl_rename)
        dele.clicked.connect(self.pl_delete)
        self.loop, self.shuffle = QCheckBox("반복"), QCheckBox("섞기")
        self.loop.toggled.connect(lambda v: self._flags(loop=v))
        self.shuffle.toggled.connect(lambda v: self._flags(shuffle=v))
        self.tracks = QListWidget()
        up, down, rm = QPushButton("↑"), QPushButton("↓"), QPushButton("빼기")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        rm.clicked.connect(self._remove_track)
        self.play_btn, self.stop_btn = QPushButton("▶ 재생목록 연주"), QPushButton("■ 정지")
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self.play_list)
        self.stop_btn.clicked.connect(self.stop)
        self.pl_status = QLabel("")
        self.pl_status.setObjectName("muted")
        pv = QVBoxLayout(pbox)
        ph = QHBoxLayout()
        for w in (self.pl_pick, new, ren, dele):
            ph.addWidget(w)
        pv.addLayout(ph)
        fh = QHBoxLayout()
        fh.addWidget(self.loop)
        fh.addWidget(self.shuffle)
        fh.addStretch(1)
        for w in (up, down, rm):
            fh.addWidget(w)
        pv.addLayout(fh)
        pv.addWidget(self.tracks, 1)
        bh = QHBoxLayout()
        bh.addWidget(self.play_btn)
        bh.addWidget(self.stop_btn)
        pv.addLayout(bh)
        pv.addWidget(self.pl_status)
        # 지금 연주 중
        self.now = QLabel("")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(8)

        cols = QHBoxLayout()
        cols.addWidget(sbox, 1)
        cols.addWidget(pbox, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(ibox)
        lay.addLayout(cols, 1)
        lay.addWidget(self.now)
        lay.addWidget(self.bar)

        # 게임에 묻는 건 2.5초(연주 중)/6초, 그 사이 진행바는 흐른 시간으로 메운다
        self.paint_timer = QTimer(self)
        self.paint_timer.timeout.connect(self.paint_now)
        self.poll_timer = QTimer(self)
        self.poll_timer.setSingleShot(True)
        self.poll_timer.timeout.connect(self.poll_perf)
        self.load_playlists()

    def showEvent(self, e):  # noqa: N802
        self.paint_timer.start(500)
        self.poll_perf()
        super().showEvent(e)

    def hideEvent(self, e):  # noqa: N802
        self.paint_timer.stop()
        self.poll_timer.stop()
        super().hideEvent(e)

    # ---- 불러오기 ----
    def refresh(self) -> None:
        q, o = self.svc.query, self.svc.opts()
        self.svc.run_bg(lambda: (q.instruments(**o), q.music_scores(**o)), self._loaded)

    def _loaded(self, r, err) -> None:
        if not r:
            return
        inst, scores = r
        while self.inst_grid.count():
            self.inst_grid.takeAt(0).widget().deleteLater()
        for i, it in enumerate(inst.get("items", [])):
            b = QPushButton(it["name"] + ("" if it["durability"] is None else f" ({it['durability']})"))
            b.setEnabled(not it["equipped"])
            if it["equipped"]:
                b.setObjectName("primary")
            b.clicked.connect(lambda _=False, n=it["name"]: self.svc.action(
                "change_instrument", {"name": n}, lambda r: self.refresh(), f"{n} 장착"))
            self.inst_grid.addWidget(b, i // 6, i % 6)
        self.owned = scores.get("items", [])
        self.render_scores()
        self.render_playlist()

    def render_scores(self) -> None:
        from mabi.query import matches
        self.scores.clear()
        for s in self.owned:
            if matches(s["title"], self.search.text()):
                it = QListWidgetItem(s["label"] + ("  🔒" if s["locked"] else ""))
                it.setData(256, s["title"])
                self.scores.addItem(it)

    # ---- 재생목록 ----
    def load_playlists(self, select: str | None = None) -> None:
        cur = select or self.pl_pick.currentData()
        self.pl_pick.blockSignals(True)
        self.pl_pick.clear()
        for pl in self.svc.playlists.lists():
            self.pl_pick.addItem(pl["name"], pl["id"])
        if cur:
            i = self.pl_pick.findData(cur)
            self.pl_pick.setCurrentIndex(max(0, i))
        self.pl_pick.blockSignals(False)
        self.render_playlist()

    def current(self) -> dict | None:
        pid = self.pl_pick.currentData()
        return next((p for p in self.svc.playlists.lists() if p["id"] == pid), None)

    def render_playlist(self) -> None:
        pl = self.current()
        self.tracks.clear()
        if not pl:
            return
        for w, v in ((self.loop, pl.get("loop")), (self.shuffle, pl.get("shuffle"))):
            w.blockSignals(True)
            w.setChecked(bool(v))
            w.blockSignals(False)
        owned = {s["title"] for s in self.owned}
        for t in pl["tracks"]:
            it = QListWidgetItem(("" if not self.owned or t in owned else "✘ ") + t.removeprefix("악보: "))
            if self.owned and t not in owned:
                it.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(MUTED))
                it.setToolTip("이 캐릭터가 갖고 있지 않거나, 직접 만든·복사한 악보라 연주할 수 없습니다")
            self.tracks.addItem(it)

    def pl_new(self) -> None:
        name, ok = QInputDialog.getText(self, "새 재생목록", "이름")
        if ok:
            self.load_playlists(self.svc.playlists.create(name.strip())["id"])

    def pl_rename(self) -> None:
        pl = self.current()
        if pl:
            name, ok = QInputDialog.getText(self, "이름 바꾸기", "이름", text=pl["name"])
            if ok and name.strip():
                self.svc.playlists.rename(pl["id"], name.strip())
                self.load_playlists()

    def pl_delete(self) -> None:
        pl = self.current()
        if pl and QMessageBox.question(self, "삭제", f"'{pl['name']}' 재생목록을 지울까요?") == QMessageBox.Yes:
            self.svc.playlists.remove(pl["id"])
            self.load_playlists()

    def _flags(self, **kw) -> None:
        pl = self.current()
        if pl:
            self.svc.playlists.set_flags(pl["id"], **kw)

    def add_selected(self) -> None:
        pl, it = self.current(), self.scores.currentItem()
        if not pl:
            pl = self.svc.playlists.create("내 재생목록")
            self.load_playlists(pl["id"])
        if it:
            self.svc.playlists.add(pl["id"], it.data(256))
            self.render_playlist()

    def _move(self, d: int) -> None:
        pl, i = self.current(), self.tracks.currentRow()
        if pl and i >= 0:
            self.svc.playlists.move(pl["id"], i, d)
            self.render_playlist()
            self.tracks.setCurrentRow(max(0, min(i + d, self.tracks.count() - 1)))

    def _remove_track(self) -> None:
        pl, i = self.current(), self.tracks.currentRow()
        if pl and i >= 0:
            self.svc.playlists.remove_track(pl["id"], i)
            self.render_playlist()

    # ---- 연주 ----
    def play_one(self, title: str) -> None:
        self.svc.action("play_music_score", {"title": title}, lambda r: self.poll_perf(), title.removeprefix("악보: ") + " 연주")

    def play_list(self) -> None:
        pl = self.current()
        if self.player and self.player.isRunning():
            return
        if not pl or not pl["tracks"]:
            self.pl_status.setText("재생목록이 비어 있습니다")
            return
        owned = {s["title"] for s in self.owned}
        tracks = [t for t in pl["tracks"] if t in owned] if self.owned else list(pl["tracks"])
        if not tracks:
            self.pl_status.setText("이 캐릭터가 연주할 수 있는 곡이 목록에 없습니다")
            return
        if pl.get("shuffle"):
            random.shuffle(tracks)
        self.player = Player(self.svc, tracks, bool(pl.get("loop")))
        self.player.status.connect(self.pl_status.setText)
        self.player.finished.connect(lambda: self.play_btn.setEnabled(True))
        self.play_btn.setEnabled(False)
        self.player.start()

    def stop(self) -> None:
        if self.player and self.player.isRunning():
            self.player.stopping = True
        else:
            self.svc.action("stop_action", None, lambda r: self.poll_perf(), "정지")

    # ---- 진행바 ----
    def poll_perf(self) -> None:
        q, o = self.svc.query, self.svc.opts()

        def done(a, e):
            if a and "error" not in a:
                self.last_perf, self.perf_at = a["perf"], time.monotonic()
            if self.isVisible():
                self.poll_timer.start(2500 if self.last_perf and self.last_perf["playing"] else 6000)
        self.svc.run_bg(lambda: q.activity(**o), done)

    def paint_now(self) -> None:
        p = self.last_perf
        if not p or not p["playing"]:
            self.now.setText("")
            self.bar.setValue(0)
            return
        raw = p["elapsed"] + (time.monotonic() - self.perf_at)
        total = p["total"]
        # ElapsedSeconds 는 곡이 끝나도 계속 오른다(게임 반복) → 총 길이로 나눈 이번 바퀴 위치
        lap = int(raw // total) if total else 0
        el = raw - lap * total if total else raw
        self.now.setText(f"▶ {p['title'].removeprefix('악보: ') or '연주 중'}  {p['instrument']}"
                         f"   {mmss(el)}{' / ' + mmss(total) if total else ''}"
                         + (f"   {lap + 1}바퀴째" if lap else ""))
        self.now.setStyleSheet(f"color: {STATUS_COLORS['OK']}")
        self.bar.setMaximum(1000)
        self.bar.setValue(int(el / total * 1000) if total else 0)
