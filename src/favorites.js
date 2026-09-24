'use strict';
/**
 * 즐겨찾기.
 *
 * 목록이 길다. 제작 레시피 87종, 채집 90종, 행동 147종… 필터와 정렬로 좁힐 수는 있어도
 * "내가 맨날 쓰는 대여섯 개"는 매번 다시 찾아야 한다. 그래서 별표를 달아 두고,
 * 화면에서는 같은 표 안에 **즐겨찾기 구역**을 따로 만들어 위로 끌어올린다.
 *
 * ── 왜 정렬이 아니라 구역인가 ───────────────────────────────
 * 즐겨찾기를 맨 위로 올리는 정렬을 하나 더 만들 수도 있었다. 그러면 "가나다순인데
 * 즐겨찾기만 위"처럼 두 기준이 섞여 무엇을 보고 있는지 알기 어려워진다.
 * 구역을 나누면 각 구역 안에서는 고른 정렬이 그대로 지켜진다.
 *
 * ── 무엇을 키로 쓰나 ────────────────────────────────────────
 * 표시 이름이 아니라 **원본 이름**(nameRaw)이다. 게임 이름에는 <color=…> 태그가 섞여
 * 있어서 표시용으로 벗긴 이름을 키로 쓰면 태그가 붙고 떨어질 때마다 별표가 풀린다.
 *
 * 연주 탭(악기·악보)에는 두지 않는다. 악보의 즐겨찾기는 이미 재생목록이고,
 * 별표까지 두면 같은 일을 하는 장치가 둘이 된다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');

const FILE = paths.dataPath('favorites.json');

/** 별표를 달 수 있는 목록. 여기 없는 이름으로 오는 요청은 조용히 무시한다. */
const LISTS = ['craft', 'alter', 'gather', 'items', 'facial', 'behaviour'];

function empty() {
  const o = {};
  for (const k of LISTS) o[k] = [];
  return o;
}

function load() {
  const base = empty();
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    for (const k of LISTS) if (Array.isArray(d[k])) base[k] = d[k].map(String);
  } catch (_) {
    /* 파일이 없거나 깨졌으면 빈 상태로 시작한다 */
  }
  return base;
}

function save(state) {
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch (_) {
    /* 저장에 실패해도 화면은 계속 돌아야 한다 */
  }
  return state;
}

/**
 * 켜져 있으면 끄고, 꺼져 있으면 켠다.
 * @returns {{ok: boolean, on: boolean, list: string, name: string, favorites: object}}
 */
function toggle(list, name) {
  const key = String(name || '');
  if (LISTS.indexOf(list) < 0 || !key) {
    return { ok: false, on: false, list: list, name: key, favorites: load() };
  }
  const state = load();
  const at = state[list].indexOf(key);
  if (at >= 0) state[list].splice(at, 1);
  else state[list].push(key);
  save(state);
  return { ok: true, on: at < 0, list: list, name: key, favorites: state };
}

/** 한 목록을 통째로 비운다. 별표를 하나씩 끄지 않아도 되게. */
function clear(list) {
  if (LISTS.indexOf(list) < 0) return load();
  const state = load();
  state[list] = [];
  return save(state);
}

module.exports = { LISTS, load, toggle, clear, FILE };
