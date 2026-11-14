"""리모콘이 쓰는 예외를 한곳에 모은다.

어디서 나든 실행기(runner)·결과 가르기(outcome)·큐가 같은 이름으로 받는다. 예전 자리(bot,
monitor.core, tasks.display, tasks.login, tasks.abyss)에서도 같은 클래스를 가져다 쓰므로 그 이름으로 import 해도 같다.
"""


# ---- 바탕 (Bot) ----

class StopRequested(Exception):
    """멈춤 키(F12)·화면의 멈춤 — 다음 대기·캡처 때 나서 전체 실행을 멈춘다."""


class StepTimeout(Exception):
    """기다리던 화면·신호가 시간 상한 안에 오지 않았다."""


class Overweight(Exception):
    """가방 무게가 한도를 넘어 숙제를 이어갈 수 없음. 실행기는 그 캐릭터를 건너뛴다."""


class MissingTemplate(Exception):
    """찾으려는 그림 템플릿 파일이 없다."""


class AuthBlocked(Exception):
    """'계정 인증 실패'가 거듭 나서 접속을 더 시도하지 않는다. 실행기는 전체 실행을 멈춘다."""


# ---- 숙제·콘텐츠 ----

class CannotProceed(RuntimeError):
    """던전 미해금, 장소를 못 찾음 등 진행할 수 없는 상황. 실행기는 실패로 기록하고 다음 숙제로 넘어간다."""


class OutOfStock(CannotProceed):
    """재료가 다 떨어져 그 일을 더 할 수 없다. 다시 돌려도 같으므로 큐 카드는 실패로 기록하고 큐에서 뺀다."""


class Stuck(RuntimeError):
    """점검자가 보기에 같은 자리에서 헛돌고 있다."""


class DisplayFixFailed(RuntimeError):
    """화면 설정(해상도·인터페이스) 맞추기 실패 — 따로 다룬다."""


class SelectFailed(StepTimeout):
    """캐릭터 선택 화면에서 카드를 고르지 못했다."""


class WrongCharacter(StepTimeout):
    """접속해 보니 고른 캐릭터가 아님 — 숙제를 시작하지 않는다."""


class LootPending(Exception):
    """입장하려는데 정산 안 한 주간 전리품이 있다 — open_entry 는 여기서 멈추고, 정산(settle_loot)은 별개 과정으로 한 뒤
    입장을 다시 이어 간다 (enter_screen). 어비스 목록은 열린 채로 둔다."""
