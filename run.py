"""일일 숙제 실행기 (콘솔). GUI 는 gui.py.

  python run.py                 profile.json 의 슬롯마다 접속 후 run.order 순서대로 실행
                                (profile.json 이 없으면 숙제할 슬롯 번호를 먼저 물어본다)
  python run.py --setup         숙제할 슬롯 번호 다시 입력
  python run.py --only silver,daily_mission
  python run.py --chars 5,6     일부 슬롯만
  python run.py --current       캐릭터 전환 없이 지금 접속한 캐릭터로만
  python run.py --force         오늘 이미 끝낸 숙제도 다시 실행
  python run.py --dry-run       인식만 하고 실제 클릭/키 입력은 하지 않음 (템플릿 점검용)
  python run.py --list          태스크 목록
"""
import argparse
import sys

from mabi import paths as mpaths
from mabi import profile as prof
from mabi import tasks
from mabi.runner import RunOptions, Runner, load_config, setup_logging


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="쉼표로 구분한 태스크 id")
    ap.add_argument("--chars", help="쉼표로 구분한 슬롯 번호")
    ap.add_argument("--current", action="store_true", help="현재 캐릭터로만 실행")
    ap.add_argument("--setup", action="store_true", help="숙제할 슬롯 번호 다시 입력")
    ap.add_argument("--force", action="store_true", help="오늘 끝낸 숙제도 다시 실행")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    paths = mpaths.load()
    cfg = load_config(paths)
    if args.list:
        for tid, (label, _) in tasks.build(cfg).items():
            print(f"{tid:20} {label}")
        return 0
    if not args.current and (args.setup or prof.load_profile(paths.profile) is None):
        prof.ask_profile(paths.profile, prof.load_profile(paths.profile))
        if args.setup:
            return 0

    setup_logging(paths)
    opts = RunOptions(
        chars=[int(x) for x in args.chars.split(",")] if args.chars else None,
        only=args.only.split(",") if args.only else None,
        current=args.current, force=args.force, dry_run=args.dry_run,
    )
    try:
        results = Runner(paths).run(opts)
    except ValueError as e:
        print(e)
        return 2
    return 0 if all(s in ("OK", "DONE") for _, s, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
