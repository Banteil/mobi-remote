'use strict';
/**
 * 레시피 장부 — 게임이 알려 준 재료 표를 모아 둔 곳.
 *
 * ── 왜 필요한가 ────────────────────────────────────────────
 * 게임은 **지금 만들 수 없는** 레시피에만 재료를 알려준다. 그것도 "모자란 것만"이다.
 * 그래서 새로 설치한 사람은 아무것도 모르는 상태로 시작하고, 앱이 할 수 있는 말은
 * "한 번 만들어 보면 그때 알아냅니다"뿐이었다. 목표를 걸 때마다 탐색 제작을 한 번씩
 * 태우는 셈이라 날개가 그냥 나간다.
 *
 * 그 표를 미리 채워서 같이 배포한다. facility-map.json 과 같은 성격이다 —
 * 게임이 제때 주지 않는 사실을 모아 둔 파일이고, 업데이트가 나오면 고쳐 넣으면 된다.
 *
 * ── 두 겹이다 ──────────────────────────────────────────────
 *   1. 배포 씨앗  <프로그램 폴더>/recipe-book.json   — 같이 실려 오는 표
 *   2. 내 수확분  %LOCALAPPDATA%/.../recipe-book.json — 이 계정에서 모은 표 (우선)
 * 배포판을 덮어써도 내가 모은 것은 살아남고, 씨앗이 갱신되면 모르던 레시피가 채워진다.
 *
 * ── 한 이름에 여러 조합이 있다 ──────────────────────────────
 * 실측 — 제작 1,834줄 중 이름이 겹치는 것이 79개, 많게는 **3갈래**다.
 *
 *   한손 도끼SS ← 특수강괴 5 · 상급 목재+ 3 · 항마석 가루 60 · 지배의 도안 2
 *   한손 도끼SS ← 은합금괴 3 · 상급 목재+ 3 · 상급 항마석 가루 20
 *
 * 같은 물건을 다른 재료로도 만들 수 있게 해 둔 것이다. 이름 하나에 재료를 몰아 담으면
 * **둘을 합친 가짜 레시피**가 만들어진다(특수강괴도 은합금괴도 다 필요한 것처럼).
 * 그래서 조합(variant)을 따로 담는다.
 *
 * ── 무엇이 한계인가 ────────────────────────────────────────
 * 한 번의 수확으로는 **그때 모자랐던 재료만** 들어온다. 감자를 넉넉히 들고 있으면
 * 통감자구이 줄에 감자가 아예 안 나온다. 그래서 조합마다 `complete` 를 두고,
 * 확인되기 전에는 "적어도 이만큼"으로만 쓴다. 재고가 다른 날 다시 수확해 합치면
 * 표는 점점 차오른다. 실제로 만들어 보고 알아낸 값(knowledge.json)이 언제나 우선이다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');
const altertable = require('./altertable');

const SEED_FILE = path.join(__dirname, '..', 'recipe-book.json');
const USER_FILE = paths.dataPath('recipe-book.json');

let cached = null;

function readFile(f) {
  try {
    const d = JSON.parse(fs.readFileSync(f, 'utf8'));
    return d && typeof d.recipes === 'object' ? d.recipes : null;
  } catch (_) {
    return null;   // 없거나 깨졌으면 없는 것으로 친다. 앱은 계속 돌아야 한다.
  }
}

/**
 * 두 겹을 **이름마다 합친다.**
 *
 * 처음에는 내 수확분이 씨앗을 통째로 덮게 했는데, 그게 데이터를 잃었다.
 * 내 표에 "숏소드: 조합 없음"이 들어 있으면 씨앗이 들고 있는 숏소드 재료까지 가려 버린다.
 * 둘 다 같은 종류의 관측(게임이 알려 준 부족 재료)이라 가릴 이유가 없다 — 합치는 것이 맞다.
 */
function mergeEntry(seed, mine) {
  if (!seed) return mine;
  if (!mine) return seed;
  const sv = (seed.variants || []).filter((v) => v && v.ingredients);
  const mv = (mine.variants || []).filter((v) => v && v.ingredients);
  if (!sv.length) return Object.assign({}, seed, mine, { variants: mv });
  if (!mv.length) return Object.assign({}, seed, mine, { variants: sv });

  // 양쪽에 조합이 있으면 내 것을 바탕으로 씨앗 것을 흡수시킨다.
  // 둘 다 한 갈래뿐이면 같은 레시피의 다른 조각이므로 합집합으로 본다.
  const out = JSON.parse(JSON.stringify(mv));
  const single = sv.length === 1 && mv.length === 1;
  for (const v of sv) absorbGroup(out, [v.ingredients], single);
  for (const v of sv) {
    if (!v.complete) continue;
    const fit = out.find((x) => compatible(x.ingredients, v.ingredients));
    if (fit) { fit.ingredients = Object.assign({}, v.ingredients); fit.complete = true; }
  }
  return Object.assign({}, seed, mine, { variants: out });
}

/**
 * 세 겹이다. 위에 있을수록 세다.
 *
 *   3. 가공 재료표 (alter-recipes.json)  — 사람이 정리한 **완전한** 사실
 *   2. 내 수확분                          — 이 계정에서 게임이 흘린 것
 *   1. 배포 씨앗                          — 같이 실려 온 것
 *
 * 1과 2는 같은 종류의 관측이라 **합친다.** 둘 다 "모자란 재료만" 본 것이라 서로의
 * 빈 곳을 메워 준다.
 *
 * 3은 다르다. 완전한 것에 불완전한 것을 섞으면 **나빠지기만 한다.** 장부가 은합금괴를
 * "특수강괴 5 · 은 광석 20 · 마력 깃든 돌 ? · 석탄 ?" 한 줄로 뭉개 놓은 것이 그 증거다
 * (실제로는 Lv.4 갈래와 Lv.6 갈래 둘). 그래서 **이름이 표에 있으면 표로 갈아끼운다.**
 *
 * 표에 없는 이름은 1+2 가 그대로 맡는다. 업데이트로 새 레시피가 생겨도 수확해서
 * 채울 길이 남아 있어야 하기 때문이다.
 */
function load() {
  if (cached) return cached;
  const seed = readFile(SEED_FILE) || {};
  const mine = readFile(USER_FILE) || {};
  const recipes = {};
  for (const k of Object.keys(seed)) recipes[k] = seed[k];
  for (const k of Object.keys(mine)) recipes[k] = mergeEntry(seed[k], mine[k]);

  let fromTable = 0;
  for (const product of altertable.names()) {
    const e = altertable.get(product);
    recipes[product] = {
      via: 'alter',
      per: e.per,
      fromTable: true,
      variants: e.variants.map((v) => ({
        ingredients: Object.assign({}, v.ingredients),
        complete: true,
        facility: v.facility,
        level: v.level,
        sec: v.sec,
      })),
    };
    fromTable++;
  }

  cached = { recipes: recipes, seedCount: Object.keys(seed).length,
    userCount: Object.keys(mine).length, tableCount: fromTable };
  return cached;
}

function reload() { cached = null; return load(); }

/** 한 레시피의 { via, per, variants: [{ingredients, complete}] }. 모르면 null. */
function recipe(name) {
  if (!name) return null;
  return load().recipes[String(name)] || null;
}

/**
 * 지금 재고로 **가장 가까운 조합**을 고른다.
 *
 * 조합이 여럿이면 어느 것으로 만들지는 게임이 정한다 — execute_crafting 에 조합을
 * 지정하는 인자가 없다. 그래서 여기서 고르는 것은 "무엇을 모아야 하나"를 말하기 위한
 * 짐작이고, 모자란 양이 가장 적은 쪽을 고른다. 사람이 그쪽을 채우는 편이 빠르다.
 *
 * @param have {(name) => number} 보유량을 돌려주는 함수
 * @returns {{ingredients, complete, lack, count}} 또는 null
 */
function pick(name, have) {
  const e = recipe(name);
  if (!e || !Array.isArray(e.variants) || !e.variants.length) return null;

  const get = typeof have === 'function' ? have : () => 0;
  let best = null;
  for (const v of e.variants) {
    if (!v.ingredients || !Object.keys(v.ingredients).length) continue;
    // 개수가 null 인 재료는 "이름만 아는" 것이다 (재료 훑기로 알아낸 것).
    // 모자란 양을 셀 수 없으니 점수에서 빼고, 대신 개수를 아는 재료가 많은 쪽을 우선한다.
    let lack = 0, known = 0, unknown = 0;
    for (const k of Object.keys(v.ingredients)) {
      const need = v.ingredients[k];
      if (need === null || need === undefined) { unknown++; continue; }
      known++;
      lack += Math.max(0, need - (get(k) || 0));
    }
    const better = !best || known > best.known || (known === best.known && lack < best.lack);
    if (better) best = { ingredients: v.ingredients, complete: !!v.complete, lack: lack, known: known, unknown: unknown };
  }
  if (!best) return null;
  best.count = e.variants.length;
  best.per = e.per || 1;
  best.via = e.via || null;
  return best;
}

/* ── 수확 ──────────────────────────────────────────────────── */

/** a 가 b 의 부분집합이고, 겹치는 값이 전부 같은가. */
function fitsInto(a, b) {
  return Object.keys(a).every((k) => b[k] !== undefined && b[k] === a[k]);
}

/** 겹치는 재료의 요구량이 전부 같은가. 겹치는 것이 없으면 true. */
function compatible(a, b) {
  return Object.keys(a).every((k) => b[k] === undefined || b[k] === a[k]);
}

function shares(a, b) {
  return Object.keys(a).some((k) => b[k] !== undefined);
}

/**
 * 이번에 본 재료 줄들을 조합 목록에 합친다.
 *
 * ── 무엇이 어려운가 ────────────────────────────────────────
 * 게임은 "지금 모자란 것"만 준다. 그래서 두 번의 관측을 놓고 **같은 조합의 다른 조각인지,
 * 아예 다른 조합인지 구분할 방법이 원리적으로 없다.** 잘못 합치면 가짜 레시피가 만들어지고
 * (특수강괴도 은합금괴도 다 필요한 것처럼), 잘못 쪼개면 있지도 않은 조합이 늘어난다.
 *
 * ── 붙잡을 수 있는 사실 하나 ────────────────────────────────
 * **한 번의 조회 안에서는 줄 하나가 곧 조합 하나다.** 같은 이름이 두 줄로 오면 그것은
 * 확실히 서로 다른 갈래다. 이것만이 추측이 아닌 근거라, 여기서부터 규칙을 세운다.
 *
 *   · 이번 조회에 그 이름이 **한 줄뿐** → 갈래도 하나다. 본 것을 전부 합집합으로 쌓는다.
 *     감자만 모자랐다가 다음엔 소금만 모자라도 둘 다 같은 레시피의 재료다.
 *     (전체 1,841개 중 1,762개가 여기 해당한다)
 *
 *   · **여러 줄** → 줄마다 제 갈래를 가진다. 같은 조회에서 온 줄끼리는 **절대 합치지 않고**,
 *     예전에 쌓아 둔 갈래 중 요구량이 어긋나지 않으면서 가장 많이 겹치는 것 하나에만 붙인다.
 *     한 갈래는 한 줄에게만 간다 — 두 줄이 같은 갈래로 몰리면 그것이 곧 가짜 합치기다.
 */
function absorbGroup(list, sets, single) {
  let added = 0;

  if (single) {
    // 갈래가 하나다. 망설일 것 없이 합집합.
    const seen = sets[0];
    if (!list.length) { list.push({ ingredients: Object.assign({}, seen), complete: false }); return 1; }
    const fit = list.find((v) => compatible(seen, v.ingredients));
    if (fit) Object.assign(fit.ingredients, seen);
    else { list.push({ ingredients: Object.assign({}, seen), complete: false }); added++; }
    return added;
  }

  const used = new Set();
  for (const seen of sets) {
    let best = null, bestShare = 0;
    for (const v of list) {
      if (used.has(v)) continue;                              // 한 갈래는 한 줄에게만
      if (!compatible(seen, v.ingredients)) continue;         // 개수가 어긋나면 다른 갈래
      const share = Object.keys(seen).filter((k) => v.ingredients[k] !== undefined).length;
      if (share > bestShare) { best = v; bestShare = share; }
    }
    if (best && bestShare > 0) {
      used.add(best);
      Object.assign(best.ingredients, seen);
    } else {
      const fresh = { ingredients: Object.assign({}, seen), complete: false };
      list.push(fresh);
      used.add(fresh);
      added++;
    }
  }
  return added;
}

/**
 * 목록 한 벌을 표에 합친다. **더하기만 한다.**
 *
 * 재고를 채우고 다시 수확하면 그 재료가 목록에서 사라지는데, 그것을 "이제 안 든다"로
 * 읽으면 표가 망가진다. 잘못 들어간 값은 사람이 파일에서 지운다.
 */
function mergeRows(book, rows, via, okKey, perKey, known) {
  const stat = { rows: 0, named: 0, lines: 0, newNames: 0, newVariants: 0, completed: 0 };

  // 이름으로 묶는다. 같은 이름이 몇 줄로 왔는지가 합치는 규칙을 가른다.
  const byName = new Map();
  for (const r of rows) {
    if (!r.DisplayName) continue;
    if (!byName.has(r.DisplayName)) byName.set(r.DisplayName, []);
    byName.get(r.DisplayName).push(r);
  }

  for (const [name, group] of byName) {
    stat.rows += group.length;

    let e = book[name];
    if (!e) { e = book[name] = { via: via, per: group[0][perKey] || 1, variants: [] }; stat.newNames++; }
    e.via = via;
    if (group[0][perKey]) e.per = group[0][perKey];
    if (!Array.isArray(e.variants)) e.variants = [];

    const sets = [];
    for (const r of group) {
      const miss = Array.isArray(r.MissingIngredients) ? r.MissingIngredients : [];
      if (!miss.length) continue;
      const seen = {};
      for (const m of miss) if (m.DisplayName) { seen[m.DisplayName] = m.Required; stat.lines++; }
      if (Object.keys(seen).length) { sets.push(seen); stat.named++; }
    }
    if (sets.length) stat.newVariants += absorbGroup(e.variants, sets, group.length === 1);

    // 실제로 만들어 보고 알아낸 값이 있으면 그 조합은 완전하다고 표시한다.
    // 어느 조합으로 만들었는지는 게임이 정했으므로, 어긋나지 않는 조합에만 붙인다.
    const k = known && known[name];
    if (k && k.ingredients && (k.confidence === 'diff' || k.confidence === 'confirmed')) {
      const fit = e.variants.find((v) => compatible(v.ingredients, k.ingredients));
      if (fit) {
        fit.ingredients = Object.assign({}, k.ingredients);
        if (!fit.complete) { fit.complete = true; stat.completed++; }
      } else {
        e.variants.push({ ingredients: Object.assign({}, k.ingredients), complete: true });
        stat.completed++;
      }
    }
  }
  return stat;
}
/** 내 수확분을 저장한다. 배포 씨앗은 건드리지 않는다. */
function saveUser(recipes) {
  const out = {
    _설명: '이 계정에서 모은 레시피 표. 배포판의 recipe-book.json 보다 우선한다.',
    _수확시각: new Date().toISOString(),
    recipes: recipes,
  };
  try {
    fs.mkdirSync(path.dirname(USER_FILE), { recursive: true });
    fs.writeFileSync(USER_FILE, JSON.stringify(out, null, 2), 'utf8');
  } catch (_) { /* 저장 실패가 조회를 막지 않는다 */ }
  cached = null;
  return out;
}

function stats() {
  const b = load();
  const names = Object.keys(b.recipes);
  let withIng = 0, complete = 0, variants = 0;
  for (const n of names) {
    const vs = b.recipes[n].variants || [];
    variants += vs.length;
    if (vs.some((v) => Object.keys(v.ingredients || {}).length)) withIng++;
    if (vs.some((v) => v.complete)) complete++;
  }
  return { total: names.length, withIngredients: withIng, complete: complete,
    variants: variants, seed: b.seedCount, mine: b.userCount };
}

/**
 * 목록 한 벌을 보고, 새로 알게 된 것이 있으면 내 표에 담는다.
 *
 * 제작·가공 목록은 앱이 어차피 계속 불러온다. 그때마다 훑어 두면 **버튼을 누르지 않아도**
 * 표가 차오른다. 재고가 달라질수록 게임이 알려 주는 재료도 달라지므로, 그냥 게임을 하다
 * 보면 모이는 구조가 된다.
 *
 * 달라진 것이 없으면 파일을 쓰지 않는다 — 목록 조회마다 380KB를 다시 쓸 이유가 없다.
 *
 * @returns 새로 담은 것이 있으면 true
 */
function harvestRows(rows, via, okKey, perKey, known) {
  if (!Array.isArray(rows) || !rows.length) return false;
  // 깊은 복사여야 한다. 얕게 뜨면 mergeRows 가 캐시 안의 variants 를 그대로 건드려서,
  // 바뀐 것이 있어도 before 와 after 가 같은 객체를 가리켜 "변화 없음"으로 읽힌다.
  const recipes = JSON.parse(JSON.stringify(load().recipes));
  const before = JSON.stringify(recipes);
  mergeRows(recipes, rows, via, okKey, perKey, known);
  if (JSON.stringify(recipes) === before) return false;
  saveUser(recipes);
  return true;
}

module.exports = {
  load, reload, recipe, pick, stats,
  mergeRows, harvestRows, saveUser, fitsInto, compatible,
  SEED_FILE, USER_FILE,
};
