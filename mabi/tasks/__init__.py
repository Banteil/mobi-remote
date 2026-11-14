"""태스크 모음. 각 태스크는 run(bot, cfg) -> str 형태이고, 반환값은 실행 요약 문자열이다.
캐릭터 접속(login)은 run.py 가 캐릭터마다 먼저 실행하므로 여기 목록에는 없다."""
from . import arbeit, black_hole, daily_mission, drill, field_boss, silver, tribute, vanguard, weekday, weekend

TASKS = {
    "weekday_dungeon": ("요일 던전", weekday.run),
    "silver": ("은동전 (사냥터/던전)", silver.run),
    "tribute": ("공물 던전", tribute.run),
    "black_hole": ("검은 구멍", black_hole.run),
    "daily_mission": ("일일 미션", daily_mission.run),
    "arbeit": ("아르바이트", arbeit.run),
    # 기타 숙제 — 일일 순서(run.order)에는 없고, 숙제 탭의 '기타 숙제' 에서 이것만 골라 돈다 (only)
    "drill": ("나이트메어 드릴", drill.run),
    # 주간 숙제 — 숙제 탭의 '주간 숙제' 에서 이것만 골라 돈다 (only). 필드 보스는 열린 시간(12·18·20·22시부터 30분)에만 — READY
    "field_boss": ("필드 보스", field_boss.run),
    "vanguard": ("뱅가드 브리치", vanguard.run),
    # 주말 퀘스트 — 토·일요일에만 있는 '주말에는 어비스!'·'주말에는 레이드!'. 한 캐릭터가 둘 다 하고 다음 캐릭터로 (SEASON)
    "weekend_abyss": ("주말 어비스", weekend.run_abyss),
    "weekend_raid": ("주말 레이드", weekend.run_raid),
}

# 정해진 시간에만 하는 숙제 → 지금 시작하면 안 되는 까닭 (열린 시간이 아님 등, 되면 ""). 새로 생기면 여기에 한 줄.
# 이 숙제들만 담은 카드는 작업 큐가 '시간 정해진 카드' 로 다룬다 (DailyKind.timed · ready): 닫혀 있으면 비켜 있다가,
# 열리면 돌던 카드를 끊어도 되는 자리에서 끊고 먼저 (mabi/cutpoint)
READY = {
    "field_boss": field_boss.not_ready,
}


# 정해진 기간에만 있는 숙제 → 지금 그 기간이 아닌 까닭 (기간이면 ""). READY 와 달리 기간이 와도 돌던 카드를 끊지 않는다 —
# 작업 큐는 이 숙제들만 담은 카드를 기간까지 비켜 두었다가, 기간이 되면 제 차례에 돈다 (주말 퀘스트는 이틀 동안 있다)
SEASON = {
    "weekend_abyss": weekend.not_now,
    "weekend_raid": weekend.not_now,
}

# 숙제 하나의 시간 상한을 따로 정하는 숙제 → 설정 칸 ([칸] task_timeout_min). 없으면 [run] task_timeout_min.
# 판을 여러 번 도는 숙제만 (주말 어비스 3판은 매칭·쓰러짐이 겹치면 45분을 넘을 수 있다)
TIMEOUT_SECTION = {
    "weekend_abyss": "weekend",
    "weekend_raid": "weekend",
}


def timeout_min(tid: str, cfg: dict) -> float:
    """숙제 tid 의 시간 상한 (분)."""
    own = cfg.get(TIMEOUT_SECTION.get(tid, ""), {}).get("task_timeout_min")
    return float(own or cfg["run"]["task_timeout_min"])


def timed(order) -> bool:
    """정해진 시간에만 하는 숙제만으로 된 순서인가."""
    return bool(order) and all(t in READY for t in order)


def not_ready(order) -> str:
    """order 의 숙제 중 지금 시작하면 안 되는 것의 까닭 (모두 그런 숙제일 때만 — 섞여 있으면 다른 숙제는 한다).
    시간 정해진 숙제(READY)와 기간 정해진 숙제(SEASON)를 같이 본다."""
    whys = [(READY.get(t) or SEASON.get(t) or str)() for t in order or ()]
    return whys[0] if whys and all(whys) else ""


# 차례가 와도 지금은 이르면 그 캐릭터의 다른 숙제 뒤로 한 번 미루는 숙제 → 이른 까닭 (괜찮으면 ""). runner 가 차례마다 묻는다.
# 공물 퀘스트는 접속 몇 분 뒤에 나타나서, 다시 켠 직후 바로 차례가 오면 기다리다 건너뛰었다 (tribute.not_yet)
LATER = {
    "tribute": tribute.not_yet,
}


# 확인 결과 남아도 '남음(직접 처리)' 으로 두고 다시 시작할 때 넘기는 숙제 (자동으로는 더 할 수 없는 것만 남는다)
MANUAL_LEFT = {"arbeit"}

# 숙제가 끝났는지 게임 상태로 다시 확인하는 함수 (run 이 예외 없이 끝나도 실제로 다 됐는지 본다)
VERIFY = {
    "weekday_dungeon": weekday.verify,
    "silver": silver.verify,
    "tribute": tribute.verify,
    "black_hole": black_hole.verify,
    "daily_mission": daily_mission.verify,
    "arbeit": arbeit.verify,
    "drill": drill.verify,
    "field_boss": field_boss.verify,
    "vanguard": vanguard.verify,
}


def build(cfg: dict) -> dict:
    """task id -> (label, callable)"""
    return dict(TASKS)
