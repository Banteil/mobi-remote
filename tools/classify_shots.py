"""실패 화면(logs/shots)을 상황별로 판정해 보고, 시험 화면 폴더(tests/fixtures/screens/<상황>/)로 나눠 담는다.

    .venv\\Scripts\\python.exe tools\\classify_shots.py                 판정만 출력
    .venv\\Scripts\\python.exe tools\\classify_shots.py --copy          판정대로 복사 (이미 있는 이름은 건너뜀)
    .venv\\Scripts\\python.exe tools\\classify_shots.py 그림.png ...    특정 그림만

복사한 뒤에는 몇 장을 눈으로 보고 판정이 틀린 것은 맞는 상황 폴더로 옮긴다 — 폴더 이름이 정답이다.
화면에 캐릭터 이름이 보이므로 이 폴더는 저장소에 올리지 않는다 (.gitignore).
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mabi.monitor import offline  # noqa: E402

DST = ROOT / "tests" / "fixtures" / "screens"


def main(args: list[str]) -> None:
    copy = "--copy" in args
    files = [Path(a) for a in args if a != "--copy"] or sorted((ROOT / "logs" / "shots").glob("*.png"))
    cfg = offline.config()
    for p in files:
        what = offline.judge(offline.read(p), cfg)
        print(f"{what:15} {p.name}")
        if copy:
            dst = DST / what / p.name
            if not any(DST.glob(f"*/{p.name}")):
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)


if __name__ == "__main__":
    main(sys.argv[1:])
