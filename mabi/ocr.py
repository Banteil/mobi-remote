"""Windows 내장 OCR(한국어)로 화면의 흰 글자를 읽는다.

버튼 글자처럼 큰 글자는 정확하지만, 던전 구역 라벨 같은 작은 픽셀 글꼴은 놓치므로
그런 곳은 템플릿을 쓰고 OCR 은 결과 확인용으로만 쓴다.
"""
import asyncio

import cv2
import numpy as np

# onnxruntime(PaddleOCR 인식기)은 winrt 보다 먼저 불러와야 한다 — 반대 순서면 프로세스가 통째로 죽는다
# (Segmentation fault, 2026-10-21 onnxruntime 1.31 + winrt). 그래서 쓰기 전이라도 여기서 먼저 올린다.
try:
    import onnxruntime  # noqa: F401
except ImportError:
    pass
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

_engine = None


def _bitmap(gray: np.ndarray) -> SoftwareBitmap:
    bgra = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGRA)
    h, w = bgra.shape[:2]
    dw = DataWriter()
    dw.write_bytes(bgra.tobytes())
    return SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)


async def _recognize(gray: np.ndarray) -> str:
    global _engine
    if _engine is None:
        _engine = OcrEngine.try_create_from_language(Language("ko"))
    return (await _engine.recognize_async(_bitmap(gray))).text


def read_text(frame: np.ndarray, region, white: int = 200, scale: int = 2) -> str:
    """region [x, y, w, h] 안의 흰 글자(모든 채널이 white 이상)를 읽는다."""
    x, y, w, h = region
    crop = frame[y:y + h, x:x + w]
    mask = (crop.min(axis=2) >= white).astype(np.uint8) * 255
    gray = 255 - cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    gray = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return asyncio.run(_recognize(gray)).strip()


# ---------------------------------------------------------------- PaddleOCR(RapidOCR) 한국어
# 나눠 쓰는 기준 (2026-10-21 저장 화면 비교):
#   한글  → RapidOCR (PP-OCRv5 한국어). 게임 글꼴에서 Windows OCR 보다 훨씬 정확 ('임무ÅI작' → '임무 시작',
#            '화면을 E*자6H' → '화면을 터치해'). 대신 띄어쓰기를 자주 빠뜨리므로 비교할 땐 공백을 빼고 한다.
#   숫자·영어 → Windows OCR (read_text). RapidOCR 은 버튼 앞 동전 아이콘에 헷갈려 '20 입장하기' 의 숫자를
#            빠뜨린다 ('“  0 입장하'). 가격 확인 같은 숫자는 read_text 로.
# 글자 위치 찾기(det)는 느리고 놓치기도 해서, 줄 위치는 우리가 찾고 '한 줄 읽기(rec)' 만 맡긴다 (한 줄 0.04초).
_rapid = None


def _rapid_engine():
    global _rapid
    if _rapid is None:
        import logging as _lg
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        _rapid = RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                                  "Rec.model_type": ModelType.MOBILE})
        _lg.getLogger("RapidOCR").setLevel(_lg.WARNING)
    return _rapid


def read_line(img: np.ndarray) -> tuple[str, float]:
    """한글 한 줄 그림(BGR) → (글자, 확신도 0..1). 인식기가 없으면 Windows OCR 로 (확신도 0)."""
    try:
        # 엔진이 use_det 를 직전 호출 값으로 기억하므로 매번 다 적는다
        r = _rapid_engine()(img, use_det=False, use_cls=False, use_rec=True)
        return (r.txts[0] if r.txts else "").strip(), float(r.scores[0]) if r.scores else 0.0
    except ImportError:
        gray = 255 - ((img.min(axis=2) >= 200).astype(np.uint8) * 255)
        gray = cv2.copyMakeBorder(cv2.resize(gray, None, fx=2, fy=2), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        return asyncio.run(_recognize(gray)).strip(), 0.0


def read_ko(frame: np.ndarray, region) -> str:
    """region [x, y, w, h] 안의 한글 한 줄 (RapidOCR). read_text 와 같은 자리에 쓰는 한글용."""
    x, y, w, h = region
    x, y = max(0, x), max(0, y)
    return read_line(frame[y:y + h, x:x + w])[0]


def nospace(t: str) -> str:
    return "".join(t.split())


def read_lines(img: np.ndarray) -> list[tuple[str, float, int]]:
    """영역 안 글자 줄들을 찾아 읽는다 → [(글자, 확신도, 줄 위 y)] 위→아래. 느리다(장당 1~2초) — 대비책으로만."""
    try:
        r = _rapid_engine()(img, use_det=True, use_cls=False, use_rec=True)
    except ImportError:
        return []
    if getattr(r, "boxes", None) is None or not r.txts:
        return []
    out = [(t.strip(), float(s), int(min(p[1] for p in b))) for b, t, s in zip(r.boxes, r.txts, r.scores)]
    return sorted(out, key=lambda x: x[2])


def find_texts(frame: np.ndarray, region=None) -> list[tuple[str, int, int]]:
    """region [x, y, w, h] (없으면 화면 전체) 안 글자 덩어리들 → [(글자, 가운데 x, 가운데 y)] 화면 좌표.
    UI 배율이 바뀌어 템플릿·고정 좌표가 안 맞는 화면(환경 설정 등)에서 버튼을 글자로 찾을 때 쓴다. 1~3초."""
    x, y, w, h = region or (0, 0, frame.shape[1], frame.shape[0])
    try:
        r = _rapid_engine()(frame[y:y + h, x:x + w], use_det=True, use_cls=False, use_rec=True)
    except ImportError:
        return []
    if getattr(r, "boxes", None) is None or not r.txts:
        return []
    return [(t.strip(), int(sum(p[0] for p in b) / 4) + x, int(sum(p[1] for p in b) / 4) + y)
            for b, t in zip(r.boxes, r.txts)]
