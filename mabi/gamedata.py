"""배포 데이터 표 (리소스 data\\) 중 코드 여러 곳이 읽는 것.

- ui.json: 게임 화면에서 글자로 찾는 문구(text)와 글자를 읽을 영역(regions)
- game-rules.json: 재화 이름·날개 비용·직업 목록 같은 게임 쪽 사실 (가공 시설 칸 수는 craft.gamerules 가 따로 읽는다)
- labels.json: 상태·출처 같은 표시 문구. 웹 화면도 같은 파일을 받아 쓴다 (api.labels)
- content.json: 필드 보스·레이드·어비스 목록과 주간 일정 (게임 데이터에서 뽑음 — 저장소 밖 도구 mabi-content-research)

데이터 폴더(paths.data)\\data 에 같은 이름의 파일이 있으면 그쪽이 우선 — 게임이 패치됐을 때 새 판을 기다리지 않고 고칠 수 있게.
"""
import datetime as dt
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


def point(key: str) -> tuple:
    """ui.json points 의 자리 [x, y] (목록이면 [x, y] 들의 튜플)."""
    v = _load("ui.json")["points"][key]
    return tuple(tuple(p) for p in v) if v and isinstance(v[0], list) else tuple(v)


def covers() -> dict[str, tuple[int, int, int, int]]:
    """게임이 다른 화면 위에 띄워 가리는 창들의 자리 (ui.json covers → regions). 이 자리는 판단에 쓰지 않는다."""
    ui = _load("ui.json")
    return {k: tuple(ui["regions"][k]) for k in ui.get("covers", {}) if not k.startswith("_")}


def covering(rect) -> list[str]:
    """rect([x, y, 너비, 높이])와 겹치는 covers 이름들 — 비었으면 가려질 일이 없는 자리."""
    x, y, w, h = rect
    return [k for k, (cx, cy, cw, ch) in covers().items()
            if x < cx + cw and cx < x + w and y < cy + ch and cy < y + h]


def covered_ok() -> dict[str, str]:
    """covers 자리와 겹쳐도 되는 영역 → 까닭 (ui.json covered_ok)."""
    return {k: v for k, v in _load("ui.json").get("covered_ok", {}).items() if not k.startswith("_")}


def rules() -> dict:
    return _load("game-rules.json")


def currency(key: str) -> str:
    """재화 이름: 'wings' 정령의 날개, 'gold' 골드, 'silver' 은동전, 'ducat' 두카트."""
    return rules()["currencies"][key]


def labels() -> dict:
    return _load("labels.json")


# ---- content.json: 게임 데이터에서 뽑은 필드 보스·레이드·어비스 목록과 일정
# 일정 표는 몇 달 치가 들어 있어 이번 주가 무엇인지는 부를 때 계산한다.
# 표가 끝나도(다음 패치 전까지 다시 뽑지 않았을 때) 마지막으로 시작한 칸을 그대로 쓴다.

_TZ = {"KST": dt.timezone(dt.timedelta(hours=9)), "UTC": dt.timezone.utc}


def _when(s: str, tz: str) -> dt.datetime | None:
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZ[tz]) if s else None


def _this_week(rows: list[dict], now: dt.datetime | None) -> list[dict]:
    """일정 표에서 지금 걸리는 칸들. 없으면 지금보다 먼저 시작한 마지막 칸 하나."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ["KST"])
    started = [r for r in rows if (_when(r["start"], r["tz"]) or now) <= now]
    hit = [r for r in started if (_when(r["end"], r["tz"]) or now + dt.timedelta(seconds=1)) > now]
    if hit:
        return hit
    return [max(started, key=lambda r: _when(r["start"], r["tz"]))] if started else []


def content() -> dict:
    return _load("content.json")


def field_bosses() -> dict[str, list[str]]:
    """필드 보스 → 고를 수 있는 난이도 (창 왼쪽 목록 순서)."""
    return {b["name"]: list(b["difficulties"]) for b in content()["fieldBoss"]["bosses"]}


def field_boss_hours() -> tuple[tuple[int, ...], int]:
    """(출현 시각들 (KST 시), 열려 있는 시간 (분))."""
    fb = content()["fieldBoss"]
    return tuple(fb["hours"]), int(fb["openMinutes"])


def raids(now: dt.datetime | None = None) -> dict[str, list[str]]:
    """이번 주 레이드 → 열린 난이도 (그 레이드 난이도 중 이번 주 최고 난이도까지)."""
    c = content()["raid"]
    out: dict[str, list[str]] = {}
    for row in _this_week(c["schedule"], now):
        for name, top in row["raids"]:
            full = c["raids"][name]
            out[name] = full[:full.index(top) + 1]
    return out


@cache
def abyss_names() -> tuple[str, ...]:
    """어비스 시즌(이름에 '어비스')의 던전 이름 전부 — 장소 이름으로 어비스 안인지 볼 때 (이번 주 것만이 아님).
    '마스 던전 심연' 같은 옛 시즌은 일반 던전 이름과 겹칠 수 있어 뺀다."""
    return tuple(n for n, v in content()["abyss"]["dungeons"].items() if "어비스" in v["season"])


def abysses(now: dt.datetime | None = None, mode: str = "solo") -> dict[str, list[str]]:
    """이번 주 어비스 던전 → 그 방식(solo 혼자하기 · party 함께하기)으로 열린 난이도."""
    c = content()["abyss"]
    out: dict[str, list[str]] = {}
    for row in _this_week(c["schedule"], now):
        for name, opened in row["dungeons"]:
            opened = set(opened.split(","))
            out[name] = [x["name"] for x in c["dungeons"][name]["difficulties"] if x[mode] and x["raw"] in opened]
    return out
