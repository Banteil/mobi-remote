"""커넥터 호환성 검사 (리모콘 src/version.js). 검증해 둔 기준선과 지금 커넥터를 비교한다.

- CLI 버전은 ProductVersion 의 semver 만 본다. '+해시'는 넥슨이 재빌드할 때마다 바뀌어(명령·비용 그대로)
  매번 경고하면 정작 중요한 경고(비용 변경)까지 무시하게 된다.
- 리모콘은 명령 이름|본문 형식만 지문으로 썼는데, 2026-10-15 판은 설명(Note)과 출력 형식만 바뀌어
  (커스텀 악보 연주 금지, 채팅 확인 창 등) 안 잡혔다 → 명령별 Note/OutputExample 해시도 저장하고 비교한다.
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from .connector import Connector

LEVELS = ["ok", "info", "warn", "error"]


def read_version_string(buf: bytes, key: str) -> str | None:
    """PE 의 VS_VERSIONINFO 문자열 (UTF-16LE 널종료, 값은 4바이트 경계에서 시작). PowerShell 없이 파일에서 직접."""
    needle = (key + "\0").encode("utf-16-le")
    at = buf.find(needle)
    if at < 0:
        return None
    p = at + len(needle)
    while p % 4:
        p += 1
    end = p
    while end + 1 < len(buf) and not (buf[end] == 0 and buf[end + 1] == 0):
        end += 2
    return buf[p:end].decode("utf-16-le", "replace").strip() or None


def cli_version(exe: str) -> dict:
    if not os.path.isabs(exe) or not os.path.exists(exe):
        return {"path": exe, "error": "exe_not_found", "productVersion": None}
    buf = Path(exe).read_bytes()
    return {"path": exe, "productVersion": read_version_string(buf, "ProductVersion"),
            "fileVersion": read_version_string(buf, "FileVersion"), "company": read_version_string(buf, "CompanyName")}


def semver(pv: str | None) -> str:
    return str(pv or "").split("+")[0].strip()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def fingerprint(cli: Connector) -> dict:
    cmds = cli.capabilities()
    return {
        "cli": cli_version(cli.locate().path),
        "commands": sorted(c["Command"] for c in cmds),
        "bodyExamples": {c["Command"]: c["BodyExample"] for c in cmds if c.get("BodyExample")},
        "costs": cli.costs(),
        # 설명·출력 형식이 바뀌면 동작이 달라질 수 있다 (명령별 해시 + 원문을 같이 둬서 무엇이 바뀌었는지 보여 준다)
        "specs": {c["Command"]: {"hash": _sha((c.get("Note") or "") + "\n" + (c.get("OutputExample") or "")),
                                 "note": c.get("Note") or "", "output": c.get("OutputExample") or ""} for c in cmds},
        "capturedAt": datetime.now().isoformat(timespec="seconds"),
    }


class Compat:
    def __init__(self, cli: Connector, baseline_file: Path, seed: Path | None = None):
        """seed: 리모콘 compat.json 같은 기존 기준선 (사용자 기준선이 없을 때만 읽는다)."""
        self.cli, self.file, self.seed = cli, baseline_file, seed

    def baseline(self) -> dict | None:
        for f in (self.file, self.seed):
            if f and f.exists():
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
        return None

    def save(self, fp: dict | None = None, note: str = "") -> dict:
        fp = dict(fp or fingerprint(self.cli))
        fp["cli"] = {k: (fp.get("cli") or {}).get(k) for k in ("productVersion", "fileVersion", "company")}
        fp.update(verifiedNote=note, verifiedAt=datetime.now().isoformat(timespec="seconds"))
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")
        return fp

    def check(self, refresh: bool = True) -> dict:
        """{level: ok|info|warn|error, changes: [{level, kind, title, detail}], first_run}"""
        if refresh:
            self.cli.capabilities(refresh=True)
        cur = fingerprint(self.cli)
        base = self.baseline()
        if not base:
            return {"level": "info", "first_run": True, "current": cur, "changes": [
                {"level": "info", "kind": "no_baseline", "title": "호환 기준선이 없습니다",
                 "detail": "지금 상태를 기준선으로 저장하면 다음부터 변경을 알려 줍니다."}]}
        ch = []
        bv, cv = semver((base.get("cli") or {}).get("productVersion")), semver(cur["cli"].get("productVersion"))
        if bv and cv and bv != cv:
            ch.append({"level": "warn", "kind": "cli_version", "title": "커넥터 버전이 올라갔습니다", "detail": f"{bv} → {cv}"})
        removed = sorted(set(base.get("commands", [])) - set(cur["commands"]))
        added = sorted(set(cur["commands"]) - set(base.get("commands", [])))
        if removed:
            ch.append({"level": "error", "kind": "commands_removed", "title": f"명령 {len(removed)}개가 사라졌습니다",
                       "detail": ", ".join(removed)})
        if added:
            ch.append({"level": "info", "kind": "commands_added", "title": f"명령 {len(added)}개가 추가되었습니다",
                       "detail": ", ".join(added)})
        bodies = [f"{c}\n  기준: {b}\n  지금: {cur['bodyExamples'][c]}" for c, b in (base.get("bodyExamples") or {}).items()
                  if c in cur["bodyExamples"] and cur["bodyExamples"][c] != b]
        if bodies:
            ch.append({"level": "warn", "kind": "body_changed", "title": f"명령 본문 형식이 바뀌었습니다 ({len(bodies)}건)",
                       "detail": "\n".join(bodies)})
        bc, cc = base.get("costs") or {}, cur["costs"]
        costs = []
        for c in sorted(set(bc) | set(cc)):
            b, n = bc.get(c), cc.get(c)
            if b != n:
                costs.append(f"{c}: {f'{b['amount']} {b['currency']}' if b else '무료'} → {f'{n['amount']} {n['currency']}' if n else '무료'}")
        if costs:
            ch.append({"level": "error", "kind": "cost_changed", "title": "명령 소모 비용이 바뀌었습니다",
                       "detail": "\n".join(costs)})
        bs = base.get("specs")
        if not bs:  # 리모콘 기준선에는 없다 → 설명·응답 형식 변경은 판단할 수 없다고 알린다
            ch.append({"level": "info", "kind": "no_spec_baseline", "title": "설명·응답 형식은 비교하지 못했습니다",
                       "detail": "기준선이 옛 형식(리모콘)이라 명령 설명 지문이 없습니다. 정상 동작을 확인했으면 기준선을 새로 저장하세요."})
        if bs:
            specs = []
            for c, s in cur["specs"].items():
                old = bs.get(c)
                if old and old.get("hash") != s["hash"]:
                    specs.append(f"{c}\n  기준: {old.get('note')} / {old.get('output')}\n  지금: {s['note']} / {s['output']}")
            if specs:
                ch.append({"level": "warn", "kind": "spec_changed", "title": f"명령 설명·응답 형식이 바뀌었습니다 ({len(specs)}건)",
                           "detail": "\n\n".join(specs)})
        level = max((LEVELS.index(c["level"]) for c in ch), default=0)
        return {"level": LEVELS[level], "first_run": False, "changes": ch, "current": cur}
