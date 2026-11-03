"""게임 단축키 — 게임 설정에서 바꿀 수 있는 키는 리모콘 옵션([game] <이름>_key)에서도 바꾼다 (사용자 11-03).
이동(WASD)과 버튼에 붙은 확인 키(Space·Esc·R 여기서 부활·A 모두 받기 …)는 게임 화면 표시 그대로라 고정이다."""
from .inputs import vk_of

# 이름: (기본 키, 옵션 창 설명). 순서대로 옵션 창에 나온다
GAME_KEYS = {
    "camera": ("z", "카메라 전환 — 흩어진 물길에서 카메라를 캐릭터 뒤로 맞출 때"),
    "storage": ("x", "보관함으로 이동 — 레이드 판 사이 나가기 창을 띄울 때"),
    "food": ("b", "음식 먹기"),
    "quest": ("j", "퀘스트 창"),
    "mission": ("n", "미션 창"),
    "map": ("m", "지도"),
    "guide": ("/", "콘텐츠 가이드"),
    "quick_nav": (".", "퀵 내비게이터 (잡화점·대장간 … 바로 가기)"),
    "fast_travel": ("t", "빠른 이동 — 비우면 쓰지 않음"),
    "skill1": ("1", "스킬 1 — 투창 패턴을 피한 뒤 전투로 돌아갈 때"),
    "ultimate": ("6", "궁극기 — 보스전"),
    "paladin": ("f5", "팔라딘 변신 — 보스전"),
}
OPTIONAL = {"fast_travel"}  # 비워도 되는 키


def of(bot_or_cfg, name: str) -> str:
    """지금 쓸 키. 설정에 없으면 기본 키 (테스트용 가짜 봇처럼 cfg 가 없어도)."""
    cfg = bot_or_cfg if isinstance(bot_or_cfg, dict) else getattr(bot_or_cfg, "cfg", None)
    game = cfg.get("game") if isinstance(cfg, dict) else None
    v = game.get(f"{name}_key") if isinstance(game, dict) else None
    return str(GAME_KEYS[name][0] if v is None else v).lower()


def check(name: str, key: str) -> str | None:
    """옵션 창에서 고른 키가 쓸 수 있는지. 문제가 있으면 그 이유."""
    if name not in GAME_KEYS:
        return f"모르는 단축키 항목: {name}"
    if not key:
        return None if name in OPTIONAL else f"{GAME_KEYS[name][1].split(' —')[0]} 키를 비울 수 없습니다"
    try:
        vk_of(key)
    except ValueError:
        return f"쓸 수 없는 키: {key}"
    return None
