'use strict';
/**
 * 무의존성 터미널 UI.
 * 한글은 터미널에서 2칸을 차지하므로 폭 계산을 직접 한다 (박스 정렬이 깨지지 않게).
 */
const readline = require('readline');

const useColor = process.stdout.isTTY && !process.env.NO_COLOR;
function wrap(code) {
  return (s) => (useColor ? '[' + code + 'm' + s + '[0m' : String(s));
}

const c = {
  dim: wrap('2'),
  bold: wrap('1'),
  red: wrap('31'),
  green: wrap('32'),
  yellow: wrap('33'),
  blue: wrap('34'),
  magenta: wrap('35'),
  cyan: wrap('36'),
  gray: wrap('90'),
  inverse: wrap('7'),
};

/** 전각(한글/한자/가나/전각기호) 여부 */
function isWide(cp) {
  return (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe6f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6)
  );
}

function stripAnsi(s) {
  return String(s).replace(/\[[0-9;]*m/g, '');
}

/** 터미널 표시 폭 */
function width(s) {
  const t = stripAnsi(s);
  let w = 0;
  for (const ch of t) w += isWide(ch.codePointAt(0)) ? 2 : 1;
  return w;
}

function padEnd(s, n) {
  const diff = n - width(s);
  return diff > 0 ? s + ' '.repeat(diff) : s;
}

function padStart(s, n) {
  const diff = n - width(s);
  return diff > 0 ? ' '.repeat(diff) + s : s;
}

/** 폭 기준으로 자르고 말줄임 */
function truncate(s, n) {
  if (width(s) <= n) return s;
  let out = '';
  let w = 0;
  for (const ch of stripAnsi(s)) {
    const cw = isWide(ch.codePointAt(0)) ? 2 : 1;
    if (w + cw > n - 1) break;
    out += ch;
    w += cw;
  }
  return out + '…';
}

const BOX = { tl: '┌', tr: '┐', bl: '└', br: '┘', h: '─', v: '│', ml: '├', mr: '┤' };

/**
 * 박스를 그린다.
 * lines: 문자열 배열. null 요소는 구분선.
 */
function box(title, lines, opts) {
  const o = opts || {};
  const inner = o.width || Math.max(
    width(title) + 4,
    lines.reduce((m, l) => Math.max(m, l === null ? 0 : width(l)), 0) + 2
  );
  const out = [];
  const titleText = title ? ' ' + title + ' ' : '';
  const left = BOX.tl + BOX.h;
  const rest = inner - width(left) - width(titleText) + 1;
  out.push(c.cyan(left) + c.bold(titleText) + c.cyan(BOX.h.repeat(Math.max(0, rest)) + BOX.tr));
  for (const l of lines) {
    if (l === null) {
      out.push(c.cyan(BOX.ml + BOX.h.repeat(inner) + BOX.mr));
    } else {
      out.push(c.cyan(BOX.v) + ' ' + padEnd(truncate(l, inner - 2), inner - 2) + ' ' + c.cyan(BOX.v));
    }
  }
  out.push(c.cyan(BOX.bl + BOX.h.repeat(inner) + BOX.br));
  return out.join('\n');
}

function table(rows, columns) {
  if (!rows.length) return c.gray('  (없음)');
  const widths = columns.map((col) =>
    Math.min(
      col.max || 40,
      Math.max(width(col.label), ...rows.map((r) => width(String(col.get(r) === undefined ? '' : col.get(r)))))
    )
  );
  const head =
    '  ' + columns.map((col, i) => c.gray(col.right ? padStart(col.label, widths[i]) : padEnd(col.label, widths[i]))).join('  ');
  const sep = '  ' + c.gray(widths.map((w) => '─'.repeat(w)).join('  '));
  const body = rows.map((r) =>
    '  ' +
    columns
      .map((col, i) => {
        const v = truncate(String(col.get(r) === undefined ? '' : col.get(r)), widths[i]);
        return col.right ? padStart(v, widths[i]) : padEnd(v, widths[i]);
      })
      .join('  ')
  );
  return [head, sep].concat(body).join('\n');
}

const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

/** 진행 표시. stop()으로 줄을 지우고 최종 메시지를 남긴다. */
function spinner(label) {
  if (!process.stdout.isTTY) {
    process.stdout.write('  ' + label + '\n');
    return { update: () => {}, stop: (final) => final && process.stdout.write('  ' + final + '\n') };
  }
  let i = 0;
  let text = label;
  const startedAt = Date.now();
  const render = () => {
    const secs = Math.floor((Date.now() - startedAt) / 1000);
    const time = secs >= 1 ? c.gray(' ' + secs + 's') : '';
    readline.clearLine(process.stdout, 0);
    readline.cursorTo(process.stdout, 0);
    process.stdout.write('  ' + c.cyan(SPINNER[i++ % SPINNER.length]) + ' ' + text + time);
  };
  render();
  const timer = setInterval(render, 90);
  return {
    update: (t) => {
      text = t;
    },
    stop: (final) => {
      clearInterval(timer);
      readline.clearLine(process.stdout, 0);
      readline.cursorTo(process.stdout, 0);
      if (final) process.stdout.write('  ' + final + '\n');
    },
  };
}

const sym = {
  ok: c.green('✔'),
  fail: c.red('✘'),
  warn: c.yellow('▲'),
  info: c.blue('·'),
  dot: c.gray('•'),
};

function clear() {
  if (process.stdout.isTTY) process.stdout.write('[2J[H');
}

function hr(n) {
  return c.gray('─'.repeat(n || 50));
}

/**
 * 방향키/숫자로 고르는 메뉴. Promise<선택된 item | null(ESC/q)>
 * items: [{key, label, hint, disabled}]
 */
function menu(items, opts) {
  const o = opts || {};
  return new Promise((resolve) => {
    if (!process.stdout.isTTY) return resolve(null);
    let idx = items.findIndex((i) => !i.disabled);
    if (idx < 0) idx = 0;
    let lastHeight = 0;

    const render = (first) => {
      if (!first) {
        readline.moveCursor(process.stdout, 0, -lastHeight);
        readline.clearScreenDown(process.stdout);
      }
      const lines = [];
      if (o.title) lines.push('  ' + c.bold(o.title));
      items.forEach((it, i) => {
        const selected = i === idx;
        const num = c.gray('[' + (i + 1) + ']');
        let label = it.disabled ? c.gray(it.label) : it.label;
        if (selected) label = c.cyan('❯ ') + c.bold(label);
        else label = '  ' + label;
        const hint = it.hint ? '  ' + c.gray(it.hint) : '';
        lines.push('  ' + num + ' ' + label + hint);
      });
      lines.push('');
      lines.push(c.gray('  ↑↓ 이동 · Enter 선택 · 숫자 바로가기 · q 나가기'));
      const text = lines.join('\n');
      process.stdout.write(text + '\n');
      lastHeight = lines.length + 1;
    };

    const finish = (val) => {
      process.stdin.removeListener('keypress', onKey);
      if (process.stdin.isTTY) process.stdin.setRawMode(false);
      process.stdin.pause();
      readline.moveCursor(process.stdout, 0, -lastHeight);
      readline.clearScreenDown(process.stdout);
      resolve(val);
    };

    const onKey = (str, key) => {
      if (!key) return;
      if (key.name === 'up' || key.name === 'k') {
        do {
          idx = (idx - 1 + items.length) % items.length;
        } while (items[idx].disabled);
        render();
      } else if (key.name === 'down' || key.name === 'j' || key.name === 'tab') {
        do {
          idx = (idx + 1) % items.length;
        } while (items[idx].disabled);
        render();
      } else if (key.name === 'return' || key.name === 'space') {
        if (!items[idx].disabled) finish(items[idx]);
      } else if (key.name === 'escape' || key.name === 'q' || (key.ctrl && key.name === 'c')) {
        finish(null);
      } else if (str && /^[1-9]$/.test(str)) {
        const n = parseInt(str, 10) - 1;
        if (items[n] && !items[n].disabled) {
          idx = n;
          render();
          finish(items[n]);
        }
      }
    };

    readline.emitKeypressEvents(process.stdin);
    if (process.stdin.isTTY) process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on('keypress', onKey);
    render(true);
  });
}

/** 한 줄 입력. Promise<string> */
function prompt(question, defaultValue) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const suffix = defaultValue ? c.gray(' (' + defaultValue + ')') : '';
    rl.question('  ' + question + suffix + ' ', (answer) => {
      rl.close();
      resolve(answer.trim() || defaultValue || '');
    });
  });
}

/** y/N 확인. 기본은 아니오. */
async function confirm(question, defaultYes) {
  const hint = defaultYes ? 'Y/n' : 'y/N';
  const a = (await prompt(question + ' ' + c.gray('[' + hint + ']'))).toLowerCase();
  if (!a) return !!defaultYes;
  return a === 'y' || a === 'yes' || a === 'ㅛ';
}

function num(n) {
  return Number(n || 0).toLocaleString('ko-KR');
}

module.exports = {
  c,
  sym,
  box,
  table,
  spinner,
  menu,
  prompt,
  confirm,
  clear,
  hr,
  width,
  padEnd,
  padStart,
  truncate,
  num,
};
