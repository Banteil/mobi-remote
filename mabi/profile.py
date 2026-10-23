"""사용자별 설정(숙제할 캐릭터 슬롯)과 하루 단위 진행 기록.

profile.json  : {"slots": [1, 2, 5], "names": {"5": "캐릭터 이름"}}
                처음 실행할 때 입력받아 저장한다 (python run.py --setup 으로 다시 입력).
state/<게임 날짜>.json : {"5": {"weekday_dungeon": "done", "silver": "fail: ..."}}
                게임 하루는 오전 6시에 초기화되므로 6시 이전은 전날로 친다.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

RESET_HOUR = 6
KEEP_DAYS = 7  # 하루 기록 파일(state/날짜.json)을 며칠치 남길지


def load_profile(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_profile(path: Path, profile: dict) -> None:
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def ask_profile(path: Path, old: dict | None = None) -> dict:
    """콘솔에서 숙제할 슬롯 번호와 (선택) 표시 이름을 입력받는다."""
    print("캐릭터 선택 화면에서 왼쪽 위부터 1, 2, 3, 4 / 다음 줄 5, 6 ... 순서입니다.")
    print("(선택 화면 정렬은 '캐릭터 생성 순'으로 두세요. 정렬이 바뀌면 번호가 달라집니다.)")
    default = ",".join(map(str, old["slots"])) if old else ""
    while True:
        raw = input(f"숙제할 슬롯 번호를 쉼표로 입력 (예: 1,2,3,4,5,6){f' [{default}]' if default else ''}: ").strip()
        raw = raw or default
        try:
            slots = sorted({int(x) for x in raw.replace(" ", "").split(",") if x})
        except ValueError:
            print("숫자와 쉼표만 입력하세요.")
            continue
        if slots and all(s >= 1 for s in slots):
            break
        print("슬롯 번호를 하나 이상 입력하세요.")
    names = dict((old or {}).get("names", {}))
    for s in slots:
        cur = names.get(str(s), "")
        name = input(f"  슬롯 {s} 표시 이름 (생략 가능){f' [{cur}]' if cur else ''}: ").strip() or cur
        if name:
            names[str(s)] = name
    profile = {"slots": slots, "names": {k: v for k, v in names.items() if int(k) in slots}}
    save_profile(path, profile)
    print(f"저장: profile.json  슬롯 {slots}")
    return profile


def characters(profile: dict) -> list[dict]:
    return [{"slot": s, "name": profile.get("names", {}).get(str(s), f"슬롯 {s}")} for s in profile["slots"]]


def game_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return (now - timedelta(hours=RESET_HOUR)).strftime("%Y-%m-%d")


class DailyState:
    """오늘(게임 날짜) 캐릭터별 숙제 결과. 'done' 이면 다음 실행 때 건너뛴다."""

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.date = game_date()
        self.path = self.dir / f"{self.date}.json"
        self.data: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.prune()

    def prune(self, keep_days: int = KEEP_DAYS) -> None:
        """keep_days 일보다 오래된 기록 파일은 지운다 (파일 이름이 게임 날짜라 문자열 비교로 충분)."""
        if not self.dir.exists():
            return
        cutoff = (datetime.strptime(self.date, "%Y-%m-%d") - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        for f in self.dir.glob("????-??-??.json"):
            if f.stem < cutoff:
                f.unlink(missing_ok=True)

    def get(self, slot: int, task: str) -> str | None:
        return self.data.get(str(slot), {}).get(task)

    def is_done(self, slot: int, task: str) -> bool:
        """끝남 — 'MANUAL'(할 수 있는 건 다 하고 남은 건 사람이 처리)도 다시 하지 않는다."""
        s = self.get(slot, task)
        return s == "done" or (isinstance(s, str) and s.startswith("MANUAL"))

    def set(self, slot: int, task: str, status: str) -> None:
        self.data.setdefault(str(slot), {})[task] = status
        self._save()

    def _save(self) -> None:
        self.dir.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 진행 위치: 중단·충돌 뒤 다시 시작하면 이 캐릭터부터 이어 한다
    PROGRESS = "_progress"

    def progress(self) -> dict | None:
        """{"slot", "task", "at"} — 마지막으로 하던 숙제. 실행이 끝까지 돌면 지워진다."""
        return self.data.get(self.PROGRESS)

    def set_progress(self, slot: int, task: str) -> None:
        self.data[self.PROGRESS] = {"slot": slot, "task": task, "at": datetime.now().strftime("%H:%M:%S")}
        self._save()

    # ---- 숙제 안의 단계: 'slot' 의 'task' 를 어디까지 했나. 다시 시작하면 그 숙제가 이걸 보고 이어 한다
    STEPS = "_steps"

    def set_step(self, slot: int, task: str, step: str, text: str = "", **data) -> None:
        """step: 단계 키 (각 숙제가 정한 고정 이름, 예 'bh_inside' — 이어 하기는 이걸로 판단), text: 사람이 읽는 설명."""
        rec = {"step": step, "text": text or step, "at": datetime.now().strftime("%H:%M:%S"), **data}
        self.data.setdefault(str(slot), {}).setdefault(self.STEPS, {})[task] = rec
        p = self.data.get(self.PROGRESS)
        if p and p.get("slot") == slot and p.get("task") == task:
            p.update(step=step, stage=rec["text"], stage_at=rec["at"])
        self._save()

    def last_step(self, slot: int, task: str) -> dict | None:
        return self.data.get(str(slot), {}).get(self.STEPS, {}).get(task)

    # ---- 캐릭터 상태 표시: 오늘 알게 된 사실 (예 'no_food' — 먹을 음식이 없음)
    FLAGS = "_flags"

    def flag(self, slot: int, key: str) -> bool:
        return key in self.data.get(str(slot), {}).get(self.FLAGS, {})

    def set_flag(self, slot: int, key: str) -> None:
        self.data.setdefault(str(slot), {}).setdefault(self.FLAGS, {})[key] = datetime.now().strftime("%H:%M:%S")
        self._save()

    # ---- 캐릭터별 오늘 횟수 (예 'food' — 음식을 먹은 횟수)
    COUNTS = "_counts"

    def count(self, slot: int, key: str) -> int:
        return self.data.get(str(slot), {}).get(self.COUNTS, {}).get(key, 0)

    def bump(self, slot: int, key: str) -> int:
        counts = self.data.setdefault(str(slot), {}).setdefault(self.COUNTS, {})
        counts[key] = counts.get(key, 0) + 1
        self._save()
        return counts[key]

    def clear_progress(self) -> None:
        if self.data.pop(self.PROGRESS, None) is not None:
            self._save()

    def failed(self, slot: int, task: str) -> bool:
        """오늘 해 봤는데 끝나지 않은 숙제 (FAIL/ERROR/CHECK 등)."""
        s = self.get(slot, task)
        return s is not None and not self.is_done(slot, task)
