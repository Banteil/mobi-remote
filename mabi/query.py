"""조회 결과 도우미 (이름 맞추기·실패 모양). 화면용 조회 결과 모양은 gui_app/legacy_shapes 가 만든다."""
from . import richtext


def matches(hay, needle) -> bool:
    """공백·대소문자 무시 부분 일치. 태그는 먼저 벗긴다."""
    if not needle:
        return True
    h = (richtext.strip(str(hay or "")) or "").lower().replace(" ", "")
    return str(needle).lower().replace(" ", "") in h


def name_fields(display: str) -> dict:
    """화면용 이름과 원문. 게임에 보낼 때는 반드시 name_raw."""
    return {"name": richtext.strip(display), "name_raw": display}


def _fail(res: dict) -> dict:
    return {"error": res.get("error"), "message": res.get("message")}


def _meta(res: dict) -> dict:
    return {"cached": res.get("cached", False), "stale": bool(res.get("stale"))}
