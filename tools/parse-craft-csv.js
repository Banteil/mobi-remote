/**
 * 제작 리스트 CSV에서 **무기**만 골라 JSON으로 옮긴다.
 *
 *   node tools/parse-craft-csv.js "<제작 리스트.csv>" [out.json]
 *
 * 무기인지는 분류 이름이 아니라 **조건 칸의 시설**로 가린다 — '무기 제작대'를 쓰는
 * 줄만 가져온다. 나중에 방어구·장신구 표가 들어와도 이 도구는 건드릴 것이 없고,
 * 시설 이름만 바꿔 부르면 된다.
 *
 * ── 이 표가 장부보다 나은 점 ───────────────────────────────
 * 게임은 "지금 만들 수 없는" 레시피의 "모자란 재료만" 알려준다. 그래서 장부
 * (recipe-book.json)는 아무리 모아도 군데군데 비고, 필요한 시설 레벨과 기술 레벨은
 * 아예 알 수 없다. 이 표는 사람이 화면을 보고 정리한 것이라 재료가 빠짐없이 들어
 * 있고 두 레벨도 있다.
 *
 * ── 같은 이름, 다른 갈래 ───────────────────────────────────
 * 가공과 마찬가지로 이름이 같은데 재료가 다른 것이 있다. 무기에서는 SS 단계가
 * 그렇다 — 제작대 Lv.3 짜리와 Lv.4 짜리가 이름이 같다. 그래서 산출물 이름 하나에
 * variants 를 여럿 매단다. 다만 **CLI에는 이 갈래를 고를 수단이 없다**(가공에서
 * 확인한 것과 같다). 그러니 이 표는 "무엇이 드는지 미리 셈하는" 용도이지,
 * 갈래를 찍어 시키는 용도가 아니다.
 */

const fs = require('fs');
const path = require('path');
const { parseCsv } = require('./craft-shots');

const FACILITY = '무기 제작대';

function parseCond(text) {
  const out = { facility: null, level: null, skill: null, skillLevel: null };
  for (const line of String(text || '').split('\n')) {
    const m = /^(.*?)\s*Lv\.?\s*(\d+)\s*$/.exec(line.trim());
    if (!m) continue;
    const name = m[1].trim();
    if (name.includes('제작대')) { out.facility = name; out.level = +m[2]; }
    else { out.skill = name; out.skillLevel = +m[2]; }
  }
  return out;
}

function parseMats(text) {
  const out = {};
  for (const line of String(text || '').split('\n')) {
    const m = /^(.*?)\s*[xX×]\s*(\d+)\s*$/.exec(line.trim());
    if (m) out[m[1].trim()] = +m[2];
  }
  return out;
}

function build(csvFile) {
  const rows = parseCsv(fs.readFileSync(csvFile, 'utf8'));
  const recipes = {};
  let cur = '';
  let rowsSeen = 0;
  const classes = new Set();

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r || !r[1]) continue;
    if (r[0]) cur = r[0];

    const cond = parseCond(r[2]);
    if (cond.facility !== FACILITY) continue;

    const ing = parseMats(r[3]);
    if (!Object.keys(ing).length) continue;

    rowsSeen++;
    classes.add(cur);
    const name = r[1].trim();
    if (!recipes[name]) recipes[name] = { via: 'craft', per: 1, variants: [] };
    recipes[name].variants.push({
      job: cur,
      facility: cond.facility,
      level: cond.level,
      skill: cond.skill,
      skillLevel: cond.skillLevel,
      ingredients: ing,
      complete: true,
    });
  }

  return { recipes: recipes, rowsSeen: rowsSeen, classes: [...classes] };
}

function main(argv) {
  const src = argv[0];
  const out = argv[1] || path.join(__dirname, '..', 'craft-weapons.json');
  if (!src) {
    console.error('사용법: node tools/parse-craft-csv.js "<제작 리스트.csv>" [out.json]');
    process.exit(2);
  }

  const { recipes, rowsSeen, classes } = build(src);
  const names = Object.keys(recipes).sort((a, b) => a.localeCompare(b, 'ko'));
  const sorted = {};
  for (const n of names) sorted[n] = recipes[n];

  const doc = {
    '_설명': '마비노기 모바일 무기 제작표. 게임 화면을 그대로 옮긴 것이라 재료가 빠짐없이 들어 있고, 제작대 레벨과 기술 레벨도 있다.',
    '_필드': {
      per: '한 번 제작에 나오는 개수',
      variants: '이름이 같은데 재료가 다른 갈래. SS 단계가 제작대 Lv.3 짜리와 Lv.4 짜리로 갈린다.',
      job: '이 무기를 쓰는 직업',
      level: '필요한 무기 제작대 레벨',
      skill: '필요한 생활 기술 (대장 기술 · 목공 · 매직 크래프트)',
      complete: '재료가 빠짐없이 적혀 있는가. 이 표는 전부 true.',
    },
    '_한계': 'CLI에는 같은 이름의 갈래를 골라 시킬 수단이 없다. 미리 셈하는 데 쓰고, 시킬 때는 게임이 고르는 대로 따른다.',
    '_출처': path.basename(src),
    '_만든시각': new Date().toISOString(),
    '_직업': classes,
    recipes: sorted,
  };

  fs.writeFileSync(out, JSON.stringify(doc, null, 1), 'utf8');

  const vs = names.reduce((s, n) => s + recipes[n].variants.length, 0);
  const mats = new Set();
  for (const n of names) for (const v of recipes[n].variants) for (const k of Object.keys(v.ingredients)) mats.add(k);
  console.log('직업 ' + classes.length + ' · 제작품 ' + names.length + '종 · 갈래 ' + vs +
    ' (표 ' + rowsSeen + '줄) · 쓰이는 재료 ' + mats.size + '가지');
  console.log('→ ' + out);
}

if (require.main === module) main(process.argv.slice(2));
module.exports = { build, parseCond, parseMats, FACILITY };
