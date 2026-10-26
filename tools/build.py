"""배포판 만들기: PyInstaller 로 dist\\mobi-remote\\ (폴더형) → Inno Setup 으로 dist\\mobi-remote-<판>-setup.exe,
그리고 app\\ 만 담은 패치 dist\\mobi-remote-<판>-patch-<구성>.zip.

    .venv\\Scripts\\python.exe tools\\build.py            # exe 폴더 + 설치 파일 + 패치
    .venv\\Scripts\\python.exe tools\\build.py --no-setup # exe 폴더 + 패치

설치 폴더:
    mobi-remote.exe, _internal\\   파이썬·Qt·OpenCV·OCR (런타임, 약 680MB) — 설치 파일로만 바뀐다
    runtime.txt                   런타임 구성 값 (아래)
    app\\                          우리 코드(mabi, gui_app)·web·data·templates·config.default.toml, version.json,
                                  packet.key (패킷 상태 표 키 — 저장소엔 없고 개발 PC 에서 넣는다)
                                  — 패치로 통째로 갈아 끼운다 (gui.py)
구성 값은 파이썬 판, 설치된 패키지 판, exe 에 묶인 모듈 목록, _internal 파일 목록, gui.py 내용의 해시다.
새 코드가 전에 없던 표준 모듈을 쓰거나 패키지를 올리면 값이 바뀌고, 그러면 새 판 확인이 패치 대신 설치 파일을 받는다.
릴리스에는 설치 파일과 패치를 둘 다 올린다.

설치 파일 이름은 '...-setup.exe' 로 끝나야 한다 — 예전(2.x) 리모콘의 새 판 확인이 GitHub 최신 릴리스에서
이 이름의 파일을 받아 실행한다. 사용자 데이터는 설치 폴더가 아니라 %LOCALAPPDATA%\\MabiDaily 에 있어(mabi/paths.py)
새 판으로 덮어써도 남는다.
"""
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "mobi-remote"
ISCC = next((p for p in (Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
                         Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe") if p.exists()),
            Path("ISCC.exe"))
APP_PACKAGES = ("mabi", "gui_app")
APP_FILES = (*APP_PACKAGES, "web", "data", "templates", "config.default.toml")


def version() -> str:
    m = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "gui_app" / "api.py").read_text(encoding="utf-8"))
    return m.group(1)


def pyinstaller() -> Path:
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", NAME, "--icon", str(ROOT / "tools" / "icon.ico"),
            "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
            # 게임 입력을 보내려면 관리자여야 한다 (gui.py 가 UAC 로 다시 띄우지만, exe 는 처음부터 관리자로)
            "--uac-admin",
            "--collect-all", "rapidocr",          # OCR 모델(.onnx)·설정(.yaml)
            "--collect-submodules", "winrt",      # Windows OCR
            "--collect-all", "winrt",
            "--hidden-import", "tomllib",
            # 우리 코드는 app\\ 에서 읽지만, 그 코드가 쓰는 표준·외부 모듈을 묶으려면 분석에는 넣어야 한다
            *[a for p in APP_PACKAGES for a in ("--collect-submodules", p)],
            # 쓰지 않는 무거운 것 (예전 pywebview 화면 등)
            "--exclude-module", "webview", "--exclude-module", "clr_loader", "--exclude-module", "pythonnet",
            "--exclude-module", "tkinter",
            # 시험·분류 도구용 (unittest.mock 을 쓴다) — 묶으면 unittest 가 딸려 와 구성 값이 바뀌어 패치 대신 설치 파일이 된다
            "--exclude-module", "mabi.monitor.offline"]
    args.append(str(ROOT / "gui.py"))
    subprocess.run(args, check=True, cwd=ROOT)
    out = ROOT / "dist" / NAME
    # 안 쓰는 큰 파일 (웹 개발자 도구 리소스 80MB+, OpenCV 동영상 ffmpeg 30MB)
    for pat in ("*devtools_resources*.pak", "opencv_videoio_ffmpeg*.dll"):
        for f in out.rglob(pat):
            f.unlink()
    return out


def runtime_id(out: Path) -> str:
    """패치를 써도 되는지 가르는 값. 이 값이 같은 설치에만 app\\ 패치를 넣는다."""
    pyz = ast.literal_eval((ROOT / "build" / NAME / "PYZ-00.toc").read_text(encoding="utf-8"))[1]
    mods = sorted(m[0] for m in pyz if m[0].partition(".")[0] not in APP_PACKAGES)
    files = sorted(str(f.relative_to(out)).lower() for f in (out / "_internal").rglob("*") if f.is_file())
    dists = sorted(f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions())
    h = hashlib.sha256()
    for part in (sys.version, (ROOT / "gui.py").read_bytes().decode("utf-8"), *mods, *files, *dists):
        h.update(part.encode("utf-8") + b"\n")
    return h.hexdigest()[:12]


def app_dir(out: Path, ver: str, runtime: str) -> Path:
    """git 이 아는 파일만 (무시 목록에 있는 개인 설정·캐시는 빠진다) app\\ 으로 복사한다."""
    app = out / "app"
    shutil.rmtree(app, ignore_errors=True)
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", *APP_FILES],
                            cwd=ROOT, check=True, capture_output=True).stdout.decode("utf-8").split("\0")
    for rel in filter(None, listed):
        src = ROOT / rel
        if src.is_file() and src.suffix != ".pyc":
            (app / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, app / rel)
    # 패킷 상태 표 키는 저장소에 없다 (mabi/packet_table.py) — 개발 PC 의 것을 직접 넣는다
    key = ROOT / "packet.key"
    if not key.exists():
        raise SystemExit(f"패킷 상태 표 키가 없습니다: {key} (mabi-packets\\packet.key.backup 에서 복사)")
    shutil.copy2(key, app / key.name)
    (app / "version.json").write_text(json.dumps({"version": ver, "runtime": runtime}), encoding="utf-8")
    (out / "runtime.txt").write_text(runtime, encoding="utf-8")
    # 사용자 데이터가 섞여 들어가지 않았는지 (data\\ 는 제작 레시피 같은 리소스만)
    for bad in ("profile.json", "state", "queue.json", "config.toml", "display_restore.json"):
        hits = list(out.rglob(bad))
        if hits:
            raise SystemExit(f"개인 데이터가 묶임: {hits}")
    return app


def patch(app: Path, ver: str, runtime: str) -> Path:
    z = ROOT / "dist" / f"{NAME}-{ver}-patch-{runtime}.zip"
    for old in (ROOT / "dist").glob(f"{NAME}-{ver}-patch-*.zip"):
        old.unlink()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(app).as_posix())
    return z


def installer(ver: str) -> Path:
    if not ISCC.exists():
        raise SystemExit(f"Inno Setup 이 없습니다: {ISCC}")
    subprocess.run([str(ISCC), f"/DAppVersion={ver}", f"/DSourceDir={ROOT / 'dist' / NAME}",
                    f"/DOutputDir={ROOT / 'dist'}", str(ROOT / "tools" / "installer.iss")], check=True)
    return ROOT / "dist" / f"{NAME}-{ver}-setup.exe"


if __name__ == "__main__":
    ver = version()
    shutil.rmtree(ROOT / "dist" / NAME, ignore_errors=True)
    out = pyinstaller()
    rt = runtime_id(out)
    print("exe 폴더:", out, "· 구성", rt)
    print("패치:", patch(app_dir(out, ver, rt), ver, rt))
    if "--no-setup" not in sys.argv:
        print("설치 파일:", installer(ver))
