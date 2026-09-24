'use strict';
/**
 * 모비 커넥터 리모콘 - 마비노기 모바일 AI 커넥터 조작
 *
 * 인자 없이 실행하면 대화형 TUI, 인자를 주면 단발 명령으로 동작한다.
 * --json을 붙이면 조회 결과를 그대로 JSON으로 뱉으므로 스크립트/에이전트가 쓰기 좋다.
 */
const connector = require('./connector');
const query = require('./query');
const cache = require('./cache');
const routines = require('./routines');
const scheduler = require('./scheduler');
const ui = require('./ui');
const errors = require('./errors');

const c = ui.c;
const sym = ui.sym;

/* ── 인자 파싱 ──────────────────────────────────────────────── */

function parseArgs(argv) {
  const flags = {};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq > 0) flags[a.slice(2, eq)] = a.slice(eq + 1);
      else if (argv[i + 1] && !argv[i + 1].startsWith('-')) flags[a.slice(2)] = argv[++i];
      else flags[a.slice(2)] = true;
    } else positional.push(a);
  }
  return { flags, positional };
}

function out(data, flags) {
  if (flags.json) {
    process.stdout.write(JSON.stringify(data) + '\n');
    return true;
  }
  return false;
}

/* ── 공통 표시 ──────────────────────────────────────────────── */

async function connectionLine() {
  const st = await connector.status();
  if (st.connected) return c.green('● connected');
  const why =
    st.reason === 'game_off'
      ? '게임 미실행'
      : st.reason === 'option_off'
      ? 'AI 에이전트 옵션 꺼짐'
      : st.pipe;
  return c.red('● ' + why);
}

async function header() {
  const [conn, me, w] = await Promise.all([
    connectionLine(),
    query.me().catch(() => ({ error: true })),
    query.wings().catch(() => ({ amount: 0 })),
  ]);
  const lines = ['연결: ' + conn];
  if (!me.error) {
    // CLI는 캐릭터명을 주지 않는다. me.title은 착용 타이틀, me.realm은 서버다.
    lines.push('캐릭터: ' + c.bold('Lv.' + me.level + ' ' + me.job) + (me.title ? c.gray('  「' + me.title + '」') : ''));
    lines.push(
      '전투력 ' + ui.num(me.combat) + c.gray('  ·  ') + '생활력 ' + ui.num(me.living) +
      c.gray('  ·  ') + '무게 ' + me.weightPct + '%'
    );
  }
  lines.push('정령의 날개: ' + c.yellow(ui.num(w.amount)) + c.gray('  (실행 1회당 5)'));
  return ui.box('모비 커넥터 리모콘', lines, { width: 52 });
}

/** 루틴 실행 진행 상황을 화면에 흘린다. */
function attachProgress(stopFlag) {
  let spin = null;
  return (ev) => {
    if (ev.type === 'step:start') {
      spin = ui.spinner(c.gray('[' + (ev.index + 1) + '/' + ev.total + '] ') + ev.label + '...');
    } else if (ev.type === 'step:done') {
      const extra = summarizeResult(ev.step, ev.result);
      if (spin) spin.stop(c.gray('[' + (ev.index + 1) + '/' + ev.total + '] ') + sym.ok + ' ' + ev.label + (extra ? c.gray('  ' + extra) : ''));
      spin = null;
    } else if (ev.type === 'step:fail') {
      const ko = ev.ko;
      const why = ko ? c.red(ko.text) + (ko.hint ? c.gray(' — ' + ko.hint) : '') + c.gray('  [' + ev.error + ']')
                     : c.red(ev.error || '') + (ev.message ? c.gray(' — ' + ev.message) : '');
      if (spin) spin.stop(c.gray('[' + (ev.index + 1) + '/' + ev.total + '] ') + sym.fail + ' ' + ev.label + '  ' + why);
      spin = null;
    } else if (ev.type === 'step:skip') {
      if (spin) spin.stop(c.gray('[' + (ev.index + 1) + '/' + ev.total + '] ') + sym.warn + ' ' + ev.label + c.gray('  건너뜀 — ' + ev.reason));
      spin = null;
    }
  };
}

function summarizeResult(step, result) {
  if (!result || !result.data) return '';
  const d = result.data;
  if (step.command === 'execute_gathering') {
    if (d.result === 'started') return '자동 낚시 시작';
    if (d.gained !== undefined) return '획득 ' + d.gained + (d.target ? '/' + d.target : '');
  }
  if (step.command === 'execute_crafting' && d.craftCount) return d.craftCount + '회 제작';
  if (Array.isArray(d)) return d.length + '건';
  if (d.items) return d.items.length + '건';
  return '';
}

function printSummary(summary) {
  const secs = Math.round(summary.durationMs / 1000);
  const mins = Math.floor(secs / 60);
  const timeText = mins > 0 ? mins + '분 ' + (secs % 60) + '초' : secs + '초';
  console.log();
  console.log(
    '  ' +
      (summary.failCount === 0 && !summary.aborted ? sym.ok + ' ' + c.green('완료') : sym.warn + ' ' + c.yellow(summary.aborted ? '중단됨' : '일부 실패')) +
      c.gray('  성공 ' + summary.okCount + ' · 실패 ' + summary.failCount) +
      c.gray('  ·  날개 ' + summary.wingsSpent + ' 소모') +
      c.gray('  ·  ' + timeText)
  );
}

/** 사전 점검 결과를 보여주고, 비용 확인을 받는다. */
async function confirmAndRun(routine, opts) {
  const o = opts || {};
  const spin = ui.spinner('사전 점검 중...');
  const pre = await routines.preflight(routine, { ignoreBusy: o.ignoreBusy });
  spin.stop();

  console.log();
  console.log('  ' + c.bold(routine.name));
  if (routine.description) console.log('  ' + c.gray(routine.description));
  console.log(
    '  ' +
      c.gray('단계 ') + routines.expand(routine).length +
      c.gray('  ·  예상 소모 ') + c.yellow(pre.cost.wings + ' 날개') +
      c.gray(' (' + pre.cost.calls + '회)') +
      c.gray('  ·  보유 ') + ui.num(pre.wings)
  );

  if (!pre.ok) {
    console.log();
    for (const r of pre.reasons) console.log('  ' + sym.fail + ' ' + c.red(r));
    // 바쁜 상태만 문제라면 무시하고 진행할지 물어본다
    const onlyBusy = pre.reasons.every((r) => r.indexOf('캐릭터가') === 0);
    if (onlyBusy && !o.yes) {
      console.log();
      if (await ui.confirm('그래도 진행할까요?')) return confirmAndRun(routine, Object.assign({}, o, { ignoreBusy: true }));
    }
    return null;
  }

  if (!o.yes && !o.dryRun) {
    console.log();
    if (!(await ui.confirm('실행할까요?', true))) {
      console.log('  ' + c.gray('취소했습니다.'));
      return null;
    }
  }

  console.log();
  const stopFlag = { stopped: false };
  const onSigint = () => {
    stopFlag.stopped = true;
    console.log('\n  ' + c.yellow('중단 요청됨 — 현재 단계가 끝나면 멈춥니다.'));
  };
  process.on('SIGINT', onSigint);

  const summary = await routines.run(routine, {
    onEvent: attachProgress(stopFlag),
    dryRun: o.dryRun,
    stopFlag: stopFlag,
  });

  process.removeListener('SIGINT', onSigint);
  printSummary(summary);
  return summary;
}

/* ── TUI 화면들 ─────────────────────────────────────────────── */

async function screenRoutine() {
  const list = routines.listRoutines();
  if (!list.length) {
    console.log('  ' + c.gray('routines/ 폴더에 루틴이 없습니다.'));
    return;
  }
  const pick = await ui.menu(
    list.map((r) => ({
      key: r.id,
      label: r.name,
      hint: routines.estimateCost(r).wings + ' 날개 · ' + routines.expand(r).length + '단계',
      routine: r,
    })),
    { title: '실행할 루틴' }
  );
  if (!pick) return;
  await confirmAndRun(pick.routine);
  await ui.prompt(c.gray('Enter로 돌아가기'));
}

async function screenGather() {
  const name = await ui.prompt('채집할 아이템 이름?');
  if (!name) return;

  const spin = ui.spinner('채집 가능 목록 확인 중...');
  const g = await query.gather({ search: name });
  spin.stop();

  if (g.error) {
    console.log('  ' + sym.fail + ' ' + c.red(errors.line(null, g.error, g.message)) + c.gray('  [' + g.error + ']'));
    return;
  }
  if (!g.matched) {
    console.log('  ' + sym.fail + ' ' + c.red('"' + name + '"과(와) 일치하는 채집 가능 아이템이 없습니다.'));
    console.log('  ' + c.gray('생활 스킬 레벨이 모자라면 목록에 나오지 않습니다.'));
    return;
  }

  let target = g.items[0];
  if (g.matched > 1) {
    const pick = await ui.menu(
      g.items.slice(0, 9).map((i) => ({
        key: i.name,
        label: i.name,
        hint: i.tool ? c.green('도구 보유') : c.red('도구 없음'),
        item: i,
      })),
      { title: '어느 것을 채집할까요?' }
    );
    if (!pick) return;
    target = pick.item;
  }

  if (!target.tool) {
    console.log('  ' + sym.warn + ' ' + c.yellow(target.name + ' 채집 도구가 없거나 망가졌습니다.'));
    if (!(await ui.confirm('그래도 시도할까요?'))) return;
  }

  const countText = await ui.prompt('몇 개 모을까요?', '100');
  const count = parseInt(countText, 10);
  if (!count || count < 1) {
    console.log('  ' + c.gray('취소했습니다.'));
    return;
  }

  const routine = routines.gatherRoutine(target.name, count);
  await confirmAndRun(routine);
  await ui.prompt(c.gray('Enter로 돌아가기'));
}

async function screenCraft() {
  const entries = [];
  for (;;) {
    const name = await ui.prompt(
      entries.length ? '추가할 제작 항목 (빈 줄이면 실행)' : '제작할 아이템 이름?'
    );
    if (!name) break;

    const spin = ui.spinner('레시피 확인 중...');
    const r = await query.craftFind(name);
    spin.stop();

    if (r.error) {
      console.log('  ' + sym.fail + ' ' + c.red(errors.line(null, r.error, r.message)) + c.gray('  [' + r.error + ']'));
      continue;
    }
    if (!r.matched) {
      console.log('  ' + sym.fail + ' ' + c.red('"' + name + '" 레시피를 찾을 수 없습니다.'));
      continue;
    }

    let target = r.items[0];
    if (r.matched > 1) {
      const pick = await ui.menu(
        r.items.slice(0, 9).map((i) => ({
          key: i.name,
          label: i.name,
          hint: i.ok ? c.green('제작 가능') + c.gray(' ·' + i.per + '개') : c.red(i.reason || '불가'),
          item: i,
        })),
        { title: '어느 레시피?' }
      );
      if (!pick) continue;
      target = pick.item;
    }

    if (!target.ok) {
      console.log('  ' + sym.fail + ' ' + c.red(target.name + ' — ' + (target.reason || '제작 불가')));
      if (target.missing && target.missing.length) {
        console.log('  ' + c.gray('부족: ' + target.missing.join(', ')));
      }
      continue;
    }

    const countText = await ui.prompt(target.name + ' 제작 횟수? ' + c.gray('(1회당 ' + target.per + '개)'), '1');
    const count = parseInt(countText, 10) || 1;
    entries.push({ name: target.name, count: count });
    console.log('  ' + sym.ok + ' 대기열에 추가: ' + target.name + ' x' + count);
  }

  if (!entries.length) return;
  const routine = routines.craftRoutine(entries);
  await confirmAndRun(routine);
  await ui.prompt(c.gray('Enter로 돌아가기'));
}

async function screenQuery() {
  for (;;) {
    const pick = await ui.menu(
      [
        { key: 'me', label: '캐릭터 정보' },
        { key: 'daily', label: '일일 미션' },
        { key: 'weekly', label: '주간 미션' },
        { key: 'craft', label: '제작 레시피 검색' },
        { key: 'gatherq', label: '채집 가능 목록' },
        { key: 'items', label: '소지품 검색' },
        { key: 'wings', label: '재화' },
        { key: 'activity', label: '현재 활동 상태' },
        { key: 'back', label: c.gray('← 뒤로') },
      ],
      { title: '조회' }
    );
    if (!pick || pick.key === 'back') return;

    console.log();
    const spin = ui.spinner('조회 중...');

    if (pick.key === 'me') {
      const m = await query.me({ refresh: true });
      spin.stop();
      console.log(
        ui.box('Lv.' + m.level + ' ' + m.job, [
          '타이틀 ' + (m.title || '(없음)') + '  ·  서버 ' + m.realm,
          '전투력 ' + ui.num(m.combat) + '   생활력 ' + ui.num(m.living),
          'HP ' + m.hp + '   포만도 ' + m.satiety,
          '무게 ' + m.weight + ' (' + m.weightPct + '%)   버프 ' + m.buffs,
        ])
      );
    } else if (pick.key === 'daily' || pick.key === 'weekly') {
      const d = await (pick.key === 'daily' ? query.daily({ refresh: true }) : query.weekly({ refresh: true }));
      spin.stop();
      console.log('  ' + c.bold(pick.key === 'daily' ? '일일 미션' : '주간 미션') + c.gray('  미완료 ' + d.open + '/' + d.total));
      console.log(
        ui.table(d.items, [
          { label: '', get: (r) => (r.done ? (r.claimed ? sym.ok : c.yellow('◆')) : ' '), max: 2 },
          { label: '미션', get: (r) => r.title, max: 24 },
          { label: '내용', get: (r) => r.desc, max: 26 },
          { label: '진행', get: (r) => r.progress, right: true, max: 8 },
        ])
      );
      console.log('  ' + c.gray(sym.ok + ' 완료+수령  ') + c.yellow('◆') + c.gray(' 완료(수령 대기)'));
    } else if (pick.key === 'craft') {
      spin.stop();
      const name = await ui.prompt('검색어?');
      if (!name) continue;
      const s2 = ui.spinner('검색 중...');
      const r = await query.craftFind(name);
      s2.stop();
      console.log('  ' + c.gray('전체 ' + r.total + '종 중 제작 가능 ' + r.craftable + '종 · 검색 결과 ' + r.matched + '건'));
      console.log(
        ui.table(r.items, [
          { label: '', get: (r2) => (r2.ok ? sym.ok : sym.fail), max: 2 },
          { label: '이름', get: (r2) => r2.name, max: 28 },
          { label: '산출', get: (r2) => r2.per, right: true, max: 4 },
          { label: '비고', get: (r2) => (r2.ok ? '' : (r2.missing || []).slice(0, 2).join(', ') || r2.reason), max: 40 },
        ])
      );
    } else if (pick.key === 'gatherq') {
      const g = await query.gather({ onlyOk: true });
      spin.stop();
      console.log('  ' + c.gray('채집 가능 ' + g.toolOk + '/' + g.total + '종'));
      const names = g.items.map((i) => i.name);
      for (let i = 0; i < names.length; i += 4) {
        console.log('  ' + names.slice(i, i + 4).map((n) => ui.padEnd(n, 18)).join(''));
      }
    } else if (pick.key === 'items') {
      spin.stop();
      const name = await ui.prompt('검색어?');
      if (!name) continue;
      const s2 = ui.spinner('검색 중...');
      const r = await query.items({ search: name, limit: 30 });
      s2.stop();
      console.log('  ' + c.gray(r.matched + '건'));
      console.log(
        ui.table(r.items, [
          { label: '이름', get: (x) => x.name, max: 30 },
          { label: '분류', get: (x) => x.category, max: 14 },
          { label: '수량', get: (x) => ui.num(x.total), right: true, max: 10 },
          { label: '위치', get: (x) => Object.keys(x.where).map((k) => k + ' ' + x.where[k]).join(', '), max: 30 },
        ])
      );
    } else if (pick.key === 'wings') {
      const r = await query.currencies({ nonZero: true, refresh: true });
      spin.stop();
      console.log(
        ui.table(r.items, [
          { label: '재화', get: (x) => x.name, max: 34 },
          { label: '보유', get: (x) => ui.num(x.amount), right: true, max: 12 },
        ])
      );
    } else if (pick.key === 'activity') {
      const a = await query.activity();
      spin.stop();
      const on = (b) => (b ? c.green('예') : c.gray('아니오'));
      console.log(
        ui.box('현재 활동', [
          '자동 진행 ' + on(a.autoPlaying) + '   자동 이동 ' + on(a.autoTraveling),
          '전투 중 ' + on(a.inCombat) + '   사망 ' + on(a.dead),
          '연주 중 ' + on(a.performing) + '   앉음 ' + on(a.sitting),
          '대화/선택 대기 ' + on(a.dialogue),
          '던전 ' + (a.dungeon || '-') + '   메인버튼 ' + (a.mainButton || '-'),
          null,
          a.busy ? c.yellow('바쁨 — 루틴 실행 전 정리 필요') : c.green('대기 상태 — 루틴 실행 가능'),
        ])
      );
    }

    console.log();
    await ui.prompt(c.gray('Enter로 돌아가기'));
    ui.clear();
  }
}

async function screenSchedule() {
  for (;;) {
    const state = scheduler.load();
    const lines = state.entries.length
      ? state.entries.map(
          (e) =>
            (e.enabled ? sym.ok : c.gray('○')) + ' ' + ui.padEnd(e.routine, 16) + c.gray(scheduler.describe(e)) + c.gray('  ' + e.id)
        )
      : [c.gray('(등록된 스케줄 없음)')];
    console.log(ui.box('스케줄', lines, { width: 52 }));
    console.log();

    const pick = await ui.menu(
      [
        { key: 'add', label: '스케줄 추가' },
        { key: 'toggle', label: '켜기/끄기', disabled: !state.entries.length },
        { key: 'remove', label: '삭제', disabled: !state.entries.length },
        { key: 'daemon', label: '상주 모드 시작', hint: '창을 열어둔 동안 감시' },
        { key: 'task', label: 'Windows 작업 스케줄러에 등록', disabled: !state.entries.length },
        { key: 'back', label: c.gray('← 뒤로') },
      ],
      { title: '스케줄 관리' }
    );
    if (!pick || pick.key === 'back') return;

    if (pick.key === 'add') {
      const list = routines.listRoutines();
      if (!list.length) {
        console.log('  ' + c.gray('먼저 routines/ 에 루틴이 있어야 합니다.'));
        continue;
      }
      const rp = await ui.menu(list.map((r) => ({ key: r.id, label: r.name, hint: r.id })), { title: '어떤 루틴을?' });
      if (!rp) continue;
      const time = await ui.prompt('실행 시각 (HH:MM)?', '06:00');
      if (!/^\d{2}:\d{2}$/.test(time)) {
        console.log('  ' + c.red('시각 형식이 올바르지 않습니다.'));
        continue;
      }
      const everyDay = await ui.confirm('매일 실행할까요?', true);
      let days = scheduler.DAYS.slice();
      if (!everyDay) {
        const input = await ui.prompt('요일 (예: mon,wed,fri)', 'mon,wed,fri');
        days = input.split(',').map((s) => s.trim().toLowerCase()).filter((d) => scheduler.DAYS.indexOf(d) >= 0);
        if (!days.length) days = scheduler.DAYS.slice();
      }
      const rec = scheduler.add({ routine: rp.key, time: time, days: days });
      console.log('  ' + sym.ok + ' 추가됨: ' + rec.routine + ' ' + scheduler.describe(rec));
    } else if (pick.key === 'toggle' || pick.key === 'remove') {
      const ep = await ui.menu(
        state.entries.map((e) => ({ key: e.id, label: e.routine + ' ' + scheduler.describe(e), hint: e.enabled ? '켜짐' : '꺼짐' })),
        { title: pick.key === 'toggle' ? '켜기/끄기' : '삭제할 항목' }
      );
      if (!ep) continue;
      if (pick.key === 'toggle') {
        const e = state.entries.find((x) => x.id === ep.key);
        scheduler.setEnabled(ep.key, !e.enabled);
        console.log('  ' + sym.ok + ' ' + (!e.enabled ? '켰습니다.' : '껐습니다.'));
      } else {
        scheduler.remove(ep.key);
        console.log('  ' + sym.ok + ' 삭제했습니다.');
      }
    } else if (pick.key === 'daemon') {
      await runDaemon();
      return;
    } else if (pick.key === 'task') {
      const ep = await ui.menu(
        state.entries.map((e) => ({ key: e.id, label: e.routine + ' ' + scheduler.describe(e), entry: e })),
        { title: '등록할 항목' }
      );
      if (!ep) continue;
      console.log();
      console.log('  ' + c.gray('다음 명령으로 Windows 작업을 등록합니다:'));
      console.log('  ' + c.cyan(scheduler.taskCommandPreview(ep.entry)));
      console.log();
      console.log('  ' + c.yellow(sym.warn + ' 시스템에 예약 작업이 생깁니다. 게임이 꺼져 있으면 사전 점검에서 멈춥니다.'));
      if (!(await ui.confirm('등록할까요?'))) continue;
      const r = scheduler.registerTask(ep.entry);
      console.log('  ' + (r.ok ? sym.ok + ' 등록 완료' : sym.fail + ' 실패 (' + r.code + ')'));
      if (r.output.trim()) console.log('  ' + c.gray(r.output.trim()));
    }

    console.log();
    await ui.prompt(c.gray('Enter로 돌아가기'));
    ui.clear();
  }
}

async function runDaemon() {
  ui.clear();
  console.log(await header());
  console.log();
  const state = scheduler.load();
  const active = state.entries.filter((e) => e.enabled);
  console.log('  ' + c.bold('상주 모드') + c.gray('  활성 스케줄 ' + active.length + '개 · Ctrl+C로 종료'));
  for (const e of active) console.log('  ' + sym.dot + ' ' + e.routine + ' ' + c.gray(scheduler.describe(e)));
  console.log();

  const spin = ui.spinner('대기 중...');
  const d = scheduler.startDaemon({
    onTick: (now) => spin.update('대기 중  ' + c.gray(now.toLocaleTimeString('ko-KR'))),
    onRun: (entry) => {
      spin.stop(sym.info + ' ' + entry.routine + ' 실행 시작 ' + c.gray(new Date().toLocaleTimeString('ko-KR')));
    },
    runner: async (routine) => {
      const summary = await routines.run(routine, { onEvent: attachProgress({}) });
      printSummary(summary);
      console.log();
      return summary;
    },
  });

  await new Promise((resolve) => {
    process.on('SIGINT', () => {
      d.stop();
      spin.stop(c.gray('상주 모드를 종료했습니다.'));
      resolve();
    });
  });
}

async function screenMaintenance() {
  const entries = cache.list();
  const lines = entries.length
    ? entries.map((e) => ui.padEnd(e.command, 24) + ui.padStart(e.sizeKB + 'KB', 8) + c.gray('  ' + e.ageSec + '초 전'))
    : [c.gray('(캐시 없음)')];
  console.log(ui.box('캐시', lines, { width: 52 }));
  console.log();

  const pick = await ui.menu(
    [
      { key: 'clear', label: '캐시 전체 삭제' },
      { key: 'caps', label: '명령 목록(CAPABILITIES) 갱신' },
      { key: 'back', label: c.gray('← 뒤로') },
    ],
    { title: '유지보수' }
  );
  if (!pick || pick.key === 'back') return;

  if (pick.key === 'clear') {
    cache.clear();
    console.log('  ' + sym.ok + ' 삭제했습니다.');
  } else if (pick.key === 'caps') {
    const spin = ui.spinner('갱신 중...');
    const cmds = await connector.refreshCapabilities();
    spin.stop(sym.ok + ' 명령 ' + cmds.length + '개');
  }
  console.log();
  await ui.prompt(c.gray('Enter로 돌아가기'));
}

/* ── TUI 메인 루프 ──────────────────────────────────────────── */

async function tui() {
  for (;;) {
    ui.clear();
    console.log(await header());
    console.log();

    const pick = await ui.menu(
      [
        { key: 'routine', label: '루틴 실행', hint: '저장된 다단계 작업' },
        { key: 'gather', label: '채집 반복', hint: '목표 수량까지' },
        { key: 'craft', label: '제작 대기열', hint: '여러 건 연속 제작' },
        { key: 'query', label: '조회', hint: '캐릭터 · 미션 · 레시피 · 소지품' },
        { key: 'schedule', label: '스케줄', hint: '시간 맞춰 자동 실행' },
        { key: 'maint', label: '캐시 / 유지보수' },
        { key: 'quit', label: c.gray('종료') },
      ],
      { title: '무엇을 할까요?' }
    );

    if (!pick || pick.key === 'quit') {
      console.log('  ' + c.gray('종료합니다.'));
      return;
    }

    ui.clear();
    if (pick.key === 'routine') await screenRoutine();
    else if (pick.key === 'gather') await screenGather();
    else if (pick.key === 'craft') await screenCraft();
    else if (pick.key === 'query') await screenQuery();
    else if (pick.key === 'schedule') await screenSchedule();
    else if (pick.key === 'maint') await screenMaintenance();
  }
}

/* ── 비대화형 명령 ──────────────────────────────────────────── */

const HELP = [
  '',
  '  ' + c.bold('모비 커넥터 리모콘') + c.gray(' — mobi-remote'),
  '',
  '  ' + c.bold('대화형'),
  '    mobi-remote                          TUI 실행',
  '',
  '  ' + c.bold('조회') + c.gray('  (--json 을 붙이면 JSON 출력)'),
  '    mobi-remote status                   연결 상태',
  '    mobi-remote me                       캐릭터 요약',
  '    mobi-remote wings                    정령의 날개 잔량',
  '    mobi-remote activity                 현재 활동 상태',
  '    mobi-remote daily [--open]           일일 미션',
  '    mobi-remote weekly [--open]          주간 미션',
  '    mobi-remote craft <검색어>            제작 레시피 검색 (부족 재료 포함)',
  '    mobi-remote craft --list [--ok]      전체/제작가능 목록',
  '    mobi-remote gather --list [--ok]     채집 가능 목록',
  '    mobi-remote alter <검색어>            가공 레시피',
  '    mobi-remote items <검색어>            소지품 검색',
  '    mobi-remote currencies [--non-zero]  재화',
  '',
  '  ' + c.bold('실행') + c.gray('  (execute_* 1회당 정령의 날개 5 소모)'),
  '    mobi-remote run <루틴id> [--yes] [--dry-run]',
  '    mobi-remote do-gather <이름> <수량> [--yes]',
  '    mobi-remote do-craft <이름> <횟수> [--yes]',
  '    mobi-remote routines                 루틴 목록',
  '',
  '  ' + c.bold('스케줄'),
  '    mobi-remote schedule list',
  '    mobi-remote schedule run             상주 모드',
  '',
  '  ' + c.bold('유지보수'),
  '    mobi-remote cache list | cache clear',
  '    mobi-remote capabilities             명령 목록 갱신',
  '    mobi-remote compat                   버전 · 호환성 검사',
  '    mobi-remote compat accept            현재 상태를 기준선으로 저장',
  '',
  '  ' + c.gray('공통 플래그: --json  --refresh  --limit N  --yes  --dry-run'),
  '',
].join('\n');

async function cli(argv) {
  const { flags, positional } = parseArgs(argv);
  const cmd = positional[0];
  const arg1 = positional[1];
  const arg2 = positional[2];
  const qopts = { refresh: !!flags.refresh, limit: flags.limit ? parseInt(flags.limit, 10) : undefined };

  if (!cmd || cmd === 'help' || flags.help) {
    console.log(HELP);
    return 0;
  }

  /* 조회 */
  if (cmd === 'status') {
    const st = await connector.status();
    if (out(st, flags)) return st.connected ? 0 : 1;
    console.log('  ' + (await connectionLine()));
    return st.connected ? 0 : 1;
  }
  if (cmd === 'me') {
    const m = await query.me(qopts);
    if (out(m, flags)) return 0;
    console.log('  Lv.' + m.level + ' ' + m.job + (m.title ? ' 「' + m.title + '」' : '') + '  전투력 ' + ui.num(m.combat) + '  생활력 ' + ui.num(m.living) + '  무게 ' + m.weightPct + '%  포만도 ' + m.satiety);
    return 0;
  }
  if (cmd === 'wings') {
    const w = await query.wings(qopts);
    if (out(w, flags)) return 0;
    console.log('  정령의 날개 ' + ui.num(w.amount) + c.gray('  (실행 ' + Math.floor(w.amount / 5) + '회분)'));
    return 0;
  }
  if (cmd === 'activity') {
    const a = await query.activity();
    if (out(a, flags)) return 0;
    console.log('  ' + (a.busy ? c.yellow('바쁨') : c.green('대기')) + c.gray('  ' + JSON.stringify(a)));
    return 0;
  }
  if (cmd === 'daily' || cmd === 'weekly') {
    const d = await (cmd === 'daily' ? query.daily(Object.assign({ onlyOpen: !!flags.open }, qopts)) : query.weekly(Object.assign({ onlyOpen: !!flags.open }, qopts)));
    if (out(d, flags)) return 0;
    console.log('  미완료 ' + d.open + '/' + d.total);
    for (const m of d.items) {
      console.log(
        '  ' + (m.done ? (m.claimed ? sym.ok : c.yellow('◆')) : ' ') + ' ' +
        ui.padEnd(ui.truncate(m.title, 24), 24) +
        ui.padEnd(ui.truncate(m.desc, 26), 26) +
        ui.padStart(m.progress, 8)
      );
    }
    return 0;
  }
  if (cmd === 'craft') {
    const r = flags.list || !arg1 ? await query.craft(Object.assign({ onlyOk: !!flags.ok }, qopts)) : await query.craftFind(arg1, qopts);
    if (out(r, flags)) return 0;
    console.log('  ' + c.gray('전체 ' + r.total + ' · 제작가능 ' + r.craftable + ' · 결과 ' + r.matched + (r.cached ? ' · 캐시' : '')));
    for (const i of r.items.slice(0, qopts.limit || 40)) {
      console.log('  ' + (i.ok ? sym.ok : sym.fail) + ' ' + ui.padEnd(i.name, 30) + c.gray('x' + i.per) + (i.missing && i.missing.length ? c.gray('  부족: ' + i.missing.slice(0, 3).join(', ')) : i.ok ? '' : c.gray('  ' + (i.reason || ''))));
    }
    return 0;
  }
  if (cmd === 'alter') {
    const r = await query.alter(Object.assign({ search: arg1, onlyOk: !!flags.ok }, qopts));
    if (out(r, flags)) return 0;
    console.log('  ' + c.gray('전체 ' + r.total + ' · 가능 ' + r.alterable + ' · 결과 ' + r.matched));
    for (const i of r.items.slice(0, qopts.limit || 40)) console.log('  ' + (i.ok ? sym.ok : sym.fail) + ' ' + ui.padEnd(i.name, 30) + c.gray('x' + i.per));
    return 0;
  }
  if (cmd === 'gather') {
    const r = await query.gather(Object.assign({ search: flags.list ? undefined : arg1, onlyOk: !!flags.ok }, qopts));
    if (out(r, flags)) return 0;
    console.log('  ' + c.gray('전체 ' + r.total + ' · 도구보유 ' + r.toolOk + ' · 결과 ' + r.matched));
    for (const i of r.items.slice(0, qopts.limit || 60)) console.log('  ' + (i.tool ? sym.ok : sym.fail) + ' ' + i.name);
    return 0;
  }
  if (cmd === 'items') {
    const r = arg1 && !flags.list ? await query.items(Object.assign({ search: arg1 }, qopts)) : await query.items(qopts);
    if (out(r, flags)) return 0;
    console.log('  ' + c.gray(r.matched + '건'));
    for (const i of r.items.slice(0, qopts.limit || 40)) {
      console.log('  ' + ui.padEnd(i.name, 30) + ui.padStart(ui.num(i.total), 8) + c.gray('  ' + Object.keys(i.where).map((k) => k + ' ' + i.where[k]).join(', ')));
    }
    return 0;
  }
  if (cmd === 'currencies') {
    const r = await query.currencies(Object.assign({ search: arg1, nonZero: !!flags['non-zero'] }, qopts));
    if (out(r, flags)) return 0;
    for (const i of r.items) console.log('  ' + ui.padEnd(i.name, 34) + ui.padStart(ui.num(i.amount), 12));
    return 0;
  }

  /* 실행 */
  if (cmd === 'routines') {
    const list = routines.listRoutines();
    if (out(list.map((r) => ({ id: r.id, name: r.name, steps: routines.expand(r).length, wings: routines.estimateCost(r).wings })), flags)) return 0;
    for (const r of list) console.log('  ' + ui.padEnd(r.id, 16) + ui.padEnd(r.name, 28) + c.gray(routines.expand(r).length + '단계 · ' + routines.estimateCost(r).wings + ' 날개'));
    return 0;
  }
  if (cmd === 'run') {
    const routine = routines.loadRoutine(arg1 || '');
    if (!routine) {
      console.error('  ' + c.red('루틴을 찾을 수 없습니다: ' + arg1));
      return 1;
    }
    const s = await confirmAndRun(routine, { yes: !!flags.yes, dryRun: !!flags['dry-run'] });
    return s && s.failCount === 0 && !s.aborted ? 0 : 1;
  }
  if (cmd === 'do-gather') {
    if (!arg1) {
      console.error('  ' + c.red('사용법: mobi-remote do-gather <이름> <수량>'));
      return 2;
    }
    const routine = routines.gatherRoutine(arg1, parseInt(arg2, 10) || 100);
    const s = await confirmAndRun(routine, { yes: !!flags.yes, dryRun: !!flags['dry-run'] });
    return s && s.failCount === 0 && !s.aborted ? 0 : 1;
  }
  if (cmd === 'do-craft') {
    if (!arg1) {
      console.error('  ' + c.red('사용법: mobi-remote do-craft <이름> <횟수>'));
      return 2;
    }
    const routine = routines.craftRoutine([{ name: arg1, count: parseInt(arg2, 10) || 1 }]);
    const s = await confirmAndRun(routine, { yes: !!flags.yes, dryRun: !!flags['dry-run'] });
    return s && s.failCount === 0 && !s.aborted ? 0 : 1;
  }

  /* 스케줄 */
  if (cmd === 'schedule') {
    if (arg1 === 'run') {
      await runDaemon();
      return 0;
    }
    const state = scheduler.load();
    if (out(state, flags)) return 0;
    if (!state.entries.length) console.log('  ' + c.gray('(등록된 스케줄 없음)'));
    for (const e of state.entries) {
      console.log('  ' + (e.enabled ? sym.ok : c.gray('○')) + ' ' + ui.padEnd(e.id, 14) + ui.padEnd(e.routine, 16) + c.gray(scheduler.describe(e)));
    }
    return 0;
  }

  /* 유지보수 */
  if (cmd === 'cache') {
    if (arg1 === 'clear') {
      cache.clear();
      console.log('  ' + sym.ok + ' 캐시를 비웠습니다.');
      return 0;
    }
    const l = cache.list();
    if (out(l, flags)) return 0;
    for (const e of l) console.log('  ' + ui.padEnd(e.command, 24) + ui.padStart(e.sizeKB + 'KB', 8) + c.gray('  ' + e.ageSec + '초 전'));
    return 0;
  }
  if (cmd === 'compat' || cmd === 'version') {
    const version = require('./version');
    if (arg1 === 'accept') {
      await connector.refreshCapabilities().catch(() => {});
      version.saveBaseline(version.fingerprint(), '명령줄에서 승인');
      console.log('  ' + sym.ok + ' 현재 상태를 기준선으로 저장했습니다.');
      return 0;
    }
    await connector.refreshCapabilities().catch(() => {});
    const info = { app: version.appVersion(), cli: version.cliVersion() };
    const res = version.check();
    if (out({ info, result: res }, flags)) return res.ok ? 0 : 1;

    console.log('  mobi-remote ' + info.app + c.gray('   CLI ' + (info.cli.productVersion || '읽을 수 없음')));
    const mark = { ok: sym.ok, info: sym.info, warn: sym.warn, error: sym.fail }[res.levelName];
    const tone = { ok: c.green, info: c.gray, warn: c.yellow, error: c.red }[res.levelName];
    console.log('  ' + mark + ' ' + tone(res.levelName === 'ok' ? '호환 확인됨' : '변경 ' + res.changes.length + '건'));
    for (const ch of res.changes) {
      console.log();
      console.log('  ' + ch.title);
      for (const line of String(ch.detail).split('\n')) console.log('    ' + c.gray(line));
    }
    if (!res.ok) console.log('\n  ' + c.gray('정상 동작을 확인했다면: mobi-remote compat accept'));
    return res.ok ? 0 : 1;
  }
  if (cmd === 'capabilities') {
    const cmds = await connector.refreshCapabilities();
    if (out(cmds.map((x) => ({ command: x.Command, description: x.Description })), flags)) return 0;
    console.log('  ' + sym.ok + ' 명령 ' + cmds.length + '개');
    for (const x of cmds) console.log('  ' + ui.padEnd(x.Command, 26) + c.gray(x.Description));
    return 0;
  }

  console.error('  ' + c.red('알 수 없는 명령: ' + cmd));
  console.log(HELP);
  return 2;
}

/* ── 진입점 ─────────────────────────────────────────────────── */

async function main() {
  const argv = process.argv.slice(2);
  if (!argv.length && process.stdout.isTTY) {
    await tui();
    return 0;
  }
  return cli(argv);
}

main()
  .then((code) => process.exit(code || 0))
  .catch((err) => {
    console.error('  ' + c.red('오류: ') + (err && err.stack ? err.stack : err));
    process.exit(1);
  });
