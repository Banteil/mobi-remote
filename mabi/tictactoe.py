"""흩어진 물길(어비스) 보스 테로사 틱택토 패턴 — 판 계산과 패킷으로 쌓는 판 상태. 움직이는 쪽은 tasks/spear.py.

패턴 (2026-11-03 abyss_runs/boss2 + 사용자 설명):
- 보스방 바닥이 3×3 발판 (가운데 X -9/0/9, Y 357.5/366.5/375.5 — 칸 간격 9).
- 보스가 칸 가운데로 정확히 걸어가 X 를 새기면 우리 차례 — 그 순간 O 담당 캐릭터에게 연출 'Abyss_S3_Forecast_Target' 이 온다
  (사용자: 보스와 가장 가까이 있던 캐릭터). 몇 초 뒤(4~9초) 보스가 담당 캐릭터 자리로 걸어가 O 를 새긴다.
- 칸은 보스의 경로 이동 목적지로 읽는다 (boss3). 보스 번호는 브레이크 패킷으로는 못 가린다 — 몬스터 여럿이 받는다.
- O 가 한 줄(가로·세로·대각선)이면 파훼, 4번 안에 못 하면 전멸.
- 보스는 첫 X 를 상하좌우 칸에 두고, 어쩔 수 없을 때가 아니면 가운데에 두지 않는다 (사용자) → 귀퉁이 → 반대 귀퉁이 → 가운데로 이긴다.
패킷은 받기만 한다.
"""
import math
import time

XS = (-9.0, 0.0, 9.0)
YS = (357.5, 366.5, 375.5)
CENTER = (1, 1)
SNAP = 4.5          # 칸 가운데에서 이만큼 안이면 그 칸
EXACT = 0.3         # X 를 새기러 갈 땐 칸 가운데로 정확히 간다
FORECAST = "Abyss_S3_Forecast_Target"
TURN = 9.0          # 차례 시작부터 보스가 O 를 새기러 출발하기까지 (실측 9초)
LINES = ([(c, r) for c in range(3)] for r in range(3))
LINES = [list(l) for l in LINES] + [[(c, r) for r in range(3)] for c in range(3)] \
    + [[(i, i) for i in range(3)], [(i, 2 - i) for i in range(3)]]


def cell_of(x: float, y: float) -> tuple[int, int] | None:
    """좌표가 들어간 칸 (열, 행). 판 밖이면 None."""
    c = min(range(3), key=lambda i: abs(XS[i] - x))
    r = min(range(3), key=lambda i: abs(YS[i] - y))
    return (c, r) if abs(XS[c] - x) <= SNAP and abs(YS[r] - y) <= SNAP else None


def center_of(cell: tuple[int, int]) -> tuple[float, float]:
    return XS[cell[0]], YS[cell[1]]


def won(board: dict, mark: str = "O") -> bool:
    return any(all(board.get(c) == mark for c in line) for line in LINES)


def choose(board: dict) -> tuple[int, int] | None:
    """O 를 둘 칸. 이기는 칸이 있으면 그것, 아니면 둔 뒤 점수가 가장 높은 칸:
    O 둘 + 남은 칸이 가운데(보스가 가운데엔 안 둔다 → 다음에 반드시 이김) 100, O 둘 10, O 하나 1 (X 가 없는 줄만).
    가운데는 이길 때만 — 마지막 수로 남겨 둔다. 빈 칸이 가운데뿐이면 가운데."""
    empty = [(c, r) for c in range(3) for r in range(3) if (c, r) not in board]
    if not empty:
        return None
    for cell in empty:
        if won({**board, cell: "O"}):
            return cell

    def score(cell):
        b = {**board, cell: "O"}
        s = 0
        for line in LINES:
            if any(b.get(c) == "X" for c in line):
                continue
            n = sum(b.get(c) == "O" for c in line)
            rest = [c for c in line if c not in b]
            s += 100 if n == 2 and rest == [CENTER] else 10 if n == 2 else n
        return s - (1000 if cell == CENTER else 0)
    return max(empty, key=score)


class TicTacToe:
    """판 상태. SpearState 가 같은 잠금 아래에서 feed 한다 (맵에 들어올 때마다 새로)."""

    def __init__(self):
        self.board: dict[tuple[int, int], str] = {}
        self.boss: int | None = None
        self.x_move: tuple[int, tuple[int, int], float] | None = None  # 칸 가운데로 가는 경로 (번호, 칸, 시각) — X 후보
        self.turn_at = 0.0          # 이번 차례 시작 (monotonic)
        self.drawer: int | None = None
        self.mine_at = 0.0          # 내가 O 담당이 된 차례 시작
        self.taken_at = 0.0
        self.resolved = True        # 이번 차례 O 를 새겼나 (보스가 출발함)
        self.done = False           # O 한 줄 완성

    def feed(self, key: str, v: dict, me: int | None, pos: dict) -> str | None:
        a = v.get("actor")
        now = time.monotonic()
        if key == "spear.timeline" and v.get("name") == FORECAST:
            # 차례 시작 — 바로 전에 칸 가운데로 간 것이 보스, 그 칸이 방금 새긴 X
            x_cell = None
            if self.x_move and now - self.x_move[2] < 6 and (self.boss is None or self.x_move[0] == self.boss):
                self.boss, x_cell = self.x_move[0], self.x_move[1]
                if x_cell not in self.board:
                    self.board[x_cell] = "X"
            self.x_move = None
            self.turn_at, self.drawer, self.resolved = now, a, False
            who = "나" if me is not None and a == me else "다른 캐릭터"
            if who == "나":
                self.mine_at = now
            return f"틱택토 차례 — X {x_cell} · O 담당 {who} · 판 {self.text()}"
        if key != "spear.path" or v.get("points") != 2 or v.get("x") is None:
            return None
        dest = (v["x"], v["y"])
        cell = cell_of(*dest)
        if cell is None:
            return None
        if self.resolved or a != self.boss:
            if math.dist(dest, center_of(cell)) <= EXACT and (self.boss is None or a == self.boss):
                self.x_move = (a, cell, now)
            return None
        if now - self.turn_at > 2:
            # 보스가 O 담당 자리로 출발 = 그 칸에 O
            self.resolved = True
            if cell and cell not in self.board:
                self.board[cell] = "O"
            if won(self.board):
                self.done = True
                return f"틱택토 O {cell} → 한 줄 완성 · 판 {self.text()}"
            return f"틱택토 O {cell} · 판 {self.text()}"
        return None

    def due(self) -> bool:
        """내가 O 담당이 됐고 아직 안 맡았다."""
        return not self.done and self.mine_at > self.taken_at and time.monotonic() - self.mine_at < TURN - 2

    def take(self) -> dict | None:
        self.taken_at = self.mine_at
        cell = choose(self.board)
        if cell is None:
            return None
        x, y = center_of(cell)
        return {"cell": cell, "x": x, "y": y, "at": self.mine_at}

    def text(self) -> str:
        return "/".join("".join(self.board.get((c, r), ".") for c in range(3)) for r in range(3))
