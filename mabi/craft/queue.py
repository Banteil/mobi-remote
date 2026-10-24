"""작업 큐 저장·기록 (queue.json · queue-history.jsonl). 큐를 돌리는 것은 화면(web/queue.js)이다.

캐릭터는 하나고 CLI 호출도 하나씩이라 동시에 돌릴 수가 없어서 큐다. 걸어 두면 순서대로 진행되고,
진행 중에도 뒤에 붙이거나 순서를 바꿀 수 있다. 껐다 켜도 목록이 남게 queue.json 에 저장하고,
진행 중이던 항목은 다시 켤 때 대기로 되돌린다 — 앱이 꺼진 동안 진행됐을 리가 없다.

상태: wait(대기) · run(진행 중) · pause(일시정지) · done(완료) · fail(중단)
"""
import json
from pathlib import Path

# 한 항목이 가질 수 있는 필드. 화면이 주는 값을 그대로 믿지 않고 걸러 담는다
FIELDS = ["id", "via", "name", "label", "recipe", "target", "status", "note",
          "spent", "steps", "have", "startHave", "per", "runs", "wings", "partial", "base", "made",
          # 일일 숙제 카드 (kind='daily'). 빠지면 다시 켰을 때 숙제 카드인 줄 몰라 새 숙제가 바꿔 끼우지 못하고 쌓인다
          "kind", "chars", "only", "force",
          # 어비스 반복 카드 (kind='abyss'; runs 는 위 runs 를 같이 쓴다 — 판 수)
          "slot", "dungeon", "difficulty", "minutes", "revive",
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
