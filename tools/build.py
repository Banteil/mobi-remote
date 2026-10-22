"""배포판 만들기: PyInstaller 로 dist\\mobi-remote\\ (폴더형) → Inno Setup 으로 dist\\mobi-remote-<판>-setup.exe.

    .venv\\Scripts\\python.exe tools\\build.py            # exe 폴더 + 설치 파일
    .venv\\Scripts\\python.exe tools\\build.py --no-setup # exe 폴더만

설치 파일 이름은 '...-setup.exe' 로 끝나야 한다 — 예전(2.x) 리모콘의 새 판 확인이 GitHub 최신 릴리스에서
이 이름의 파일을 받아 실행한다. 사용자 데이터는 설치 폴더가 아니라 %LOCALAPPDATA%\\MabiDaily 에 있어(mabi/paths.py)
새 판으로 덮어써도 남는다.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "mobi-remote"
ISCC = next((p for p in (Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
                         Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe") if p.exists()),
            Path("ISCC.exe"))


def version() -> str:
    m = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "gui_app" / "api.py").read_text(encoding="utf-8"))
    return m.group(1)


def pyinstaller() -> Path:
    sep = ";"
    datas = [("web", "web"), ("templates", "templates"), ("data", "data"), ("config.default.toml", ".")]
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", NAME, "--icon", str(ROOT / "tools" / "icon.ico"),
            "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
            # 게임 입력을 보내려면 관리자여야 한다 (gui.py 가 UAC 로 다시 띄우지만, exe 는 처음부터 관리자로)
            "--uac-admin",
            "--collect-all", "rapidocr",          # OCR 모델(.onnx)·설정(.yaml)
            "--collect-submodules", "winrt",      # Windows OCR
            "--collect-all", "winrt",
            "--hidden-import", "tomllib",
            # 쓰지 않는 무거운 것 (예전 pywebview 화면 등)
            "--exclude-module", "webview", "--exclude-module", "clr_loader", "--exclude-module", "pythonnet",
            "--exclude-module", "tkinter"]
    for src, dst in datas:
        args += ["--add-data", f"{ROOT / src}{sep}{dst}"]
    args.append(str(ROOT / "gui.py"))
    subprocess.run(args, check=True, cwd=ROOT)
    out = ROOT / "dist" / NAME
    # 안 쓰는 큰 파일 (웹 개발자 도구 리소스 80MB+, OpenCV 동영상 ffmpeg 30MB)
    for pat in ("*devtools_resources*.pak", "opencv_videoio_ffmpeg*.dll"):
        for f in out.rglob(pat):
            f.unlink()
    # 사용자 데이터가 섞여 들어가지 않았는지 (data\ 는 제작 레시피 같은 리소스만)
    for bad in ("profile.json", "state", "queue.json", "config.toml"):
        hits = list(out.rglob(bad))
        if hits:
            raise SystemExit(f"개인 데이터가 묶임: {hits}")
    return out


def installer(ver: str) -> Path:
    if not ISCC.exists():
        raise SystemExit(f"Inno Setup 이 없습니다: {ISCC}")
    subprocess.run([str(ISCC), f"/DAppVersion={ver}", f"/DSourceDir={ROOT / 'dist' / NAME}",
                    f"/DOutputDir={ROOT / 'dist'}", str(ROOT / "tools" / "installer.iss")], check=True)
    return ROOT / "dist" / f"{NAME}-{ver}-setup.exe"


if __name__ == "__main__":
    ver = version()
    shutil.rmtree(ROOT / "dist" / NAME, ignore_errors=True)
    print("exe 폴더:", pyinstaller())
    if "--no-setup" not in sys.argv:
        print("설치 파일:", installer(ver))
