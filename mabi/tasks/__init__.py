"""태스크 모음. 각 태스크는 run(bot, cfg) -> str 형태이고, 반환값은 실행 요약 문자열이다.
캐릭터 접속(login)은 run.py 가 캐릭터마다 먼저 실행하므로 여기 목록에는 없다."""
from . import arbeit, black_hole, daily_mission, silver, tribute, weekday

TASKS = {
    "weekday_dungeon": ("요일 던전", weekday.run),
    "silver": ("은동전 (사냥터/던전)", silver.run),
    "tribute": ("공물 던전", tribute.run),
    "black_hole": ("검은 구멍", black_hole.run),
    "daily_mission": ("일일 미션", daily_mission.run),
    "arbeit": ("아르바이트", arbeit.run),
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
}


def build(cfg: dict) -> dict:
    """task id -> (label, callable)"""
    return dict(TASKS)
