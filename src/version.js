'use strict';
/**
 * 버전 · 호환성 검사.
 *
 * 이 프로그램은 두 가지에 의존한다.
 *   1) MabinogiMobile_CLI.exe 자체 (실행 파일 버전)
 *   2) 게임 클라이언트가 동적으로 주는 명령 스키마 (capabilities)
 *
 * 둘 중 두 번째가 실제로 앱을 깨뜨린다. CLI가 그대로여도 게임이 업데이트되면
 * 명령이 사라지거나 본문 형식이나 비용이 바뀔 수 있기 때문이다.
 * 그래서 검증해 둔 기준선(compat.json)과 현재 상태를 비교해 경고한다.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const connector = require('./connector');

const paths = require('./paths');

/*
 * 기준선은 두 자리에 있다.
 *
 *   씨앗  프로그램 폴더의 compat.json — 배포할 때 넣어 둔, 만든 사람이 확인한 기준
 *   내 것 %LOCALAPPDATA%/.../compat.json — 이 컴퓨터에서 내가 갱신한 기준 (우선)
 *
 * 포장한 뒤에는 프로그램 폴더가 app.asar 안이라 읽기 전용이다. 거기에 쓰려 하면
 * 조용히 실패해서, '확인했다'고 눌러도 다음에 켜면 같은 경고가 또 뜬다.
 */
const COMPAT_SEED = path.join(__dirname, '..', 'compat.json');
const COMPAT_FILE = paths.dataPath('compat.json');
const PKG_FILE = path.join(__dirname, '..', 'package.json');

/** 심각도. 숫자가 클수록 위험하다. */
const LEVEL = { ok: 0, info: 1, warn: 2, error: 3 };
const LEVEL_NAME = ['ok', 'info', 'warn', 'error'];

function appVersion() {
  try {
    return JSON.parse(fs.readFileSync(PKG_FILE, 'utf8')).version || '0.0.0';
  } catch (_) {
    return '0.0.0';
  }
}

/* ── CLI 실행 파일 버전 ─────────────────────────────────────── */

/**
 * PE의 VS_VERSIONINFO에서 문자열 값을 읽는다.
 * 키와 값 모두 UTF-16LE 널종료 문자열이고, 값은 4바이트 경계에서 시작한다.
 */
function readVersionString(buf, key) {
  const needle = Buffer.from(key + '\0', 'ucs2');
  const at = buf.indexOf(needle);
  if (at < 0) return null;
  let p = at + needle.length;
  while (p % 4 !== 0) p++;
  let end = p;
  while (end + 1 < buf.length && !(buf[end] === 0 && buf[end + 1] === 0)) end += 2;
  const val = buf.slice(p, end).toString('ucs2').trim();
  return val || null;
}

/**
 * CLI 실행 파일의 버전 정보. PowerShell을 띄우지 않고 파일에서 직접 읽는다.
 * @returns {{path, productVersion, fileVersion, company, size, mtime} | {error}}
 */
function cliVersion() {
  const exe = connector.exePath();
  // PATH로만 잡히는 경우엔 파일을 못 읽을 수 있다
  const file = path.isAbsolute(exe) ? exe : null;
  if (!file || !fs.existsSync(file)) {
    return { path: exe, error: 'exe_not_found', productVersion: null, fileVersion: null };
  }
  try {
    const st = fs.statSync(file);
    const buf = fs.readFileSync(file);
    return {
      path: file,
      productVersion: readVersionString(buf, 'ProductVersion'),
      fileVersion: readVersionString(buf, 'FileVersion'),
      company: readVersionString(buf, 'CompanyName'),
      size: st.size,
      mtime: st.mtime.toISOString(),
    };
  } catch (err) {
    return { path: file, error: String(err && err.message), productVersion: null, fileVersion: null };
  }
}

/* ── 명령 스키마 지문 ───────────────────────────────────────── */

function sha256(s) {
  return crypto.createHash('sha256').update(s, 'utf8').digest('hex');
}

/**
 * "0.1.0+a62d48bb..." 에서 앞의 0.1.0 만 꺼낸다.
 * 뒤의 빌드 해시는 재빌드마다 바뀌므로 비교 대상이 아니다.
 */
function semverOf(productVersion) {
  return String(productVersion || '').split('+')[0].trim();
}

/**
 * 명령 집합의 서명. 이름과 본문 형식만 넣는다.
 * 설명(Description/Note)은 문구가 다듬어질 수 있어 제외한다 — 그건 별도로 비교한다.
 */
function commandSignature(commands) {
  const canon = commands
    .map((c) => (c.Command || '') + '|' + (c.BodyExample || ''))
    .sort()
    .join('\n');
  return sha256(canon);
}

/** 현재 상태 지문 전체 */
function fingerprint() {
  const commands = connector.loadCapabilities();
  const costs = connector.commandCosts(true);
  return {
    appVersion: appVersion(),
    cli: cliVersion(),
    commandCount: commands.length,
    commandSignature: commandSignature(commands),
    commands: commands.map((c) => c.Command).sort(),
    bodyExamples: commands.reduce((acc, c) => {
      if (c.BodyExample) acc[c.Command] = c.BodyExample;
      return acc;
    }, {}),
    costs: costs,
    capturedAt: new Date().toISOString(),
  };
}

/* ── 기준선 ─────────────────────────────────────────────────── */

function loadBaseline() {
  for (const file of [COMPAT_FILE, COMPAT_SEED]) {
    try {
      return JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (_) { /* 다음 자리를 본다 */ }
  }
  return null;
}

/**
 * 기준선은 배포판에 함께 실린다. 그래서 만든 사람의 PC에서만 의미가 있는 값
 * (설치 경로·파일 크기·수정 시각)은 빼고 저장한다. 비교에도 쓰이지 않는다.
 */
function sanitizeCli(cli) {
  if (!cli) return null;
  return {
    productVersion: cli.productVersion,
    fileVersion: cli.fileVersion,
    company: cli.company,
  };
}

function saveBaseline(fp, note) {
  const data = Object.assign({}, fp, {
    cli: sanitizeCli(fp.cli),
    _설명: '검증된 호환 기준선입니다. 게임/CLI 업데이트 후 앱이 정상 동작하는 것을 확인했다면 앱의 호환성 화면에서 갱신하세요.',
    verifiedNote: note || '',
    verifiedAt: new Date().toISOString(),
  });
  fs.mkdirSync(path.dirname(COMPAT_FILE), { recursive: true });
  fs.writeFileSync(COMPAT_FILE, JSON.stringify(data, null, 2), 'utf8');
  return data;
}

/* ── 비교 ───────────────────────────────────────────────────── */

function diffArrays(base, cur) {
  const b = new Set(base || []);
  const c = new Set(cur || []);
  return {
    added: Array.from(c).filter((x) => !b.has(x)),
    removed: Array.from(b).filter((x) => !c.has(x)),
  };
}

/**
 * 기준선과 현재 상태를 비교한다.
 * @returns {{level, levelName, ok, changes: Array<{level, kind, title, detail}>, baseline, current}}
 */
function check(current) {
  const cur = current || fingerprint();
  const base = loadBaseline();
  const changes = [];

  if (!base) {
    return {
      level: LEVEL.info,
      levelName: 'info',
      ok: true,
      firstRun: true,
      changes: [{
        level: 'info',
        kind: 'no_baseline',
        title: '호환 기준선이 없습니다',
        detail: '현재 상태를 기준선으로 저장하면 다음 실행부터 변경을 감지합니다.',
      }],
      baseline: null,
      current: cur,
    };
  }

  // 1) CLI 실행 파일 버전 — 빌드 해시는 빼고 semver만 본다.
  //
  // ProductVersion은 "0.1.0+<git해시>" 형태인데, 넥슨이 게임을 재빌드할 때마다
  // 해시가 바뀐다. 실제로 연속 세 번 해시만 바뀌고 명령·비용은 그대로였다.
  // 그걸 매번 경고하면 정작 중요한 경고(비용 변경)까지 무시하게 된다.
  // 기능이 달라지는 신호는 semver 변경과 아래의 스키마 비교가 담당한다.
  const bp = base.cli && base.cli.productVersion;
  const cp = cur.cli && cur.cli.productVersion;
  if (semverOf(bp) && semverOf(cp) && semverOf(bp) !== semverOf(cp)) {
    changes.push({
      level: 'warn',
      kind: 'cli_version',
      title: 'CLI 버전이 올라갔습니다',
      detail: semverOf(bp) + '  →  ' + semverOf(cp) +
        '\n명령이나 비용이 함께 바뀌지 않았는지 아래를 확인하세요.',
    });
  }

  // 2) 명령 추가/제거 — 제거는 앱 기능이 직접 깨진다
  const d = diffArrays(base.commands, cur.commands);
  if (d.removed.length) {
    changes.push({
      level: 'error',
      kind: 'commands_removed',
      title: '명령 ' + d.removed.length + '개가 사라졌습니다',
      detail: d.removed.join(', ') + '\n이 기능을 쓰는 화면은 동작하지 않습니다.',
    });
  }
  if (d.added.length) {
    changes.push({
      level: 'info',
      kind: 'commands_added',
      title: '명령 ' + d.added.length + '개가 추가되었습니다',
      detail: d.added.join(', ') + '\n콘솔 탭에서 바로 쓸 수 있지만 전용 화면은 없습니다.',
    });
  }

  // 3) 본문 형식 변경 — 잘못된 본문을 보내면 invalid_body로 거부된다
  const changedBodies = [];
  const baseBodies = base.bodyExamples || {};
  const curBodies = cur.bodyExamples || {};
  for (const cmd of Object.keys(baseBodies)) {
    if (curBodies[cmd] !== undefined && curBodies[cmd] !== baseBodies[cmd]) {
      changedBodies.push(cmd + '\n    기준: ' + baseBodies[cmd] + '\n    현재: ' + curBodies[cmd]);
    }
  }
  if (changedBodies.length) {
    changes.push({
      level: 'warn',
      kind: 'body_changed',
      title: '명령 본문 형식이 바뀌었습니다 (' + changedBodies.length + '건)',
      detail: changedBodies.join('\n'),
    });
  }

  // 4) 비용 변경 — 잘못 알면 날개를 예상보다 많이 쓴다. 가장 민감한 항목.
  const baseCosts = base.costs || {};
  const curCosts = cur.costs || {};
  const costLines = [];
  for (const cmd of new Set(Object.keys(baseCosts).concat(Object.keys(curCosts)))) {
    const b = baseCosts[cmd];
    const c = curCosts[cmd];
    if (!b && c) costLines.push(cmd + ': 무료 → ' + c.amount + ' ' + c.currency);
    else if (b && !c) costLines.push(cmd + ': ' + b.amount + ' ' + b.currency + ' → 무료');
    else if (b && c && (b.amount !== c.amount || b.currency !== c.currency)) {
      costLines.push(cmd + ': ' + b.amount + ' ' + b.currency + ' → ' + c.amount + ' ' + c.currency);
    }
  }
  if (costLines.length) {
    changes.push({
      level: 'error',
      kind: 'cost_changed',
      title: '명령 소모 비용이 바뀌었습니다',
      detail: costLines.join('\n') + '\n실행 전 확인 창의 금액을 반드시 다시 보세요.',
    });
  }

  // 5) 위에서 안 잡혔는데 서명만 다르면, 설명 문구 등 다른 변화가 있다는 뜻
  if (!changes.length && base.commandSignature !== cur.commandSignature) {
    changes.push({
      level: 'info',
      kind: 'signature',
      title: '명령 스키마에 소소한 변경이 있습니다',
      detail: '이름과 본문 형식은 그대로입니다.',
    });
  }

  const level = changes.reduce((m, c) => Math.max(m, LEVEL[c.level] || 0), LEVEL.ok);
  return {
    level,
    levelName: LEVEL_NAME[level],
    ok: level < LEVEL.warn,
    firstRun: false,
    changes,
    baseline: base,
    current: cur,
  };
}

module.exports = {
  appVersion,
  cliVersion,
  commandSignature,
  semverOf,
  fingerprint,
  loadBaseline,
  saveBaseline,
  check,
  readVersionString,
  LEVEL,
  COMPAT_FILE,
};
