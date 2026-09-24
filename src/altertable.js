'use strict';
/**
 * 가공 재료표 — 사람이 정리한 **완전한** 표.
 *
 * ── 장부와 무엇이 다른가 ───────────────────────────────────
 * 장부(recipe-book.json)는 게임이 흘린 것을 주워 모은 **관측**이다. 게임은 "지금 만들 수
 * 없는" 레시피의 "모자란 재료만" 알려주므로 아무리 모아도 군데군데 비고, 필요한 시설
 * 레벨과 걸리는 시간은 아예 알 수 없다.
 *
 * 이 표는 사람이 정리한 **사실**이다. 재료가 빠짐없이 들어 있고 레벨과 시간도 있다.
 * 실측 — 86가지 중 장부가 개수를 모르던 것 55건, 재료가 빠졌거나 틀린 것 44건,
 *        갈래를 하나로 뭉개 놓은 것 3건. 레벨은 장부 0건 / 표 86건 전부.
 *
 * ── 그래서 합치지 않고 갈아끼운다 ──────────────────────────
 * 완전한 것에 불완전한 것을 섞으면 나빠지기만 한다. 장부가 은합금괴를
 * "특수강괴 5 · 은 광석 20 · 마력 깃든 돌 ? · 석탄 ?" 한 줄로 뭉개 놓은 것이 바로 그
 * 결과다(실제로는 Lv.4 갈래와 Lv.6 갈래 둘). 그래서 **이름이 표에 있으면 표만 쓴다.**
 * 표에 없는 이름은 장부가 그대로 맡는다 — 업데이트로 새 레시피가 생겨도 수확 경로가
 * 살아 있어야 한다.
 *
 * ── 이름 두 가지 ───────────────────────────────────────────
 * 표는 **산출물 이름**으로 적혀 있고, 게임에 시킬 때 쓰는 것은 **레시피 이름**이다.
 * 둘은 대개 같지만, 갈래가 여럿이면 게임이 재료를 괄호로 붙여 구분한다.
 *
 *   철괴(광석)      ← 표의 철괴 갈래1 [광석 20]
 *   철괴(철 광석)   ← 표의 철괴 갈래2 [철 광석 10]
 *
 * **다만 늘 그러는 것은 아니다.** 실측 — 게임 레시피 87개 중 괄호로 갈라지는 것은
 * 철괴 하나뿐이다. 은합금괴·최상급 가죽·최상급 목재·최상급 옷감은 갈래가 둘인데도
 * 게임이 **같은 이름 하나로** 내놓는다 (시설이 Lv.6 이어도 그렇다).
 *
 * CLI 응답에도 갈래를 가를 **아무 표시가 없다.** 실측 —
 *
 *   한 줄이 들고 있는 칸: DisplayName · Alterable · ProducedPerWork · Reason · MissingIngredients
 *   은합금괴 두 줄은 DisplayName 이 글자 하나 다르지 않고, 다른 것은 MissingIngredients 뿐이다.
 *
 * 시킬 때 쓰는 execute_altering 의 본문도 {"displayName": "..."} 하나뿐이라
 * 번호나 코드로 고를 수단이 없다. **커넥터가 지원하지 않는 일이다.**
 *
 * 그래서 이름을 **지어내지 않는다.** 게임이 실제로 쓰는 이름 목록에 있을 때만 괄호를
 * 붙이고, 없으면 산출물 이름 그대로 쓴다.
 *
 * ── 그럼 시키면 어느 갈래가 도나 ──────────────────────────
 * **언제나 첫 줄이다.** 실측으로 확인했다 — 최상급 목재의 두 줄이 **둘 다 실행 가능한**
 * 상태를 만들어 놓고 시켰더니, 줄어든 재료가 이랬다.
 *
 *   상급 목재+   9 → 4  (-5)    ← 1번줄(Lv.4)의 재료
 *   단단한 통나무 95 → 95  (0)    ← 2번줄(Lv.6)의 재료, 그대로
 *
 * 즉 "실행 가능한 쪽을 고른다"가 아니라 **목록의 첫 줄**을 잡는다. 그리고 CLI 의 줄
 * 순서는 이 표의 갈래 순서와 같다(네 가지 모두에서 Lv.4 가 먼저).
 *
 * 그래서 이름으로 못 가리는 가공품은 **0번 갈래만 고를 수 있다.** 계획을 다른 갈래로
 * 세우면 실제로 도는 것과 어긋나므로, 아예 후보에서 뺀다.
 */
const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'alter-recipes.json');

let cached = null;

function load() {
  if (cached) return cached;
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    cached = (d && d.recipes) || {};
  } catch (_) {
    cached = {};    // 표가 없거나 깨졌어도 앱은 장부만으로 계속 돈다
  }
  return cached;
}

function reload() { cached = null; return load(); }

function get(product) { return load()[product] || null; }
function has(product) { return !!load()[product]; }
function names() { return Object.keys(load()); }

/** "철괴(광석)" → ['철괴', '광석'] · 괄호가 없으면 null */
function splitRecipeName(s) {
  const m = /^(.*?)\s*\((.+)\)$/.exec(String(s || '').trim());
  return m ? [m[1].trim(), m[2].trim()] : null;
}

/**
 * 게임의 레시피 이름으로 표의 갈래를 찾는다.
 *
 * 괄호 안은 그 갈래를 가르는 재료 이름이다. 다만 괄호가 **이름의 일부**인 경우도 있어서
 * (광휘의 결정(유령 반딧불이)) 이름 그대로 찾는 쪽을 먼저 본다.
 */
function forRecipe(recipeName) {
  const tbl = load();
  const direct = tbl[recipeName];
  if (direct) return { product: recipeName, entry: direct, index: direct.variants.length === 1 ? 0 : -1 };

  const p = splitRecipeName(recipeName);
  if (!p || !tbl[p[0]]) return null;
  const entry = tbl[p[0]];
  const i = entry.variants.findIndex((v) => Object.keys(v.ingredients).indexOf(p[1]) >= 0);
  return i >= 0 ? { product: p[0], entry: entry, index: i } : null;
}

/**
 * 갈래 하나를 **게임에 시킬 이름**으로.
 *
 * 괄호 이름은 지어내면 안 된다. 게임이 그렇게 부르는 것만 그렇게 부른다 —
 * 없는 이름을 만들어 시키면 그냥 실패한다.
 *
 * @param known  게임이 실제로 쓰는 레시피 이름들. 안 주면 괄호를 붙이지 않는다.
 * @returns { name, ambiguous }  ambiguous 면 이 이름으로는 갈래를 못 고른다는 뜻.
 */
function recipeNameOf(product, index, known) {
  const e = get(product);
  if (!e || e.variants.length <= 1) return { name: product, ambiguous: false };

  const v = e.variants[index] || e.variants[0];
  const others = e.variants.filter((_, i) => i !== index);
  // 다른 갈래에는 없는 재료가 그 갈래의 이름표가 될 수 있다
  const mark = Object.keys(v.ingredients)
    .find((k) => others.every((o) => o.ingredients[k] === undefined));
  const guess = mark ? product + '(' + mark + ')' : null;

  if (guess && known && known.has && known.has(guess)) return { name: guess, ambiguous: false };
  return { name: product, ambiguous: true };
}

/**
 * 지금 시설 레벨로 **돌릴 수 있는** 갈래들.
 *
 * 하나도 없으면 빈 배열이 아니라 `{ runnable: [], all: [...] }` 로 돌려준다 —
 * "레벨이 모자라서 못 한다"와 "그런 레시피가 없다"는 다른 말이고, 화면에는 그 둘을
 * 다르게 적어야 한다.
 *
 * @param levels { '금속 가공 시설': 4, ... }
 */
function variantsFor(product, levels) {
  const e = get(product);
  if (!e) return null;
  const lv = levels || {};
  const runnable = [];
  e.variants.forEach((v, i) => {
    const have = lv[v.facility];
    if (v.level == null || (have != null && have >= v.level)) runnable.push(i);
  });
  return { entry: e, runnable: runnable, all: e.variants.map((_, i) => i) };
}

/**
 * **실제로 골라서 시킬 수 있는** 갈래 번호들.
 *
 * 이름이 갈래마다 다르면 전부 고를 수 있다(철괴). 이름이 하나뿐이면 시켜도 첫 줄만
 * 도니까 0번 하나뿐이다 — 나머지는 계획에 넣어 봐야 어긋나기만 한다.
 *
 * @param known 게임이 실제로 쓰는 레시피 이름들
 */
function selectable(product, known) {
  const e = get(product);
  if (!e) return [];
  if (e.variants.length <= 1) return [0];
  const out = [];
  e.variants.forEach((_, i) => {
    if (!recipeNameOf(product, i, known).ambiguous) out.push(i);
  });
  return out.length ? out : [0];
}

/**
 * 목록의 **한 줄**을 표의 갈래 하나에 맞춘다.
 *
 * 이름이 같은 줄이 여럿 오는 레시피가 있다(은합금괴는 Lv.4 와 Lv.6 두 줄). 이름만 보고
 * 첫 갈래로 몰면 두 줄이 같은 레벨·같은 시간으로 보인다 — 실제로는 재료도 시간도 다르다.
 *
 * 두 가지로 맞춘다.
 *
 *   1. **모자란 재료**로. 그 갈래에만 있는 재료가 모자란 목록에 있으면 그 갈래다.
 *      가장 확실하지만, 그 줄이 지금 실행 가능하면 모자란 목록이 아예 없다.
 *   2. **나온 차례**로. CLI 의 줄 순서는 표의 갈래 순서와 같다 — 네 가지 모두에서
 *      Lv.4 가 먼저였고, 실제로 시켰을 때도 첫 줄이 돌았다.
 *
 * @param missing  그 줄의 모자란 재료 이름들 (없으면 빈 배열)
 * @param nth      같은 이름이 몇 번째로 나왔는가 (0부터)
 */
function matchRow(recipeName, missing, nth) {
  const hit = forRecipe(recipeName);
  if (!hit) return null;
  const vs = hit.entry.variants;
  if (hit.index >= 0) return { product: hit.product, index: hit.index, variant: vs[hit.index] };
  if (vs.length === 1) return { product: hit.product, index: 0, variant: vs[0] };

  // 1) 그 갈래에만 있는 재료가 모자란 목록에 있나
  const miss = new Set(missing || []);
  if (miss.size) {
    const only = vs.map((v, i) =>
      Object.keys(v.ingredients).filter((k) =>
        vs.every((o, j) => j === i || o.ingredients[k] === undefined)));
    const hits = [];
    only.forEach((keys, i) => { if (keys.some((k) => miss.has(k))) hits.push(i); });
    if (hits.length === 1) return { product: hit.product, index: hits[0], variant: vs[hits[0]] };
  }

  // 2) 나온 차례대로
  const i = Math.min(Math.max(0, nth || 0), vs.length - 1);
  return { product: hit.product, index: i, variant: vs[i] };
}

module.exports = {
  load, reload, get, has, names,
  forRecipe, matchRow, recipeNameOf, variantsFor, selectable, splitRecipeName,
  FILE,
};
