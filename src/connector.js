'use strict';
/**
 * MabinogiMobile_CLI 호출 래퍼.
 *
 * - 비ASCII 본문은 base64: 접두사로 인코딩해 전달한다 (Windows 콘솔 코드페이지 손상 방지).
 * - stdout은 \uXXXX 이스케이프된 UTF-8 JSON이므로 JSON.parse로 복원된다.
 *   파싱 실패 시 last-response.json(실제 UTF-8)로 폴백한다.
 * - 게임 클라이언트는 거부도 exit 0으로 반환하므로 code와 body.error를 모두 본다.
 */
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const settings = require('./settings');

const EXE_NAME = 'MabinogiMobile_CLI.exe';

// 설치 경로를 담고 있는 레지스트리 키. 64비트/32비트 뷰를 모두 본다.
// 넥슨 설치 관리자가 남기는 키. 64비트 OS에서는 WOW6432Node 쪽에 들어간다(실측).
const REG_KEYS = [
  'HKLM\\SOFTWARE\\WOW6432Node\\Nexon\\MabinogiM',
  'HKLM\\SOFTWARE\\Nexon\\MabinogiM',
  'HKCU\\SOFTWARE\\Nexon\\MabinogiM',
];

const LOCALAPPDATA =
  process.env.LOCALAPPDATA ||
  path.join(process.env.USERPROFILE || '', 'AppData', 'Local');

const LAST_RESPONSE = path.join(LOCALAPPDATA, 'MabinogiMobileCLI', 'last-response.json');
const CAPABILITIES = path.join(LOCALAPPDATA, 'MabinogiMobileCLI', 'CAPABILITIES.json');

// CLI transport 레벨 종료 코드. 0/게임측 거부와 구분된다.
const EXIT_REASON = {
  2: 'usage_error',
  3: 'canceled',
  4: 'unknown_command',
  5: 'disconnected',
};

// 1회 실행마다 정령의 날개를 소모하는 명령.
// 실제 비용은 CAPABILITIES의 Note에서 런타임에 읽어낸다(commandCosts 참고).
// 아래 값은 CAPABILITIES를 읽지 못했을 때의 폴백이자, 호환성 검사의 기준선이다.
// complete_altering_work는 수령만 하므로 비용이 없다.
const WING_COST = 5;
const COSTED_COMMANDS = new Set([
  'execute_gathering',
  'execute_crafting',
  'execute_altering',
]);

// "Running this command consumes 5 정령의 날개." 형태의 문장을 읽는다.
const COST_RE = /consumes\s+(\d+)\s+([^.]+?)\s*\./i;

let costMapCache = null;

/**
 * 명령별 소모 비용 표. CAPABILITIES의 Note에서 직접 읽으므로
 * 게임이 비용을 바꿔도 앱의 예상치가 따라간다.
 * @returns {{[command: string]: {amount: number, currency: string}}}
 */
function commandCosts(refresh) {
  if (costMapCache && !refresh) return costMapCache;
  const map = {};
  for (const c of loadCapabilities()) {
    const m = COST_RE.exec(c.Note || '');
    if (m) map[c.Command] = { amount: parseInt(m[1], 10), currency: m[2].trim() };
  }
  // CAPABILITIES를 못 읽었으면 폴백을 쓴다 (비용을 0으로 보는 것보다 안전하다)
  if (!Object.keys(map).length) {
    for (const cmd of COSTED_COMMANDS) map[cmd] = { amount: WING_COST, currency: '정령의 날개' };
  }
  costMapCache = map;
  return map;
}

/** 이 명령이 소모하는 비용. 없으면 null. */
function costOf(command) {
  return commandCosts()[command] || null;
}

function isCosted(command) {
  return !!costOf(command);
}

// 게임 상태를 바꾸는 명령 (조회가 아닌 것)
const ACTION_COMMANDS = new Set([
  'write_chat',
  'play_music_score',
  'change_instrument',
  'stop_action',
  'stand_up',
  'execute_gathering',
  'execute_altering',
  'complete_altering_work',
  'execute_crafting',
]);

/**
 * 레지스트리 값 하나를 읽는다. reg.exe는 Windows 기본 내장이라 의존성이 없다.
 * 출력 예: "    RootPath    REG_SZ    D:\Nexon\MabinogiMobile"
 */
function readRegValue(key, name) {
  try {
    const r = spawnSync('reg', ['query', key, '/v', name], {
      encoding: 'utf8',
      windowsHide: true,
      timeout: 5000,
    });
    if (r.status !== 0 || !r.stdout) return null;
    const m = new RegExp(name + '\\s+REG_\\w+\\s+(.+)').exec(r.stdout);
    return m ? m[1].trim() : null;
  } catch (_) {
    return null;
  }
}

/**
 * 제거 프로그램 목록에서 설치 폴더 후보를 긁어 온다.
 *
 * **폴더 이름으로 거르지 않는다.** 예전에는 값에 "MabinogiMobile"이 들어 있는지 봤는데,
 * 설치 폴더 이름은 사람이 바꿀 수 있어서 그러면 놓친다. 대신 경로가 될 만한 값을 전부 모아
 * 그 안에 실행 파일이 실제로 있는지로 판정한다 — 223개를 확인하는 데 14ms였다(실측).
 *
 * DisplayName은 한글("마비노기 모바일")이라 콘솔 코드페이지에 따라 깨지므로 쓰지 않는다.
 * 대신 ASCII로 남는 InstallLocation · DisplayIcon · UninstallString 세 값에서 경로를 뽑는다.
 * 실측 — InstallLocation만 보면 놓치는 경우가 있는데, DisplayIcon에는 exe 전체 경로가 남아 있다.
 */
function uninstallDirs() {
  const roots = [
    'HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
    'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
    'HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
  ];
  const likely = [];   // 이름부터 마비노기로 보이는 것
  const rest = [];
  const seen = Object.create(null);

  for (const root of roots) {
    let out = '';
    try {
      const r = spawnSync('reg', ['query', root, '/s'], {
        encoding: 'utf8',
        windowsHide: true,
        timeout: 15000,
        maxBuffer: 64 * 1024 * 1024,
      });
      if (r.status !== 0 || !r.stdout) continue;
      out = r.stdout;
    } catch (_) {
      continue;
    }

    for (const line of out.split(/\r?\n/)) {
      const m = /\s(?:InstallLocation|DisplayIcon|UninstallString)\s+REG_\w+\s+(.+)$/.exec(line);
      if (!m) continue;
      let v = m[1].trim().replace(/^"/, '');
      // `"...exe" -mode:uninstall` 처럼 뒤에 인자가 붙는 값에서 경로만 떼어 낸다
      const q = v.indexOf('"');
      if (q > 0) v = v.slice(0, q);
      v = v.trim().replace(/,\s*\d+$/, '');   // DisplayIcon 의 ",0" 같은 아이콘 번호
      if (!/^[a-zA-Z]:\\/.test(v)) continue;

      const dir = /\.(exe|dll|ico)$/i.test(v) ? path.dirname(v) : v.replace(/[\\/]+$/, '');
      if (!dir || seen[dir.toLowerCase()]) continue;
      seen[dir.toLowerCase()] = true;
      (/mabinogi|마비노기/i.test(dir) ? likely : rest).push(dir);
    }
  }
  return likely.concat(rest);
}

/** 지금 이 PC에 실제로 있는 드라이브. C부터 본다 — A·B는 없는 플로피를 찔러 느려질 수 있다. */
function drives() {
  const out = [];
  for (let i = 'C'.charCodeAt(0); i <= 'Z'.charCodeAt(0); i++) {
    const d = String.fromCharCode(i) + ':';
    try { if (fs.existsSync(d + '\\')) out.push(d); } catch (_) { /* 접근 불가 */ }
  }
  return out;
}

/** 넥슨 런처가 흔히 쓰는 배치. 드라이브는 고정하지 않고 실제 있는 것만 훑는다. */
const INSTALL_PATTERNS = [
  'Nexon\\MabinogiMobile',
  'Program Files\\Nexon\\MabinogiMobile',
  'Program Files (x86)\\Nexon\\MabinogiMobile',
  'Games\\Nexon\\MabinogiMobile',
  'Nexon\\마비노기 모바일',
];

/**
 * `<드라이브>\Nexon` 밑을 한 겹만 훑는다.
 * 폴더 이름을 바꿔 설치했더라도 넥슨 폴더 안에만 있으면 여기서 걸린다.
 * readdir 한 번이라 비용이 거의 없다.
 */
function nexonSubdirs() {
  const out = [];
  for (const d of drives()) {
    const base = d + '\\Nexon';
    try {
      if (!fs.existsSync(base)) continue;
      for (const name of fs.readdirSync(base)) out.push(path.join(base, name));
    } catch (_) { /* 권한이 없으면 넘어간다 */ }
  }
  return out;
}

/**
 * CLI 실행 파일 후보를 **하나씩 게을리** 내놓는다.
 *
 * 배열로 미리 다 만들면 앞에서 이미 찾았어도 뒤쪽 탐색 비용을 매번 치른다.
 * 실측 — 제거 프로그램 목록을 훑는 데만 1.6초가 걸리는데, 레지스트리 RootPath가
 * 맞는 보통의 경우에는 거기까지 갈 일이 없다. 그래서 생성기로 바꿨다(152ms → 4ms).
 *
 * 순서는 **정확한 것 → 싼 것 → 비싼 것**이다.
 */
function* exeCandidates() {
  // 1. 환경변수 — 수동 지정 및 테스트용
  if (process.env.MM_CLI_PATH) yield { path: process.env.MM_CLI_PATH, source: 'MM_CLI_PATH 환경변수' };

  // 2. 사용자가 설정에서 직접 지정한 경로
  try {
    const s = settings.load();
    if (s.cliPath) yield { path: s.cliPath, source: '설정에서 지정' };
  } catch (_) { /* 설정을 못 읽어도 탐색은 계속한다 */ }

  // 3. 넥슨이 설치할 때 남기는 레지스트리 값 (가장 정확하고 빠르다)
  for (const k of REG_KEYS) {
    const dir = readRegValue(k, 'RootPath');
    if (dir) yield { path: path.join(dir, EXE_NAME), source: '레지스트리 ' + k.split('\\').pop() };
  }

  // 4. 흔한 설치 배치 — 파일 존재 확인뿐이라 사실상 공짜다
  for (const d of drives()) {
    for (const p of INSTALL_PATTERNS) {
      yield { path: path.join(d + '\\', p, EXE_NAME), source: '기본 설치 경로' };
    }
  }

  // 5. <드라이브>\Nexon 아래 한 겹 — 폴더 이름을 바꿔 설치한 경우
  for (const dir of nexonSubdirs()) {
    yield { path: path.join(dir, EXE_NAME), source: 'Nexon 폴더 탐색' };
  }

  // 6. 제거 프로그램 목록 전수 조사 (1초 이상, 마지막 수단)
  for (const dir of uninstallDirs()) {
    yield { path: path.join(dir, EXE_NAME), source: '레지스트리 제거 프로그램 목록' };
  }
}


let resolved = null;

/**
 * 실행 파일 경로를 찾는다. 한 번 찾으면 프로세스가 끝날 때까지 재사용한다.
 * @returns {{path: string, source: string, found: boolean, tried: string[]}}
 */
function resolveExe(force) {
  if (resolved && !force && (!resolved.found || fs.existsSync(resolved.path))) return resolved;

  const tried = [];
  for (const c of exeCandidates()) {
    tried.push(c.path);
    try {
      if (fs.existsSync(c.path)) {
        resolved = { path: c.path, source: c.source, found: true, tried: tried };
        return resolved;
      }
    } catch (_) {
      /* 접근 불가한 경로는 넘어간다 */
    }
  }

  // 못 찾으면 이름만 넘겨 PATH에 맡긴다. 그래도 없으면 spawn이 깔끔하게 실패한다.
  resolved = { path: EXE_NAME, source: 'PATH (탐색 실패)', found: false, tried: tried };
  return resolved;
}

/**
 * 어떤 경로를 어떤 순서로 보는지 그대로 펼쳐 준다.
 * "커넥터를 못 찾겠다"는 신고를 받았을 때 무엇까지 봤는지 확인하는 용도다.
 * 탐색 자체와 같은 생성기를 쓰므로 실제 동작과 어긋날 일이 없다.
 */
function candidatePaths() {
  const out = [];
  for (const c of exeCandidates()) {
    let exists = false;
    try { exists = fs.existsSync(c.path); } catch (_) { /* 접근 불가 */ }
    out.push({ path: c.path, source: c.source, exists: exists });
  }
  return out;
}

function exePath() {
  return resolveExe().path;
}

function isAscii(s) {
  for (let i = 0; i < s.length; i++) if (s.charCodeAt(i) > 127) return false;
  return true;
}

/** 본문을 CLI 인자 하나로 변환한다. 비ASCII면 base64: 접두사를 붙인다. */
function encodeBody(body) {
  if (body === undefined || body === null) return null;
  const s = typeof body === 'string' ? body : JSON.stringify(body);
  if (s === '') return null;
  if (isAscii(s)) return s;
  return 'base64:' + Buffer.from(s, 'utf8').toString('base64');
}

function parseOutput(stdout) {
  const text = (stdout || '').trim();
  if (text) {
    try {
      return JSON.parse(text);
    } catch (_) {
      /* 이스케이프 복원 실패 시 파일 폴백 */
    }
  }
  try {
    return JSON.parse(fs.readFileSync(LAST_RESPONSE, 'utf8'));
  } catch (_) {
    return text ? { raw: text } : null;
  }
}

/**
 * 명령을 실행한다.
 * @returns {{promise: Promise<Result>, cancel: function}}
 *   Result = { ok, code, reason, data, error, message, durationMs }
 */
function runCancelable(command, body, opts) {
  const options = opts || {};
  const args = [command];
  const encoded = encodeBody(body);
  if (encoded !== null) args.push(encoded);

  const startedAt = Date.now();

  // spawn은 비동기 'error' 이벤트뿐 아니라 동기 예외도 던진다
  // (경로가 이상하거나 Node가 실행을 거부하는 경우 EINVAL 등).
  // 여기서 잡지 않으면 호출자까지 예외가 올라가 UI가 멈춘다.
  let child;
  try {
    child = spawn(exePath(), args, { windowsHide: true });
  } catch (err) {
    const failed = {
      ok: false,
      code: -1,
      reason: 'spawn_failed',
      data: null,
      error: 'spawn_failed',
      message: String((err && err.message) || err),
      durationMs: Date.now() - startedAt,
    };
    return { promise: Promise.resolve(failed), cancel: () => {} };
  }

  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (d) => {
    stdout += d.toString('utf8');
  });
  child.stderr.on('data', (d) => {
    stderr += d.toString('utf8');
  });

  const promise = new Promise((resolve) => {
    child.on('error', (err) => {
      resolve({
        ok: false,
        code: -1,
        reason: 'spawn_failed',
        data: null,
        error: 'spawn_failed',
        message: err.message,
        durationMs: Date.now() - startedAt,
      });
    });

    child.on('close', (code) => {
      const data = parseOutput(stdout);
      const bodyError = data && typeof data === 'object' ? data.error : null;
      const reason = EXIT_REASON[code] || (bodyError ? String(bodyError) : null);
      resolve({
        ok: code === 0 && !bodyError,
        code,
        reason,
        data,
        error: bodyError || EXIT_REASON[code] || null,
        message:
          (data && data.message) ||
          stderr.trim() ||
          (EXIT_REASON[code] ? EXIT_REASON[code] : null),
        durationMs: Date.now() - startedAt,
      });
    });
  });

  if (options.timeoutMs) {
    const t = setTimeout(() => child.kill(), options.timeoutMs);
    promise.then(() => clearTimeout(t));
  }

  return { promise, cancel: () => child.kill() };
}

function run(command, body, opts) {
  return runCancelable(command, body, opts).promise;
}

/** 연결 상태. reason: game_off | option_off | null */
async function status() {
  const r = await run('status');
  const pipe = r.data && r.data.pipe;
  return {
    connected: pipe === 'connected',
    pipe: pipe || 'unknown',
    reason: (r.data && r.data.reason) || null,
    raw: r,
  };
}

function loadCapabilities() {
  try {
    const d = JSON.parse(fs.readFileSync(CAPABILITIES, 'utf8'));
    return d.commands || [];
  } catch (_) {
    return [];
  }
}

async function refreshCapabilities() {
  const r = await run('capabilities');
  if (r.ok && r.data && r.data.commands) {
    fs.mkdirSync(path.dirname(CAPABILITIES), { recursive: true });
    fs.writeFileSync(CAPABILITIES, JSON.stringify(r.data, null, 2), 'utf8');
    costMapCache = null; // 명령 목록이 바뀌었으니 비용표도 다시 읽는다
    return r.data.commands;
  }
  return loadCapabilities();
}

module.exports = {
  run,
  runCancelable,
  status,
  loadCapabilities,
  refreshCapabilities,
  encodeBody,
  exePath,
  resolveExe,
  candidatePaths,
  EXE_NAME,
  WING_COST,
  COSTED_COMMANDS,
  ACTION_COMMANDS,
  commandCosts,
  costOf,
  isCosted,
  LAST_RESPONSE,
  CAPABILITIES,
};
