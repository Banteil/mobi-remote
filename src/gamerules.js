'use strict';
/**
 * 게임 쪽 규칙 표 (game-rules.json).
 *
 * 커넥터가 알려주지 않지만 프로그램이 알아야 하는 값들이다.
 * 지금은 가공 시설의 레벨별 칸 수 하나뿐이다.
 *
 * ── 왜 파일로 빼나 ─────────────────────────────────────────
 * 코드에 박아 두면 게임이 패치될 때마다 프로그램을 고쳐 다시 빌드해야 한다.
 * 파일로 두면 값만 바꾸고 다시 켜면 끝이다. 배포 후에 대응하기도 쉽다.
 *
 * 파일이 없거나 깨져 있어도 프로그램은 떠야 한다. 그래서 같은 내용을 기본값으로
 * 들고 있다가 그쪽으로 떨어진다 — 여기서 예외를 던지면 앱이 아예 못 뜬다.
 */
const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'game-rules.json');

/** 파일을 못 읽었을 때 쓰는 값. game-rules.json 과 같은 내용을 유지할 것. */
const FALLBACK = {
  alteringFacility: {
    maxLevel: 6,
    slotsByLevel: { 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7 },
  },
};

let cached = null;
let usedFallback = false;

function load() {
  if (cached) return cached;
  try {
    const raw = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    const f = raw.alteringFacility;
    // 최소한의 형태 검사. 깨진 값으로 칸 수를 계산하면 날개가 헛나간다.
    if (!f || !(f.maxLevel > 0) || !f.slotsByLevel || !(f.slotsByLevel[1] > 0)) {
      throw new Error('alteringFacility 형식이 올바르지 않습니다');
    }
    cached = raw;
    usedFallback = false;
  } catch (_) {
    cached = FALLBACK;
    usedFallback = true;
  }
  return cached;
}

/** 가공 시설 규칙 { maxLevel, slotsByLevel } */
function alteringFacility() {
  return load().alteringFacility;
}

/** 레벨 → 칸 수. 표에 없는 레벨은 가장 가까운 값으로 맞춘다. */
function slotsForLevel(level) {
  const f = alteringFacility();
  const n = Math.round(Number(level));
  if (!(n >= 1)) return f.slotsByLevel[1];
  const hit = f.slotsByLevel[n] || f.slotsByLevel[String(n)];
  if (hit > 0) return hit;
  return f.slotsByLevel[f.maxLevel] || f.slotsByLevel[String(f.maxLevel)] || f.slotsByLevel[1];
}

/** 칸 수 → 레벨. 화면에 "지금 몇 레벨로 보고 있는지"를 적을 때 쓴다. 없으면 null. */
function levelForSlots(slots) {
  const f = alteringFacility();
  for (let lv = 1; lv <= f.maxLevel; lv++) {
    if (slotsForLevel(lv) === slots) return lv;
  }
  return null;
}

/** 레벨 1일 때의 칸 수. 아무것도 모를 때의 안전한 기본값이다. */
function minSlots() {
  return slotsForLevel(1);
}

function maxLevel() {
  return alteringFacility().maxLevel;
}

/** 규칙 파일을 못 읽어 기본값으로 돌고 있는가. 화면에 알릴 때 쓴다. */
function isFallback() {
  load();
  return usedFallback;
}

module.exports = {
  FILE, load, alteringFacility, slotsForLevel, levelForSlots, minSlots, maxLevel, isFallback,
};
