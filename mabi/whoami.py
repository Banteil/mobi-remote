"""지금 접속한 캐릭터가 어느 슬롯인지 알아낸다.

get_my_info 에는 캐릭터 이름이 없다. 그래서 슬롯마다 '지문'(서버·레벨·직업·타이틀·생활력·매력·데코 점수 등)을
기억해 두고, 지금 값과 가장 비슷한 슬롯을 고른다. 지문은 숙제가 그 슬롯으로 접속했을 때 저절로 새로 쓰고,
사람이 캐릭터 탭에서 '지금 캐릭터로 기억' 을 눌러도 쓴다.

값들은 조금씩 자라므로(전투력·생활력) 정확히 같기를 바라지 않고 가까운 정도로 잰다. 둘째 후보와 차이가
작으면 확실하지 않다고 돌려준다 — 이름을 지어내 보여 주는 것보다 '모름' 이 낫다.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

# (키, 무게, 허용 비율) — 허용 비율만큼 벌어지면 0점. 데코·매력은 잘 안 변해서 무겁게, 전투력은 직업·장비로 흔들려 가볍게
NUMERIC = (("decor", 1.5, 0.05), ("attract", 1.5, 0.05), ("living", 1.0, 0.08), ("combat", 0.5, 0.15))
EXACT = (("job", 2.0), ("title", 1.5), ("level", 1.0))
SURE_SCORE, SURE_GAP = 0.75, 0.15
MIN_SCORE = 0.4  # 이보다 낮으면 어느 슬롯도 아니라고 본다 (처음 보는 캐릭터)


def fingerprint(info: dict | None) -> dict | None:
    """get_my_info 원본 → 지문. 값이 없으면 None."""
    if not isinstance(info, dict) or info.get("Level") is None:
        return None

    def v(k):
        return (info.get(k) or {}).get("Value")
    return {"realm": info.get("RealmName") or "", "level": info.get("Level"),
            "job": info.get("EnabledCombatJobDisplayName") or "", "title": info.get("Title") or "",
            "combat": v("CombatScore"), "living": v("LivingScore"), "attract": v("AttractivenessScore"),
            "decor": v("DecorScore")}


def similarity(a: dict, b: dict) -> float:
    """0..1. 서버가 다르면 0."""
    if a.get("realm") and b.get("realm") and a["realm"] != b["realm"]:
        return 0.0
    got = total = 0.0
    for k, w in EXACT:
        if k == "title" and not (a.get(k) or b.get(k)):
            continue  # 둘 다 타이틀이 없으면 판단 재료가 아니다
        total += w
        got += w if a.get(k) == b.get(k) else 0
    for k, w, tol in NUMERIC:
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            continue
        total += w
        got += w * max(0.0, 1 - abs(x - y) / max(1, abs(y)) / tol)
    return got / total if total else 0.0


class Characters:
    """data/characters.json: {"slots": {"1": {"fp": {...}, "seen": "..."}}}"""

    def __init__(self, data_dir: Path):
        self.file = Path(data_dir) / "characters.json"
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("slots"), dict):
                return d
        except (OSError, ValueError):
            pass
        return {"slots": {}}

    def _save(self, d: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.file)

    def learn(self, slot: int, fp: dict) -> None:
        with self._lock:
            d = self.load()
            d["slots"].setdefault(str(slot), {}).update(fp=fp, seen=datetime.now().isoformat(timespec="seconds"))
            self._save(d)

    def set_card(self, slot: int, level, job) -> None:
        """캐릭터 선택 화면에서 읽은 레벨·직업 (카드 표시용. 알아보기에는 쓰지 않는다)."""
        with self._lock:
            d = self.load()
            e = d["slots"].setdefault(str(slot), {})
            e["card"] = {"level": level, "job": job}
            self._save(d)

    def consistent(self, slot: int, fp: dict) -> bool:
        """이 슬롯 카드에서 읽어 둔 직업·레벨과 지금 값이 맞는지 (모르면 True). 접속 직후 커넥터가 이전 캐릭터
        정보를 잠깐 돌려주거나 엉뚱한 캐릭터로 들어갔을 때 그 값을 이 슬롯으로 기억하지 않으려고."""
        card = (self.load()["slots"].get(str(slot)) or {}).get("card") or {}
        if card.get("job") and fp.get("job") and card["job"] != fp["job"]:
            return False
        return not (card.get("level") and fp.get("level") and int(card["level"]) > int(fp["level"]))

    def forget(self, slot: int) -> None:
        with self._lock:
            d = self.load()
            if d["slots"].pop(str(slot), None) is not None:
                self._save(d)

    def identify(self, fp: dict | None, slots: list[int] | None = None) -> dict:
        """{slot, score, sure, ranks:[(slot, score)]}. slots 를 주면 그 슬롯들 안에서만 고른다."""
        if not fp:
            return {"slot": None, "score": 0, "sure": False, "ranks": []}
        known = self.load()["slots"]
        ranks = sorted(((int(s), round(similarity(fp, e["fp"]), 3)) for s, e in known.items()
                        if e.get("fp") and (slots is None or int(s) in slots)), key=lambda r: -r[1])
        if not ranks:
            return {"slot": None, "score": 0, "sure": False, "ranks": []}
        best = ranks[0]
        if best[1] < MIN_SCORE:
            return {"slot": None, "score": best[1], "sure": False, "ranks": ranks}
        gap = best[1] - (ranks[1][1] if len(ranks) > 1 else 0)
        # 생활력·매력·데코는 계정 공용일 수 있어 직업이 다르면 확실하다고 하지 않는다
        same_job = (known[str(best[0])]["fp"].get("job") or "") == (fp.get("job") or "")
        return {"slot": best[0], "score": best[1], "sure": best[1] >= SURE_SCORE and gap >= SURE_GAP and same_job,
                "ranks": ranks}
