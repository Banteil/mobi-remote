"""작업 큐 결과 보고 — 큐가 한 번 도는 동안(시작 → 다 끝남·전체 중단) 카드마다 무엇을 했고 무엇을 얻었나.

일시정지는 한 번 도는 중으로 친다 (이어 하면 같은 보고서에 쌓인다). 다 끝나거나 전체 중단(Ctrl+F12)이면 닫고 화면에 띄운다.

얻은 것: CLI get_items(소모품·재료 — 장비·의상은 없음)와 get_currencies 를 앞뒤로 찍어 뺀다. 둘 다 비용 없는 조회다.
  일일 숙제는 캐릭터를 바꿔 가며 하므로 캐릭터마다 (runner 가 접속 뒤·그 캐릭터 끝에 찍는다),
  나머지 카드는 카드 앞뒤로 (지금 접속한 캐릭터).
가방과 보관함을 합쳐 세므로 옮기기만 한 것은 변화가 아니다. 음식·재료처럼 줄어든 것은 '쓴 것' 으로 따로 둔다.
"""
import time

from .craft.knowledge import diff_items, item_totals

RESULT = ("done", "fail", "pause", "stop", "removed", "preempt", "abort")


def snapshot(query) -> dict | None:
    """query(command) → CLI 응답(실패면 None). {items: {이름: 개수}, cur: {재화: 수량}} — 둘 다 못 읽으면 None."""
    items = query("get_items")
    cur = query("get_currencies")
    if items is None and cur is None:
        return None
    return {"items": item_totals(items) if items is not None else None,
            "cur": {c.get("DisplayName"): int(c.get("Amount") or 0) for c in cur or [] if isinstance(c, dict)}
            if cur is not None else None}


def loot(before: dict | None, after: dict | None, who: str = "") -> dict | None:
    """앞뒤 스냅샷 → {who, gained: {이름: +n}, used: {이름: n}, cur: {재화: ±n}}. 비교할 수 없거나 변화가 없으면 None."""
    if not before or not after:
        return None
    out = {"who": who, "gained": {}, "used": {}, "cur": {}}
    if before.get("items") is not None and after.get("items") is not None:
        for k, d in diff_items(before["items"], after["items"]).items():
            (out["gained"] if d > 0 else out["used"])[k] = abs(d)
    if before.get("cur") is not None and after.get("cur") is not None:
        out["cur"] = diff_items(before["cur"], after["cur"])
    return out if out["gained"] or out["used"] or out["cur"] else None


class LootMeter:
    """한 캐릭터 몫의 얻은 것. 그 캐릭터로 접속을 마친 뒤 open, 그 캐릭터를 끝낼 때(다른 캐릭터로 바꾸기 전·작업 끝) close
    → emit({who, gained, used, cur}). 일일 숙제(runner)·어비스·레이드 반복이 같이 쓴다 — 카드 앞뒤로 재면 캐릭터를
    바꾼 카드는 다른 캐릭터 가방끼리 뺀다 (2026-10-30 결과 창에 룬의 파편 +16만 등)."""

    def __init__(self, emit):
        self.emit, self._at = emit, None

    def open(self, bot, who: str) -> None:
        self._at = (who, snapshot(bot.state.query)) if bot.state.available() else None

    def close(self, bot) -> None:
        if not self._at:
            return
        who, before = self._at
        self._at = None
        x = loot(before, snapshot(bot.state.query), who)
        if x:
            self.emit(x)


def total(loots: list[dict]) -> dict:
    """여러 loot 를 하나로 더한다."""
    out = {"gained": {}, "used": {}, "cur": {}}
    for x in loots:
        for k in out:
            for name, n in (x.get(k) or {}).items():
                out[k][name] = out[k].get(name, 0) + n
    out["cur"] = {k: v for k, v in out["cur"].items() if v}
    return out


def merge_tasks(old: list, new: list) -> list:
    """일일 숙제 결과 [[이름표, 상태, 요약]] 를 이어 붙인다. 같은 이름표는 새 것으로 —
    단 이어 한 실행이 '오늘 이미 끝남'(DONE)으로 넘긴 것은 앞 실행의 결과(OK 등)를 남긴다."""
    rows = {r[0]: list(r) for r in old or []}
    order = [r[0] for r in old or []]
    for r in new or []:
        label = r[0]
        if label not in rows:
            order.append(label)
        elif r[1] == "DONE":
            continue
        rows[label] = list(r)
    return [rows[k] for k in order]


class QueueReport:
    def __init__(self):
        self.data = {"start": int(time.time() * 1000), "end": None, "why": None, "cards": []}

    def card(self, it: dict) -> dict:
        """이 카드의 칸 (처음이면 만든다 — 밀렸다 이어 한 카드는 같은 칸에 쌓인다)."""
        c = next((c for c in self.data["cards"] if c["id"] == it.get("id")), None)
        if c is None:
            c = {"id": it.get("id"), "kind": it.get("kind") or "goal", "label": it.get("label") or "", "result": "run",
                 "note": "", "secs": 0, "runs": 0, "view": {}, "loot": [], "tasks": []}
            self.data["cards"].append(c)
        return c

    def add_loot(self, it: dict, x: dict | None) -> None:
        if x:
            self.card(it)["loot"].append(x)

    def card_end(self, it: dict, result: str, secs: float, view: dict, detail: str = "", tasks: list | None = None) -> None:
        c = self.card(it)
        c.update(result=result, note=it.get("note") or "", view=view or {}, detail=detail)
        c["secs"] += int(secs)
        c["runs"] += 1
        if tasks:
            c["tasks"] = merge_tasks(c["tasks"], tasks)

    def finish(self, why: str) -> dict:
        """why: done(다 끝남) · abort(전체 중단)."""
        self.data.update(end=int(time.time() * 1000), why=why)
        self.data["total"] = total([x for c in self.data["cards"] for x in c["loot"]])
        return self.data

    @property
    def empty(self) -> bool:
        return not self.data["cards"]
