'use strict';
/**
 * 무거운 조회 응답을 로컬에 캐시한다.
 * get_craftable_items는 444KB/1834건이라 매번 받으면 느리고, 클로드가 읽으면 ~137k 토큰이다.
 * 캐시는 프로그램 폴더가 아니라 %LOCALAPPDATA%에 둔다 (배포판을 덮어써도 남게).
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');
const connector = require('./connector');

const CACHE_DIR = paths.dataPath('cache');

// 명령별 기본 TTL(ms). 자주 안 변하는 목록일수록 길게.
const TTL = {
  get_craftable_items: 10 * 60 * 1000,
  get_alterable_items: 10 * 60 * 1000,
  get_gatherable_items: 10 * 60 * 1000,
  get_items: 2 * 60 * 1000,
  get_music_scores: 60 * 60 * 1000,
  get_instruments: 60 * 60 * 1000,
  get_social_actions: 60 * 60 * 1000,
  get_currencies: 60 * 1000,
  get_my_info: 30 * 1000,
  get_daily_missions: 60 * 1000,
  get_weekly_missions: 5 * 60 * 1000,
  get_quests: 60 * 1000,
  get_inventory: 30 * 1000,
  get_current_environment: 15 * 1000,
  get_activity: 5 * 1000,
  get_altering_works: 30 * 1000,
  // 주변 정보는 움직이면 바로 바뀌므로 캐시하지 않는다
  get_near_npcs: 0,
  get_near_pcs: 0,
};
const DEFAULT_TTL = 60 * 1000;

function cacheFile(command) {
  return path.join(CACHE_DIR, command + '.json');
}

function read(command, maxAgeMs) {
  const ttl = maxAgeMs === undefined ? TTL[command] || DEFAULT_TTL : maxAgeMs;
  if (ttl <= 0) return null;
  try {
    const st = fs.statSync(cacheFile(command));
    if (Date.now() - st.mtimeMs > ttl) return null;
    const entry = JSON.parse(fs.readFileSync(cacheFile(command), 'utf8'));
    return { data: entry.data, ageMs: Date.now() - st.mtimeMs, cached: true };
  } catch (_) {
    return null;
  }
}

function write(command, data) {
  try {
    fs.mkdirSync(CACHE_DIR, { recursive: true });
    fs.writeFileSync(
      cacheFile(command),
      JSON.stringify({ command, savedAt: new Date().toISOString(), data }),
      'utf8'
    );
  } catch (_) {
    /* 캐시 실패는 치명적이지 않다 */
  }
}

/**
 * 같은 명령이 이미 날아가 있으면 그 결과를 같이 쓴다.
 *
 * 대시보드는 재화 카드와 상단바 날개가 모두 get_currencies를 필요로 해서,
 * 한 틱에 같은 명령을 두 번 부르고 있었다. 호출부마다 막지 않고 여기서 합친다.
 */
const inflight = new Map();

/**
 * 캐시 우선 조회. opts.refresh=true면 무조건 새로 받는다.
 * @returns {{data, cached: boolean, ageMs: number, error?: string}}
 */
async function get(command, opts) {
  const options = opts || {};
  if (!options.refresh) {
    const hit = read(command, options.maxAgeMs);
    if (hit) return hit;
  }

  // 게임이 꺼진 걸 이미 아는 상황에서는 호출하지 않는다.
  // 연결 실패 판정에만 약 5초가 걸려서, 화면마다 그 시간을 기다리게 된다.
  if (options.offline) {
    const stale = read(command, Infinity);
    if (stale) return { data: stale.data, cached: true, ageMs: stale.ageMs, stale: true };
    return { data: null, cached: false, ageMs: 0, error: 'disconnected' };
  }

  if (inflight.has(command)) return inflight.get(command);

  const p = (async () => {
    const r = await connector.run(command);
    if (!r.ok) {
      // 실패 시 만료된 캐시라도 있으면 그걸 준다 (오프라인 열람 목적)
      const stale = read(command, Infinity);
      if (stale) return { data: stale.data, cached: true, ageMs: stale.ageMs, stale: true };
      return { data: null, cached: false, ageMs: 0, error: r.error || 'unknown', message: r.message };
    }
    write(command, r.data);
    return { data: r.data, cached: false, ageMs: 0 };
  })();

  inflight.set(command, p);
  try {
    return await p;
  } finally {
    inflight.delete(command);
  }
}

function clear(command) {
  try {
    if (command) fs.unlinkSync(cacheFile(command));
    else fs.rmSync(CACHE_DIR, { recursive: true, force: true });
    return true;
  } catch (_) {
    return false;
  }
}

function list() {
  try {
    return fs.readdirSync(CACHE_DIR).map((f) => {
      const st = fs.statSync(path.join(CACHE_DIR, f));
      return {
        command: f.replace(/\.json$/, ''),
        sizeKB: Math.round(st.size / 1024),
        ageSec: Math.round((Date.now() - st.mtimeMs) / 1000),
      };
    });
  } catch (_) {
    return [];
  }
}

module.exports = { get, read, write, clear, list, CACHE_DIR, TTL };
