'use strict';
/**
 * 루틴 실행 엔진.
 *
 * 루틴은 단계 배열이다. 각 단계는 CLI 명령 하나를 부르거나 대기한다.
 * execute_gathering / execute_crafting / execute_altering은 1회당 정령의 날개 5를 쓰므로,
 * 실행 전에 총 비용을 계산해 확인을 받고, 잔량이 모자라면 시작하지 않는다.
 */
const fs = require('fs');
const path = require('path');
const connector = require('./connector');
const query = require('./query');
const cache = require('./cache');
const errors = require('./errors');

const ROUTINE_DIR = path.join(__dirname, '..', 'routines');

function listRoutines() {
  try {
    return fs
      .readdirSync(ROUTINE_DIR)
      .filter((f) => f.endsWith('.json'))
      .map((f) => {
        const r = loadRoutine(path.join(ROUTINE_DIR, f));
        return r ? Object.assign({ file: f, id: f.replace(/\.json$/, '') }, r) : null;
      })
      .filter(Boolean);
  } catch (_) {
    return [];
  }
}

function loadRoutine(fileOrId) {
  const p = path.isAbsolute(fileOrId)
    ? fileOrId
    : path.join(ROUTINE_DIR, fileOrId.endsWith('.json') ? fileOrId : fileOrId + '.json');
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (_) {
    return null;
  }
}

function saveRoutine(id, routine) {
  fs.mkdirSync(ROUTINE_DIR, { recursive: true });
  fs.writeFileSync(path.join(ROUTINE_DIR, id + '.json'), JSON.stringify(routine, null, 2), 'utf8');
}

/** 단계 배열을 (반복 포함) 실제 실행 단위로 펼친다. */
function expand(routine) {
  const out = [];
  for (const step of routine.steps || []) {
    const times = Math.max(1, step.repeat || 1);
    for (let i = 0; i < times; i++) {
      out.push(Object.assign({}, step, { iteration: i + 1, iterations: times }));
    }
  }
  return out;
}

/**
 * 총 소모 예상치. 비용은 CAPABILITIES에서 읽으므로 게임이 값을 바꿔도 따라간다.
 * 여러 재화가 섞이면 byCurrency에 나눠 담는다.
 */
function estimateCost(routine) {
  let calls = 0;
  let wings = 0;
  const byCurrency = {};
  for (const s of expand(routine)) {
    if (!s.command) continue;
    const c = connector.costOf(s.command);
    if (!c) continue;
    calls++;
    byCurrency[c.currency] = (byCurrency[c.currency] || 0) + c.amount;
    if (c.currency === '정령의 날개') wings += c.amount;
  }
  return { calls: calls, wings: wings, byCurrency: byCurrency };
}

/** 게임 상태를 바꾸는 단계가 하나라도 있는지. 조회 전용 루틴은 안전 점검을 건너뛴다. */
function hasActions(routine) {
  return (routine.steps || []).some((s) => s.command && connector.ACTION_COMMANDS.has(s.command));
}

function stepLabel(step) {
  if (step.label) {
    return step.iterations > 1 ? step.label + ' (' + step.iteration + '/' + step.iterations + ')' : step.label;
  }
  if (step.wait) return step.wait + 'ms 대기';
  return step.command || '알 수 없는 단계';
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * 사전 점검. 실행 가능하면 ok:true.
 * @returns {{ok, reasons: string[], wings, cost, activity}}
 */
async function preflight(routine, opts) {
  const o = opts || {};
  const reasons = [];

  const st = await connector.status();
  if (!st.connected) {
    reasons.push(
      st.reason === 'game_off'
        ? '게임 클라이언트가 실행되어 있지 않습니다.'
        : st.reason === 'option_off'
        ? '게임 설정에서 "MM AI 에이전트 활성화"가 꺼져 있습니다.'
        : '게임에 연결할 수 없습니다 (' + st.pipe + ').'
    );
    return { ok: false, reasons, wings: 0, cost: estimateCost(routine), activity: null };
  }

  const cost = estimateCost(routine);
  const w = await query.wings({ refresh: true });
  const wings = w.amount || 0;
  if (cost.wings > wings) {
    reasons.push('정령의 날개 부족: ' + cost.wings + ' 필요, ' + wings + ' 보유.');
  }

  const act = await query.activity();
  // 조회 전용 루틴은 캐릭터가 뭘 하고 있든 상관없다.
  if (hasActions(routine)) {
    if (!o.ignoreBusy && act.busy) {
      const what = [];
      if (act.autoPlaying) what.push('자동 진행 중');
      if (act.autoTraveling) what.push('자동 이동 중');
      if (act.inCombat) what.push('전투 중');
      if (act.performing) what.push('연주 중');
      if (act.dialogue) what.push('대화/선택 대기 중');
      reasons.push('캐릭터가 ' + what.join(', ') + '입니다. 먼저 정리해 주세요.');
    }
    if (act.dead) reasons.push('캐릭터가 사망 상태입니다.');
  }

  return { ok: reasons.length === 0, reasons, wings, cost, activity: act, hasActions: hasActions(routine) };
}

/**
 * 루틴을 실행한다.
 * @param routine 루틴 객체
 * @param opts {onEvent, dryRun, stopFlag}
 *   onEvent({type, ...}) - type: step:start | step:done | step:fail | step:skip | done
 *   stopFlag - {stopped: boolean} 외부에서 중단 신호를 준다
 * @returns {{steps, okCount, failCount, wingsSpent, durationMs, aborted}}
 */
async function run(routine, opts) {
  const o = opts || {};
  const emit = o.onEvent || (() => {});
  const steps = expand(routine);
  const results = [];
  const startedAt = Date.now();
  let wingsSpent = 0;
  let aborted = false;
  let current = null;

  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];

    if (o.stopFlag && o.stopFlag.stopped) {
      aborted = true;
      emit({ type: 'step:skip', index: i, total: steps.length, step, label: stepLabel(step), reason: '사용자 중단' });
      break;
    }

    const label = stepLabel(step);
    emit({ type: 'step:start', index: i, total: steps.length, step, label });

    // 대기 단계
    if (step.wait) {
      await sleep(step.wait);
      results.push({ label, ok: true, skipped: false });
      emit({ type: 'step:done', index: i, total: steps.length, step, label, result: null });
      continue;
    }

    if (!step.command) {
      results.push({ label, ok: false, error: 'no_command' });
      emit({ type: 'step:fail', index: i, total: steps.length, step, label, error: 'no_command' });
      continue;
    }

    // 무게 가드 - 채집/제작 전에 인벤토리가 꽉 찼는지 본다
    if (step.guard && step.guard.maxWeightPct) {
      const info = await query.me({ refresh: true });
      if (!info.error && info.weightPct >= step.guard.maxWeightPct) {
        results.push({ label, ok: false, skipped: true, error: 'overweight' });
        emit({
          type: 'step:skip',
          index: i,
          total: steps.length,
          step,
          label,
          reason: '무게 ' + info.weightPct + '% (한도 ' + step.guard.maxWeightPct + '%)',
        });
        if (step.stopOnError !== false) {
          aborted = true;
          break;
        }
        continue;
      }
    }

    if (o.dryRun) {
      results.push({ label, ok: true, dryRun: true });
      emit({ type: 'step:done', index: i, total: steps.length, step, label, result: { dryRun: true } });
      continue;
    }

    const cost = connector.costOf(step.command);
    const handle = connector.runCancelable(step.command, step.body, { timeoutMs: step.timeoutMs });
    current = handle;
    const r = await handle.promise;
    current = null;

    // 게임측이 받아들였으면 날개는 이미 소모됐다고 본다
    if (cost && r.ok) wingsSpent += cost.amount;

    // 조회 단계는 캐시를 갱신해 둔다 (뒤 단계가 최신값을 쓰도록)
    if (r.ok && step.command.startsWith('get_')) cache.write(step.command, r.data);

    if (r.ok) {
      results.push({ label, ok: true, data: r.data, durationMs: r.durationMs });
      emit({ type: 'step:done', index: i, total: steps.length, step, label, result: r });
    } else {
      const ko = errors.describe(step.command, r.error, r.message, r.data);
      results.push({ label, ok: false, error: r.error, message: r.message, ko });
      emit({ type: 'step:fail', index: i, total: steps.length, step, label, error: r.error, message: r.message, ko, result: r });
      if (step.stopOnError !== false) {
        aborted = true;
        break;
      }
    }

    if (step.delayAfter) await sleep(step.delayAfter);
  }

  const summary = {
    name: routine.name,
    steps: results,
    okCount: results.filter((r) => r.ok).length,
    failCount: results.filter((r) => !r.ok).length,
    wingsSpent,
    durationMs: Date.now() - startedAt,
    aborted,
  };
  emit({ type: 'done', summary });
  return summary;
}

/* ── 내장 루틴 생성기 ───────────────────────────────────────── */

/**
 * 채집 반복. execute_gathering은 1회 최대 100개까지만 모으고 끝나므로
 * 목표 수량에 맞춰 호출 횟수를 나눈다.
 */
function gatherRoutine(displayName, totalWanted, opts) {
  const o = opts || {};
  const calls = Math.max(1, Math.ceil(totalWanted / 100));
  return {
    name: displayName + ' 채집 x' + totalWanted,
    description: 'execute_gathering ' + calls + '회 (1회당 최대 100개)',
    steps: [
      {
        label: displayName + ' 채집',
        command: 'execute_gathering',
        body: { displayName: displayName },
        repeat: calls,
        guard: { maxWeightPct: o.maxWeightPct || 95 },
        stopOnError: o.continueOnError ? false : true,
        delayAfter: o.delayAfter || 1000,
      },
    ],
  };
}

/** 제작 대기열. 항목별로 execute_crafting을 순서대로 돌린다. */
function craftRoutine(entries, opts) {
  const o = opts || {};
  return {
    name: '제작 대기열 (' + entries.length + '건)',
    description: entries.map((e) => e.name + ' x' + e.count).join(', '),
    steps: entries.map((e) => ({
      label: e.name + ' 제작 x' + e.count,
      command: 'execute_crafting',
      body: { displayName: e.name, craftCount: e.count },
      guard: { maxWeightPct: o.maxWeightPct || 95 },
      stopOnError: o.continueOnError ? false : true,
      delayAfter: o.delayAfter || 1000,
    })),
  };
}

module.exports = {
  listRoutines,
  loadRoutine,
  saveRoutine,
  expand,
  estimateCost,
  preflight,
  run,
  stepLabel,
  hasActions,
  gatherRoutine,
  craftRoutine,
  ROUTINE_DIR,
};
