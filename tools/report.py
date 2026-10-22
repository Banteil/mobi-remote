"""실행 리포트 요약과 진단 파일 내보내기 (콘솔). 사용법은 mabi/report_tools.py 맨 위 설명."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mabi.report_tools import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
