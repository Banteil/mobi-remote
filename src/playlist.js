'use strict';
/**
 * 연주 재생목록.
 *
 * 커넥터는 캐릭터명은커녕 캐릭터 고유 ID조차 주지 않는다(조회 19종 전수 확인).
 * 그래서 "이 목록은 어느 캐릭터 것"을 앱이 자동으로 알 방법이 없다.
 *
 * 대신 이렇게 푼다.
 *   · 목록은 계정/캐릭터와 무관하게 저장하고 사용자가 이름을 붙인다
 *   · 재생할 때 현재 캐릭터의 보유 악보와 대조해 **가진 곡만** 재생한다
 * 캐릭터를 바꿔도 목록이 깨지지 않고 알아서 줄어든다.
 *
 * 저장 위치는 프로그램 폴더가 아니라 %LOCALAPPDATA%다. 배포판을 덮어써도 남는다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');

const FILE = paths.dataPath('playlists.json');

function load() {
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    return Array.isArray(d.lists) ? d : { lists: [] };
  } catch (_) {
    return { lists: [] };
  }
}

function save(state) {
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch (_) {
    /* 저장 실패해도 화면은 계속 동작해야 한다 */
  }
  return state;
}

function list() {
  return load().lists;
}

function get(id) {
  return load().lists.find((x) => x.id === id) || null;
}

function create(name) {
  const state = load();
  const item = {
    id: 'pl' + Date.now().toString(36),
    name: (name || '새 재생목록').slice(0, 40),
    tracks: [],
    loop: false,
    shuffle: false,
    createdAt: new Date().toISOString(),
  };
  state.lists.push(item);
  save(state);
  return item;
}

function update(id, patch) {
  const state = load();
  const item = state.lists.find((x) => x.id === id);
  if (!item) return null;
  if (patch.name !== undefined) item.name = String(patch.name).slice(0, 40);
  if (patch.tracks !== undefined) item.tracks = patch.tracks.slice(0, 300);
  if (patch.loop !== undefined) item.loop = !!patch.loop;
  if (patch.shuffle !== undefined) item.shuffle = !!patch.shuffle;
  save(state);
  return item;
}

function remove(id) {
  const state = load();
  const before = state.lists.length;
  state.lists = state.lists.filter((x) => x.id !== id);
  save(state);
  return state.lists.length < before;
}

/** 곡을 목록 끝에 더한다. 이미 있으면 그대로 둔다. */
function addTrack(id, title) {
  const item = get(id);
  if (!item) return null;
  if (!item.tracks.includes(title)) item.tracks.push(title);
  return update(id, { tracks: item.tracks });
}

function removeTrack(id, index) {
  const item = get(id);
  if (!item || index < 0 || index >= item.tracks.length) return item;
  item.tracks.splice(index, 1);
  return update(id, { tracks: item.tracks });
}

/** 순서를 한 칸 옮긴다. delta는 -1(위) 또는 +1(아래). */
function moveTrack(id, index, delta) {
  const item = get(id);
  if (!item) return null;
  const to = index + delta;
  if (index < 0 || index >= item.tracks.length || to < 0 || to >= item.tracks.length) return item;
  const [t] = item.tracks.splice(index, 1);
  item.tracks.splice(to, 0, t);
  return update(id, { tracks: item.tracks });
}

module.exports = {
  list, get, create, update, remove,
  addTrack, removeTrack, moveTrack,
  FILE,
};
