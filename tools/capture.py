"""템플릿 제작 도구.

  python tools/capture.py snap                 게임 중 F9 = 스크린샷 저장, F10 = 종료
  python tools/capture.py crop <png> <name>    스크린샷에서 드래그로 영역 선택 → templates/<name>.png
                                               (--rect x,y,w,h 로 영역 직접 지정 가능)
  python tools/capture.py test <name> [--image <png>]   매칭 점수 확인 (기본: 현재 게임 화면)
  python tools/capture.py missing              config.toml 이 참조하는데 아직 없는 템플릿 목록
  python tools/capture.py digits silver 17 [--image <png>]   재화 숫자 샘플 등록 (보이는 값을 입력)
  python tools/capture.py read [--image <png>]                재화 숫자 판독 테스트
"""
import argparse
import json
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mabi.digits import DigitReader  # noqa: E402
from mabi.inputs import key_pressed, vk_of  # noqa: E402
from mabi.screen import Screen  # noqa: E402
from mabi.vision import Vision  # noqa: E402
from mabi.window import GameWindow  # noqa: E402

TEMPLATES = ROOT / "templates"
CAPTURES = ROOT / "captures"


def load_cfg() -> dict:
    from mabi.runner import _merged  # config.toml 은 기본값과 다른 값만 담는다 (mabi.userconfig)
    return _merged(tomllib.loads((ROOT / "config.default.toml").read_text(encoding="utf-8")),
                   tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8")))


def imread(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"이미지를 읽을 수 없습니다: {path}")
    return img


def imwrite(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(path.suffix, img)[1].tofile(str(path))


def cmd_snap(_args) -> None:
    cfg = load_cfg()
    screen = Screen(GameWindow(cfg["game"]["window_title"]))
    f9, f10 = vk_of("f9"), vk_of("f10")
    print("게임 화면에서 F9 = 저장, F10 = 종료")
    while not key_pressed(f10):
        if key_pressed(f9):
            path = CAPTURES / f"{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            imwrite(path, screen.grab())
            print(f"저장: {path}")
            while key_pressed(f9):
                time.sleep(0.05)
        time.sleep(0.05)


def cmd_crop(args) -> None:
    img = imread(Path(args.image))
    if args.rect:
        x, y, w, h = map(int, args.rect.split(","))
    else:
        win = f"drag to select '{args.name}' - Enter/Space confirm, C cancel"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 1600, 900)
        x, y, w, h = map(int, cv2.selectROI(win, img, showCrosshair=False))
        cv2.destroyAllWindows()
    if w == 0 or h == 0:
        sys.exit("취소됨")
    imwrite(TEMPLATES / f"{args.name}.png", img[y:y + h, x:x + w])

    index_path = TEMPLATES / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    entry = {"roi": [x, y, w, h]}
    if args.anywhere:
        entry = {}  # 화면 어디서든 나타날 수 있는 템플릿 (예: 목록의 '받기' 버튼)
    if args.threshold:
        entry["threshold"] = args.threshold
    index[args.name] = entry
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"저장: templates/{args.name}.png  roi={[x, y, w, h]}{' (전체 탐색)' if args.anywhere else ''}")


def cmd_test(args) -> None:
    cfg = load_cfg()
    if args.image:
        frame = imread(Path(args.image))
    else:
        frame = Screen(GameWindow(cfg["game"]["window_title"])).grab()
    vision = Vision(TEMPLATES, cfg["vision"]["threshold"], cfg["vision"]["roi_margin"])
    tpl = vision.template(args.name)
    # 임계값 무시하고 최고 점수 위치를 보여준다
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    _, best, _, (bx, by) = cv2.minMaxLoc(res)
    m = vision.find(frame, args.name)
    th = vision.threshold_for(args.name, None)
    print(f"전체 화면 최고 점수 {best:.3f} at ({bx}, {by})  임계값 {th}")
    print(f"설정 기준 매칭: {'O ' + f'{m.score:.3f} at {m.center}' if m else 'X'}")
    out = frame.copy()
    th_, tw = tpl.shape[:2]
    cv2.rectangle(out, (bx, by), (bx + tw, by + th_), (0, 255, 0) if m else (0, 0, 255), 2)
    path = CAPTURES / f"test_{args.name}.png"
    imwrite(path, out)
    print(f"결과 이미지: {path}")


def _frame(cfg: dict, image: str | None) -> np.ndarray:
    if image:
        return imread(Path(image))
    return Screen(GameWindow(cfg["game"]["window_title"])).grab()


def cmd_digits(args) -> None:
    """스크린샷 속 재화 숫자를 사람이 알려준 값으로 라벨링해 숫자 샘플로 저장."""
    cfg = load_cfg()
    reader = DigitReader(TEMPLATES / "digits", cfg["counters"]["white_threshold"])
    glyphs = reader.segment(_frame(cfg, args.image), cfg["counters"][args.counter])
    if len(glyphs) != len(args.value):
        sys.exit(f"글자 {len(glyphs)}개를 찾았는데 값 '{args.value}' 는 {len(args.value)}자리입니다. 영역/임계값 확인 필요")
    for d, g in zip(args.value, glyphs):
        label, diff = reader.classify(g)
        if label == d and diff < 0.08:
            print(f"  {d}: 기존 샘플과 거의 같음 (diff {diff:.3f}), 건너뜀")
            continue
        n = len(list((TEMPLATES / "digits").glob(f"{d}_*.png")))
        imwrite(TEMPLATES / "digits" / f"{d}_{n}.png", g)
        print(f"  {d}: 저장 digits/{d}_{n}.png")


def cmd_read(args) -> None:
    cfg = load_cfg()
    reader = DigitReader(TEMPLATES / "digits", cfg["counters"]["white_threshold"])
    frame = _frame(cfg, args.image)
    for name in ("silver", "tribute"):
        glyphs = reader.segment(frame, cfg["counters"][name])
        detail = [reader.classify(g) for g in glyphs]
        print(f"{name}: {reader.read(frame, cfg['counters'][name])}  "
              f"{[(lb, round(df, 3)) for lb, df in detail]}")


def referenced_templates(cfg: dict) -> list[str]:
    names: list[str] = []

    def add(v):
        if isinstance(v, str) and v:
            names.append(v)
        elif isinstance(v, list):
            for x in v:
                add(x)

    for k, v in cfg["ui"].items():
        add(v)
    dm = cfg["daily_mission"]
    for k in ("open_steps", "claim_all", "claim", "milestone_claim", "incomplete"):
        add(dm.get(k))
    for section, keys in {"weekday_dungeon": ("tag", "go", "dungeon_tab"),
                          "silver": (),
                          "tribute": ("quest_card", "quest_go", "dungeon_tab", "very_hard"),
                          "black_hole": ("card",)}.items():
        for k in keys:
            add(cfg[section].get(k))
    return list(dict.fromkeys(names))


def cmd_missing(_args) -> None:
    names = referenced_templates(load_cfg())
    missing = [n for n in names if not (TEMPLATES / f"{n}.png").exists()]
    print(f"참조된 템플릿 {len(names)}개 중 {len(missing)}개 없음")
    for n in missing:
        print(f"  - {n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snap").set_defaults(fn=cmd_snap)
    p = sub.add_parser("crop")
    p.add_argument("image")
    p.add_argument("name")
    p.add_argument("--threshold", type=float)
    p.add_argument("--anywhere", action="store_true", help="위치 고정 없이 화면 전체에서 탐색")
    p.add_argument("--rect", help="드래그 대신 영역 지정: x,y,w,h")
    p.set_defaults(fn=cmd_crop)
    p = sub.add_parser("test")
    p.add_argument("name")
    p.add_argument("--image")
    p.set_defaults(fn=cmd_test)
    sub.add_parser("missing").set_defaults(fn=cmd_missing)
    p = sub.add_parser("digits", help="숫자 샘플 등록")
    p.add_argument("counter", choices=["silver", "tribute"])
    p.add_argument("value", help="화면에 보이는 현재값 (예: 17)")
    p.add_argument("--image")
    p.set_defaults(fn=cmd_digits)
    p = sub.add_parser("read", help="재화 숫자 판독 테스트")
    p.add_argument("--image")
    p.set_defaults(fn=cmd_read)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
