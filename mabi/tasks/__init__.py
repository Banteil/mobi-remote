"""태스크 모음. 각 태스크는 run(bot, cfg) -> str 형태이고, 반환값은 실행 요약 문자열이다.
캐릭터 접속(login)은 run.py 가 캐릭터마다 먼저 실행하므로 여기 목록에는 없다."""
from . import arbeit, black_hole, daily_mission, drill, field_boss, silver, tribute, vanguard, weekday

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
}

# 정해진 시간에만 하는 숙제 → 지금 시작하면 안 되는 까닭 (열린 시간이 아님 등, 되면 ""). 새로 생기면 여기에 한 줄.
# 이 숙제들만 담은 카드는 작업 큐가 '시간 정해진 카드' 로 다룬다 (DailyKind.timed · ready): 닫혀 있으면 비켜 있다가,
# 열리면 돌던 카드를 끊어도 되는 자리에서 끊고 먼저 (mabi/cutpoint)
READY = {
    "field_boss": field_boss.not_ready,
}


def timed(order) -> bool:
    """정해진 시간에만 하는 숙제만으로 된 순서인가."""
    return bool(order) and all(t in READY for t in order)


def not_ready(order) -> str:
    """order 의 숙제 중 지금 시작하면 안 되는 것의 까닭 (모두 그런 숙제일 때만 — 섞여 있으면 다른 숙제는 한다)."""
    whys = [READY[t]() if t in READY else "" for t in order or ()]
    return whys[0] if whys and all(whys) else ""


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
