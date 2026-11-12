"""패킷으로 알게 된 상태(PacketState)와 받은 이벤트 기록(Seen), history 에 쌓을 상태 사본."""
import copy
import time
from dataclasses import dataclass, field

# CLI 가 같은 뜻으로 알려 주는 오래 남는 상태 — CLI 를 물을 때마다 그 답으로 맞춘다 (merge_cli)
CLI_FACTS = ("dungeon_state", "field_state", "dead")


@dataclass
class Seen:
    seq: int
    at: float      # time.monotonic()
    key: str
    vals: dict


@dataclass
class PacketState:
    """패킷으로 알게 된 지금 상태. 감시를 켠 뒤 처음 오기 전까지는 모른다(None)."""
    channel: int | None = None
    channel_type: str = ""
    channel_name: str = ""
    loading: bool = False            # 맵을 떠났고 새 맵에 아직 안 들어감
    loading_at: float = 0.0          # 로딩이 시작된 때 (monotonic) — 오래 가면 맵 진입을 놓쳤나 CLI 로 본다 (Bot.map_loading)
    in_game: bool | None = None      # 게임 서버 입장 뒤 True, 로그아웃(캐릭터 선택 화면) 뒤 False. 감시를 켠 뒤 둘 다 없었으면 None
    dungeon_state: str | None = None  # NotInDungeon / Entering / InProgress / Cleared
    dungeon: int | None = None
    abyss_result: int = 0            # 어비스 결과 (클리어 순간 어비스 번호, 나가면 0)
    abyss_matching: int = 0          # 우연한 만남 매칭: 0 없음 · 1 요청 · 2 찾는 중 · 3 잡힘 (어비스 맵에 들어가면 0)
    # 레이드 (caps/raid1 2026-10-28): Lobby 배 위 · InProgress 출항~판 진행 · Cleared 보스 처치. 감시를 켠 뒤 안 왔으면 None
    raid_state: str | None = None
    raid_result: int = 0             # 레이드 결과 (보스 처치 순간 레이드 번호, 맵을 옮기면 0)
    raid_boss: bool = False          # 이 맵에서 레이드 보스전이 시작됨
    # 나이트메어 드릴 (caps/drill1 2026-11-08): 최고 기록 구역(맵 진입·클리어 때 옴, 기록 없으면 0. 접속 캐릭터가 바뀌면 None)
    # · 방금 깬 구역(결과 창과 같은 때, 다음 구역 입장·맵 진입이면 0)
    drill_best: int | None = None
    drill_records: int = 0           # 최고 기록 개수 (직업마다 하나) — 여럿이면 drill_best 가 지금 직업 것인지 모른다
    drill_result: int = 0
    campfire: bool = False           # 이 맵에 모닥불이 나타남 (어비스는 보스방 앞)
    # 모닥불 뒤 연출 = 어비스 보스 등장 (abyss1: 모닥불 → 연출 → 클리어). 모닥불만으로는 보스방 앞 잡몹 전투까지 보스전으로
    # 봐 변신을 33초 일찍 썼다 (2026-10-30 16:49:27 F5 → 16:50:00 연출). 모닥불 앞 연출은 주마다 첫 입장 연출이라 빼고 (사용자),
    # 맵 진입을 못 봤으면(판 도중에 리모콘을 켬 — 모닥불을 놓쳤을 수 있다, 16:56) 연출만으로 본다 (입장 연출은 이미 지났다)
    boss_scene: bool = False
    # 궁극기·팔라딘 변신 게이지 (현재/필요). 둘 다 같은 값으로 오르고 궁극기는 300, 팔라딘은 500 에서 찬다. 감시를 켠 뒤 안 왔으면 None
    ult: float | None = None
    ult_max: float | None = None
    pal: float | None = None
    pal_max: float | None = None
    can_paladin: bool | None = None  # 이 맵에서 팔라딘 변신을 쓸 수 있나 (맵 진입 때 옴)
    # 내 캐릭터 변신: 패킷이 시작·끝에 한 번씩 온다 (2026-10-30 F5 1초 뒤 · 그 20초 뒤). 변신 중이면 시작한 때 (monotonic), 아니면 0.
    # 끝 패킷을 놓쳐도 부르는 쪽이 변신 시간(20초)으로 끊는다
    transform_start: float = 0.0
    transformed_here: bool = False   # 이 맵에서 변신했다 (팔라딘 변신은 던전마다 한 번)
    transform_seen: float = 0.0      # 내 변신 패킷(시작이든 끝이든)을 마지막으로 받은 때
    field_state: str | None = None   # 사냥터: NotInBattlefield / InProgress / WaitingForChannelTransfer(클리어)
    boss_battle: bool = False
    dead: bool | None = None         # 내 캐릭터가 쓰러짐 (부활 창 열림). 나한테만 오는 부활 가능 여부로 안다
    dead_at: float = 0.0             # 쓰러진 때 (monotonic)
    revives_used: int | None = None  # 이 판에서 쓴 부활 횟수 (화면의 '남은 부활 횟수' = 최대 - 쓴 횟수)
    revives_max: int | None = None
    satiety: int | None = None
    # 장비 내구도 비율 (현재/최대) — 수리(또는 캐릭터 바꿈) 뒤로 깎임 알림에서 본 가장 낮은 값. 알림에 장비 번호가 없어
    # 어느 장비인지 모르니 가장 낮은 것을 쓴다. 감시를 켠 뒤 아직 안 깎였으면 None
    durability: float | None = None
    weight: float | None = None
    max_weight: float | None = None
    char_id: int | None = None       # 내 캐릭터 고유 번호 (안 바뀜) — 맵을 옮길 때마다 오는 내 개인 데이터 맨 앞
    me: int | None = None            # 내 캐릭터 오브젝트 번호 — 맵마다 바뀐다. 등장 캐릭터 중 고유 번호가 든 것 (없으면 포만감 설정)
    me_map: float = 0.0              # me 를 정한 맵 (그 맵의 entered_at) — 한 맵에서 한 번만 정한다
    my_name: str | None = None       # 접속한 캐릭터 이름 (내 등장 메시지에서). 캐릭터를 바꾸면 다음 맵 진입 때 새로 안다
    dialogue_npc: int | None = None  # 대화 중인 NPC 오브젝트 번호 (대화 중이 아니면 None)
    # 지금 대사 뒤 할 일 (대사 내용의 dialogueAction): SelectKeyword 메뉴 버튼 · EndDialogue 작별 인사(눌러야 끝남) ·
    # OpenNPCRepair 대장간 수리 창 · AfterRepair 수리 뒤 등. 대화가 아니면 ''
    dialogue_action: str = ""
    dialogue_step: int = 0           # 대사마다 1씩 오른다 — 눌러서 대사가 넘어갔는지 본다
    dialogue_menu: bool = False      # NPC 메뉴(선택지 버튼)가 떠 있음
    ai: str = ""                     # 내 캐릭터 자동 행동 (InteractAI = NPC 에게 다가가는 중)
    cutscene: bool = False           # 컷신(연출) 재생 중
    traveling: bool | None = None    # 내 자동 이동 중 (시작·끝은 나한테만 온다). 감시를 켠 뒤 한 번도 안 왔으면 None
    travel_points: int = 0           # 이번 자동 이동의 경로 점 개수
    travel_index: int = 0            # 지금 향하는 점 번호 (남은 점 = travel_points - travel_index)
    fast_travel_ok: bool | None = None  # 지금 빠른 이동(T)이 되는가 (FastTravelAvailableState == Enabled)
    combat: str | None = None        # 내 전투 상태 NonCombat / CombatReady / InCombat / CombatEnd. 내 번호를 알아야 안다
    entered_at: float = 0.0          # 마지막 맵 진입 (monotonic)
    dimensions_cleared: list | None = None  # 깬 검은 구멍들이 나타난 시각 (ms). 맵에 들어갈 때마다 온다
    dye_open_at: float | None = None   # 염색 미니게임이 열린 때 (monotonic). 끝·취소·맵 떠남이면 None
    dye_known: bool = False            # 감시를 켠 뒤 염색 열림·끝이나 맵 이동을 봤나 (못 봤으면 켜기 전 상태를 모른다)
    # 퀘스트 창 '추천' 항목 종류 (RecommendedActivityType). 2(요일 던전)면 요일 던전을 아직 안 한 것.
    # 2 가 빠지는 건 클리어(Add 6 → Remove 2)일 수도, 가방 정리(5)에 밀린 것(weight1 13:12:45)일 수도 있어 완료 신호로 못 쓴다
    recommend: int | None = None
    # 출석 대화 시작 (monotonic, 0 = 없음). 날짜가 바뀐 뒤 메인 화면으로 갈 때 NPC 가 한두 마디(무작위) 한 뒤 출석부와
    # '출석부 건너뛰기' 가 뜬다. 끝 신호는 아직 모른다 → 건너뛰기를 누르거나 맵을 옮기면 지우고, 오래되면 끝난 것으로 본다
    attendance_at: float = 0.0
    changed_at: dict = field(default_factory=dict)  # CLI_FACTS 필드 → 패킷이 마지막으로 바꾼 때 (monotonic)
    extra: dict = field(default_factory=dict)

    def attending(self, limit: float = 90) -> bool:
        """출석 대화 중 (시작 패킷을 받고 아직 건너뛰지 않음)."""
        return bool(self.attendance_at) and time.monotonic() - self.attendance_at < limit

    @property
    def fresh(self) -> bool:
        """감시를 켠 뒤 맵에 들어온 적이 있나 — 그러면 대화·컷신처럼 '없음' 이 기본인 상태도 믿을 수 있다."""
        return self.channel is not None

    @property
    def in_combat(self) -> bool | None:
        return None if self.combat is None else self.combat in ("CombatReady", "InCombat")

    @property
    def in_dialogue(self) -> bool:
        return self.dialogue_npc is not None


def _snapshot(s: "PacketState") -> "PacketState":
    """history 에 쌓을 상태 사본. copy.copy 만 하면 changed_at·extra 가 모든 사본과 같은 dict 라 지난 순간 값이 바뀐다."""
    snap = copy.copy(s)
    snap.changed_at, snap.extra = dict(s.changed_at), dict(s.extra)
    return snap
