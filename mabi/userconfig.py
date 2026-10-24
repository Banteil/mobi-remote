"""사용자 설정(config.toml)은 배포 기본값(config.default.toml)과 다른 값만 담는다.

예전에는 처음 켤 때 기본 설정을 통째로 복사해서, 새 판에서 기본값을 고쳐도 사용자에게는 옛 값이 남았다
(2026-10-24: arbeit.gather_timeout 을 300 → 180 으로 바꿨는데 config.toml 은 300 그대로). 이제는
  - 읽을 때: 기본값 위에 사용자 값을 덮는다 (runner.load_config — 엔진용 dict)
  - 고칠 때: doc() 가 같은 방식으로 합친 tomlkit 문서를 주고, save() 가 기본값과 다른 키만 골라 쓴다
설정 화면 코드(daily_api·chars_api)는 전체 문서를 고치듯 쓰면 된다.
"""
import tomllib

import tomlkit
from tomlkit.items import Table

from .paths import Paths

HEADER = ("기본값(config.default.toml)과 다른 설정만 여기에 둔다. 없는 키는 기본값을 따른다.\n"
          "기본값을 바꾸고 싶으면 그 키를 [표] 아래에 적으면 된다.")
SPARSE_MARK = "sparse"  # 이 파일을 '다른 값만' 형식으로 옮겼다는 표시 (맨 위 주석)

# 옛 판에서 기본 설정을 통째로 복사해 둔 값 → 사용자가 고른 게 아니라 옛 기본값이라 옮길 때 버린다.
# (config.default.toml 을 바꿀 때 바뀐 키의 옛 값을 여기에 더한다)
OLD_DEFAULTS = {
    ("arbeit", "gather_timeout"): [300],
    ("tribute", "max_runs"): [5],
}


def _read(path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _default_doc(paths: Paths):
    return tomlkit.parse(_read(paths.resources / "config.default.toml"))


def _overlay(base, over) -> None:
    """tomlkit 표 base 위에 over 를 덮는다 (주석은 사용자 쪽이 있으면 그쪽)."""
    for k, v in over.items():
        if isinstance(v, Table) and isinstance(base.get(k), Table):
            _overlay(base[k], v)
        else:
            base[k] = v


def doc(paths: Paths):
    """고칠 수 있는 설정 문서 = 기본값 + 사용자 값 (save 로 저장)."""
    d = _default_doc(paths)
    _overlay(d, tomlkit.parse(_read(paths.config)))
    return d


def _diff(cur, base, path=()) -> dict:
    """cur 중 base 와 다른 것만 {키: tomlkit item 또는 하위 dict}."""
    out = {}
    for k, v in cur.items():
        b = base.get(k) if base is not None else None
        if isinstance(v, Table):
            sub = _diff(v, b if isinstance(b, Table) else None, (*path, k))
            if sub:
                out[k] = sub
            continue
        val = v.unwrap() if hasattr(v, "unwrap") else v
        if b is not None and val == (b.unwrap() if hasattr(b, "unwrap") else b):
            continue
        out[k] = v
    return out


def _build(diff: dict, table=None):
    t = table if table is not None else tomlkit.table(is_super_table=all(isinstance(x, dict) for x in diff.values()))
    for k, v in diff.items():
        t[k] = _build(v) if isinstance(v, dict) else v
    return t


def save(paths: Paths, d) -> None:
    """d(doc() 로 받아 고친 문서) 중 기본값과 다른 키만 config.toml 에 쓴다."""
    out = tomlkit.document()
    for line in HEADER.splitlines():
        out.add(tomlkit.comment(line))
    out.add(tomlkit.comment(SPARSE_MARK))
    out.add(tomlkit.nl())
    _build(_diff(d, _default_doc(paths)), out)
    paths.config.write_text(tomlkit.dumps(out), encoding="utf-8")


def migrate(paths: Paths, log=None) -> bool:
    """통째로 복사해 둔 옛 config.toml 을 '다른 값만' 형식으로 한 번 옮긴다. 옛 파일은 config.toml.bak 으로 남긴다."""
    p = paths.config
    text = _read(p)
    if not text or f"# {SPARSE_MARK}" in text.splitlines()[:5] or not (paths.resources / "config.default.toml").exists():
        return False
    user = tomlkit.parse(text)
    for (sec, key), olds in OLD_DEFAULTS.items():
        t = user.get(sec)
        if isinstance(t, Table) and key in t and t[key].unwrap() in olds:
            del t[key]
    tomllib.loads(text)  # 깨진 파일이면 건드리지 않는다 (예외가 위로)
    p.with_name(p.name + ".bak").write_text(text, encoding="utf-8")
    d = _default_doc(paths)
    _overlay(d, user)
    save(paths, d)
    if log:
        log.info("설정 파일을 '기본값과 다른 값만' 형식으로 옮김 (옛 파일: config.toml.bak)")
    return True
