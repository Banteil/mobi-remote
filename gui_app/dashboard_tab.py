"""대시보드: 캐릭터 · 위치 · 지금 하는 일 · 재화 · 주변 사람과 NPC."""
from PySide6.QtWidgets import (QFormLayout, QGridLayout, QGroupBox, QHeaderView, QLabel, QListWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .services import Services
from .style import MUTED, STATUS_COLORS

FLAGS = [("auto_playing", "자동 진행"), ("auto_traveling", "자동 이동"), ("in_combat", "전투"), ("performing", "연주"),
         ("dialogue", "대화·선택 대기"), ("sitting", "앉음"), ("riding", "탑승"), ("dead", "쓰러짐")]
DUNGEON = {"NotInDungeon": "", "InProgress": "던전 진행 중", "Cleared": "던전 클리어"}


def _form(box: QGroupBox, keys: list[tuple[str, str]]) -> dict[str, QLabel]:
    f = QFormLayout(box)
    out = {}
    for k, label in keys:
        out[k] = QLabel("-")
        f.addRow(label, out[k])
    return out


class DashboardTab(QWidget):
    def __init__(self, svc: Services):
        super().__init__()
        self.svc = svc
        me_box = QGroupBox("캐릭터")
        self.me = _form(me_box, [("title", "타이틀"), ("level", "레벨·직업"), ("realm", "서버"), ("combat", "전투력"),
                                 ("living", "생활력"), ("hp", "생명력"), ("satiety", "포만감"), ("weight", "무게"),
                                 ("buffs", "버프")])
        env_box = QGroupBox("위치")
        self.env = _form(env_box, [("space", "장소"), ("channel", "채널"), ("weather", "날씨"), ("erinn_time", "에린 시각"),
                                   ("pos", "좌표")])
        act_box = QGroupBox("지금 하는 일")
        self.act = QLabel("-")
        self.act.setWordWrap(True)
        QVBoxLayout(act_box).addWidget(self.act)
        cur_box = QGroupBox("재화")
        self.cur = QLabel("-")
        self.cur.setWordWrap(True)
        QVBoxLayout(cur_box).addWidget(self.cur)

        pcs_box = QGroupBox("주변 플레이어 (이름 칸은 서버)")
        self.pcs = QTableWidget(0, 6)
        self.pcs.setHorizontalHeaderLabels(["서버", "거리", "Lv", "직업", "전투력", "상태"])
        self.pcs.verticalHeader().setVisible(False)
        self.pcs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pcs.setEditTriggers(QTableWidget.NoEditTriggers)
        QVBoxLayout(pcs_box).addWidget(self.pcs)
        npc_box = QGroupBox("주변 NPC")
        self.npcs = QListWidget()
        QVBoxLayout(npc_box).addWidget(self.npcs)

        self.note = QLabel("")
        self.note.setStyleSheet(f"color: {STATUS_COLORS['CHECK']}")
        g = QGridLayout(self)
        g.addWidget(self.note, 3, 0, 1, 2)
        g.addWidget(me_box, 0, 0)
        g.addWidget(env_box, 0, 1)
        g.addWidget(act_box, 1, 1)
        g.addWidget(cur_box, 1, 0)
        g.addWidget(pcs_box, 2, 0)
        g.addWidget(npc_box, 2, 1)
        g.setRowStretch(2, 1)
        svc.tick.connect(self.refresh_if_visible)

    def refresh_if_visible(self) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        q, o = self.svc.query, self.svc.opts()

        def work():
            return {"me": q.me(**o), "env": q.environment(**o), "act": q.activity(**o),
                    "cur": q.currencies(non_zero=True, **o), "pcs": q.near_pcs(**o), "npcs": q.near_npcs(**o)}
        self.svc.run_bg(work, self._show)

    def _show(self, r, err) -> None:
        if not r:
            return
        me = r["me"]
        # 게임이 꺼져 있으면 마지막으로 저장해 둔 값이다 — 지금 값처럼 보이면 안 된다
        stale = [v for v in r.values() if isinstance(v, dict) and v.get("stale")]
        self.note.setText("게임에 연결되지 않아 마지막으로 저장된 값을 보여 줍니다" if stale or self.svc.online is False else "")
        if "error" not in me:
            self.me["title"].setText(me["title"] or "-")
            self.me["level"].setText(f"Lv.{me['level']} {me['job'] or ''}")
            self.me["realm"].setText(me["realm"] or "-")
            self.me["combat"].setText(f"{me['combat']:,}" if me["combat"] else "-")
            self.me["living"].setText(f"{me['living']:,}" if me["living"] else "-")
            self.me["hp"].setText("{}/{}".format(*me["hp"]))
            self.me["satiety"].setText("{}/{}".format(*me["satiety"]))
            self.me["weight"].setText("{}/{}  ({}%)".format(*me["weight"], me["weight_pct"]))
            self.me["buffs"].setText(str(me["buffs"] or 0))
        env = r["env"]
        if "error" not in env:
            for k in ("space", "channel", "weather", "erinn_time"):
                self.env[k].setText(str(env.get(k) or "-"))
            self.env["pos"].setText("{}, {}".format(*env["pos"]) if env.get("pos") else "-")
        act = r["act"]
        if "error" not in act:
            on = [label for k, label in FLAGS if act.get(k)]
            if act.get("dungeon") and DUNGEON.get(act["dungeon"], act["dungeon"]):
                on.append(DUNGEON.get(act["dungeon"], act["dungeon"]))
            if act["perf"]["playing"]:
                on.append(f"연주: {act['perf']['title']}")
            self.act.setText("  ·  ".join(on) if on else "쉬는 중")
        cur = r["cur"]
        if "error" not in cur:
            self.cur.setText("   ".join(f"{c['name']} <b>{c['amount']:,}</b>" for c in cur["items"]))
        self.pcs.setRowCount(0)
        for p in r["pcs"]["items"]:
            row = self.pcs.rowCount()
            self.pcs.insertRow(row)
            tags = [t for t, on in (("친구", p["friend"]), ("파티", p["party"]), ("길드", p["guild"]),
                                    ("전투", p["in_combat"]), ("연주", p["playing"])) if on]
            for c, v in enumerate([p["name"], f"{p['distance']}m", p["level"], p["job"], p["combat"], " ".join(tags)]):
                self.pcs.setItem(row, c, QTableWidgetItem("" if v is None else f"{v:,}" if isinstance(v, int) and c == 4 else str(v)))
        self.npcs.clear()
        for n in r["npcs"]["items"]:
            self.npcs.addItem(n.get("DisplayName") or n.get("Name") or str(n) if isinstance(n, dict) else str(n))
