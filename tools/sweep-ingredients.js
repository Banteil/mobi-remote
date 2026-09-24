'use strict';
/**
 * 재료 이름으로 거꾸로 물어 레시피의 **재료 이름 집합**을 알아낸다.
 *
 *   node tools/sweep-ingredients.js            훑어서 결과만 보여 준다
 *   node tools/sweep-ingredients.js --write    알아낸 것을 장부에 적는다
 *   node tools/sweep-ingredients.js --check    배운 레시피를 교차검증한다
 *
 * ── 어떻게 가능한가 ────────────────────────────────────────
 * get_craftable_items 의 본문 필터는 명세상 **재료 이름에도 걸린다.**
 *
 *   > The body filter is matched against the recipe name OR any ingredient name
 *
 * 즉 게임은 전체 재료 목록을 갖고 있으면서 응답에만 싣지 않는 것이다. 그러면 재료 이름을
 * 하나씩 넣어 보고 "이 레시피가 걸렸다" = "이 재료를 쓴다"로 읽으면 된다.
 * 만들 수 있어서 재료를 안 알려주던 레시피도 이 방법에는 걸린다.
 *
 * ── 부분 문자열이라는 함정 ─────────────────────────────────
 * 필터는 부분 문자열이라 "목재"로 물으면 "상급 목재"·"최상급 목재"·"목재+"를 쓰는 것까지
 * 다 걸린다. 그래서 **가장 구체적인 이름에만 귀속**시킨다 — 어떤 레시피가 "목재"에도
 * "상급 목재"에도 걸렸다면 그 레시피의 재료는 "상급 목재"쪽으로 본다.
 * (실측 — 숏소드는 "목재"에만 걸리고 "상급 목재"에는 안 걸린다. 갈림이 깨끗하다.)
 *
 * ── 무엇을 얻고 무엇을 못 얻나 ─────────────────────────────
 * 재료 **이름**은 알아내지만 **개수(Required)는 여전히 모른다.** 개수는 그 재료가 모자랄 때
 * 게임이 알려 주는 값으로만 채워진다. 그래서 이 도구는 장부의 빈칸을 "이름만 아는" 상태로
 * 바꾸고, 개수는 평소 수확이 채우게 둔다.
 */
const fs = require('fs');
const connector = require('../src/connector');
const knowledge = require('../src/knowledge');
const book = require('../src/recipebook');

const WRITE = process.argv.indexOf('--write') >= 0;
const CHECK = process.argv.indexOf('--check') >= 0;

async function pull(command, body) {
  const r = await connector.run(command, body);
  if (!r.ok) throw new Error(command + ' 실패: ' + (r.error || r.message));
  return (r.data && r.data.items) || [];
}

/** 물어볼 재료 이름들 — 장부에 이미 나온 재료 + 채집 가능 목록. */
function materialNames(recipes, gatherable) {
  const set = new Set(gatherable);
  for (const n of Object.keys(recipes)) {
    for (const v of recipes[n].variants || []) {
      for (const k of Object.keys(v.ingredients || {})) set.add(k);
    }
  }
  return [...set].sort();
}

(async function main() {
  const recipes = JSON.parse(JSON.stringify(book.load().recipes));
  const gather = (await pull('get_gatherable_items')).map((r) => r.DisplayName);
  const mats = materialNames(recipes, gather);

  console.log('물어볼 재료 ' + mats.length + '종. 전부 조회라 비용은 없습니다.');
  console.log('');

  // 재료 → 그 재료가 걸린 레시피 이름들
  const hits = new Map();
  const vague = new Map();   // 이름 때문에 걸렸을 수도 있는 것
  let done = 0;
  for (const m of mats) {
    const rows = [];
    for (const cmd of ['get_craftable_items', 'get_alterable_items']) {
      try { rows.push(...await pull(cmd, m)); } catch (_) { /* 한 번 실패는 건너뛴다 */ }
    }
    // 레시피 **이름**에 그 문자열이 들어 있으면 이름으로 걸린 것인지 재료로 걸린 것인지
    // 가릴 수 없다. 목재+ 는 "목재"로 물어도 걸리는데, 이름 때문인지 재료 때문인지 모른다.
    // 그래서 확실한 것만 재료로 삼고, 애매한 것은 따로 표시해 둔다.
    const names = rows.map((r) => r.DisplayName);
    hits.set(m, new Set(names.filter((n) => !n.includes(m))));
    vague.set(m, new Set(names.filter((n) => n.includes(m) && n !== m)));
    done++;
    if (done % 25 === 0) process.stdout.write('  ' + done + '/' + mats.length + '\r');
  }
  console.log('  ' + done + '/' + mats.length + ' 완료');
  console.log('');

  /* 가장 구체적인 이름에만 귀속시킨다 */
  const byRecipe = new Map();   // 레시피 → Set(재료)
  const longFirst = [...mats].sort((a, b) => b.length - a.length);
  for (const m of longFirst) {
    for (const r of hits.get(m)) {
      if (!byRecipe.has(r)) byRecipe.set(r, new Set());
      const cur = byRecipe.get(r);
      // 이미 더 긴(구체적인) 이름으로 담았다면 그 이름의 부분 문자열은 버린다
      let covered = false;
      for (const have of cur) if (have.includes(m)) { covered = true; break; }
      if (!covered) cur.add(m);
    }
  }

  /* 교차검증 — 직접 만들어 보고 배운 값과 대조 */
  if (CHECK) {
    const learned = knowledge.load().recipes || {};
    console.log('◆ 배운 레시피 교차검증');
    for (const name of Object.keys(learned)) {
      const e = learned[name];
      if (!e.ingredients) continue;
      const seen = byRecipe.get(name) || new Set();
      const mine = Object.keys(e.ingredients);
      // 이름이 겹쳐 가릴 수 없는 재료는 "틀렸다"고 말하지 않는다.
      // 목재+ ← 목재 처럼, 레시피 이름이 재료 이름을 품고 있으면 필터로는 구분이 안 된다.
      const undecidable = mine.filter((k) => !seen.has(k) &&
        ((vague.get(k) && vague.get(k).has(name)) || name.includes(k)));
      const missFromGame = mine.filter((k) => !seen.has(k) && !undecidable.includes(k));
      const extraInGame = [...seen].filter((k) => !mine.includes(k));
      const mark = missFromGame.length ? '▲' : (undecidable.length ? '?' : '✔');
      console.log('  ' + mark + ' ' + name + '  (' + e.confidence + ', 관측 ' + (e.observed || 0) + '회)');
      console.log('      배운 값   ' + mine.join(' · '));
      console.log('      게임 색인 ' + ([...seen].join(' · ') || '(걸린 것 없음)'));
      if (undecidable.length) console.log('      가릴 수 없음(이름 겹침): ' + undecidable.join(' · '));
      if (missFromGame.length) console.log('      게임 색인에 없음: ' + missFromGame.join(' · '));
      if (extraInGame.length) console.log('      배운 값에 없음:   ' + extraInGame.join(' · '));
    }
    console.log('');
  }

  /* 장부의 빈칸 채우기 */
  let filled = 0, grew = 0;
  for (const [name, set] of byRecipe) {
    const e = recipes[name];
    if (!e) continue;
    const vs = e.variants || (e.variants = []);
    const known = new Set();
    for (const v of vs) for (const k of Object.keys(v.ingredients || {})) known.add(k);

    const unknown = [...set].filter((k) => !known.has(k));
    if (!unknown.length) continue;

    if (!vs.length) {
      // 재료를 하나도 모르던 레시피 — 이름만 아는 조합을 만든다 (개수는 null)
      const ing = {};
      for (const k of set) ing[k] = null;
      vs.push({ ingredients: ing, complete: false, namesOnly: true });
      filled++;
    } else if (vs.length === 1) {
      // 갈래가 하나면 빠진 이름을 그 조합에 더한다
      for (const k of unknown) vs[0].ingredients[k] = null;
      vs[0].namesOnly = vs[0].namesOnly || undefined;
      grew++;
    }
    // 갈래가 여럿이면 어느 쪽 재료인지 가릴 수 없어 건드리지 않는다
  }

  const withIng = Object.keys(recipes).filter((k) =>
    (recipes[k].variants || []).some((v) => Object.keys(v.ingredients || {}).length)).length;

  console.log('◆ 결과');
  console.log('  재료 이름을 알아낸 레시피 ' + byRecipe.size + '종');
  console.log('  빈칸을 채운 레시피 ' + filled + '종 · 이름을 더한 레시피 ' + grew + '종');
  console.log('  재료를 아는 레시피 ' + book.stats().withIngredients + ' → ' + withIng + '종');

  if (WRITE) {
    book.saveUser(recipes);
    console.log('  저장했습니다: ' + book.USER_FILE);
  } else {
    console.log('  (--write 를 붙이면 장부에 적습니다)');
  }
})().catch((err) => {
  console.error('훑기 실패: ' + err.message);
  process.exit(1);
});
