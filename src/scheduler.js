'use strict';
/**
 * 스케줄.
 *
 * 두 가지 방식을 지원한다.
 *  1) 상주 모드 - 이 프로그램을 띄워 둔 채로 시각을 감시한다 (mobi-remote schedule run).
 *  2) Windows 작업 스케줄러 등록 - 프로그램을 안 띄워도 OS가 시간에 맞춰 실행한다.
 *     실제 등록은 사용자가 명시적으로 확인했을 때만 한다 (시스템 변경이므로).
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');
const { spawnSync } = require('child_process');
const routines = require('./routines');

const STATE_DIR = paths.dataPath();
const SCHEDULE_FILE = path.join(STATE_DIR, 'schedule.json');
const LOG_FILE = path.join(STATE_DIR, 'schedule.log');

const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const DAY_LABEL = { sun: '일', mon: '월', tue: '화', wed: '수', thu: '목', fri: '금', sat: '토' };

function load() {
  try {
    return JSON.parse(fs.readFileSync(SCHEDULE_FILE, 'utf8'));
  } catch (_) {
    return { entries: [] };
  }
}

function save(state) {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  fs.writeFileSync(SCHEDULE_FILE, JSON.stringify(state, null, 2), 'utf8');
}

function add(entry) {
  const state = load();
  const id = entry.id || 'sch' + Date.now().toString(36);
  const rec = {
    id: id,
    routine: entry.routine,
    time: entry.time,
    days: entry.days && entry.days.length ? entry.days : DAYS.slice(),
    enabled: entry.enabled !== false,
    lastRun: null,
  };
  state.entries.push(rec);
  save(state);
  return rec;
}

function remove(id) {
  const state = load();
  const before = state.entries.length;
  state.entries = state.entries.filter((e) => e.id !== id);
  save(state);
  return state.entries.length < before;
}

function setEnabled(id, enabled) {
  const state = load();
  const e = state.entries.find((x) => x.id === id);
  if (!e) return false;
  e.enabled = enabled;
  save(state);
  return true;
}

function describe(entry) {
  const days =
    entry.days.length === 7 ? '매일' : entry.days.map((d) => DAY_LABEL[d] || d).join('');
  return days + ' ' + entry.time;
}

function log(line) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    fs.appendFileSync(LOG_FILE, '[' + new Date().toISOString() + '] ' + line + '\n', 'utf8');
  } catch (_) {
    /* 로그 실패는 무시 */
  }
}

function hhmm(d) {
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

/** 지금 실행해야 할 항목들. 같은 분에 두 번 돌지 않도록 lastRun을 본다. */
function due(now) {
  const t = now || new Date();
  const key = t.toDateString() + ' ' + hhmm(t);
  const day = DAYS[t.getDay()];
  const state = load();
  return state.entries.filter(
    (e) => e.enabled && e.time === hhmm(t) && e.days.indexOf(day) >= 0 && e.lastRun !== key
  );
}

function markRan(id, now) {
  const t = now || new Date();
  const state = load();
  const e = state.entries.find((x) => x.id === id);
  if (e) {
    e.lastRun = t.toDateString() + ' ' + hhmm(t);
    save(state);
  }
}

/**
 * 상주 모드. 30초마다 확인한다.
 * @param opts {onRun, onTick, runner}  runner(routine) -> Promise<summary>
 */
function startDaemon(opts) {
  const o = opts || {};
  const intervalMs = o.intervalMs || 30000;
  let running = false;

  const tick = async () => {
    if (o.onTick) o.onTick(new Date());
    if (running) return;
    const list = due();
    if (!list.length) return;
    running = true;
    for (const entry of list) {
      const routine = routines.loadRoutine(entry.routine);
      if (!routine) {
        log('루틴 없음: ' + entry.routine);
        markRan(entry.id);
        continue;
      }
      log('실행 시작: ' + entry.routine + ' (' + entry.id + ')');
      if (o.onRun) o.onRun(entry, routine);
      try {
        const pre = await routines.preflight(routine);
        if (!pre.ok) {
          log('사전 점검 실패: ' + pre.reasons.join(' / '));
          markRan(entry.id);
          continue;
        }
        const summary = await (o.runner ? o.runner(routine) : routines.run(routine));
        log(
          '완료: ' +
            entry.routine +
            ' 성공 ' +
            summary.okCount +
            ' / 실패 ' +
            summary.failCount +
            ' / 날개 ' +
            summary.wingsSpent
        );
      } catch (err) {
        log('오류: ' + (err && err.message));
      }
      markRan(entry.id);
    }
    running = false;
  };

  const timer = setInterval(tick, intervalMs);
  tick();
  return { stop: () => clearInterval(timer) };
}

/* ── Windows 작업 스케줄러 ──────────────────────────────────── */

function taskName(entry) {
  return 'mobi-remote-' + entry.id;
}

/** 등록에 쓰일 schtasks 명령을 문자열로 보여준다 (실행 전 확인용). */
function taskCommandPreview(entry) {
  const cmd = path.join(__dirname, '..', 'mobi-remote.cmd');
  const days = entry.days.length === 7 ? '/sc daily' : '/sc weekly /d ' + entry.days.map((d) => d.toUpperCase()).join(',');
  return (
    'schtasks /create /tn "' +
    taskName(entry) +
    '" /tr "\\"' +
    cmd +
    '\\" run ' +
    entry.routine +
    ' --yes" ' +
    days +
    ' /st ' +
    entry.time +
    ' /f'
  );
}

/** 실제 등록. 사용자가 확인한 뒤에만 호출할 것. */
function registerTask(entry) {
  const cmd = path.join(__dirname, '..', 'mobi-remote.cmd');
  const args = [
    '/create',
    '/tn',
    taskName(entry),
    '/tr',
    '"' + cmd + '" run ' + entry.routine + ' --yes',
    '/st',
    entry.time,
    '/f',
  ];
  if (entry.days.length === 7) args.push('/sc', 'daily');
  else args.push('/sc', 'weekly', '/d', entry.days.map((d) => d.toUpperCase()).join(','));

  const r = spawnSync('schtasks', args, { encoding: 'utf8', windowsHide: true });
  return {
    ok: r.status === 0,
    code: r.status,
    output: (r.stdout || '') + (r.stderr || ''),
  };
}

function unregisterTask(entry) {
  const r = spawnSync('schtasks', ['/delete', '/tn', taskName(entry), '/f'], {
    encoding: 'utf8',
    windowsHide: true,
  });
  return { ok: r.status === 0, code: r.status, output: (r.stdout || '') + (r.stderr || '') };
}

module.exports = {
  load,
  save,
  add,
  remove,
  setEnabled,
  describe,
  due,
  markRan,
  startDaemon,
  log,
  taskName,
  taskCommandPreview,
  registerTask,
  unregisterTask,
  DAYS,
  DAY_LABEL,
  SCHEDULE_FILE,
  LOG_FILE,
};
