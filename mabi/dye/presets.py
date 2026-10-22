"""염색 프리셋 — 자주 쓰는 색 세 벌을 이름 붙여 저장한다. (mobi-remote src/dyeprefs.js 와 같은 형식)

염색은 한 번에 세 칸을 고르는 일이라 색이 늘 셋씩 다닌다. 같은 조합(머리색, 길드 유니폼)을
여러 번 쓰므로 매번 hex 를 다시 치게 두지 않는다.

파일: <data_dir>/dye-presets.json
  {"presets": [{"id", "name"(≤40), "colors"[3], "tol"[3] (0~40, 기본 5)}], "currentId"}
처음 쓸 때 파일이 없으면 %LOCALAPPDATA%\\mobi-remote\\dye-presets.json 을 복사해 온다 (원본은 안 건드린다).
"""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import time
from pathlib import Path

FILE_NAME = "dye-presets.json"
TOL_DEFAULT = 5
TOL_MAX = 40
NAME_MAX = 40

# 처음 켰을 때 빈 화면을 보지 않도록. 스크린샷에서 쓰이던 값이다.
# 오차는 색마다 — 딱 맞아야 하는 색과 비슷하면 되는 색이 한 조합에 섞인다.
SAMPLE = {
    "id": "sample",
    "name": "예시",
    "colors": ["#005855", "#82FFFF", "#FFF8A9"],
    "tol": [5, 5, 5],
}


def legacy_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local")
    return Path(base) / "mobi-remote" / FILE_NAME


def _empty() -> dict:
    # JS 는 SAMPLE 객체를 그대로 넣어 고치면 상수까지 바뀐다. 여기서는 복사한다.
    return {"presets": [copy.deepcopy(SAMPLE)], "currentId": SAMPLE["id"]}


def _js_number(v) -> float:
    """JS Number(v) 흉내. 숫자로 못 읽으면 NaN."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return math.nan
    return math.nan


def _num(n: float):
    """정수면 정수로 — JSON 에 5.0 대신 5 로 남도록 (JS 와 같은 파일)."""
    return int(n) if float(n).is_integer() else n


def three(colors) -> list[str]:
    """색 세 칸을 항상 세 칸으로. 빈 칸은 빈 문자열."""
    out = [str(c or "").strip() for c in (colors if isinstance(colors, list) else [])[:3]]
    while len(out) < 3:
        out.append("")
    return out


def three_tol(tol, fallback=None) -> list:
    """오차 세 칸. 없거나 이상한 값은 기본값, 0~40 으로 가둔다."""
    base = fallback if isinstance(fallback, (int, float)) and not isinstance(fallback, bool) else TOL_DEFAULT
    out = []
    for v in (tol if isinstance(tol, list) else [])[:3]:
        n = _js_number(v)
        out.append(_num(base) if math.isnan(n) else _num(max(0.0, min(float(TOL_MAX), n))))
    while len(out) < 3:
        out.append(_num(base))
    return out


def _new_id() -> str:
    n = int(time.time() * 1000)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = digits[r] + s
    return "p" + (s or "0")


class PresetStore:
    """load/add/update/remove/select 는 모두 파일을 새로 읽어 고치고, 바뀐 상태 전체를 돌려준다."""

    def __init__(self, data_dir, import_legacy: bool = True):
        self.file = Path(data_dir) / FILE_NAME
        if import_legacy:
            self._import_legacy()

    def _import_legacy(self) -> None:
        if self.file.exists():
            return
        src = legacy_file()
        try:
            if src.is_file():
                self.file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, self.file)    # 읽기만 한다 — 원본은 리모콘이 계속 쓴다
        except OSError:
            pass

    def load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or not isinstance(d.get("presets"), list):
                return _empty()
            # 옛 파일에는 색마다의 오차가 없고 전체 하나(tolerance)만 있었다. 그 값으로 세 칸을 채운다.
            old = d.get("tolerance")
            old = old if isinstance(old, (int, float)) and not isinstance(old, bool) else TOL_DEFAULT
            presets = [
                {**p, "tol": three_tol(p.get("tol"), old)}
                for p in d["presets"]
                if isinstance(p, dict) and p.get("id") and isinstance(p.get("colors"), list)
            ]
            first = d["presets"][0] if d["presets"] else None
            cur = d.get("currentId") or (first.get("id") if isinstance(first, dict) else None) or None
            return {"presets": presets, "currentId": cur}
        except (OSError, ValueError, TypeError, AttributeError):
            return _empty()

    def save(self, state: dict) -> dict:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass    # 저장 실패가 화면을 막지 않는다
        return state

    def current(self, state: dict | None = None) -> dict | None:
        s = state or self.load()
        ps = s.get("presets") or []
        return next((p for p in ps if p.get("id") == s.get("currentId")), ps[0] if ps else None)

    def add(self, name, colors) -> dict:
        s = self.load()
        p = {
            "id": _new_id(),
            "name": str(name or "이름 없음")[:NAME_MAX],
            "colors": three(colors),
            "tol": three_tol(None),
        }
        s["presets"].append(p)
        s["currentId"] = p["id"]
        self.save(s)
        return s

    def update(self, id_, *, name=None, colors=None, tol=None) -> dict:
        s = self.load()
        p = next((x for x in s["presets"] if x.get("id") == id_), None)
        if p is None:
            return s
        if name is not None:
            p["name"] = str(name)[:NAME_MAX]
        if colors is not None:
            p["colors"] = three(colors)
        if tol is not None:
            p["tol"] = three_tol(tol)
        return self.save(s)

    def remove(self, id_) -> dict:
        s = self.load()
        s["presets"] = [x for x in s["presets"] if x.get("id") != id_]
        if not s["presets"]:
            s["presets"] = [copy.deepcopy(SAMPLE)]     # 마지막 것을 지우면 예시가 돌아온다
        if not any(x.get("id") == s["currentId"] for x in s["presets"]):
            s["currentId"] = s["presets"][0]["id"]
        return self.save(s)

    def select(self, id_) -> dict:
        s = self.load()
        if any(x.get("id") == id_ for x in s["presets"]):
            s["currentId"] = id_
            self.save(s)
        return s
