# 코드 구조와 작업 방향

새 기능을 넣거나 구조를 바꾸기 전에 읽는다. 작업 원칙은 저장소 맨 위 `CLAUDE.md` 에, 기능별 진행 메모는 `docs/STATUS.md` 에 있다.

## 한눈에

```
gui.py ─ gui_app/            화면(PySide6 + web/ 의 HTML·JS). 화면이 부르는 파이썬 쪽은 *_api.py
          ├ daily_api.py      일일 숙제·어비스·레이드 시작/멈춤 (작업 스레드를 띄운다)
          └ queue_api.py      작업 큐의 카드 종류(Kind) — 숙제·어비스·레이드·목표·동작
mabi/
  bot.py                      게임 조작의 바탕: 창·캡처·입력·대기(wait/sleep, 멈춤·시간 상한 확인)·상태(state = CLI, packets = 패킷)
  place.py                    '지금 어디인가' 공통 사실 (맵 종류·던전 안 등) — 새 판단은 여기에 더한다
  runner.py                   일일 숙제 실행기: 캐릭터마다 접속 → 숙제들 → 실패 분류·복구
  workqueue.py                작업 큐: 카드를 위에서부터 Kind.run 으로 돌린다
  queue_report.py             큐 결과(한 일·얻은 것). 얻은 것은 LootMeter 하나로 잰다
  monitor/                    점검자: 화면·패킷을 보고 처리기를 고른다 (Ctx 로 일마다 다른 것만 넘긴다)
  tasks/                      숙제·콘텐츠 하나씩. 공통 부품은 아래 표
```

## 공통 부품 — 같은 일을 또 만들지 말고 이것을 쓴다

| 하는 일 | 부품 | 쓰는 곳 |
|---|---|---|
| 캐릭터로 접속 (타이틀·선택 화면·다른 캐릭터에서) | `tasks/login.run` · 이름 비교 `login.current_name` / `name_matches` | runner, Repeat |
| 반복 콘텐츠의 틀 (판 수·시간, 진행 알림, 캐릭터 확인, 판 사이 수리, 뒤로 보내기) | `tasks/repeat.Repeat` | `abyss.AbyssRepeat`, `raid.RaidRepeat` |
| 판 사이 수리할지 / 수리했는데 그대로인지 | `tasks/repair.due` · `repair.run` | Repeat |
| 얻은 것 재기 (캐릭터 접속 뒤 open, 그 캐릭터 끝에 close) | `queue_report.LootMeter` → `'loot'` 이벤트 | runner, Repeat(부르는 쪽 `daily_api._repeat_launch`), 큐 Kind 들이 같은 이벤트로 받음 |
| 지금 어디인가 | `place.place(bot)` | 복구·나가기·시작 점검 |
| 작업 시작 점검 (지난 패킷 상태를 믿지 않고 CLI 로 맞춤) | `bot.check_in()` | 모든 작업 시작·이어 하기 |
| NPC 대화·메뉴·확인 창 처리 | `monitor` + `Ctx` (대사 내용이 아니라 메뉴·단계·버튼 글자로 판단) | 아르바이트·숙제 |
| 화면 글자 찾기·누르기 | `tasks/ui_text` | 곳곳 |
| 큐 카드 한 종류 | `workqueue.Kind` 를 상속 (`own_loot`, `run`, `view`, `where` …) | `queue_api` |

## 새 기능을 짤 때

1. **먼저 찾는다.** 위 표와 `grep` 으로 같은 일을 하는 함수·클래스가 있는지 본다 (접속, 나가기, 이동, 대기, 화면 판단, 결과 집계 …).
2. **있으면 쓴다.** 조금 다르면 기존 것을 넓혀서(인자·훅) 둘 다 쓰게 한다. 새 방식이 더 나으면 기존 것을 그 방식으로 전면
   바꿔도 된다 — 다만 쓰는 곳을 모두 옮기고 옛 길은 지운다 (두 길이 남으면 한쪽만 고쳐지는 버그가 난다).
3. **공통은 기반 클래스·공용 함수로, 다른 것만 덮어쓴다.** 예: `Repeat` 는 순서와 집계를 쥐고, 하위 클래스는
   `where` · `leave_for_switch` · `loop` 같은 종류별 단계만 구현한다. 큐 카드는 `Kind` 를 상속한다.
4. **판단은 CLI 가 기준**, 패킷은 실시간 변화·CLI 에 없는 정보에. 화면 전환은 고정 sleep 이 아니라 시간 상한 + 확실한 신호.
5. 테스트(`tests/`)를 함께 단다. 공통 부품은 그 부품의 테스트로, 하위 클래스는 다른 부분만.

## 아직 한 길로 모으지 못한 것 (2026-10-30 점검)

손댈 때 같이 모은다. 위험이 큰 순서.

- **인터페이스(PC·80%) 맞추기가 두 곳**: `runner._prepare_interface`(접속 뒤 다시 맞추고, 맞춘 뒤 접속 재시도)와
  `daily_api._repeat_launch`(캐릭터 접속 전에 한 번만). 큐는 실제로 맞췄는지와 상관없이 `session["iface"]` 를 켠다.
  → 공용 함수로 빼서 접속 직후 부르고, 맞췄을 때만 표시.
- **콘텐츠 안에서 나가기가 네 벌**: `content.leave_dungeon` · `abyss.leave` · `raid.leave`/`leave_ship` · `login._leave_dungeon`.
  `runner.recover` 와 `login` 은 어비스·레이드를 모른다 → `place()` 의 종류로 나눠 부르는 하나로.
- **실패 분류·가방 무게 감시가 runner 에만**: 게임 꺼짐·연속 실행 제한·같은 실패 연속·가방 무게. 반복(어비스·레이드)은
  예외를 모두 'failed' 로만 본다 → runner 의 분류를 공용으로 빼서 반복도 쓴다.
- **빠른 이동(T) 네 벌**: `content.travel`(이동 시작 패킷을 기다림) · abyss/raid 입구 이동 · `repair` · `monitor.handlers.fast_travel`.
  → '이동 시작 대기 + 반복 확인' 하나로.
- 화면(web/daily.js)의 어비스·레이드 진행 처리도 거의 같은 코드가 두 벌.
