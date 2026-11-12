# mobi-remote 작업 원칙

마비노기 모바일 PC 클라이언트를 화면·입력·CLI 조회로 돌리는 리모콘 (일일 숙제·어비스·레이드·작업 큐).
코드 구조와 공통 부품은 **`docs/ARCHITECTURE.md`** 를 먼저 읽는다. 기능별 메모는 `docs/STATUS.md`.

## 지켜야 할 것

- **게임에 보내지 않는다.** 패킷은 받기(sniff)만 — 전송·변조·주입·재전송, 게임 메모리 읽기·후킹 금지.
  게임 설치 폴더는 읽기만 하고 분석은 복사본으로. 게임 조작은 키·마우스 입력으로만, CLI 는 조회에만 쓴다.
- **실제 캐릭터 이름을 저장소에 쓰지 않는다** (코드·주석·커밋·문서·릴리스 노트). pre-commit / commit-msg 훅이 `profile.json` 이름으로 검사한다.
- **상태 판단은 CLI 가 기준**, 패킷은 실시간 변화와 CLI 에 없는 정보에. 작업을 시작할 때마다 지금 상태부터 본다 (`bot.check_in`).
- **시간 + 상태로 판단.** 화면 전환을 고정 sleep 으로 가정하지 않는다 — 시간 상한과 확실한 신호를 같이 본다.
- **NPC 대사 내용으로 판단하지 않는다.** 메뉴가 떴는지·단계가 넘어갔는지·버튼 글자로.
- 단축키 배지가 있는 버튼은 키로 누른다. 부활은 '여기서 부활' 만.

## 구조 방향

- **같은 일은 한 곳에서.** 새 기능 전에 비슷한 구현이 있는지 찾고(ARCHITECTURE 의 공통 부품 표), 있으면 그대로 쓰거나
  둘이 같이 쓰게 넓힌다. 새 방식이 더 나으면 기존 것을 전면 수정해도 되지만 옛 길은 남기지 않는다.
- **객체 지향으로**: 공통 흐름은 기반 클래스·공용 부품(`Repeat`, `Kind`, `LootMeter`, `monitor.Ctx` …),
  종류마다 다른 것만 오버라이딩·주입으로.
- 과하게 복잡하게 만들지 않는다. 고칠 때 한쪽만 땜질하지 말고 같은 일을 하는 다른 곳도 본다.

## 값을 둘 자리

코드에 숫자·글자를 박지 않는다 — 게임 패치·사용자 조절 때 코드를 고치지 않게. `tests/test_value_homes.py` 가 일부를 막는다.

| 값 | 자리 | 읽기 |
|---|---|---|
| 화면에서 찾는 문구, 읽을 영역, 누르는 자리 (1920x1080) | `data/ui.json` text · regions · points | `gamedata.text/words/region/point` |
| 한 기능의 화면 좌표가 이미 설정 구역에 모여 있으면 (지도 `[map]` 등) | 그 구역 | `bot.cfg[구역][키]` |
| 게임 규칙 (재화 이름, 날개·추가 루팅 비용, 직업, 시설 칸 수) | `data/game-rules.json` | `gamedata.rules()` |
| 게임 데이터에서 뽑은 목록·일정 (필드 보스·레이드·어비스) | `data/content.json` — 손으로 고치지 않고 다시 뽑는다 | `gamedata.raids/abysses/field_bosses` |
| 사용자가 조절하는 값, 시간 상한 | `config.default.toml` (사용자 `config.toml` 이 덮음) | `cfg[구역][키]` — `cfg.get(구역, {})` 로 기본값을 또 들지 않는다 |
| 화면이 비워 보낸 값의 기본값 | `config.default.toml` | `userconfig.default(paths, 구역, 키)` |
| 웹 화면이 기억하는 값 | settings.json | `pref()`/`setPref()` + `api.CFG_KEYS` — `localStorage` 금지 |
| 상태·출처 같은 표시 문구 | `data/labels.json` | `gamedata.labels()` |

## 작업 방식

- 테스트: `.venv/Scripts/python.exe -m unittest discover -s tests` — 바꾼 동작에 테스트를 단다.
- 커밋 메시지는 한국어, 제목에 무엇을, 본문에 왜(어떤 일이 있었나). 수정은 커밋까지, 판 올림·릴리스는 사용자가 정할 때.
- 판 번호는 `gui_app/api.py` 의 `APP_VERSION`. 배포판은 `tools/build.py` (설치 파일 + 패치 zip 을 함께 릴리스).
  빌드 venv 에 개발용 패키지를 깔지 않는다 — 설치된 패키지 목록이 런타임 구성 값에 들어가 패치 대신 설치 파일을 받게 된다.
- 리모콘이 돌고 있으면 재시작하지 않는다 (로그 `logs/<날짜>.log` 로 먼저 확인).
- 검증은 샘플 몇 개로 — 수백 장 일괄 비교는 하지 않는다.
