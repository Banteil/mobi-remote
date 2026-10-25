"""시험용 화면 만들기: 실제 캡처에서 시험이 읽는 영역(data/ui.json regions)만 남기고 나머지는 검게 지운다.
캡처 원본은 캐릭터 이름이 보여 저장소에 못 올린다 — 이름이 없는 영역만 남긴 것을 tests/fixtures 에 넣는다.

    .venv\\Scripts\\python.exe tools\\make_fixture.py captures\\abyss\\<원본>.png abyss_entry abyss_entry_top abyss_entry_right

남긴 영역에 이름이 들어가지 않았는지 결과 그림을 꼭 눈으로 확인한다.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mabi import gamedata as gd  # noqa: E402


def main(src: str, name: str, *regions: str) -> Path:
    img = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR)
    out = np.zeros_like(img)
    for key in regions:
        x, y, w, h = gd.region(key)
        out[y:y + h, x:x + w] = img[y:y + h, x:x + w]
    dst = ROOT / "tests" / "fixtures" / f"{name}.png"
    dst.parent.mkdir(exist_ok=True)
    ok, buf = cv2.imencode(".png", out)
    dst.write_bytes(buf.tobytes())
    return dst


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    print(main(*sys.argv[1:]))
