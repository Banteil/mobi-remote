"""데이터 폴더의 작은 JSON 저장소들 (재생목록·즐겨찾기 등).

처음 열 때 파일이 없으면 리모콘(%LOCALAPPDATA%\\mobi-remote\\)의 같은 파일을 복사해 온다 (원본은 건드리지 않음).
"""
import json
import os
import shutil
from pathlib import Path

REMOTE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "mobi-remote"


class JsonStore:
    def __init__(self, path: Path, default: dict, import_from: str | None = None):
        self.path, self.default = path, default
        if not path.exists() and import_from and (REMOTE / import_from).exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REMOTE / import_from, path)

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else json.loads(json.dumps(self.default))
        except (OSError, ValueError):
            return json.loads(json.dumps(self.default))

    def save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # 저장 실패해도 화면은 계속 동작해야 한다


class Playlists(JsonStore):
    """연주 재생목록. 커넥터는 캐릭터 식별자를 안 주므로 목록은 캐릭터와 무관하게 두고,
    재생할 때 지금 캐릭터가 가진 악보만 추린다 (캐릭터를 바꿔도 목록이 깨지지 않는다)."""

    def __init__(self, path: Path):
        super().__init__(path, {"lists": []}, "playlists.json")

    def lists(self) -> list[dict]:
        return self.load().get("lists", [])

    def _edit(self, pid: str, fn) -> dict | None:
        d = self.load()
        item = next((x for x in d.get("lists", []) if x["id"] == pid), None)
        if item is None:
            return None
        fn(item)
        item["tracks"] = item.get("tracks", [])[:300]
        self.save(d)
        return item

    def remove(self, pid: str) -> None:
        d = self.load()
        d["lists"] = [x for x in d.get("lists", []) if x["id"] != pid]
        self.save(d)

    def rename(self, pid, name):
        return self._edit(pid, lambda x: x.update(name=name[:40]))

    def add(self, pid, title):
        return self._edit(pid, lambda x: title in x["tracks"] or x["tracks"].append(title))

    def move(self, pid, i, delta):
        def mv(x):
            t = x["tracks"]
            j = i + delta
            if 0 <= i < len(t) and 0 <= j < len(t):
                t[i], t[j] = t[j], t[i]
        return self._edit(pid, mv)


class Favorites(JsonStore):
    """{목록 종류: [name_raw, ...]} — 키는 게임 원문 이름."""

    def __init__(self, path: Path):
        super().__init__(path, {}, "favorites.json")

    def get(self, kind: str) -> set[str]:
        return set(self.load().get(kind, []))
