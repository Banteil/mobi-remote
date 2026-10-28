"""작업 큐 카드 저장(queue.json)·작업 기록(queue-history.jsonl) 파일. 큐 자체는 mabi/workqueue.py 다."""
import json
from pathlib import Path

# 한 항목이 가질 수 있는 필드. 화면이 주는 값을 그대로 믿지 않고 걸러 담는다
FIELDS = ["id", "via", "name", "label", "recipe", "target", "status", "note",
          "spent", "steps", "have", "startHave", "per", "runs", "wings", "partial", "base", "made",
          # 일일 숙제 카드 (kind='daily'). 빠지면 다시 켰을 때 숙제 카드인 줄 몰라 새 숙제가 바꿔 끼우지 못하고 쌓인다
          "kind", "chars", "only", "force",
          # 어비스 반복 카드 (kind='abyss'; runs 는 위 runs 를 같이 쓴다 — 판 수)
          "slot", "dungeon", "difficulty", "minutes", "revive",
          # 레이드 반복 카드 (kind='raid' — 어비스와 같고 장소 칸만 raid). 빠지면 다시 켰을 때 '레이드 None'
          "raid",
          # 한 번 하는 행동 카드 (kind='action' — 제작·채집·가공·수령·연주 버튼)
          "act", "command", "body", "detail", "skipConfirm",
          "doneRuns", "doneSecs", "fit"]  # 어비스 카드가 멈췄다 다시 돌 때 이미 한 판·초

# 작업 기록 (끝난 항목 한 줄씩, queue-history.jsonl). 화면의 '기록' 창이 읽는다
HISTORY_FIELDS = ["start", "end", "kind", "label", "result", "detail", "note"]
HISTORY_KEEP = 1000


def record(file: Path, entry: dict) -> None:
    """끝난 항목 하나를 기록 끝에 붙인다. 오래된 것은 HISTORY_KEEP 줄만 남기고 버린다."""
    row = {k: entry[k] for k in HISTORY_FIELDS if isinstance(entry, dict) and k in entry}
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        lines = file.read_text(encoding="utf-8").splitlines() if file.exists() else []
        lines = (lines + [json.dumps(row, ensure_ascii=False)])[-HISTORY_KEEP:]
        file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # 기록에 실패해도 큐는 계속 돈다


def history(file: Path, limit: int = 300) -> list[dict]:
    """최근 기록부터 limit 개."""
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def load(file: Path) -> dict:
    try:
        d = json.loads(file.read_text(encoding="utf-8"))
        return {"items": d["items"] if isinstance(d.get("items"), list) else []}
    except (OSError, ValueError, AttributeError):
        return {"items": []}


def save(file: Path, state: dict) -> dict:
    items = [{k: x[k] for k in FIELDS if k in x}
             for x in (state.get("items") if isinstance(state, dict) and isinstance(state.get("items"), list) else [])]
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 저장에 실패해도 진행 중인 큐는 계속 돌아야 한다
    return {"items": items}
