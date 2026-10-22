"""GUI 실행. 게임이 관리자 권한으로 돌아 입력을 보내려면 이 프로그램도 관리자여야 하므로,
일반 권한으로 켜지면 UAC 로 자신을 다시 띄우고 끝난다."""
import ctypes
import sys


def _relaunch_as_admin() -> bool:
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in [sys.argv[0], *sys.argv[1:]])
    # ShellExecute 반환값이 32 보다 크면 성공. 사용자가 UAC 를 거절하면 일반 권한으로 그냥 연다
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32


if __name__ == "__main__":
    if "--no-elevate" not in sys.argv and _relaunch_as_admin():
        sys.exit(0)
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
