r"""버튼 시험 화면(tests/fixtures/buttons/<템플릿>/yes|no/)을 담고 점수를 본다.

    .venv\Scripts\python.exe tools\button_fixture.py                      그림으로 못 찾은 화면(logs/shots/*_missed_*.png) 담기
    .venv\Scripts\python.exe tools\button_fixture.py <템플릿> 그림.png ...  그 버튼이 있는 화면으로 담기
    .venv\Scripts\python.exe tools\button_fixture.py <템플릿> --no 그림.png  그 버튼이 없는 화면으로 담기
    .venv\Scripts\python.exe tools\button_fixture.py --scores              담긴 화면마다 점수 (그림@2 등 더한 뒤 확인)

못 찾은 화면이 쌓이면 그중 한 장에서 버튼을 잘라 templates/<템플릿>@2.png 로 더하고 (tools/capture.py crop 뒤 이름 바꿈)
--scores 와 tests/test_buttons.py 로 다른 화면이 깨지지 않았는지 본다. 화면에 캐릭터 이름이 보여 저장소에 올리지 않는다.
"""
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mabi.monitor import offline  # noqa: E402
from mabi.vision import Vision  # noqa: E402

DST = ROOT / "tests" / "fixtures" / "buttons"
MISSED = re.compile(r"\d{8}_\d{6}_missed_(.+)\.png")


def add(name: str, src: Path, yes: bool = True) -> None:
    d = DST / name / ("yes" if yes else "no")
    d.mkdir(parents=True, exist_ok=True)
    if not (d / src.name).exists():
        shutil.copy2(src, d / src.name)
        print(f"담음 {name}/{d.name}/{src.name}")


def scores() -> None:
    v = offline.config()["vision"]
    vision = Vision(ROOT / "templates", v["threshold"], v["roi_margin"])
    for p in sorted(DST.glob("*/*/*.png")):
        name = p.parent.parent.name
        m = vision.best(cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR), name)
        th = vision.threshold_for(name, None)
        ok = (m is not None and m.score >= th) == (p.parent.name == "yes")
        print(f"{'OK ' if ok else 'BAD'} {name:24} {p.parent.name:3} {m.score if m else 0:.2f}/{th:.2f}  {p.name}")


def main(args: list[str]) -> None:
    if "--scores" in args:
        return scores()
    if not args:
        for p in sorted((ROOT / "logs" / "shots").glob("*_missed_*.png")):
            add(MISSED.fullmatch(p.name).group(1), p)
        return
    name, rest = args[0], args[1:]
    yes = "--no" not in rest
    for a in rest:
        if a != "--no":
            add(name, Path(a), yes)


if __name__ == "__main__":
    main(sys.argv[1:])
