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
| 반복 콘텐츠의 틀 (판 수·시간, 진행 알림, 캐릭터 확인, 판 사이 수리, 뒤로 보내기, 가방 무게 감시) | `tasks/repeat.Repeat` | `abyss.AbyssRepeat`, `raid.RaidRepeat` |
| 콘텐츠 안에서 나가기 (나가기 → 확인 창 → 확인 → 밖 메인) | `tasks/exits.Exit` (확인 창 띄우기만 다르면 `open_dialog`) · 자리에 맞게 고르기 `exits.leave_instance` | `DungeonExit`, `abyss.AbyssExit`, `raid.RaidExit`/`ShipExit`, `drill.DrillExit`, `field_boss.FieldBossExit`, 실패 뒤 정리, 접속 |
| 콘텐츠 안에서 끝날 때까지 지켜보기 (패킷으로 깨며 기다림 → 끝났나 → 쓰러짐·끼어든 창 → 부활 → 먹기·궁극기 → 시간 상한) | `tasks/content.Fight` 를 상속해 `wake`·`packet_end`·`dead_end`·`screen_end` … 만 덮어씀 | `abyss.AbyssPlay`, `raid.RaidPlay`, `drill.ZoneFight` |
| 메뉴(ESC)에서 콘텐츠 열기 (ESC 를 먹은 창은 넘기고 다시) | `ui_text.open_menu(bot, 글자 키, …)` | 어비스·레이드·나이트메어 드릴·필드 보스 |
| '이동하기'·'바로 가기' 뒤 도착 화면(입장 창·NPC 대화)이 뜰 때까지 (로딩 동안 안 봄, 멈춤 n번 = 창 없이 멈춤, 늦은 빠른 이동) | `content.wait_arrival` (시간 상한은 각자 설정 키) | 어비스·레이드 입구, 드릴, 뱅가드, 필드 보스, `content.go_talk` |
| 로딩이면 끝날 때까지 '어디인가' · 메인 화면까지 기다리기 | `content.where_settled(bot, where)` · `content.wait_settled` | 어비스·레이드 |
| 게임을 뒤로 보내고 하던 창 돌려주기 | `Bot.to_back` · 구간만이면 `with bot.behind_while(설정)` | `Repeat.to_back`, 드릴, 뱅가드 |
| 초록 체크·켜진 스위치 (화면 조각의 초록 비율) | `vision.green` · `green_ratio` (기준값은 자리마다 인자로) | 콘텐츠 가이드 달성 체크, 우연한 만남 스위치 |
| 작업이 예외로 끝났을 때 결과 가르기·정리 (게임 꺼짐 → 멈춤, 연속 실행 제한 창 → 게임 다시 켜기 뒤 이어 함, 가방 무게 → HEAVY) | `outcome.classify` · `outcome.escalate` · `outcome.recover` | runner, `daily_api._repeat_launch` |
| 돌던 카드를 끊어도 되는 자리에서 끊고 먼저 할 카드(시간 정해진 카드·게임 다시 켜기)를 하기 | `cutpoint.check`·`cut`·`due` → 큐 `cut_for_timed` (먼저 할 카드는 `Kind.timed`) | `Bot.step`, `Repeat.yield_between`, CLI 걸음 카드 |
| 연속 실행 제한 창 → 게임 다시 켜기 (창 감지 `run_limit_shown`, 창 닫기 신호 → 넥슨 플러그 바로실행 → 같은 캐릭터로 접속) | `restart.watch`·`now`·`run` · 큐 카드 `queue_api.RestartKind` · 맨 위에 올리기 `WorkQueue.put_first` | cutpoint, `outcome.escalate` |
| 서버 연결 끊김 창(점검 등) → 게임 끄고 큐 일시정지 (창 감지 `server_down_shown` — 색 먼저, 글자로 확인) | `restart.server_down` · 큐 고리 `restart.set_pause_hook` | 점검자 `detect.look` SERVER_DOWN → `handlers.server_down`, `outcome.escalate` |
| 인터페이스 PC·80% 맞추기 (한 번, 게임 안·콘텐츠 밖일 때) | `tasks/display.InterfaceFit` → `'interface'` 이벤트 | runner, Repeat |
| 빠른 이동(T) — 이동 시작을 기다린 뒤 | `Bot.fast_travel(wait)` | 숙제 이동, 아르바이트(점검자), 어비스·레이드 입구, 수리 |
| 가방이 꽉 찼나 | `Bot.overweight()` (패킷, 모르면 CLI) | runner 접속 뒤, `Bot.check_weight` |
| 보스전 궁극기·팔라딘 변신 (캐릭터마다 따로, 판 진행 확인마다 tick) | `tasks/boss_skills.BossSkills` · 지금 캐릭터 설정으로 `BossSkills.for_current` · 보스전인가 `Repeat.boss_fight` | Repeat(어비스·레이드), 드릴, 필드 보스 |
| 판 사이 수리할지 / 수리했는데 그대로인지 | `tasks/repair.due` · `repair.run` | Repeat |
| 얻은 것 재기 (캐릭터 접속 뒤 open, 그 캐릭터 끝에 close) | `queue_report.LootMeter` → `'loot'` 이벤트 | runner, Repeat(부르는 쪽 `daily_api._repeat_launch`), 큐 Kind 들이 같은 이벤트로 받음 |
| 지금 어디인가 | `place.place(bot)` | 복구·나가기·시작 점검 |
| 맵 종류 이름 (패킷 channel_type) — 글자로 적지 않는다 | `place` 상수 `ABYSS`·`RAID`·`RAID_LOBBY`·`DUNGEON`·`DRILL`·`FIELD`(사냥터)·`OPEN_FIELD`(마을)·`FIELD_BOSS`·`OPEN_MAPS` · 콘텐츠 맵인가 `place.is_instance` | 패킷 감시, 끊는 자리, 어비스·레이드·드릴·필드 보스 |
| CLI get_activity 읽기 (던전 상태·사냥터 안·쓰러짐·바쁨 …) — 키를 직접 읽지 않는다 | `game_state.Activity.of(act)` (`in_dungeon`·`in_field`·`busy` …) · Bot 안에서는 `_act_state` | 패킷 감시 맞추기, place, 점검자 idle, 태스크 |
| 예외 (StepTimeout·CannotProceed·StopRequested·Stuck …) | `mabi/exceptions.py` (예전 자리 bot·content·monitor 에서 import 해도 같은 클래스) | 곳곳 |
| 작업 시작 점검 (지난 패킷 상태를 믿지 않고 CLI 로 맞춤) | `bot.check_in()` | 모든 작업 시작·이어 하기 |
| NPC 대화·메뉴·확인 창 처리 | `monitor` + `Ctx` (대사 내용이 아니라 메뉴·단계·버튼 글자로 판단) | 아르바이트·숙제 |
| 점검자 처리 결과로 갈래 나누기 (기다림인가·수락했나) — 글자로 비교하지 않는다 | `monitor.Did` (StrEnum, 로그엔 글자 그대로) · 기다림 모음 `monitor.WAITS` | Bot.to_main, 접속, 어비스 정산, 아르바이트, 수리 |
| 대화 상태를 믿을 수 있는 패킷 상태 · '화면을 터치해 주세요' 글자 | `dialogue.packet_state` · `content.touch_prompt_visible(bot, frame)` | 점검자, 대화, 클리어 뒤 |
| 다른 모듈이 Bot 하나에 걸쳐 기억할 값 — bot 에 밑줄 속성을 붙이지 않는다 | `Bot.marks` (`bot.Marks` 에 칸을 더한다) · 점검자 `Bot.monitor` | 점검자, 출석, 아르바이트 |
| 끼어들기 막는 구간 · F12 와 같은 일시정지 — stopper·_interrupting 을 직접 만지지 않는다 | `bot.no_interrupt()` · `bot.pause_as_key()` (`pause` 는 조작 사이 기본 대기) | 점검자 check, 네트워크 불안정 |
| 화면 글자 찾기·누르기 (한 번 읽은 글자들에서 찾기는 `ui_text.match`) · 띄어쓰기 빼기 · 태그 지우기 | `tasks/ui_text` · `ocr.nospace` · `richtext.strip` | 곳곳 |
| 화면 판단에 쓰면 안 되는 자리 (게임이 위에 띄우는 창 — 연속 실행 제한 창) | `data/ui.json` covers · `gamedata.covering` · 예외 covered_ok · 시험 `tests/test_covers.py` | 모든 글자 영역·그림 ROI·설정 영역 |
| 어비스·레이드 입장 창 (입장 창인가·버튼·지금 탭·우연한 만남, 탭 바꾸기) | `tasks/entry` (`parse`·`read`·`set_tab`·`ensure_chance`·`wait_button`) | 어비스, 레이드 (버튼 기다리기는 드릴도) |
| 아래 가운데 '확인' (퀘스트 완료·레이드·필드 보스 결과 창) | `content.confirm_text` | 점검자, 레이드·필드 보스 결과 |
| 게임 단축키 (Z 카메라·X 보관함·J 퀘스트 … 옵션에서 바꿈) — 글자를 직접 쓰지 않는다 | `keys.of(bot, "camera")` · 목록 `keys.GAME_KEYS` | 곳곳. 이동 WASD·버튼 확인 키(Space·Esc·R)는 고정 |
| 여러 신호(패킷·CLI·화면)로 우선순위 판단 | `judge.decide` | 어비스 단계, 쓰러짐, 로딩 |
| 게임 화면(실제 픽셀) 위에 Qt 창 겹치기 — 게임이 있는 모니터·배율 | `queue_overlay.to_logical` | 작업 큐 오버레이, 염색 표시 |
| 염색 팔레트가 떠 있나·색 찾을 범위 (자리는 게임 화면 비율로 정해 둠, 테두리로 확인) | `dye.detect.palette_at` · `frame_skip` | `dye.tracker.DyeTracker` |
| 큐 카드 한 종류 | `workqueue.Kind` 를 상속 (`own_loot`, `run`, `view`, `where` …) | `queue_api` |
| GUI 에서 게임 조작용 Bot 하나 (만들기 → 주인 이름으로 등록 → 닫기) · 멈추기 · '다른 일이 도는 중인가' | `DailyApi._game_bot(주인)` · `_bot_stop(주인)` · `_busy_reason` (스레드 + 등록된 Bot 모두) · 큐 카드 예외 가르기 `QueueApi._q_failed` | 큐 카드(캐릭터 맞추기·각인 강화·게임 다시 켜기), 어비스·레이드 반복, 캐릭터 자동 설정, 화면 설정 |
| 어비스·레이드 반복 시작·결과·멈춤 (종류별 상태 `RepeatRun`, 장소 칸 `REPEATS`) | `DailyApi._repeat_launch(kind, …)` · `_rep(kind).result` · `_repeat_stop(kind)` | `AbyssKind`·`RaidKind`, 화면 `daily_abyssStop`·`raidStop` |
| 큐 카드의 게임 명령 (막힘 → 확인 창이 닫히길 기다림 → 한 번 더) | `QueueApi._q_exec` | 목표 카드, 전체 수령 |
| 목표 걸음 → CLI 명령·본문, 거절 → 할 일 (게임 규칙) | `craft.execute.step_command` · `step_failure` (`STEP_*`) | `GoalKind._execute` |
| 보유량 (이름 → 가방+보관함 총 개수, 태그 벗긴 이름도 세려면 `bare=True`) | `craft.knowledge.item_totals` | 목표·계획·화면(bare), 학습·얻은 것(원문만) |
| 캐릭터 목록 · 캐릭터별 오늘 할 숙제 순서 | `profile.chars(paths)` · `runner.task_order` (`tasks_by_slot`) | 실행기, 일일·캐릭터 탭, 큐 카드, 접속·보스전 |
| 설정 읽기 (두 파일이 그대로면 캐시, 늘 사본) · 배포 기본값 하나 · 작은 도우미 | `runner.load_config` · `userconfig.default` · `silver_defaults` · `places` · `is_fkey` | 곳곳 (기본값 글자를 코드에 다시 적지 않는다) |
| 화면: 카드 종류의 표시 · 큐 그림이 바뀔 때 부를 것 | `qRegisterKind(name, def)` · `qOnPaint(fn)` (web/queue.js) | daily.js |
| 화면: '시작'(지금 바로, 돌던 카드는 뒤로) · '목표'(큐 맨 아래에 담기) | `qStart(spec, opts)` · `qEnqueue(spec)` (web/queue.js) · 버튼 짝 `bindStartQueue` (daily.js) | 숙제·어비스·레이드 탭, 제작·가공·채집·연주 |
| 화면: 모달 창 (확인·숫자·목록·글자 입력 모두) | `openModal({title, body, ok, cancel, value, no})` (web/app.js) | `confirmModal` · `prompt*` · 큐 질문 창 |
| 화면: `<option>` 줄 · 캐릭터 고르기 | `selectOptions(items, cur)` · `charOptions` · `charCheck` (web/app.js) | 곳곳의 select, 숙제·어비스·레이드 탭, 큐 카드 |
| 화면: 검색 · 시간 글자 | `normSearch` · `hit` · `fmtDur` · `dur`(남은 시간) · `fmtClock` · `fmtHM` (web/app.js) | 목록 검색, 큐 결과·기록, 연주 |
| 화면: 다시 켜도 기억할 값 | `pref` · `setPref` (web/app.js → 파이썬 settings) — `mm.cfg.set` 을 직접 부르지 않는다 | 곳곳 |

## 새 기능을 짤 때

1. **먼저 찾는다.** 위 표와 `grep` 으로 같은 일을 하는 함수·클래스가 있는지 본다 (접속, 나가기, 이동, 대기, 화면 판단, 결과 집계 …).
2. **있으면 쓴다.** 조금 다르면 기존 것을 넓혀서(인자·훅) 둘 다 쓰게 한다. 새 방식이 더 나으면 기존 것을 그 방식으로 전면
   바꿔도 된다 — 다만 쓰는 곳을 모두 옮기고 옛 길은 지운다 (두 길이 남으면 한쪽만 고쳐지는 버그가 난다).
3. **공통은 기반 클래스·공용 함수로, 다른 것만 덮어쓴다.** 예: `Repeat` 는 순서와 집계를 쥐고, 하위 클래스는
   `where` · `leave_for_switch` · `loop` 같은 종류별 단계만 구현한다. 큐 카드는 `Kind` 를 상속한다.
4. **판단은 CLI 가 기준**, 패킷은 실시간 변화·CLI 에 없는 정보에. 화면 전환은 고정 sleep 이 아니라 시간 상한 + 확실한 신호.
5. 테스트(`tests/`)를 함께 단다. 공통 부품은 그 부품의 테스트로, 하위 클래스는 다른 부분만.
6. **화면 위 가운데(연속 실행 제한 창 자리, `data/ui.json` covers)는 판단에 쓰지 않는다.** 그 창은 언제든 떠서 끌 때까지 남는다.
   그 자리에 글자 영역·그림 ROI 를 두면 `tests/test_covers.py` 가 막는다 — 그 밖의 신호를 찾고, 누르기 전용이거나 다른 신호가
   먼저인 것만 covered_ok 에 까닭을 적는다. 창이 뜨면 큐가 끊어도 되는 자리에서 게임을 다시 켜므로(`mabi/restart`), 가려져서
   그때까지 일이 늦어지거나 실패하는 정도면 '다시 켬' 으로 적어도 된다 — 다만 가려져 **틀린 것을 저장하거나 고르는** 일은 막는다
   (예: 캐릭터 읽기는 창이 보이면 멈춘다).

## 한 길로 모은 기록 (2026-10-30)

같은 일이 여러 벌 있어 한쪽만 고쳐지던 것들 — 다시 따로 만들지 않는다.
- 얻은 것 재기: runner 안 / 어비스·레이드 카드 앞뒤 → `LootMeter`
- 반복 루프: abyss.repeat / raid.repeat → `Repeat` + 하위 클래스
- 판 사이 수리 판단: 어비스에만 '수리했는데 그대로면 멈춤' → `repair.due`
- 인터페이스 맞추기: runner / 반복 실행부 → `InterfaceFit` (큐는 실제로 맞췄을 때만 기억)
- 나가기: 네 벌 → `exits.Exit` (실패 뒤 정리·접속이 어비스·레이드 안도 처리)
- 실패 가르기·가방 무게: runner 에만 → `outcome` · `Bot.overweight`
- 빠른 이동: 네 벌 → `Bot.fast_travel`
- 화면(web/daily.js): 어비스·레이드 탭 진행·시작·담기 → `onRepeatEvent` · `startRepeat` · `repeatSpec`,
  탭마다의 '시작'·'목표' → `qStart` · `qEnqueue` · `bindStartQueue`, 필드 보스 목록 → 파이썬 `field_boss.choices`
- 화면(web/*.js, 2026-11-12): 모달 네 벌 → `openModal`, `<option>`·캐릭터 고르기 → `selectOptions` · `charOptions` · `charCheck`,
  검색 다섯 벌 → `hit`, 시간 글자 여섯 벌 → `fmtDur` · `fmtClock` · `fmtHM`, 큐 결과 이름표 두 벌 → `Q_RESULT`,
  설정 저장 → `setPref`

(2026-11-12, tasks/ 정리)
- 메뉴(ESC)에서 항목 열기: 네 벌 → `ui_text.open_menu`
- '이동하기' 뒤 도착 기다리기: 여섯 벌(go_talk 포함) → `content.wait_arrival`
- 우연한 만남 켜기·버튼 기다리기·where_settled·_wait_settled(레이드가 어비스 private 을 씀) → `entry.ensure_chance`·`entry.wait_button`·`content.where_settled`·`content.wait_settled`
- 콘텐츠 안 전투 대기: 어비스·레이드·드릴 세 벌 → `content.Fight` · BossSkills 만들기 세 벌 → `BossSkills.for_current`
- 드릴·필드 보스 나가기: Exit 를 다시 구현 → `DrillExit` · `FieldBossExit`
- 게임 뒤로 보내기: 세 벌 → `Bot.to_back` · `behind_while`
- 초록 판정: 세 벌 → `vision.green` · `green_ratio`
- 글자 처리(띄어쓰기·찾기·태그): display·arbeit·login·raid → `ocr.nospace` · `ui_text.match` · `richtext.strip`
- 이름 충돌: `abyss.after_clear`(보상 화면인가) → `abyss.at_reward` (`content.after_clear` 는 클리어 뒤 정리 동작)

(2026-11-12, gui_app·craft 정리)
- 가공 작업 현황: 화면용 복사본(legacy_shapes) → `lists.altering_works` + 키 이름만 바꿈
- 보유량 합치기 네 벌(goal·knowledge·plan·legacy_shapes) → `knowledge.item_totals(bare=)`
- Bot 수명 관리 여덟 벌 → `_game_bot` · `_bot_stop` · `_q_failed`. `_busy_reason` 이 큐 카드 Bot·화면 설정 되돌리기도 본다
- 어비스·레이드의 문자열 계약(`_{kind}_launch/_result/_bot/_thread`, `daily_{kind}Stop`) → `RepeatRun` · `_repeat_launch` · `_repeat_stop`,
  비운 값의 기본값은 config.default.toml 에서 (`userconfig.default`)
- 캐릭터 탭의 숙제 순서 재계산 → `runner.task_order`, 캐릭터 목록 상용구 → `profile.chars`
- 막힘 재시도 두 벌 → `_q_exec`, 목표 걸음의 게임 규칙 → `craft.execute.step_command`·`step_failure`
- 설정 읽기: 부를 때마다 TOML 두 개 → `load_config` 캐시. 상수: APP_NAME·큐 상태 이름표·채집 100·제작 10 을 한 곳에

(2026-11-12, 코어 정리 — bot·monitor·packet_monitor·place·queue)
- 예외 열한 개가 bot·content·monitor.core·display·login·abyss 에 흩어짐 → `mabi/exceptions.py`
- CLI get_activity 해석 여러 벌(packet_monitor 셋·place·content·display·점검자 idle·busy_why·cli_idle) → `game_state.Activity`.
  display 는 대화를 `act["dialogue"]["IsDialoguePlaying"]` 로 읽어 늘 거짓이던 것도 함께 바로잡음
- 맵 종류 글자·모듈마다 다시 정의한 상수(`ABYSS_MAP`·`RAID_MAP`·`LOBBY_MAP`·`field_boss.MAP`·`drill.MAP`·`OPEN_FIELD`·`OPEN_MAPS`) → `place` 상수
- bot 에 붙이던 밑줄 속성(`_skip_seen`·`_network_*`·`_attendance_clicked`·`_arb_*`·`_gatherable`·`_monitor`) → `Bot.marks`·`Bot.monitor`,
  `bot._act`·`bot._interrupting`·`stopper.by_key/stopped` 직접 만지기 → `Activity.of(bot.activity())`·`no_interrupt`·`pause_as_key`
- 점검자가 `dialogue._packet`·`content._touch_texts` 를 가져다 씀 → `packet_state`·`touch_prompt_visible(bot, frame)`
- 처리 결과 글자 비교 → `monitor.Did`
- `Vision.find` 는 같은 frame 객체에 같은 질문이면 앞 답을 쓴다 (frame 이 바뀌면 버림) · `has` 는 이름마다 한 번
- queue.json 은 파일에 남는 칸이 바뀔 때만 쓴다 (`craft.queue.encode` 로 비교 — 시간으로 미루지 않아 잃는 것 없음)

새로 비슷한 것을 발견하면 아래 '아직 모으지 못한 것' 절에 적고, 모으면 위 기록으로 옮긴다.

## 아직 모으지 못한 것

- 모듈 사이 밑줄 이름 import 가 아직 남음: `login` → `charscan._read_card`·`arbeit._settle`, `window` → `inputs._send`,
  `craft.lists` → `query._fail`. 점검자(monitor) 밖이라 이번 정리(2026-11-12 코어)에서는 두었다.
- `monitor.offline.screen_bot` 은 Mock 에 Bot 의 `_frame`·`_require_template` 을 심어 진짜 Bot 메서드를 빌려 쓴다 (화면 판정 시험 도구).
- 화면의 '지금 하는 행동'(gui_app/legacy_shapes `q_activity`)은 get_activity 를 따로 읽는다 — 연주·선택지 기다림까지 '바쁨' 으로 보는
  화면용 뜻이라 `Activity.busy` 와 다르다. 합치려면 `Activity` 에 연주·앉음 칸을 더하고 화면용 busy 를 따로 둔다.

- 필드 보스 전투(`field_boss.fight`)·뱅가드 진행(`vanguard.play`)은 `content.Fight` 를 안 쓴다 — 패킷 기다림 없이 화면을 짧게
  보고(결과 창 '확인'·성장 가이드 15초마다·화면 터치), 필드 보스는 먹지 않고 뱅가드는 CLI 활동·궁극기가 없다. 옮기려면 Fight 에
  '패킷 대신 짧게 쉬기'·'싸우는 중이 아니어도 쉬기' 같은 갈래가 더 필요하다.
