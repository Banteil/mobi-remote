"""실행 리포트(logs/runs/*.json) 요약과 진단 파일 내보내기. 콘솔은 tools/report.py, GUI 는 기록 탭에서 쓴다.

  python tools/report.py                 최근 실행들의 숙제별 성공률, 자주 나온 실패, 평균 소요 시간
  python tools/report.py --last          가장 최근 실행 하나를 자세히
  python tools/report.py --days 7        최근 7일만
  python tools/report.py --export        최근 실행 리포트 + 그날 로그 + 관련 스크린샷을 zip 하나로 (logs/export_*.zip)
  python tools/report.py --export --anon 캐릭터 이름을 슬롯 번호로 바꿔서 내보내기
"""
import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import paths as mpaths

PATHS = RUNS = SHOTS = None


def use(paths: "mpaths.Paths | None" = None) -> None:
    """리포트를 읽고 쓸 경로를 정한다 (기본: mpaths.load())."""
    global PATHS, RUNS, SHOTS
    PATHS = paths or mpaths.load()
    RUNS, SHOTS = PATHS.runs, PATHS.shots
SHOT_RE = re.compile(r"\d{8}_\d{6}_[\w\-]+\.png")


def load_runs(days: int | None) -> list[dict]:
    if RUNS is None:
        use()
    runs = []
    cutoff = datetime.now() - timedelta(days=days) if days else None
    for f in sorted(RUNS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if cutoff and datetime.fromisoformat(d["started"]) < cutoff:
            continue
        d["_file"] = f
        runs.append(d)
    return runs


def _short(msg: str) -> str:
    """실패 메시지에서 스크린샷 이름·숫자를 빼서 같은 종류끼리 묶는다."""
    msg = SHOT_RE.sub("", msg).replace("→", "").strip()
    return re.sub(r"\d+", "N", msg)[:90]


def summarize(runs: list[dict]) -> None:
    if not runs:
        print("리포트가 없습니다 (logs/runs).")
        return
    stat = defaultdict(Counter)
    secs = defaultdict(list)
    fails = defaultdict(Counter)
    events = Counter()
    for r in runs:
        for ch in r["characters"]:
            for t in ch["tasks"]:
                st = t.get("status") or "중단됨"
                stat[t["id"]][st] += 1
                if t.get("seconds") is not None and st == "OK":
                    secs[t["id"]].append(t["seconds"])
                if st not in ("OK", "DONE"):
                    fails[t["id"]][_short(t.get("summary") or "")] += 1
                for e in t.get("events", []):
                    events[(t["id"], _short(e["message"]))] += 1
    print(f"실행 {len(runs)}회  ({runs[0]['started']} ~ {runs[-1]['started']})\n")
    print(f"{'숙제':16} {'성공/전체':>9} {'평균(초)':>8}  결과")
    for tid, c in stat.items():
        total = sum(c.values())
        avg = sum(secs[tid]) / len(secs[tid]) if secs[tid] else 0
        print(f"{tid:16} {c['OK']:>4}/{total:<4} {avg:>8.0f}  {dict(c)}")
    print("\n자주 나온 실패")
    for tid, c in fails.items():
        for msg, n in c.most_common(3):
            print(f"  {tid:14} {n}회  {msg}")
    print("\n자주 나온 경고")
    for (tid, msg), n in events.most_common(10):
        print(f"  {tid:14} {n}회  {msg}")


def detail(r: dict) -> None:
    print(f"{r['_file'].name}  v{r['version']}  {r['started']} ~ {r.get('finished') or '(끝나지 않음)'}")
    env = r["env"]
    print(f"환경: 창 {env.get('client_size')}  관리자 {env.get('admin')}  CLI {env.get('cli')}  {env.get('os')}")
    for ch in r["characters"]:
        print(f"\n[{ch['slot']}] {ch['name']}")
        for t in ch["tasks"]:
            b, a = t.get("before") or {}, t.get("after") or {}
            delta = ", ".join(f"{k} {b.get(k)}→{a.get(k)}" for k in ("silver", "tribute") if b.get(k) != a.get(k))
            print(f"  {t['id']:16} {t.get('status') or '중단됨':6} {t.get('seconds') or 0:>5}s  {t.get('summary') or ''}"
                  + (f"  ({delta})" if delta else ""))
            for e in t.get("events", []):
                print(f"      {e['time']} {e['kind']}: {e['message']}")
    for e in r.get("events", []):
        print(f"  {e['time']} {e['kind']}: {e['message']}")


def export(runs: list[dict], anon: bool) -> Path:
    out = PATHS.logs / f"export_{datetime.now():%Y%m%d_%H%M%S}.zip"
    names = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        days = set()
        for r in runs:
            text = r["_file"].read_text(encoding="utf-8")
            for ch in r["characters"]:
                if ch.get("name"):
                    names[ch["name"]] = f"slot{ch['slot']}"
            for shot in set(SHOT_RE.findall(text)):
                if (SHOTS / shot).exists():
                    z.write(SHOTS / shot, f"shots/{shot}")
            days.add(r["started"][:10].replace("-", ""))
            z.writestr(f"runs/{r['_file'].name}", _anon(text, names) if anon else text)
        for d in days:
            log = PATHS.logs / f"{d}.log"
            if log.exists():
                text = log.read_text(encoding="utf-8", errors="replace")
                z.writestr(f"logs/{log.name}", _anon(text, names) if anon else text)
        cfg = PATHS.config
        if cfg.exists():
            z.write(cfg, "config.toml")
    return out


def _anon(text: str, names: dict) -> str:
    for name, slot in names.items():
        text = text.replace(name, slot)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--last", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--anon", action="store_true")
    ap.add_argument("--runs", type=int, default=5, help="--export 때 넣을 최근 실행 수")
    args = ap.parse_args()
    use()
    runs = load_runs(args.days)
    if args.export:
        print(f"저장: {export(runs[-args.runs:], args.anon)}")
    elif args.last:
        if runs:
            detail(runs[-1])
    else:
        summarize(runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
