'use strict';
/**
 * 로컬 설정.
 *
 * 프로그램 폴더가 아니라 %LOCALAPPDATA%에 둔다. 배포판을 덮어써도 설정이 살아남고,
 * 폴더를 통째로 남에게 줘도 내 설정이 딸려가지 않는다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');

const FILE = paths.dataPath('settings.json');

const DEFAULTS = {
  /** 자동 탐색이 실패했을 때 사용자가 직접 지정한 MabinogiMobile_CLI.exe 경로 */
  cliPath: '',
  /**
   * 표별 정렬 기준. 탭 이름 → 정렬 키.
   * 매번 고르게 하면 번거로워서 기억해 둔다. 기본값은 CLI가 준 순서다 —
   * 그게 게임 화면 순서라, 바꿔 버리면 인게임과 대조가 안 된다.
   */
  sort: {},
  /** 'dark' | 'light'. 화면 전용 설정이라 게임 호출과 무관하다. */
  theme: 'dark',
  /**
   * 정해 둔 시설 레벨이 실제와 어긋날 때 물어볼지.
   * 사용자가 "다시 묻지 않기"를 고르면 false가 되고, 옵션에서 다시 켤 수 있다.
   */
  askFacilityLevelMismatch: true,
};

function load() {
  try {
    return Object.assign({}, DEFAULTS, JSON.parse(fs.readFileSync(FILE, 'utf8')));
  } catch (_) {
    return Object.assign({}, DEFAULTS);
  }
}

function save(patch) {
  const next = Object.assign(load(), patch || {});
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(next, null, 2), 'utf8');
  } catch (_) {
    /* 저장에 실패해도 화면은 계속 동작해야 한다 */
  }
  return next;
}

module.exports = { load, save, FILE, DEFAULTS };
