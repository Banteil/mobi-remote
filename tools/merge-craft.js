/**
 * 스크린샷에서 뽑아낸 표를 큰 표에 합친다.
 *
 *   node tools/merge-craft.js <뽑아낸.csv> <큰표.csv> <분류> [--write]
 *
 * --write 를 주기 전에는 **무엇이 달라지는지만** 보여 주고 파일은 건드리지 않는다.
 * 합칠 때는 먼저 '<이름> (백업 YYYY-MM-DD).csv'로 원본을 떠 둔다.
 *
 * 합치는 방식은 **분류 구역 통째로 갈아 끼우기**다. 스크린샷은 그 분류의 제작대를
 * 처음부터 끝까지 찍은 것이므로, 화면에 없는 줄은 게임에서 사라진 줄이다. 다만
 * 사라지는 줄은 하나하나 적어 보여 주므로, 찍다 만 폴더로 돌리면 바로 눈에 띈다.
 *
 * 물음표가 남은 줄이 있으면 아무것도 하지 않는다. 덜 읽힌 표로 멀쩡한 표를
 * 덮어쓰는 일은 없어야 한다 — 스샷을 보고 그 자리를 채운 뒤에 다시 부른다.
 */

const fs = require('fs');
const { parseCsv, toCsv } = require('./craft-shots');

function flat(s) { return String(s || '').replace(/\s+/g, ''); }

function rowsOf(file) {
  return parseCsv(fs.readFileSync(file, 'utf8'));
}

function main(argv) {
  const [made, master, cls] = argv;
  const write = argv.includes('--write');
  if (!made || !master || !cls) {
    console.error('사용법: node tools/merge-craft.js <뽑아낸.csv> <큰표.csv> <분류> [--write]');
    process.exit(2);
  }

  const fresh = rowsOf(made).slice(1).filter((r) => r[1])
    .map((r) => [r[1], r[2] || '', r[3] || '']);
  const holes = fresh.filter((r) => /\?/.test(r[0] + r[1] + r[2]));
  if (holes.length) {
    console.error('물음표가 남은 줄이 ' + holes.length + '개 있어 합치지 않는다:');
    for (const h of holes) console.error('  ' + h[0] + ' | ' + h[2].replace(/\n/g, ' / '));
    process.exit(1);
  }

  const rows = rowsOf(master);
  let cur = '', from = -1, to = -1;
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][0]) cur = rows[i][0];
    if (cur === cls) { if (from < 0) from = i; to = i; }
  }
  const old = from < 0 ? [] : rows.slice(from, to + 1).filter((r) => r[1]).map((r) => [r[1], r[2] || '', r[3] || '']);

  // 짝을 지어 본다. 이름과 조건이 같은 줄이 여럿일 수 있어 하나씩 집어낸다.
  const pool = old.slice();
  const added = [], same = [];
  for (const f of fresh) {
    let at = pool.findIndex((o) => o[0] === f[0] && flat(o[1]) === flat(f[1]) && flat(o[2]) === flat(f[2]));
    if (at < 0) at = pool.findIndex((o) => o[0] === f[0] && flat(o[1]) === flat(f[1]));
    if (at < 0) { added.push(f); continue; }
    const [hit] = pool.splice(at, 1);
    if (flat(hit[2]) === flat(f[2])) same.push(f);
    else added.push(Object.assign(f, { was: hit[2] }));
  }

  console.log(cls + ' — 기존 ' + old.length + '줄, 화면 ' + fresh.length + '줄');
  console.log('  그대로 ' + same.length + ' · 새로 들어오거나 바뀐 줄 ' + added.length + ' · 화면에 없어 빠질 줄 ' + pool.length);
  for (const a of added) {
    console.log('  ' + (a.was ? '~' : '+') + ' ' + a[0] + ' | ' + a[1].replace(/\n/g, ' / ') + ' | ' + a[2].replace(/\n/g, ' / '));
    if (a.was) console.log('      기존: ' + a.was.replace(/\n/g, ' / '));
  }
  for (const p of pool) console.log('  - ' + p[0] + ' | ' + p[1].replace(/\n/g, ' / ') + ' | ' + p[2].replace(/\n/g, ' / '));

  if (!write) { console.log('\n(보여만 줬다. 합치려면 --write)'); return; }

  const block = fresh.map((f, i) => [i === 0 ? cls : '', f[0], f[1], f[2]]);
  const next = from < 0 ? rows.concat(block) : rows.slice(0, from).concat(block, rows.slice(to + 1));
  const backup = master.replace(/\.csv$/i, ' (백업 ' + new Date().toLocaleString('sv-SE').slice(0, 16).replace(' ', ' ').replace(':', '시') + ').csv');
  fs.copyFileSync(master, backup);
  fs.writeFileSync(master, toCsv(next), 'utf8');
  console.log('\n합쳤다. 원본은 ' + backup + ' 에 떠 뒀다.');
}

if (require.main === module) main(process.argv.slice(2));
module.exports = { main };
