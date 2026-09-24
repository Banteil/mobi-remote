'use strict';
/**
 * 렌더러에 노출하는 유일한 통로.
 * Node(fs, child_process 등)는 절대 넘기지 않고, 정해진 IPC 채널만 감싼다.
 */
const { contextBridge, ipcRenderer } = require('electron');
const settings = require('../src/settings');

/**
 * 시작 테마를 **동기로** 읽어 둔다.
 *
 * IPC로 물어보면 응답이 오기 전에 화면이 한 번 그려져서, 라이트 모드인데도
 * 어두운 화면이 번쩍였다가 바뀐다. preload는 페이지 스크립트보다 먼저 돌고
 * 파일을 직접 읽을 수 있으므로 여기서 끝낸다.
 */
let initialTheme = 'dark';
try {
  initialTheme = settings.load().theme === 'light' ? 'light' : 'dark';
} catch (_) { /* 설정을 못 읽으면 기본값으로 */ }

/** 메인이 보내는 이벤트를 구독한다. 반환값은 구독 해제 함수. */
function on(channel, cb) {
  const handler = (_e, payload) => cb(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

contextBridge.exposeInMainWorld('mm', {
  /** 첫 페인트 전에 theme.js 가 읽어 간다 */
  initialTheme: initialTheme,

  /* 조회 */
  status: () => ipcRenderer.invoke('status'),
  query: (name, opts) => ipcRenderer.invoke('query', name, opts),
  queryMany: (names, opts) => ipcRenderer.invoke('queryMany', names, opts),

  /* 실행 */
  exec: (command, body) => ipcRenderer.invoke('exec', command, body),
  cancel: () => ipcRenderer.invoke('cancel'),
  costOf: (command, times) => ipcRenderer.invoke('costOf', command, times),

  /* 메타 */
  capabilities: (refresh) => ipcRenderer.invoke('capabilities', refresh),

  /* 로그 */
  log: {
    tail: (n) => ipcRenderer.invoke('log:tail', n),
    files: () => ipcRenderer.invoke('log:files'),
    open: () => ipcRenderer.invoke('log:open'),
  },

  /* 학습된 지식 */
  knowledge: {
    get: () => ipcRenderer.invoke('kn:get'),
    setSlots: (f, n) => ipcRenderer.invoke('kn:setSlots', f, n),
    setLevel: (f, n) => ipcRenderer.invoke('kn:setLevel', f, n),
    rules: () => ipcRenderer.invoke('kn:rules'),
    markFull: (f, n) => ipcRenderer.invoke('kn:markFull', f, n),
    forgetRecipe: (name) => ipcRenderer.invoke('kn:forgetRecipe', name),
  },
  cfg: {
    get: () => ipcRenderer.invoke('cfg:get'),
    sort: (tab, key) => ipcRenderer.invoke('cfg:sort', tab, key),
    theme: (v) => ipcRenderer.invoke('cfg:theme', v),
    set: (key, value) => ipcRenderer.invoke('cfg:set', key, value),
  },
  goal: {
    next: (name, target) => ipcRenderer.invoke('goal:next', name, target),
  },

  /* 재생목록 */
  pl: {
    list: () => ipcRenderer.invoke('pl:list'),
    create: (name) => ipcRenderer.invoke('pl:create', name),
    update: (id, patch) => ipcRenderer.invoke('pl:update', id, patch),
    remove: (id) => ipcRenderer.invoke('pl:remove', id),
    addTrack: (id, title) => ipcRenderer.invoke('pl:addTrack', id, title),
    removeTrack: (id, i) => ipcRenderer.invoke('pl:removeTrack', id, i),
    moveTrack: (id, i, d) => ipcRenderer.invoke('pl:moveTrack', id, i, d),
  },

  /* 제작 계획 */
  planCraft: (name, target, opts) => ipcRenderer.invoke('plan:craft', name, target, opts),
  /** 가공 목표를 사슬 끝까지 — 무엇을 몇 번 캐야 하는지까지 */
  planNeeds: (target, count, opts) => ipcRenderer.invoke('plan:needs', target, count, opts),

  /* CLI 경로 */
  cli: {
    locate: (force) => ipcRenderer.invoke('cli:locate', force),
    choose: () => ipcRenderer.invoke('cli:choose'),
    clearPath: () => ipcRenderer.invoke('cli:clearPath'),
  },

  /* 염색 도우미 */
  dye: {
    prefs: () => ipcRenderer.invoke('dye:prefs'),
    add: (name, colors) => ipcRenderer.invoke('dye:add', name, colors),
    update: (id, patch) => ipcRenderer.invoke('dye:update', id, patch),
    remove: (id) => ipcRenderer.invoke('dye:remove', id),
    select: (id) => ipcRenderer.invoke('dye:select', id),
    source: () => ipcRenderer.invoke('dye:source'),
    snap: () => ipcRenderer.invoke('dye:snap'),
    shot: () => ipcRenderer.invoke('dye:shot'),
    draw: (payload) => ipcRenderer.invoke('dye:draw', payload),
    protect: (on) => ipcRenderer.invoke('dye:protect', on),
    hide: () => ipcRenderer.invoke('dye:hide'),
  },

  /* 새 판 확인 — 받는 것까지만 하고, 설치는 사람이 누를 때 */
  update: {
    check: () => ipcRenderer.invoke('update:check'),
    download: (asset) => ipcRenderer.invoke('update:download', asset),
    install: (file) => ipcRenderer.invoke('update:install', file),
    page: () => ipcRenderer.invoke('update:page'),
    onProgress: (cb) => on('mm:update-progress', cb),
  },

  /* 창 — 작업 큐를 접을 때 창도 같이 좁힌다 */
  win: {
    narrow: (px) => ipcRenderer.invoke('win:narrow', px),
  },

  /* 레시피 장부 */
  book: {
    stats: () => ipcRenderer.invoke('book:stats'),
    harvest: () => ipcRenderer.invoke('book:harvest'),
  },

  /* 작업 큐 */
  queue: {
    load: () => ipcRenderer.invoke('queue:load'),
    save: (state) => ipcRenderer.invoke('queue:save', state),
  },

  /* 즐겨찾기 */
  fav: {
    all: () => ipcRenderer.invoke('fav:all'),
    toggle: (list, name) => ipcRenderer.invoke('fav:toggle', list, name),
    clear: (list) => ipcRenderer.invoke('fav:clear', list),
  },

  /* 버전 · 호환성 */
  version: {
    info: () => ipcRenderer.invoke('version:info'),
    check: (refresh) => ipcRenderer.invoke('version:check', refresh),
    accept: (note) => ipcRenderer.invoke('version:accept', note),
  },

  /* 루틴 */
  routines: {
    list: () => ipcRenderer.invoke('routines:list'),
    run: (id, opts) => ipcRenderer.invoke('routines:run', id, opts),
  },

  /* 캐시 */
  cache: {
    list: () => ipcRenderer.invoke('cache:list'),
    clear: (command) => ipcRenderer.invoke('cache:clear', command),
  },

  openExternal: (url) => ipcRenderer.invoke('openExternal', url),

  /* 이벤트 */
  onExecStart: (cb) => on('mm:exec-start', cb),
  onExecDone: (cb) => on('mm:exec-done', cb),
  onRoutineEvent: (cb) => on('mm:routine-event', cb),
  /** 가공 시설 레벨이 자동으로 정해졌을 때 알려 준다 */
  onFacilityLevel: (cb) => on('mm:facility-level', cb),
});
