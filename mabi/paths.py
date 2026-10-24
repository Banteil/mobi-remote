"""파일 경로를 한곳에서 정한다. 다른 모듈은 경로를 직접 만들지 않고 Paths 를 받아 쓴다.

- 리소스(읽기 전용): 템플릿, 기본 config.toml. 설치판은 설치 폴더의 app\\ (패치로 바뀌는 곳, gui.py) 에 코드와 같이 있다.
- 데이터(쓰기): 설정, 캐릭터 프로필, 하루 기록, 로그, 스크린샷, 실행 리포트.
    개발 중(파이썬으로 실행): 프로젝트 폴더 그대로 (지금까지의 배치 유지)
    exe(포터블): 실행 파일 옆 MabiDaily_data\\ , 쓸 수 없는 위치면 %LOCALAPPDATA%\\MabiDaily\\
- paths.json(데이터 폴더 기준 위치에 있음)으로 데이터 폴더 전체나 로그·스크린샷 폴더만 따로 바꿀 수 있다.
"""
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "MabiDaily"
PROJECT = Path(__file__).resolve().parent.parent


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """코드(mabi\\)가 있는 폴더 — 개발 중엔 프로젝트, 설치판은 app\\ (web·data·templates 가 코드 옆에 있다)."""
    return PROJECT


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def default_data_dir() -> Path:
    """개발: 프로젝트 폴더. exe: %LOCALAPPDATA%\\MabiDaily\\ (설치판을 지우거나 새 판으로 덮어써도 설정·기록이 남게).
    exe 옆에 portable.txt 가 있으면 무설치판으로 보고 exe 옆 MabiDaily_data\\ (쓸 수 없는 위치면 LOCALAPPDATA)."""
    if not frozen():
        return PROJECT
    here = Path(sys.executable).resolve().parent
    portable = here / f"{APP_NAME}_data"
    if (here / "portable.txt").exists() and _writable(portable):
        return portable
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME


@dataclass
class Paths:
    data: Path
    resources: Path = field(default_factory=resource_dir)
    logs: Path | None = None
    shots: Path | None = None

    def __post_init__(self):
        self.logs = self.logs or self.data / "logs"
        self.shots = self.shots or self.logs / "shots"

    # ---- 데이터 ----
    @property
    def runs(self) -> Path:
        return self.logs / "runs"

    @property
    def state(self) -> Path:
        return self.data / "state"

    @property
    def profile(self) -> Path:
        return self.data / "profile.json"

    @property
    def config(self) -> Path:
        """사용자 설정 — 기본값(config.default.toml)과 다른 값만 담는다 (mabi.userconfig). 없으면 빈 파일로 만든다.
        개발 중 프로젝트 폴더의 config.toml 은 개발자 개인 설정이라 배포 기본으로 쓰지 않는다."""
        p = self.data / "config.toml"
        if not p.exists():
            self.data.mkdir(parents=True, exist_ok=True)
            if (self.resources / "config.default.toml").exists():
                from .userconfig import HEADER, SPARSE_MARK
                p.write_text("".join(f"# {s}\n" for s in [*HEADER.splitlines(), SPARSE_MARK]), encoding="utf-8")
            else:
                shutil.copyfile(self.resources / "config.toml", p)
        return p

    @property
    def settings(self) -> Path:
        """GUI 설정 (창 위치, 보관 기간 등)."""
        return self.data / "settings.json"

    # ---- 리소스 ----
    @property
    def templates(self) -> Path:
        """데이터 폴더에 templates\\ 가 있으면 그쪽이 우선 (게임 업데이트로 템플릿을 갈아 끼울 때)."""
        override = self.data / "templates"
        return override if (override / "index.json").exists() else self.resources / "templates"

    def ensure(self) -> "Paths":
        for d in (self.data, self.logs, self.shots, self.runs, self.state):
            d.mkdir(parents=True, exist_ok=True)
        return self


def _overrides_file(base: Path) -> Path:
    return base / "paths.json"


def load(base: Path | None = None) -> Paths:
    """기본 데이터 폴더의 paths.json 에 적힌 대로 경로를 정한다 ({"data": ..., "logs": ..., "shots": ...})."""
    base = base or default_data_dir()
    over = {}
    f = _overrides_file(base)
    if f.exists():
        try:
            over = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            over = {}
    p = Path(over["data"]) if over.get("data") else base
    return Paths(data=p,
                 logs=Path(over["logs"]) if over.get("logs") else None,
                 shots=Path(over["shots"]) if over.get("shots") else None).ensure()


def save_overrides(data: str = "", logs: str = "", shots: str = "", base: Path | None = None) -> None:
    """빈 문자열이면 기본값. 바뀐 경로는 다음 실행부터 적용된다."""
    base = base or default_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    vals = {k: v for k, v in (("data", data), ("logs", logs), ("shots", shots)) if v}
    f = _overrides_file(base)
    if vals:
        f.write_text(json.dumps(vals, ensure_ascii=False, indent=2), encoding="utf-8")
    elif f.exists():
        f.unlink()
