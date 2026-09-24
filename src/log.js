'use strict';
/**
 * 파일 로그.
 *
 * 화면의 호출 기록은 앱을 끄면 사라진다. 실패 코드를 나중에 확인할 수 없어서
 * "아까 무슨 에러였죠?"에 답할 방법이 없었다. 특히 비용이 나가는 명령은
 * 무엇이 왜 실패했는지 남아야 한다.
 *
 * 하루 한 파일로 쌓고 오래된 것은 지운다. 전부 로컬에만 있고 어디로도 보내지 않는다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');

const DIR = paths.dataPath('logs');

const KEEP_DAYS = 14;
const MAX_BYTES = 5 * 1024 * 1024;

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

let renamedToday = false;

function file() {
  const p = path.join(DIR, 'mobi-remote-' + today() + '.log');
  // 이름을 바꾸기 전에 오늘 쓰던 파일이 있으면 이어서 쓴다.
  // 안 그러면 같은 날 기록이 두 파일로 갈라져 화면의 최근 줄에서 앞부분이 사라진다.
  if (!renamedToday) {
    renamedToday = true;
    try {
      const old = path.join(DIR, 'mm-auto-' + today() + '.log');
      if (fs.existsSync(old) && !fs.existsSync(p)) fs.renameSync(old, p);
    } catch (_) { /* 못 옮겨도 새 파일로 계속 쓴다 */ }
  }
  return p;
}

function stamp() {
  return new Date().toISOString().replace('T', ' ').slice(0, 23);
}

let cleaned = false;

/** 오래된 로그를 지운다. 프로세스당 한 번만 훑는다. */
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  try {
    const cutoff = Date.now() - KEEP_DAYS * 86400000;
    for (const f of fs.readdirSync(DIR)) {
      // 이름을 바꾸기 전 파일도 같이 세고 지운다. 안 그러면 옛 로그가 영원히 남는다.
      if (!/^(mobi-remote|mm-auto)-\d{4}-\d{2}-\d{2}\.log$/.test(f)) continue;
      const p = path.join(DIR, f);
      if (fs.statSync(p).mtimeMs < cutoff) fs.unlinkSync(p);
    }
  } catch (_) {
    /* 정리 실패는 무시 */
  }
}

function write(level, tag, message, extra) {
  try {
    fs.mkdirSync(DIR, { recursive: true });
    cleanup();
    const p = file();
    // 한 파일이 너무 커지면 잘라낸다 (루틴을 오래 돌릴 때 대비)
    try {
      if (fs.statSync(p).size > MAX_BYTES) {
        fs.renameSync(p, p.replace(/\.log$/, '.1.log'));
      }
    } catch (_) { /* 파일이 없으면 그냥 새로 만든다 */ }

    let line = stamp() + '  ' + level.padEnd(5) + ' [' + tag + '] ' + message;
    if (extra !== undefined && extra !== null) {
      let s;
      try { s = typeof extra === 'string' ? extra : JSON.stringify(extra); }
      catch (_) { s = String(extra); }
      if (s.length > 2000) s = s.slice(0, 2000) + '…(잘림)';
      line += '  ' + s;
    }
    fs.appendFileSync(p, line + '\n', 'utf8');
  } catch (_) {
    /* 로그 실패가 앱을 멈추면 안 된다 */
  }
}

const info = (tag, msg, extra) => write('INFO', tag, msg, extra);
const warn = (tag, msg, extra) => write('WARN', tag, msg, extra);
const error = (tag, msg, extra) => write('ERROR', tag, msg, extra);

/**
 * 명령 실행 한 건을 남긴다. 비용이 나갔으면 실패해도 반드시 기록한다.
 * 큰 조회 응답(수백 KB)은 본문을 남기지 않고 요약만 적는다.
 */
function command(cmd, body, result) {
  const ok = result && result.ok;
  const spent = result && result.costInfo ? result.costInfo.amount : (result && result.wingsSpent) || 0;
  const parts = [
    ok ? 'ok' : 'FAIL',
    (result && result.durationMs) + 'ms',
  ];
  if (spent) parts.push('비용 ' + spent);
  if (!ok && result && result.error) parts.push('error=' + result.error);
  if (!ok && result && result.data && result.data.kind) parts.push('kind=' + result.data.kind);

  const extra = {};
  if (body !== undefined && body !== null) extra.body = body;
  // 실패했거나 비용이 나간 경우에만 응답을 남긴다 — 조회 성공까지 남기면 로그가 터진다
  if (!ok || spent) extra.data = result && result.data;

  write(ok ? 'INFO' : 'WARN', 'cmd', cmd + ' — ' + parts.join(' · '),
    Object.keys(extra).length ? extra : null);
}

/** 최근 N줄을 읽어 온다 (앱에서 보여줄 때 쓴다). */
function tail(lines) {
  try {
    const txt = fs.readFileSync(file(), 'utf8');
    const all = txt.split(/\r?\n/).filter(Boolean);
    return all.slice(-(lines || 200));
  } catch (_) {
    return [];
  }
}

function listFiles() {
  try {
    return fs.readdirSync(DIR)
      .filter((f) => f.endsWith('.log'))
      .map((f) => {
        const st = fs.statSync(path.join(DIR, f));
        return { name: f, sizeKB: Math.round(st.size / 1024), mtime: st.mtime.toISOString() };
      })
      .sort((a, b) => b.name.localeCompare(a.name));
  } catch (_) {
    return [];
  }
}

module.exports = { info, warn, error, command, tail, listFiles, DIR, file };
