# 통합 계획: 일일 숙제 + 모비 커넥터 리모콘 → 파이썬 단일 프로그램

작성: 2026-10-21. 방향: 리모콘(Electron, 지금은 `mobi-remote-legacy` 폴더)의 기능을 전부 이 프로젝트의
PySide6 GUI(`gui.py`, `gui_app/`)로 옮기고, 일일 숙제 엔진(`mabi/`)과 한 프로그램으로 합친다.
옮기는 동안 기존 리모콘은 그대로 쓴다.

## 원칙
- **프로세스 하나, 관리자 권한 하나.** 입력(SendInput)이 관리자 게임에 닿으려면 관리자여야 한다.
  리모콘이 관리자에서 화면 캡처가 죽던 문제(getUserMedia)는 파이썬 캡처(mss)에는 없다 → 커서 헬퍼 같은 별도 관리자 프로세스가 필요 없다.
- **숙제·염색·커넥터가 같은 기반을 쓴다**: 창 찾기, 캡처, 입력, OCR(winrt), CLI 호출, 경로(`mabi/paths.py`), 로그, 설정.
- **리모콘의 학습 데이터는 그대로 읽는다**: `%LOCALAPPDATA%\mobi-remote\` 의 knowledge.json, favorites.json,
  playlists.json, queue.json, dye-presets.json, settings.json 을 첫 실행 때 가져온다(복사, 원본은 건드리지 않음).
- 화면 문구는 기능에 필요한 것만. 이유는 코드 주석에.

## 단계

### 1단계 — 뼈대 + 일일 숙제 GUI  ✅ 1차 완료 (2026-10-21)
- [x] `mabi/paths.py`: 리소스/데이터 경로 분리, 포터블(exe 옆 `MabiDaily_data\`) ↔ `%LOCALAPPDATA%\MabiDaily\`, `paths.json` 수동 지정
- [x] `mabi/runner.py`: 실행 루프를 run.py 에서 분리, 이벤트 콜백(start/character/task_start/task_end/done), GUI 중단 버튼
- [x] `gui.py`: 관리자 아니면 UAC 로 다시 띄움
- [x] 일일 숙제 탭: 캐릭터·숙제 선택, 시작/중단(F12 동일), 캐릭터 × 숙제 실시간 표, 로그
- [x] ~~기록 탭~~ (3.2.0 에서 뺌 — 로그와 오늘 진행 표로 충분)
- [x] 설정 탭: 캐릭터(슬롯·이름), 은동전 기본값·캐릭터별(사냥터 횟수/던전/층), 가방 무게 한도, 저장 경로
- [ ] 실제 게임으로 GUI 실행 확인 (내일 6시 이후 전체 숙제)
- [ ] 보관 기간 설정(기록·로그·스크린샷)

### 2단계 — 공통 기반 이식  ✅ (connector, cache, errors, compat, richtext, query — 제작·가공 조회는 6번에서) (리모콘 `src/connector.js`, `cache.js`, `query.js`, `log.js`, `version.js`)
- CLI 호출 모듈: 비ASCII 본문 base64, `last-response.json` 대체 읽기, 종료 코드(2/3/4/5), 취소, **동시 실행 1개**
- CLI 경로 탐색 6단계(환경변수 → 설정 → 레지스트리 `Nexon\MabinogiM\RootPath` → 드라이브 × 설치 패턴 → `\Nexon\*` → 제거 프로그램 목록), 결과 캐시
  → 지금 `config.toml` 의 `cli_path` 고정값을 대체
- 연결 상태(game_off / option_off / no_connector, 꺼져 있으면 5초 걸리는 점 → 오프라인 플래그로 캐시 직행)
- 조회 캐시(명령별 TTL, 같은 명령 합치기, 오프라인·실패 시 만료 캐시)
- 조회 정규화(query.js): 리치텍스트 nameRaw/표시명, 유령 미션 제거, 퀘스트 진행도 중복 제거, 보관함 포함 재료 계산
- 비용: CAPABILITIES Note 에서 런타임 파싱, 응답 `cost` 문장으로 실제 소모량
- 호환성 검사(CLI 버전·명령 목록·본문 형식·비용 지문, semver 만 비교) + **Note/OutputExample 지문 추가** — 2026-10-15 판처럼 설명만 바뀐 변경을 잡기 위해 (docs/CLI_CHANGES.md)
- 명령 로그(일별, 14일, 5MB 회전, 실패·비용 발생 시에만 본문)

### 3단계 — 리모콘 화면 이식 (순서 = 쓰는 빈도)
1. ✅ **상단바 + 대시보드**: 연결 상태, 레벨·직업, 날개, 무게%. 캐릭터·위치·활동·재화·주변 카드, 자동 갱신(꺼짐/3/5/10/30초, 창 숨김·실행 중엔 건너뜀)
2. ✅ **미션**: 일일/주간 진행·수령대기·끝, 퀘스트 트래커. (일일 숙제의 미션 처리와 같은 데이터)
3. ✅ **소지품** (즐겨찾기는 아직): 검색·분류·보관처·정렬·즐겨찾기, 보관처별 합계
4. ✅ **연주**: 악기 교체, 악보 목록, 재생목록(반복·셔플, 곡 끝 감지 → `stop_action` → 다음 곡), 진행바 보간
5. ✅ **소셜**: 채팅, 표정(EmojiText), 행동(ChatCommands, 일어서기 = `stand_up`)
6. ✅ **채집 / 제작 / 가공** + **작업 큐 + 목표 루프** (가장 큼)
   - 비용 확인 창, 시설 칸·레벨(사전 차단: 꽉 차면 CLI 를 부르지 않음 = 날개 5 절약), 완료분 수령
   - 학습 지식(knowledge.json), 인벤 diff 레시피 학습 규칙, 산출물 추정, 같은 이름 갈래, 제작 상한 10
   - 목표 루프(goal.nextStep): 한 걸음씩, 같은 걸음 4회면 정지, 최대 300걸음
7. ✅ **옵션**: 커넥터 위치(찾기/직접 지정), 호환성, 명령 직접 호출, 호출 기록, 파일 로그, 트레이로 닫기, 테마

### 4단계 — 염색 도우미 ✅ (실제 게임 확인 전)
- 캡처: mss 로 주 모니터 120ms 주기 (Electron 처럼 창 보호가 필요하면 `SetWindowDisplayAffinity`)
- 팔레트 검출(격자 색차·채도, 덩어리 점수, 테두리 스냅, 질감 관문), 스포이드 선·동그라미 찾기, 최빈색 읽기,
  Lab ΔE(CIE76) 로 목표색 최근접점·허용 범위 점 찾기 — dye.js 알고리즘 그대로 numpy 로
- 오버레이: 투명·클릭 통과·항상 위 창(Qt `WindowTransparentForInput` + `FramelessWindowHint` + `WindowStaysOnTopHint`)
- 프리셋(dye-presets.json 형식 유지), 색 편집(SV 판, HEX/RGB, 화면에서 집기 + 돋보기), 화면 저장
- 커서 1px 이동: 같은 프로세스에서 RegisterHotKey (Ctrl+WASD, 염색 팔레트가 떠 있는 동안만) — 별도 헬퍼 불필요
- **픽셀 조작 = 키보드로 마우스 1px 이동** (Ctrl+Alt+WASD). 리모콘은 별도 관리자 PowerShell 헬퍼로 어정쩡하게 구현돼 있다 →
  같은 프로세스에서 RegisterHotKey + SetCursorPos 로 바로. 스포이드를 목표 색 점에 정확히 맞출 때 쓴다

### 6단계 — 포장
- PyInstaller 단일 exe (`--uac-admin`, 템플릿·기본 config 포함), 아이콘, 단일 인스턴스, 트레이
- 리모콘 데이터 가져오기, 업데이트 확인(GitHub releases)

### 3-1단계 — 화면을 웹으로 (껍데기만 교체)  ✅ (2026-10-21)
Qt 위젯 화면(gui_app/*_tab.py)은 모양이 별로라, **레거시 리모콘의 웹 화면(web/)을 그대로 쓰고 속은 파이썬**으로 바꿨다.
- 엔진: **QtWebEngine**(QWebEngineView + QWebChannel). pywebview(WebView2)는 투명 창이 안 돼서 탈락 —
  염색 오버레이·트레이·단축키가 Qt 라 같은 이벤트 루프여야 한다.
- `web/bridge.js` 가 레거시 preload 와 같은 모양의 `window.mm.*` 를 만들어 `backend.call(id, 'kn.setLevel', args)` 로 보낸다.
  파이썬은 이름의 '.' 을 '_' 로 바꿔 `Api.kn_setLevel` 을 **작업 스레드**에서 부르고 JSON 으로 돌려준다.
  파이썬 → 화면 이벤트는 `backend.event(채널, json)` 하나 (mm:exec-start, mm:daily, mm:dye-state, mm:chars-scan …).
- `gui_app/api.py` 가 레거시 ipcMain 핸들러 전부를 옮긴 것. 돌려주는 모양은 `legacy_shapes.py` 가 레거시와 맞춘다
  (레거시 node 와 45건 대조, 차이 0). 일일 숙제는 `daily_api.py`, 캐릭터 탭은 `chars_api.py`, 염색은 `dye_service.py` 를 섞는다.
- 염색: 레거시는 화면(렌더러)이 캡처했지만 QtWebEngine 엔 데스크톱 캡처가 없어 **파이썬(mss)이 캡처·검출**하고
  레거시 draw 와 같은 모양의 payload 를 화면에 보낸다 → 화면 미리보기 코드는 그대로.
  스포이드(dye.snap)·염색 화면 저장(dye.shot)은 창을 숨기지 않고 캡처 제외(`SetWindowDisplayAffinity`)로 처리.
- 진입점 `gui_app/web_main.py`: 단일 인스턴스(QLocalServer `MobiRemote-single`), 트레이, closeToTray, 닫을 때 정리.
- 이름 "모비 커넥터 리모콘" 3.0.0. 옛 Qt 탭(gui_app/main.py, *_tab.py)은 아직 지우지 않았다.

### 3-2단계 — 캐릭터 탭  ✅ (2026-10-21)
맨 앞 탭이자 시작 탭. 게임의 캐릭터 선택 화면처럼 카드로 보여 준다 (`web/chars.js`, `gui_app/chars_api.py`).
- 카드: 그림(`portraits/<슬롯>.png`), 레벨·직업, 이름, 요약(사냥터 N회 · 던전 N층 · 검은 구멍). 끈 항목은 취소선.
  지금 접속한 캐릭터(아래 '알아보기'가 확실할 때)는 노란 테두리 + '접속 중'.
- 카드를 누르면 → **캐릭터별 설정 창**: 이름, 그림 바꾸기/지우기, 사냥터(장소·횟수, 0 = 안 감),
  남은 은동전 던전(던전 안 감 포함)·층, 검은 구멍 돌기(기본 켬), 캐릭터 빼기.
  '기본값' 대신 **실제 적용 값**을 보여 주고, 저장할 땐 공통 설정과 **다른 값만** `[silver.by_slot.N]` 에 남긴다
  (공통 설정을 바꾸면 그 캐릭터도 따라 바뀜). 이 탭이 모르는 키(difficulty, zone)는 건드리지 않는다.
- 검은 구멍 끄기 = `[run.skip_by_slot] N = ["black_hole"]` + `[silver.by_slot.N] black_hole_in_field = false`
  (사냥터 안 검은 구멍까지). 일일 숙제 표에는 '안 함'.
- **자동 설정** (`mabi/tasks/charscan.py`): 확인을 받고 게임을 캐릭터 선택 화면으로 내보내 카드마다 그림·이름·레벨·직업을 읽은 뒤
  골라져 있던 캐릭터로 다시 접속(약 30초). 결과 확인 창에서 이름을 고쳐 '적용'해야 저장된다 (OCR 만 믿지 않음).
  기존 이름은 기본 유지. 첫 줄은 스크롤 맨 위, 마지막 줄은 맨 아래에서 읽는다 (세 줄 이상이면 가운데 줄은 못 읽음).
  - 이름 줄 = '접속 시간'(17시간·30초) 줄 바로 위. 화면 맨 아래 어두운 곳에 걸려 글자가 회색이면 글자 찾기(det)로 다시 읽는다.
  - 마지막으로 읽은 화면은 `logs/shots/charscan_top.png` / `charscan_bottom.png` 로 덮어써 남긴다.
  - 실기 확인(2026-10-21): 6명 이름·레벨·직업 모두 정확.
- **지금 접속한 캐릭터 알아보기** (`mabi/whoami.py`, `characters.json`): CLI 에 캐릭터 이름이 없어서 슬롯마다
  get_my_info 지문(서버·레벨·직업·타이틀·생활력·매력·데코·전투력)을 기억해 가까운 슬롯을 고른다. 상단바에 이름 표시(불확실하면 '?').
  숙제가 접속할 때마다(`runner._remember`), 자동 설정이 다시 접속할 때 새로 기억한다.
  - 접속한 캐릭터의 직업이 카드에서 읽어 둔 직업과 다르면 **기억하지 않는다** (사람이 다른 카드를 클릭한 경우 등).
  - 직업이 다르면 '확실'로 보지 않는다 (생활력·매력·데코는 계정 공용일 수 있음).

### OCR 규칙 (사용자 결정, 2026-10-21)
- **한글은 RapidOCR**(PP-OCRv5 한국어, onnxruntime) — `ocr.read_ko(frame, region)`, `ocr.read_line(img)`.
  게임 글꼴에서 Windows OCR 보다 훨씬 정확 ('옥'을 Windows 는 '목' 처럼 받침·모음을 틀림, '임무ÅI작' → '임무 시작').
  띄어쓰기는 자주 빠뜨리므로 비교는 공백을 빼고 (`ocr.nospace`, `content.has_word`).
- **숫자·영어는 Windows OCR** — `ocr.read_text`. RapidOCR 은 버튼 앞 동전 아이콘에 헷갈려 '20 입장하기' 의 숫자를 빠뜨린다.
- 섞인 버튼('20 입장하기', '10 임무 시작', '2층 3구역 진입')은 `content.read_button` → (가격 = Windows, 글자 = 둘 다).
  가격은 Windows 숫자, 단어('입장'·'시작'·'심층'·'N층 M구역')는 두 OCR 중 하나라도 맞으면. '심층'은 어느 쪽이든 보이면 중단.
- 예외: 캐릭터 카드 레벨 배지(흰 바탕 검은 숫자)는 Windows(흰 글자용)가 못 읽어 RapidOCR — 표시용.
- 주의: `onnxruntime` 을 `winrt` 보다 **먼저** import 해야 한다 (반대면 프로세스가 segfault). `mabi/ocr.py` 맨 위에서 처리.
  RapidOCR 엔진은 `use_det` 를 직전 호출 값으로 기억하므로 매번 명시한다.
- 설치: `pip install --no-deps rapidocr` (opencv-python-headless 를 끌어와 opencv-python 과 cv2 가 겹치므로).
  모델은 처음 쓸 때 내려받는다 (`.venv/Lib/site-packages/rapidocr/models/` — 한국어 인식 13MB, 글자 찾기 10MB).
  exe 포장 때 이 모델 파일들을 같이 넣을 것.

## 지금 구조
```
gui.py              GUI 실행 (관리자 아니면 UAC 로 다시) → gui_app/web_main.py
run.py              콘솔 실행 (일일 숙제만)
web/                화면 — app.js(공통·탭 틀) · craft.js · queue.js · music.js · dye-ui.js · daily.js · chars.js,
                    main.js(시작, 마지막에 읽음) + bridge.js. 같은 전역을 써서 index.html 의 script 순서가 중요하다
gui_app/            web_shell(QtWebEngine 껍데기) · web_main(진입점·트레이) · api(+legacy_shapes) · daily_api · chars_api ·
                    queue_api(작업 큐 카드 종류: 숙제·어비스·목표·행동, F12) · dye_service(+dye_tab: 겹쳐 그리는 창)
mabi/               엔진: paths, userconfig, runner, report, bot, vision, ocr, inputs, game_state, profile, whoami, connector,
                    cache, query, progress, workqueue(작업 큐), craft/, dye/,
                    tasks/(login, charscan, weekday, silver, tribute, black_hole, daily_mission, arbeit, abyss, display, content)
tests/              python -m unittest discover tests · node tests/queue.test.js (게임 없이)
config.toml         숙제 설정 — 기본값과 다른 값만 (mabi.userconfig, 화면은 tomlkit 으로 고침)
profile.json        숙제할 슬롯·이름 · characters.json 슬롯별 지문·카드 정보 · portraits/ 카드 그림
```

## 2026-10-21 밤 상태 (웹 화면 전환 전 기록)
- 3단계 화면 전부 + 4단계 염색 도우미까지 1차 완료. 게임에 연결해 실제로 눌러 본 것은 아직 없음 (게임 꺼짐/연결 상태에서 조회 화면만 확인).
- 제작·가공 판단(mabi/craft)은 리모콘 JS 와 같은 캐시·지식 파일로 대조해 1,834줄·목표 계산까지 일치.
  고친 리모콘 버그: 제작품 이름의 괄호를 벗겨 '구할 수 없음'이 되던 것(goal.js:105), 비재료 사유 검사가 죽어 있던 것(goal.js:101).
- 염색 검출(mabi/dye)은 합성 이미지 6장에서 dye.js 와 비트 단위 일치, 한 바퀴 약 39ms.
  고친 리모콘 버그: 빈 칸이 있으면 칸 색이 밀리던 것(app.js:3086), 가려졌을 때 '직전 값'이 처음 잰 색이던 것(app.js:3320).
- 남은 것: 실제 게임으로 각 기능 확인, 6단계(exe 포장 — data\ 를 datas 에 넣을 것).

## 2026-10-21 밤 상태 (웹 화면 전환 후)
- 웹 화면 + 일일 숙제·기록·캐릭터·염색 연결 완료. 화면 JS 오류 0. 염색 시작/중지·스포이드는 실제 화면 캡처로 확인.
- 캐릭터 자동 설정은 실제 게임으로 확인. 숙제 엔진의 OCR 교체(한글 → RapidOCR)는 저장 화면으로만 확인 — 다음 숙제 실행 때 실제 확인.
- git: `python` 브랜치, 마지막 커밋 68a04cb 이후 변경은 아직 커밋 안 함. GitHub 3.0 push 는 확인 후.
- 남은 것: 실제 숙제 실행으로 확인, 옛 Qt 탭 정리, 6단계(exe — web\, data\, templates\, RapidOCR 모델 포함).
