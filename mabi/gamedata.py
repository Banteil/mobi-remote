"""배포 데이터 표 (리소스 data\\) 중 코드 여러 곳이 읽는 것.

- ui.json: 게임 화면에서 글자로 찾는 문구(text)와 글자를 읽을 영역(regions)
- game-rules.json: 재화 이름·날개 비용·직업 목록 같은 게임 쪽 사실 (가공 시설 칸 수는 craft.gamerules 가 따로 읽는다)
- labels.json: 상태·출처 같은 표시 문구. 웹 화면도 같은 파일을 받아 쓴다 (api.labels)

데이터 폴더(paths.data)\\data 에 같은 이름의 파일이 있으면 그쪽이 우선 — 게임이 패치됐을 때 새 판을 기다리지 않고 고칠 수 있게.
"""
import json
from functools import cache
from pathlib import Path

from . import paths


@cache
def _load(name: str) -> dict:
    for d in (_override_dir(), paths.resource_dir() / "data"):
        f = d / name if d else None
        if f and f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"데이터 파일 없음: data\\{name}")


def _override_dir() -> Path | None:
    try:
        return paths.load().data / "data"
    except OSError:
        return None


def text(key: str) -> str:
    """ui.json 의 문구 하나 (목록이면 첫 번째)."""
    v = _load("ui.json")["text"][key]
    return v[0] if isinstance(v, list) else v


def words(key: str) -> list[str]:
    """ui.json 의 문구 목록 (하나뿐이어도 목록으로)."""
    v = _load("ui.json")["text"][key]
    return list(v) if isinstance(v, list) else [v]


def region(key: str) -> tuple[int, int, int, int]:
    return tuple(_load("ui.json")["regions"][key])


def rules() -> dict:
    return _load("game-rules.json")


def currency(key: str) -> str:
    """재화 이름: 'wings' 정령의 날개, 'gold' 골드, 'silver' 은동전, 'ducat' 두카트."""
    return rules()["currencies"][key]


def labels() -> dict:
    return _load("labels.json")
