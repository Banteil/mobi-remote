'use strict';
/**
 * 이 프로그램이 쓰는 폴더 한 곳.
 *
 * 설정·캐시·학습 데이터·재생목록·로그가 전부 여기 밑에 들어간다.
 * 프로그램 폴더가 아니라 %LOCALAPPDATA%에 두는 이유는 배포판을 덮어써도 살아남고,
 * 폴더를 통째로 남에게 주더라도 내 데이터가 딸려가지 않게 하기 위해서다.
 *
 * ── 왜 모듈로 뺐나 ─────────────────────────────────────────
 * 전에는 여섯 모듈이 각자 path.join(LOCALAPPDATA, '...') 를 적고 있었다.
 * 이름이 바뀌면 여섯 군데를 동시에 고쳐야 하고, 하나라도 빠뜨리면
 * 설정은 새 폴더에서 읽으면서 캐시는 옛 폴더에 쓰는 상태가 된다.
 */
const fs = require('fs');
const path = require('path');

const LOCALAPPDATA =
  process.env.LOCALAPPDATA ||
  path.join(process.env.USERPROFILE || '', 'AppData', 'Local');

/** 현재 폴더 이름. 표시 이름("모비 커넥터 리모콘")과 달리 ASCII 슬러그를 쓴다. */
const DIR_NAME = 'mobi-remote';

/** 이름을 바꾸기 전에 쓰던 폴더. 한 번만 옮겨 온다. */
const OLD_DIR_NAME = 'mm-auto';

const DATA_DIR = path.join(LOCALAPPDATA, DIR_NAME);

/**
 * 옛 폴더가 있고 새 폴더가 없으면 통째로 옮긴다.
 *
 * 이름을 바꿨다고 사용자가 쌓아 둔 것(학습한 레시피, 시설 칸 수, 재생목록, 설정)을
 * 버리게 할 수는 없다. 옮기기에 실패해도 프로그램은 새 폴더에서 빈 상태로 동작한다 —
 * 여기서 예외를 던지면 앱이 아예 못 뜬다.
 */
let migrated = false;
function migrateOnce() {
  if (migrated) return;
  migrated = true;
  try {
    const old = path.join(LOCALAPPDATA, OLD_DIR_NAME);
    if (!fs.existsSync(old) || fs.existsSync(DATA_DIR)) return;
    fs.renameSync(old, DATA_DIR);
  } catch (_) {
    /* 옮기지 못해도 새 폴더로 계속 간다 */
  }
}

/** 데이터 폴더 아래 경로를 만든다. 처음 부를 때 옛 폴더를 옮겨 온다. */
function dataPath() {
  migrateOnce();
  return path.join.apply(null, [DATA_DIR].concat(Array.prototype.slice.call(arguments)));
}

module.exports = { DATA_DIR, DIR_NAME, OLD_DIR_NAME, dataPath, migrateOnce, LOCALAPPDATA };
