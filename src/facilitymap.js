'use strict';
/**
 * 가공 레시피 → 시설 표 (facility-map.json).
 *
 * 커넥터가 주지 않는 정보라 파일로 들고 있는다. 자세한 사정은 그 파일의 _설명을 볼 것.
 *
 * ── 이 표와 관측값의 관계 ──────────────────────────────────
 * 실제로 큐에서 본 값(knowledge.json 의 itemFacility)이 **항상 이긴다.**
 * 이 표는 아직 본 적 없는 레시피를 위한 보조 수단이고, 한 번 돌리면 관측값으로 덮인다.
 * 그래서 여기 값이 틀려도 한 번 써 보면 저절로 고쳐지고, 잘못된 값이 굳지 않는다.
 *
 * 파일이 없거나 깨져 있어도 프로그램은 떠야 한다 — 그때는 빈 표로 돈다.
 * 표가 비면 예전처럼 "처음 돌리는 레시피는 미리 검사 못 함" 상태가 될 뿐이다.
 */
const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'facility-map.json');

let cached = null;
let broken = false;

function load() {
  if (cached) return cached;
  try {
    const raw = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    cached = {
      facilities: Array.isArray(raw.facilities) ? raw.facilities : [],
      recipes: raw.recipes && typeof raw.recipes === 'object' ? raw.recipes : {},
    };
    broken = false;
  } catch (_) {
    cached = { facilities: [], recipes: {} };
    broken = true;
  }
  return cached;
}

/** 이 레시피의 시설. 표에 없으면 null. */
function facilityOf(recipeName) {
  if (!recipeName) return null;
  return load().recipes[recipeName] || null;
}

/** 게임에 있는 가공 시설 이름들 */
function facilities() {
  return load().facilities.slice();
}

/** 표에 적힌 레시피 수 */
function size() {
  return Object.keys(load().recipes).length;
}

/** 파일을 못 읽었는가. 화면에 알릴 때 쓴다. */
function isBroken() {
  load();
  return broken;
}

module.exports = { FILE, facilityOf, facilities, size, isBroken };
