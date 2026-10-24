"""제작·가공의 판단 계층 (리모콘 mobi-remote 의 src/ 를 옮긴 것).

파일은 두 곳으로 나뉜다.
- 배포 표(읽기 전용, 리소스 data\\): game-rules · facility-map · alter-recipes · recipe-book(씨앗)
- 학습 데이터(데이터 폴더): knowledge.json · recipe-book.json(내 수확분) · queue.json
처음 쓸 때 데이터 폴더에 학습 파일이 없으면 리모콘(%LOCALAPPDATA%\\mobi-remote\\)에서 복사해 온다 —
리모콘으로 쌓아 둔 시설 레벨·레시피를 버리지 않으려고. 원본은 건드리지 않는다.

GUI 는 CraftData(paths.data, paths.resources / "data") 하나만 만들어 각 모듈 함수에 넘긴다.
"""
import os
import shutil
from pathlib import Path

from .altertable import AlterTable
from .facilitymap import FacilityMap
from .gamerules import GameRules
from .knowledge import Knowledge
from .recipebook import RecipeBook

REMOTE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "mobi-remote"
IMPORT_FILES = ("knowledge.json", "recipe-book.json")


class CraftData:
    def __init__(self, data_dir: Path, bundled_dir: Path, import_from: Path | None = REMOTE):
        self.data_dir, self.bundled_dir = Path(data_dir), Path(bundled_dir)
        self.imported = self._import(import_from) if import_from else []
        self.rules = GameRules(self.bundled_dir / "game-rules.json")
        self.facilitymap = FacilityMap(self.bundled_dir / "facility-map.json")
        self.altertable = AlterTable(self.bundled_dir / "alter-recipes.json")
        self.recipebook = RecipeBook(self.bundled_dir / "recipe-book.json", self.data_dir / "recipe-book.json",
                                     self.altertable)
        self.knowledge = Knowledge(self.data_dir / "knowledge.json", self.rules, self.recipebook, self.facilitymap)
        self.queue_file = self.data_dir / "queue.json"
        self.history_file = self.data_dir / "queue-history.jsonl"

    def _import(self, src: Path) -> list[str]:
        """없는 학습 파일만 리모콘에서 복사한다. 실패해도 빈 상태로 계속 간다."""
        done = []
        for name in IMPORT_FILES:
            dst = self.data_dir / name
            if dst.exists() or not (src / name).is_file():
                continue
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src / name, dst)
                done.append(name)
            except OSError:
                pass
        return done


_default: CraftData | None = None


def configure(data_dir: Path, bundled_dir: Path, import_from: Path | None = REMOTE) -> CraftData:
    """앱 전체가 같이 쓸 CraftData 를 정한다 (GUI 시작 시 한 번)."""
    global _default
    _default = CraftData(data_dir, bundled_dir, import_from)
    return _default


def data() -> CraftData:
    if _default is None:
        raise RuntimeError("mabi.craft.configure() 를 먼저 불러야 합니다")
    return _default
