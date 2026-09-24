'use strict';
/**
 * "이걸 N개 만들려면 지금 무엇을 얼마나 해야 하나" — 사슬 끝까지.
 *
 * ── 기존 plan.js 와 무엇이 다른가 ──────────────────────────
 * plan.js 는 게임이 알려 준 **한 겹**을 본다. 재료가 또 가공품이면 거기서 멈춘다.
 * 게임이 재료의 재료를 알려주지 않기 때문이다.
 *
 * 이제 표(alter-recipes.json)가 있으니 **끝까지 펼 수 있다.** 그래서 이 파일은
 * "최상급 옷감 9개" 같은 목표를 받아 밖에서 구해 올 것까지 한 번에 내놓는다.
 *
 * ── 소지품을 층마다 뺀다 ───────────────────────────────────
 * 이게 핵심이다. 상급 옷감을 이미 들고 있으면 그것을 양털부터 다시 만들 이유가 없다.
 * 재고를 **주머니(pool)** 하나에 담아 두고, 필요할 때마다 거기서 먼저 꺼낸다.
 * 한 번 가공하면 목표보다 많이 나오는 경우가 흔한데(철괴는 한 번에 3개), 남는 것도
 * 주머니에 돌려 넣어 다음 단계가 쓰게 한다.
 *
 * ── 갈래가 여럿이면 실제로 재 보고 고른다 ──────────────────
 * 철괴는 광석 20 갈래와 철 광석 10 갈래가 있고, 어느 쪽이 싼지는 **지금 내 재고에**
 * **달렸다.** 그래서 후보마다 계획을 따로 세워 보고 채집 횟수가 적은 쪽을 고른다.
 *
 * ── 다만 고를 수 있는 것만 후보다 ──────────────────────────
 * 은합금괴·최상급 가죽/목재/옷감은 갈래가 둘인데 게임이 **같은 이름 하나로** 내놓는다.
 * 시켜 보니 언제나 **첫 줄(낮은 레벨 쪽)** 이 돈다 — 두 줄 다 실행 가능한 상태에서도
 * 그랬다. 그러니 다른 갈래로 계획을 세우면 실제와 어긋난다. 후보에서 뺀다.
 */
const altertable = require('./altertable');

const GATHER_PER_CALL = 100;   // 채집 한 번에 최대 100개 (get_gatherable_items 제약)

function toMap(owned) {
  const m = new Map();
  if (!owned) return m;
  if (owned instanceof Map) { for (const [k, v] of owned) m.set(k, v); return m; }
  for (const k of Object.keys(owned)) m.set(k, owned[k]);
  return m;
}

/**
 * 한 가지 갈래 선택안으로 계획을 끝까지 세운다.
 *
 * @param choice  { 산출물이름: 갈래번호 } — 미리 정해 둔 것만. 없으면 여기서 고른다.
 */
function run(target, count, ctx, choice) {
  const pool = toMap(ctx.owned);
  const levels = ctx.levels || {};
  const gatherable = ctx.gatherable || new Set();

  const steps = new Map();      // 산출물 → { runs, index }
  const short = new Map();      // 더 못 만드는 것 → 모자란 개수
  const blocked = [];           // 레벨이 모자라 못 돌리는 것
  const chosen = {};            // 이번 계획에서 고른 갈래

  // 너비 우선. 깊이 우선으로 하면 같은 재료를 여러 번 훑어 남는 것을 못 나눠 쓴다.
  const queue = [{ name: target, qty: count }];
  let guard = 0;

  while (queue.length) {
    if (++guard > 20000) break;            // 표가 이상해도 앱은 멈추지 않는다
    const { name, qty: want } = queue.shift();
    let qty = want;

    // 1) 주머니에서 먼저 꺼낸다
    const have = pool.get(name) || 0;
    if (have > 0) {
      const use = Math.min(have, qty);
      pool.set(name, have - use);
      qty -= use;
    }
    if (qty <= 0) continue;

    // 2) 가공으로 만들 수 있나
    const info = altertable.variantsFor(name, levels);
    if (!info) {
      short.set(name, (short.get(name) || 0) + qty);
      continue;
    }
    // 이름으로 못 가리는 갈래는 시켜도 첫 줄만 돈다. 그것만 후보로 둔다.
    const pick = altertable.selectable(name, ctx.recipeNames);

    let idx;
    if (choice && choice[name] !== undefined) {
      idx = choice[name];
    } else if (pick.length) {
      // 고를 수 있는 것 중 레벨이 되는 첫 번째
      const okOnes = pick.filter((i) => info.runnable.indexOf(i) >= 0);
      idx = okOnes.length ? okOnes[0] : pick[0];
    } else if (info.runnable.length) {
      idx = info.runnable[0];
    } else {
      // 레벨이 모자란다. 계산은 계속하되(무엇이 필요한지는 알려줘야 한다) 표시는 남긴다.
      idx = info.all[0];
      const v = info.entry.variants[idx];
      if (!blocked.some((b) => b.product === name)) {
        blocked.push({
          product: name, facility: v.facility,
          needLevel: v.level, haveLevel: levels[v.facility] == null ? null : levels[v.facility],
        });
      }
    }
    chosen[name] = idx;

    const v = info.entry.variants[idx];
    const per = info.entry.per || 1;
    const runs = Math.ceil(qty / per);

    const st = steps.get(name) || { product: name, index: idx, runs: 0 };
    st.runs += runs;
    st.index = idx;
    steps.set(name, st);

    // 3) 많이 나온 만큼은 주머니로 돌려 다음이 쓰게 한다
    const made = runs * per;
    if (made > qty) pool.set(name, (pool.get(name) || 0) + (made - qty));

    for (const [ing, cnt] of Object.entries(v.ingredients)) {
      queue.push({ name: ing, qty: cnt * runs });
    }
  }

  /* ── 채집으로 메울 것과 아예 못 구하는 것 ── */
  const gather = [], missing = [];
  for (const [name, need] of short) {
    const row = { name: name, need: need, have: ctx.ownedOf ? ctx.ownedOf(name) : (toMap(ctx.owned).get(name) || 0) };
    if (gatherable.has(name)) {
      gather.push(Object.assign(row, { calls: Math.ceil(need / GATHER_PER_CALL) }));
    } else {
      missing.push(row);
    }
  }
  gather.sort((a, b) => b.need - a.need);
  missing.sort((a, b) => b.need - a.need);

  return { steps, short, gather, missing, blocked, chosen, pool };
}

/** 깊은 것부터 — 재료를 먼저 만들고 그 다음 것을 만들도록 차례를 세운다. */
function order(steps) {
  const list = [...steps.values()];
  const rank = new Map();
  const depth = (name, seen) => {
    if (rank.has(name)) return rank.get(name);
    if (seen.has(name)) return 0;                  // 순환이면 멈춘다 (표에는 없지만 방어)
    const st = steps.get(name);
    if (!st) return 0;
    const e = altertable.get(name);
    const v = e && e.variants[st.index];
    let d = 0;
    for (const ing of Object.keys((v && v.ingredients) || {})) {
      if (steps.has(ing)) d = Math.max(d, depth(ing, new Set([...seen, name])) + 1);
    }
    rank.set(name, d);
    return d;
  };
  for (const st of list) depth(st.product, new Set());
  return list.sort((a, b) => (rank.get(a.product) || 0) - (rank.get(b.product) || 0));
}

/**
 * 목표 하나를 끝까지 계획한다.
 *
 * @param target     산출물 이름
 * @param count      새로 만들 개수
 * @param ctx        { owned, levels, gatherable, slots }
 *   owned      { 이름: 개수 } 또는 Map — 가방 + 창고 합계
 *   levels     { 시설이름: 레벨 }
 *   gatherable  Set — 채집으로 얻을 수 있는 이름
 *   slots       { 시설이름: 칸수 } — 있으면 병렬로 돌렸을 때의 시간도 낸다
 *   recipeNames Set — 게임이 실제로 쓰는 가공 레시피 이름. 괄호 이름을 지어내지 않으려고 쓴다.
 */
function plan(target, count, ctx) {
  const c = ctx || {};
  if (!altertable.has(target)) {
    return { ok: false, error: 'not_in_table', target: target };
  }
  if (!(count > 0)) return { ok: false, error: 'bad_count', target: target };

  /* 갈래가 여럿인 가공품만 골라 조합을 만들어 본다. 표에 넷뿐이라 값이 싸다. */
  const multi = altertable.names().filter((n) => {
    const e = altertable.get(n);
    return e.variants.length > 1;
  });

  // 먼저 한 번 돌려 어떤 갈래가 실제로 쓰이는지 본다
  const first = run(target, count, c, null);
  const used = multi.filter((n) => first.steps.has(n));

  let best = first;
  if (used.length && used.length <= 4) {
    const combos = [];
    const build = (i, acc) => {
      if (i === used.length) { combos.push(Object.assign({}, acc)); return; }
      const n = used[i];
      const info = altertable.variantsFor(n, c.levels);
      const sel = altertable.selectable(n, c.recipeNames);
      const ok = sel.filter((i) => info.runnable.indexOf(i) >= 0);
      const cand = ok.length ? ok : (sel.length ? sel : info.all);
      for (const idx of cand) { acc[n] = idx; build(i + 1, acc); }
      delete acc[n];
    };
    build(0, {});
    // 채집 횟수가 적은 쪽, 같으면 가공 횟수가 적은 쪽
    const cost = (r) => [
      r.gather.reduce((a, g) => a + g.calls, 0),
      r.missing.length ? 1e9 : 0,
      [...r.steps.values()].reduce((a, s) => a + s.runs, 0),
    ];
    for (const combo of combos.slice(0, 32)) {
      const r = run(target, count, c, combo);
      const A = cost(r), B = cost(best);
      if (A[1] < B[1] || (A[1] === B[1] && (A[0] < B[0] || (A[0] === B[0] && A[2] < B[2])))) best = r;
    }
  }

  /* ── 차례와 시간 ── */
  const list = order(best.steps).map((st) => {
    const e = altertable.get(st.product);
    const v = e.variants[st.index];
    const rn = altertable.recipeNameOf(st.product, st.index, c.recipeNames);
    return {
      product: st.product,
      recipe: rn.name,
      // 게임이 갈래를 같은 이름으로 내놓는 경우가 있다. 그때는 시켜도 어느 쪽이
      // 돌지 알 수 없으므로 화면에 그대로 알린다.
      ambiguous: rn.ambiguous,
      runs: st.runs,
      per: e.per,
      produced: st.runs * e.per,
      facility: v.facility,
      level: v.level,
      sec: v.sec,
      ingredients: v.ingredients,
    };
  });

  const serial = list.reduce((a, s) => a + (s.sec || 0) * s.runs, 0);

  // 시설마다 칸이 여러 개면 같이 돌릴 수 있다. 시설별로 나눠 칸 수로 나눈다 —
  // 단계 사이의 앞뒤 관계까지 따지지는 않으므로 **아래쪽 어림값**이다.
  let parallel = null;
  if (c.slots) {
    const byFac = new Map();
    for (const s of list) {
      byFac.set(s.facility, (byFac.get(s.facility) || 0) + (s.sec || 0) * s.runs);
    }
    parallel = 0;
    for (const [fac, sec] of byFac) {
      const n = Math.max(1, (c.slots[fac] || 1));
      parallel = Math.max(parallel, Math.ceil(sec / n));
    }
  }

  const facilities = {};
  for (const s of list) facilities[s.facility] = Math.max(facilities[s.facility] || 0, s.level || 0);

  return {
    ok: true,
    // 갈래를 이름으로 못 고르는 단계가 있으면 알려 준다
    ambiguous: list.filter((s) => s.ambiguous).map((s) => s.product),
    target: target,
    count: count,
    steps: list,
    totalRuns: list.reduce((a, s) => a + s.runs, 0),
    gather: best.gather,
    missing: best.missing,
    blocked: best.blocked,
    facilities: facilities,
    time: { serial: serial, parallel: parallel },
  };
}

module.exports = { plan, order, GATHER_PER_CALL };
