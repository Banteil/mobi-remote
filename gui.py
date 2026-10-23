"""GUI 실행. 게임이 관리자 권한으로 돌아 입력을 보내려면 이 프로그램도 관리자여야 하므로,
일반 권한으로 켜지면 UAC 로 자신을 다시 띄우고 끝난다.

exe(설치판)에서는 우리 코드(mabi, gui_app)와 web·data·templates 를 exe 안이 아니라 설치 폴더의 app\\ 에서 읽는다.
새 판이 파이썬·라이브러리 구성(runtime.txt)이 같으면 app\\ 만 갈아 끼우는 패치(수 MB)로 끝난다 (gui_app/api.py 새 판 확인).
이 파일은 exe 안에 묶여 패치로 바뀌지 않으므로 여기에는 패치 적용과 경로 잡기만 둔다."""
import ctypes
import sys
from pathlib import Path

APP_PACKAGES = ("mabi", "gui_app")


def _relaunch_as_admin() -> bool:
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in [sys.argv[0], *sys.argv[1:]])
    # ShellExecute 반환값이 32 보다 크면 성공. 사용자가 UAC 를 거절하면 일반 권한으로 그냥 연다
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32


def _wait_pid() -> None:
    """패치를 받은 앞 프로그램이 '--wait-pid N' 으로 이 프로그램을 띄우고 꺼진다. 다 꺼질 때까지 기다린다 (최대 30초)."""
    if "--wait-pid" not in sys.argv:
        return
    i = sys.argv.index("--wait-pid")
    try:
        pid = int(sys.argv[i + 1])
    except (IndexError, ValueError):
        return
    del sys.argv[i:i + 2]
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        k.WaitForSingleObject(h, 30000)
        k.CloseHandle(h)


def _apply_patch(home: Path) -> None:
    """update\\patch.zip 이 있으면 app\\ 을 그것으로 바꾼다. 실패하면 지금 app\\ 그대로 켠다 (이유는 update\\patch-error.txt)."""
    import json
    import shutil
    import zipfile
    zf, app = home / "update" / "patch.zip", home / "app"
    if not zf.is_file():
        return
    new, old = home / "app.new", home / "app.old"
    try:
        shutil.rmtree(new, ignore_errors=True)
        with zipfile.ZipFile(zf) as z:
            z.extractall(new)
        meta = json.loads((new / "version.json").read_text(encoding="utf-8"))
        runtime = (home / "runtime.txt").read_text(encoding="utf-8").strip()
        if meta.get("runtime") != runtime:
            raise RuntimeError(f"구성이 다른 패치 ({meta.get('runtime')} ≠ {runtime}) — 설치 파일로 받아야 함")
        shutil.rmtree(old, ignore_errors=True)
        if app.exists():
            app.rename(old)
        new.rename(app)
        shutil.rmtree(old, ignore_errors=True)
        (home / "update" / "patch-error.txt").unlink(missing_ok=True)
    except Exception as e:
        if not app.exists() and old.exists():
            old.rename(app)
        shutil.rmtree(new, ignore_errors=True)
        (home / "update" / "patch-error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
    finally:
        zf.unlink(missing_ok=True)


class _AppFinder:
    """mabi·gui_app 은 exe 안에 묶인 것보다 app\\ 의 파일을 먼저 쓴다 (sys.meta_path 맨 앞)."""

    def __init__(self, app: Path):
        self.app = str(app)

    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] not in APP_PACKAGES:
            return None
        from importlib.machinery import PathFinder
        return PathFinder.find_spec(name, path if "." in name else [self.app])


def _use_app_dir() -> None:
    if not getattr(sys, "frozen", False):
        return
    home = Path(sys.executable).resolve().parent
    _wait_pid()
    _apply_patch(home)
    app = home / "app"
    if (app / "mabi").is_dir() and (app / "gui_app").is_dir():
        sys.meta_path.insert(0, _AppFinder(app))


if __name__ == "__main__":
    if "--no-elevate" not in sys.argv and _relaunch_as_admin():
        sys.exit(0)
    _use_app_dir()
    # pythonw 는 콘솔이 없어 네이티브 충돌(Qt 등) 때 흔적이 안 남는다 → 모든 스레드의 파이썬 스택을 파일로
    import faulthandler
    from mabi import paths as _mp
    _crash = _mp.load().logs / "crash.log"  # exe 는 설치 폴더가 아니라 데이터 폴더의 logs\
    _crash.parent.mkdir(parents=True, exist_ok=True)
    faulthandler.enable(open(_crash, "a", encoding="utf-8"), all_threads=True)
    # 숙제 중 Qt6WebEngineCore 가 같은 자리(0xd03880)에서 두 번 죽음 (2026-10-22, 게임 로딩 직후).
    # 게임과 GPU 를 나눠 쓰는 경로가 의심돼 화면은 소프트웨어로 그린다 (UI 가 단순해 느려지지 않음)
    import os
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    from gui_app.web_main import main
    sys.exit(main())
