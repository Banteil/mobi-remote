'use strict';
/**
 * 제작 · 가공 목표 사전 점검.
 *
 * "이 아이템을 N개 새로 만들려면 무엇이 얼마나 필요한가"를 계산한다.
 * 쓰는 조회가 전부 무료라, 정령의 날개를 한 개도 쓰기 전에 판단할 수 있다.
 *
 * ── N은 보유량을 뺀 수가 아니다 ────────────────────────────
 * 처음에는 "N개까지 채운다"였다. 쓰다 보니 어긋났다. 못을 400개 들고 있는데 600개를
 * 더 만들려면 1000을 적어야 하고, 얼마를 갖고 있는지 먼저 확인해야 목표를 정할 수 있다.
 * 그래서 **적은 수만큼 새로 만든다**로 바꿨다. 보유량은 참고로만 보여 준다.
 *
 * ── 제작과 가공은 같은 모양이다 ─────────────────────────────
 * get_craftable_items 와 get_alterable_items 는 필드 이름만 다르고 구조가 같다.
 *   Craftable / ProducedPerCraft      ↔  Alterable / ProducedPerWork
 * 다른 점은 하나다. **가공은 레시피 이름이 산출물 이름이 아니다.**
 * "철괴(광석)"과 "철괴(철 광석)"은 둘 다 철괴를 만든다. 그래서 보유량을 셀 때는
 * 레시피 이름이 아니라 산출물 이름으로 세야 한다 — 레시피 이름으로는 언제나 0이 나온다.
 *
 * ── 알아야 할 제약 ──────────────────────────────────────────
 * get_craftable_items는 **제작 불가능한** 레시피에만 MissingIngredients를 붙인다.
 * 게다가 그 목록은 "가방 기준으로 모자란 재료"만 담는다 (실측: 재료 줄 2,501개 중
 * Owned >= Required 인 것이 0개. 달걀프라이가 달걀 없이 소금만 적어 온다).
 * 즉 전체 레시피를 볼 수 있는 방법이 없다.
 *
 * Required는 **1회 제작당** 소모량이다 (결과물 1개당이 아니다).
 * 실측 — 못 1회 제작: 철괴 2 소모, 못 10 산출(ProducedPerCraft 10).
 * 결과물 기준이라면 Required가 0.2여야 하는데 이 필드는 항상 정수다.
 * 그래서 총량은 Required × ceil(목표 / ProducedPerCraft) 로 계산한다.
 *
 * 그래서 두 가지 상황이 갈린다.
 *   · 지금 제작 불가 → 모자란 재료는 알 수 있다. Required(1회분) × 필요횟수로 총량 추정.
 *   · 지금 제작 가능 → 재료를 하나도 모른다. 해보는 수밖에 없다.
 */
const cache = require('./cache');
const richtext = require('./richtext');
const knowledge = require('./knowledge');
const needs = require('./needs');
const altertable = require('./altertable');
const facilitymap = require('./facilitymap');

/** 재료를 어떻게 구할 수 있는지 */
const SOURCE = {
  GATHER: '채집',
  ALTER: '가공',
  CRAFT: '제작',
  NONE: '자동불가',
};

function sumByName(rows, nameKey, countKey) {
  const m = new Map();
  for (const r of rows || []) {
    const n = r[nameKey];
    m.set(n, (m.get(n) || 0) + r[countKey]);
    const bare = richtext.strip(n);
    if (bare !== n) m.set(bare, (m.get(bare) || 0) + r[countKey]);
  }
  return m;
}

/**
 * 제작 목표 계획을 세운다.
 * @param displayName 레시피 이름 (게임 표기 그대로)
 * @param target 목표 보유 수량
 * @returns 계획 객체. error가 있으면 계산 실패.
 */
async function makePlan(displayName, target, opts) {
  const o = opts || {};
  const [craft, gather, alter, items] = await Promise.all([
    cache.get('get_craftable_items', o),
    cache.get('get_gatherable_items', o),
    cache.get('get_alterable_items', o),
    cache.get('get_items', o),
  ]);
  if (!craft.data) return { error: craft.error || 'no_data' };

  const recipes = craft.data.items || [];
  const alterRecipes = (alter.data && alter.data.items) || [];

  // 제작에서 먼저 찾고, 없으면 가공에서 찾는다. 이름이 겹치는 경우는 없었다.
  const find = (list) =>
    list.find((r) => r.DisplayName === displayName) ||
    list.find((r) => richtext.strip(r.DisplayName) === richtext.strip(displayName));

  let recipe = find(recipes);
  let kind = 'craft';
  if (!recipe) {
    recipe = find(alterRecipes);
    kind = 'alter';
  }

  // 채집은 레시피가 없다. "몇 번 부르면 되나"만 세면 끝이다.
  if (!recipe) {
    const g = find((gather.data && gather.data.items) || []);
    if (g) return gatherPlan(g, target, items, gather.cached);
  }
  if (!recipe) return { error: 'not_found', name: displayName };

  const isAlter = kind === 'alter';
  const okKey = isAlter ? 'Alterable' : 'Craftable';
  const perKey = isAlter ? 'ProducedPerWork' : 'ProducedPerCraft';
  // 가공만 레시피 이름과 산출물 이름이 다르다
  const product = isAlter ? knowledge.productOf(recipe.DisplayName) : recipe.DisplayName;

  const gatherable = new Set((gather.data && gather.data.items ? gather.data.items : []).map((x) => x.DisplayName));
  const alterable = new Set((alter.data && alter.data.items ? alter.data.items : []).map((x) => x.DisplayName));
  const craftable = new Set(recipes.map((x) => x.DisplayName));
  const owned = sumByName(Array.isArray(items.data) ? items.data : [], 'DisplayName', 'Count');

  const classify = (name) =>
    gatherable.has(name) ? SOURCE.GATHER
    : alterable.has(name) ? SOURCE.ALTER
    : craftable.has(name) ? SOURCE.CRAFT
    : SOURCE.NONE;

  const per = recipe[perKey] || 1;
  const have = owned.get(product) || owned.get(richtext.strip(product)) || 0;
  // target 은 "새로 만들 개수"다. 보유량은 빼지 않는다.
  const short = Math.max(0, target);
  const runs = Math.ceil(short / per);

  const base = {
    kind: kind,
    name: recipe.DisplayName,
    // 자동 진행은 레시피가 아니라 산출물을 기준으로 판단한다
    product: product,
    displayName: richtext.strip(recipe.DisplayName),
    productName: richtext.strip(product),
    target: target,
    have: have,
    producedPerCraft: per,
    runs: runs,
    craftableNow: !!recipe[okKey],
    reason: recipe.Reason || null,
    cached: craft.cached,
  };

  if (short === 0) return Object.assign(base, { done: true, ingredients: [], blockers: [] });

  /** { 이름: 1회분 소모량 } → 계획 항목으로 편다. */
  const expand = (per1, from) =>
    Object.keys(per1).map((name) => {
      const totalNeed = per1[name] * runs;
      const has = owned.get(name) || 0;
      return {
        name: name,
        displayName: richtext.strip(name),
        per: per1[name],
        total: totalNeed,
        have: has,
        lack: Math.max(0, totalNeed - has),
        source: classify(name),
        from: from,
      };
    });

  // 만들 수 있는 상태면 게임이 재료를 알려주지 않는다. 그때 기댈 곳이 둘이다 —
  // 전에 만들어 보고 알아낸 값, 그리고 레시피 장부(다른 시점에 게임이 알려 준 것을 모은 표).
  if (recipe[okKey]) {
    const got = knowledge.recipeIngredients(recipe.DisplayName, {
      have: (n) => owned.get(n) || 0,
    });
    if (got) {
      const ing = expand(got.ingredients, got.source);
      return Object.assign(base, {
        learnedRecipe: true,
        recipeSource: got.source,
        recipeComplete: got.complete,
        recipeVariants: got.variants,
        ingredients: ing,
        blockers: ing.filter((i) => i.lack > 0 && i.source === SOURCE.NONE),
        autoFixable: ing.filter((i) => i.lack > 0 && i.source !== SOURCE.NONE),
        ok: ing.every((i) => !(i.lack > 0 && i.source === SOURCE.NONE)),
        // 이름이 동적이라 조사를 붙이지 않는 문장으로 쓴다
        note:
          '게임은 지금 만들 수 있는 것의 재료를 알려주지 않습니다. ' +
          (got.source === 'observed'
            ? '이 숫자는 전에 이것을 만들어 봤을 때 알아낸 값입니다.'
            : '이 숫자는 레시피 표에서 가져왔습니다') +
          (got.source !== 'observed' && !got.complete
            ? ' — 재료가 더 있을 수 있습니다.'
            : got.source !== 'observed' ? '.' : '') +
          (got.variants > 1 ? ' 이 이름은 재료 조합이 ' + got.variants + '가지라, 지금 재고에 가까운 쪽을 보여 줍니다.' : ''),
      });
    }
    return Object.assign(base, {
      unknownIngredients: true,
      ingredients: [],
      blockers: [],
      note:
        '지금은 만들 수 있는 상태라 게임이 재료 목록을 주지 않습니다. ' +
        runs + '회분 재료가 되는지는 미리 알 수 없습니다. ' +
        '한 번 만들어 보면 재료를 알아내서, 다음부터는 미리 계산합니다.',
    });
  }

  // 게임이 준 부족분. 여기에 배워 둔 레시피가 있으면 빠진 재료까지 채워 넣는다.
  const per1 = {};
  for (const m of recipe.MissingIngredients || []) per1[m.DisplayName] = m.Required;
  const learned = knowledge.recipe(recipe.DisplayName);
  let filledIn = false;
  if (knowledge.recipeIsComplete(learned)) {
    for (const k of Object.keys(learned.ingredients)) {
      if (per1[k] === undefined) { per1[k] = learned.ingredients[k]; filledIn = true; }
    }
  }
  const ingredients = expand(per1, 'game');

  // 자동으로 구할 수 없으면서 실제로 모자란 것만 진짜 걸림돌이다
  const blockers = ingredients.filter((i) => i.lack > 0 && i.source === SOURCE.NONE);
  const autoFixable = ingredients.filter((i) => i.lack > 0 && i.source !== SOURCE.NONE);

  return Object.assign(base, {
    ingredients: ingredients,
    blockers: blockers,
    autoFixable: autoFixable,
    ok: blockers.length === 0,
    // 게임은 모자란 재료만 준다. 배워 둔 레시피로 나머지를 채웠다면 알려 준다.
    filledFromKnowledge: filledIn || undefined,
    recipeConfidence: filledIn ? learned.confidence : undefined,
  });
}

/**
 * 채집 목표.
 *
 * 재료도, 레시피도, 시설도 없다. 한 호출에 **최대 100개**가 들어오고 날개 5가 나간다.
 * 그래서 계획이라고 할 것은 "몇 번 부르면 되나" 하나뿐이다.
 *
 * 다만 100개는 상한이지 보장이 아니다. 실제로 몇 개가 들어올지는 해 봐야 알아서,
 * 여기 적히는 횟수는 **최소치**다. 자동 진행은 매번 남은 수량을 다시 세므로 모자라면
 * 알아서 더 부른다.
 */
const GATHER_PER_CALL = 100;

function gatherPlan(row, target, items, cached) {
  const owned = sumByName(Array.isArray(items.data) ? items.data : [], 'DisplayName', 'Count');
  const name = row.DisplayName;
  const have = owned.get(name) || owned.get(richtext.strip(name)) || 0;
  const short = Math.max(0, target);   // 새로 캘 개수

  return {
    kind: 'gather',
    gather: true,
    name: name,
    product: name,
    displayName: richtext.strip(name),
    productName: richtext.strip(name),
    target: target,
    have: have,
    producedPerCraft: GATHER_PER_CALL,
    runs: Math.ceil(short / GATHER_PER_CALL),
    craftableNow: !!row.ToolOk,
    toolOk: !!row.ToolOk,
    cached: cached,
    done: short === 0,
    ingredients: [],
    blockers: [],
    ok: !!row.ToolOk,
    note: row.ToolOk
      ? '한 번 부르면 최대 ' + GATHER_PER_CALL + '개까지 들어옵니다. 실제 수량은 해 봐야 알아서 ' +
        '아래 횟수는 최소치이며, 자동 진행이 남은 수량을 매번 다시 세어 모자라면 더 부릅니다.'
      : '도구가 없거나 망가져 지금은 채집할 수 없습니다. 도구를 갖춘 뒤 다시 계산하세요.',
  };
}

/**
 * 사슬 끝까지 세우는 계획.
 *
 * makePlan 은 게임이 알려 준 **한 겹**만 본다 — 게임이 재료의 재료를 알려주지 않기
 * 때문이다. 가공 재료표가 생긴 뒤로는 끝까지 펼 수 있고, 그래야 "그래서 무엇을 몇 번
 * 캐야 하는가"가 나온다.
 *
 * 여기서는 게임에서 사실만 모아 needs 에 넘긴다. 계산은 전부 needs 가 한다 —
 * 조회는 전부 무료라 날개를 한 개도 쓰지 않는다.
 */
async function deepPlan(target, count, opts) {
  const o = opts || {};
  if (!altertable.has(target)) return { ok: false, error: 'not_in_table', target: target };

  const [items, gather, alter] = await Promise.all([
    cache.get('get_items', o),
    cache.get('get_gatherable_items', o),
    cache.get('get_alterable_items', o),
  ]);

  // 가방 + 창고를 합친 보유량. 제작·가공은 창고 재고까지 재료로 쓴다.
  const owned = sumByName(Array.isArray(items.data) ? items.data : [], 'DisplayName', 'Count');

  const gatherable = new Set(((gather.data && gather.data.items) || []).map((x) => richtext.strip(x.DisplayName)));
  const recipeNames = new Set(((alter.data && alter.data.items) || []).map((x) => richtext.strip(x.DisplayName)));

  // 시설 레벨과 칸 수는 알아 둔 것에서 읽는다
  const levels = {}, slots = {};
  for (const fac of facilitymap.facilities()) {
    const s = knowledge.facilitySlots(fac);
    if (s && s.level) levels[fac] = s.level;
    if (s && s.slots) slots[fac] = s.slots;
  }

  const r = needs.plan(target, count, {
    owned: owned, levels: levels, gatherable: gatherable, slots: slots, recipeNames: recipeNames,
  });
  return Object.assign(r, { cached: items.cached && gather.cached && alter.cached });
}

module.exports = { makePlan, deepPlan, SOURCE };
