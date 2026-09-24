'use strict';
/**
 * 레시피 장부 수확기 — 배포 씨앗(recipe-book.json)을 만든다.
 *
 *   node tools/harvest-recipes.js          내 수확분에 합친다 (%LOCALAPPDATA%)
 *   node tools/harvest-recipes.js --seed   배포 씨앗 파일에 합친다 (프로그램 폴더)
 *
 * get_craftable_items / get_alterable_items 를 한 번씩 부른다. 둘 다 조회라 공짜다.
 * 합치는 규칙과 조합(variant) 처리는 전부 src/recipebook.js 에 있다 —
 * 앱 안의 "레시피 표 수확" 버튼도 같은 코드를 쓴다.
 */
const fs = require('fs');
const connector = require('../src/connector');
const knowledge = require('../src/knowledge');
const book = require('../src/recipebook');

const toSeed = process.argv.indexOf('--seed') >= 0;
const FILE = toSeed ? book.SEED_FILE : book.USER_FILE;

function readRecipes(f) {
  try {
    const d = JSON.parse(fs.readFileSync(f, 'utf8'));
    if (d && typeof d.recipes === 'object') return d.recipes;
  } catch (_) { /* 처음 돌리는 경우 */ }
  return {};
}

const SEED_HEAD = {
  _설명:
    '제작·가공 레시피 표. 게임이 준 MissingIngredients 를 모은 것이며, ' +
    'tools/harvest-recipes.js --seed 로 갱신한다. 손으로 고쳐도 된다.',
  _필드: {
    via: 'craft | alter',
    per: '1회 산출 개수 (ProducedPerCraft / ProducedPerWork)',
    variants: '같은 이름을 만드는 서로 다른 재료 조합들. 한 이름에 최대 3갈래까지 확인됨',
    'variants[].ingredients': '{ 재료이름: 1회분 소모량 }',
    'variants[].complete':
      'true 면 재료가 전부 들어 있다. false 면 "적어도 이만큼"이라는 뜻 — ' +
      '게임은 그때 모자랐던 재료만 알려주기 때문이다.',
  },
  _한계:
    '지금 만들 수 있는 레시피는 게임이 재료를 아예 알려주지 않는다. ' +
    '재고가 다른 시점에 다시 수확해 합치면 표가 차오른다.',
};

async function pull(command) {
  const r = await connector.run(command);
  if (!r.ok) throw new Error(command + ' 실패: ' + (r.error || r.message));
  return (r.data && r.data.items) || [];
}

(async function main() {
  const recipes = readRecipes(FILE);
  const before = Object.keys(recipes).length;
  const known = knowledge.load().recipes || {};
  const totals = { rows: 0, named: 0, lines: 0, newNames: 0, newVariants: 0, completed: 0 };

  for (const [command, via, okKey, perKey] of [
    ['get_craftable_items', 'craft', 'Craftable', 'ProducedPerCraft'],
    ['get_alterable_items', 'alter', 'Alterable', 'ProducedPerWork'],
  ]) {
    const rows = await pull(command);
    const s = book.mergeRows(recipes, rows, via, okKey, perKey, known);
    for (const k of Object.keys(totals)) totals[k] += s[k];
    console.log(command + ' — ' + s.rows + '줄 중 ' + s.named + '줄이 재료를 알려 줬습니다.');
  }

  const out = toSeed
    ? Object.assign({}, SEED_HEAD, { _수확시각: new Date().toISOString(), recipes: recipes })
    : { _설명: '이 계정에서 모은 레시피 표.', _수확시각: new Date().toISOString(), recipes: recipes };
  fs.writeFileSync(FILE, JSON.stringify(out, null, 2), 'utf8');

  const names = Object.keys(recipes);
  const variants = names.reduce((n, k) => n + (recipes[k].variants || []).length, 0);
  const withIng = names.filter((k) => (recipes[k].variants || []).some((v) => Object.keys(v.ingredients || {}).length)).length;
  const done = names.filter((k) => (recipes[k].variants || []).some((v) => v.complete)).length;

  console.log('');
  console.log('레시피 ' + before + ' → ' + names.length + '개 (새 이름 ' + totals.newNames + ')');
  console.log('조합 ' + variants + '개 (새 조합 ' + totals.newVariants + ') · 재료 줄 ' + totals.lines + '개');
  console.log('재료를 아는 레시피 ' + withIng + '개 · 그중 완전한 것 ' + done + '개');
  console.log(FILE);
})().catch((err) => {
  console.error('수확 실패: ' + err.message);
  process.exit(1);
});
