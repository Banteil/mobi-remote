# 모비 커넥터 리모콘 (파이썬판)

마비노기 모바일(PC, 1920x1080) 리모콘 + 일일 숙제 자동화. 조회는 공식 커넥터 CLI, 숙제 조작은 화면 템플릿 매칭 + OCR + SendInput.

> 넥슨 운영정책상 매크로 사용은 제재 대상이 될 수 있습니다. 사용 책임은 본인에게 있습니다.

## 화면 실행 (모비 커넥터 리모콘 3.0)
```powershell
.\.venv\Scripts\pythonw.exe gui.py     # 관리자가 아니면 UAC 로 다시 띄움
```
탭: **캐릭터**(시작 탭, 캐릭터별 숙제 설정·자동 설정) · 대시보드 · 제작 · 가공 · 채집 · 소지품 · 미션 · 연주 · 소셜 · 염색 ·
일일 숙제 · 숙제 기록. 화면은 `web/`(HTML/JS), 속은 파이썬 — 구조는 [docs/PLAN.md](docs/PLAN.md).

설치: `pip install -r requirements.txt` 후 **`pip install --no-deps rapidocr`** (한글 OCR. 의존성을 같이 깔면
opencv-python-headless 가 들어와 opencv-python 과 겹칩니다).

함께 깔면 좋은 것: **[Npcap](https://npcap.com/#download)** (무료). 게임 서버가 보내는 패킷을 받기만 해서 맵 이동·던전·대화 같은
상태를 화면보다 빨리 압니다. 무료판은 재배포·무인 설치가 허락되지 않아 설치 파일에 넣지 않고, 없으면 설치 마지막 화면,
켤 때 위쪽 알림 띠(포터블판 포함, '다시 묻지 않기' 가능), 옵션 창 '패킷 감시' 줄에서 받는 곳을 엽니다. 없어도 리모콘은
화면·CLI 로 돕니다. 설치한 뒤 '다시 확인' 을 누르면 리모콘을 다시 켜지 않고 감시가 켜집니다.
새 판은 켤 때 한 번 확인하고, 옵션 창 '새 판 확인' 으로 언제든 다시 확인해 그 자리에서 받아 설치할 수 있습니다.

## 콘솔 실행 (관리자 권한 터미널)
게임이 관리자 권한으로 실행되므로, 봇도 관리자 권한이 아니면 입력이 무시됩니다.

```powershell
.\.venv\Scripts\python.exe run.py               # 숙제할 캐릭터 전원 (처음엔 슬롯 번호를 물어봄)
.\.venv\Scripts\python.exe run.py --setup       # 숙제할 슬롯 번호 다시 입력
.\.venv\Scripts\python.exe run.py --chars 5,6   # 일부 슬롯만
.\.venv\Scripts\python.exe run.py --only silver # 일부 숙제만
.\.venv\Scripts\python.exe run.py --current     # 캐릭터 전환 없이 현재 캐릭터로
.\.venv\Scripts\python.exe run.py --force       # 오늘 끝낸 숙제도 다시
.\.venv\Scripts\python.exe run.py --dry-run     # 클릭 없이 인식만
```
실행 중 **F12** = 일시정지 · 다시 누르면 이어 하기, **Shift+F12** = 지금 작업만 중단하고 다음으로, **Ctrl+F12** = 큐 전체 중단.
로그는 `logs/`, 실패 시 스크린샷은 `logs/shots/` (7일 지나면 지운다).

숙제별 동작, 확인된 게임 동작, 남은 일은 [docs/STATUS.md](docs/STATUS.md) 에 정리되어 있습니다.
실행 중에는 게임 화면을 다른 창으로 가리지 말고, Windows 방해 금지 모드를 켜 두세요.

## 캐릭터 선택
처음 실행하면 **숙제할 슬롯 번호**(캐릭터 선택 화면에서 왼쪽 위부터 1, 2, 3, 4 / 다음 줄 5, 6 …)와
표시 이름(선택)을 물어보고 `profile.json` 에 저장합니다. 숙제가 필요 없는 캐릭터는 빼면 됩니다.
- 선택 화면 정렬은 **캐릭터 생성 순**으로 두세요. 정렬이 바뀌면 번호가 달라집니다.
- 보유 캐릭터 수는 화면에서 자동으로 셉니다 (두 줄, 8명까지 지원).
- 카드 위치는 카드의 `•••` 버튼으로 계산하고, 스크롤과 노란 선택 테두리를 확인한 뒤에만 접속합니다.
  확인에 실패하면 엉뚱한 캐릭터로 들어가지 않고 실패 처리합니다.
- 캐릭터 접속 사이에는 `[login].min_interval` 초 이상 간격을 둡니다 (잦은 전환은 인증 오류를 부름).
- 캐릭터별 숙제 순서는 `config.toml` 의 `[run.tasks_by_slot]` 로, 끌 숙제는 `[run.skip_by_slot]` 로 바꿀 수 있습니다
  (화면의 캐릭터 탭이 슬롯·이름·캐릭터별 설정을 고치고, '자동 설정'으로 선택 화면에서 읽어 올 수도 있습니다).

## 하루 진행 기록
숙제 결과는 `state/<게임 날짜>.json` 에 캐릭터(슬롯)별로 저장됩니다. 게임은 **오전 6시**에 초기화되므로
6시 전은 전날로 칩니다. 오늘 숙제를 모두 끝낸 캐릭터는 다시 실행해도 접속하지 않고 건너뜁니다.

## 게임 상태 조회 (CLI)
게임 설정의 **MM AI 에이전트 활성화**를 켜면 설치되는 `MabinogiMobile_CLI.exe` 의 조회 명령으로
재화 개수 등 상태를 읽습니다 (`mabi/game_state.py`). 조작에는 쓰지 않습니다.
설정이 꺼져 있거나 7일 만료되면 HUD 숫자 판독으로 대체합니다.

## 템플릿 만들기
1. `python tools/capture.py missing` 으로 필요한 템플릿 목록 확인
2. `python tools/capture.py snap` 실행 후 게임에서 각 화면마다 **F9** (끝내면 F10) → `captures/`
3. `python tools/capture.py crop captures/<파일>.png <템플릿이름>` 으로 드래그해서 저장
   (`--rect x,y,w,h` 로 영역을 직접 지정할 수도 있음)
   - 목록 속 버튼처럼 위치가 바뀌는 것은 `--anywhere`
4. `python tools/capture.py test <템플릿이름>` 으로 점수 확인 (0.85 이상이면 양호)

## 재화 숫자 샘플
은동전/공물 개수는 HUD 의 흰 숫자를 0~9 샘플과 비교해 읽습니다 (`templates/digits/`).
아직 없는 숫자가 나오면 판독에 실패하므로, 다른 값일 때 화면을 보며 등록하세요.
```powershell
.\.venv\Scripts\python.exe tools\capture.py digits silver 43    # 화면에 보이는 은동전 값
.\.venv\Scripts\python.exe tools\capture.py read                # 판독 확인
```

템플릿은 버튼의 **변하지 않는 부분**(아이콘, 글자)만 작게 자르는 것이 좋습니다.
숫자·애니메이션·캐릭터가 섞인 영역은 피하세요.

## 구조
- `mabi/` window(창) · screen(캡처) · vision(매칭) · ocr(한글 RapidOCR / 숫자·영어 Windows OCR) · inputs(입력) ·
  game_state(CLI 조회) · bot(대기/클릭/복구 API) · whoami(캐릭터 카드 정보)
- `mabi/tasks/` login · charscan(캐릭터 선택 화면 읽기) · weekday · silver · tribute · black_hole · daily_mission ·
  arbeit(아르바이트) · display(게임 화면 설정) · content(던전/사냥터 공용)
- `gui_app/` · `web/` 화면 (docs/PLAN.md '지금 구조')
- `config.default.toml` 기본 설정 (실행 순서·숙제별 설정·템플릿 이름). `config.toml` 에는 이와 다른 값만 저장되고
  나머지는 기본값을 따른다 — 새 판에서 바뀐 기본값이 그대로 적용된다 (개인 설정이라 저장소에는 올리지 않음)
- `profile.json` 숙제할 슬롯 · `state/` 하루 진행 기록 (숙제 안 단계까지 — 끊기면 그 자리부터 이어 함)
- `captures/` 템플릿을 잘라낸 원본 스크린샷
