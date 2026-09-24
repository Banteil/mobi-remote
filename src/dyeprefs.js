'use strict';
/**
 * 염색 프리셋 — 자주 쓰는 색 세 벌을 이름 붙여 저장한다.
 *
 * 염색은 한 번에 세 칸을 고르는 일이라 색이 늘 셋씩 다닌다. 그리고 같은 조합을
 * 여러 번 쓴다 (머리색 한 벌, 길드 유니폼 한 벌). 그래서 매번 hex 를 다시 치게 두지 않고
 * 이름 붙여 저장해 둔다.
 *
 * 이 파일은 저장만 한다. 색을 찾는 계산은 app/renderer/dye.js 에 있다 —
 * 화면 픽셀이 렌더러에만 있어서 계산도 거기서 한다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');

const FILE = paths.dataPath('dye-presets.json');

/** 처음 켰을 때 빈 화면을 보지 않도록. 스크린샷에서 쓰이던 값이다. */
const SAMPLE = {
  id: 'sample',
  name: '예시',
  colors: ['#005855', '#82FFFF', '#FFF8A9'],
  // 허용 오차는 **색마다** 다르다. 딱 맞아야 하는 색이 있고 비슷하면 되는 색이 있어서,
  // 하나로 묶으면 한쪽 기준에 다른 쪽이 끌려간다.
  tol: [5, 5, 5],
};

const TOL_DEFAULT = 5;

function empty() {
  return { presets: [SAMPLE], currentId: SAMPLE.id };
}

function load() {
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    if (!Array.isArray(d.presets)) return empty();
    // 예전 파일에는 색마다의 오차가 없고 전체 하나만 있었다. 그 값으로 세 칸을 채운다.
    const old = typeof d.tolerance === 'number' ? d.tolerance : TOL_DEFAULT;
    return {
      presets: d.presets
        .filter((p) => p && p.id && Array.isArray(p.colors))
        .map((p) => Object.assign({}, p, { tol: threeTol(p.tol, old) })),
      currentId: d.currentId || (d.presets[0] && d.presets[0].id) || null,
    };
  } catch (_) {
    return empty();
  }
}

function save(state) {
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch (_) { /* 저장 실패가 화면을 막지 않는다 */ }
  return state;
}

/** 색 세 칸을 항상 세 칸으로 맞춘다. 빈 칸은 빈 문자열로 둔다. */
function three(colors) {
  const out = (Array.isArray(colors) ? colors : []).slice(0, 3).map((c) => String(c || '').trim());
  while (out.length < 3) out.push('');
  return out;
}

/** 오차 세 칸. 없거나 이상한 값은 기본값으로 채운다. */
function threeTol(tol, fallback) {
  const base = typeof fallback === 'number' ? fallback : TOL_DEFAULT;
  const out = (Array.isArray(tol) ? tol : []).slice(0, 3).map((v) => {
    const n = Number(v);
    return isNaN(n) ? base : Math.max(0, Math.min(40, n));
  });
  while (out.length < 3) out.push(base);
  return out;
}

function add(name, colors) {
  const s = load();
  const p = {
    id: 'p' + Date.now().toString(36),
    name: String(name || '이름 없음').slice(0, 40),
    colors: three(colors),
    tol: threeTol(null),
  };
  s.presets.push(p);
  s.currentId = p.id;
  save(s);
  return s;
}

function update(id, patch) {
  const s = load();
  const p = s.presets.find((x) => x.id === id);
  if (!p) return s;
  if (patch.name !== undefined) p.name = String(patch.name).slice(0, 40);
  if (patch.colors !== undefined) p.colors = three(patch.colors);
  if (patch.tol !== undefined) p.tol = threeTol(patch.tol);
  return save(s);
}

function remove(id) {
  const s = load();
  s.presets = s.presets.filter((x) => x.id !== id);
  if (!s.presets.length) s.presets = [SAMPLE];
  if (!s.presets.some((x) => x.id === s.currentId)) s.currentId = s.presets[0].id;
  return save(s);
}

function select(id) {
  const s = load();
  if (s.presets.some((x) => x.id === id)) { s.currentId = id; save(s); }
  return s;
}

module.exports = { load, save, add, update, remove, select, FILE };
