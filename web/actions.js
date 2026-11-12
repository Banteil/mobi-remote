'use strict';
/* 명령 실행 (비용 확인·결과 알림·호출 기록). app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 명령 실행 (비용 확인 포함) ─────────────────── */

let busy = false;
/** 마지막으로 확인된 연결 상태. 꺼져 있으면 5초짜리 호출을 피한다. */
let online = true;

/** 날개가 드는 명령이면 비용을 보여 주고 묻는다. 해도 되면 cost 정보, 아니면 null. */
async function confirmCost(command, o) {
  const cost = await mm.costOf(command, o.times || 1);
  if (cost.costed && !o.skipConfirm) {
    const enough = cost.enough;
    const cur = cost.currency || '정령의 날개';
    const html =
      '<p>' + esc(o.label || command) + '</p>' +
      '<div class="cost">' +
        '<div>소모 <span class="big">' + num(cost.total) + '</span> ' + esc(cur) +
          (o.times > 1 ? ' <span class="muted">(' + cost.perCall + ' × ' + o.times + '회)</span>' : '') + '</div>' +
        '<div class="muted">보유 ' + num(cost.balance) + ' → 실행 후 ' + num(cost.balance - cost.total) + '</div>' +
        (enough ? '' : '<div class="bad">' + esc(cur) + '이(가) 부족합니다.</div>') +
      '</div>' +
      (o.note ? '<p class="hint">' + esc(o.note) + '</p>' : '');

    if (!enough) {
      await confirmModal('실행 불가', html, '닫기');
      return null;
    }
    if (!(await confirmModal('실행 확인', html))) return null;
  } else if (o.confirmText && !o.skipConfirm) {
    if (!(await confirmModal('확인', '<p>' + esc(o.confirmText) + '</p>'))) return null;
  }
  return cost;
}

async function runAction(command, body, opts) {
  const o = opts || {};
  if (busy) {
    toast('실행 중', '이전 명령이 끝난 뒤 다시 시도하세요.', 'bad');
    return null;
  }
  const cost = await confirmCost(command, o);
  if (!cost) return null;

  busy = true;
  setBusy(true, (o.label || command) + ' 실행 중…');
  say(command + ' 호출…');

  let r;
  try {
    r = await mm.exec(command, body);
  } catch (err) {
    // IPC 자체가 실패한 경우. finally가 없으면 busy가 true로 남아
    // 이후 모든 명령이 "다른 명령이 실행 중"으로 막힌다.
    r = { ok: false, error: 'ipc_failed', message: String((err && err.message) || err), durationMs: 0 };
  } finally {
    busy = false;
    setBusy(false);
  }

  if (r.ok) {
    const extra = r.wingsSpent ? ' · ' + (cost.currency || '날개') + ' ' + r.wingsSpent + ' 소모' : '';
    toast('완료 — ' + (o.label || command), describeResult(command, r.data) + ' (' + r.durationMs + 'ms)' + extra, 'ok');
    say('완료: ' + command);
  } else {
    // 메인이 붙여 준 한국어 해설을 우선 쓰고, 없으면 원문을 보여준다
    const ko = r.ko;
    const head = '실패 — ' + (o.label || command);
    if (ko) {
      // 번역이 있으면 영어 원문은 굳이 띄우지 않는다. 필요하면 콘솔 탭 응답에서 볼 수 있다.
      toast(head + ': ' + ko.text, ko.hint || '', 'bad');
      say('실패: ' + ko.text);
    } else {
      toast(head, (r.error || '') + (r.message ? ' · ' + r.message : ''), 'bad');
      say('실패: ' + command + ' (' + (r.error || '') + ')');
    }
  }

  logCall(command, r);
  refreshTopbar();
  return r;
}

/** 큐가 행동을 마친 뒤 다시 읽을 탭 (아래 mm.onExecDone) */
const ACT_REFRESH = {
  craft: () => loadCraft(true), alter: () => loadAlter(true), collect: () => loadAlter(true), collectAll: () => loadAlter(true),
};

/* 작업 큐(파이썬)가 부른 명령: 시작·끝을 화면에서 runAction 과 똑같이 알린다 (origin 이 있는 것만 — 화면이 부른 것은 runAction 이 알린다) */
mm.onExecStart((m) => {
  if (m && m.origin) setBusy(true, (m.origin.label || m.command) + ' 실행 중…');
});
mm.onExecDone((m) => {
  if (!m || !m.origin) return;
  setBusy(false);
  const label = m.origin.label || m.command;
  if (!m.origin.quiet) {
    if (m.ok) {
      toast('완료 — ' + label, describeResult(m.command, m.data) + ' (' + m.durationMs + 'ms)' +
        (m.wingsSpent ? ' · 날개 ' + m.wingsSpent + ' 소모' : ''), 'ok');
    } else if (m.ko) {
      toast('실패 — ' + label + ': ' + m.ko.text, m.ko.hint || '', 'bad');
    } else {
      toast('실패 — ' + label, (m.error || '') + (m.message ? ' · ' + m.message : ''), 'bad');
    }
    logCall(m.command, m);
  }
  refreshTopbar();
  const re = ACT_REFRESH[m.origin.act];
  if (re) re();
});

function describeResult(command, d) {
  if (!d) return '응답 없음';
  if (command === 'execute_gathering') {
    if (d.result === 'started') return '자동 낚시 시작';
    if (d.gained !== undefined) return '획득 ' + d.gained + (d.target ? '/' + d.target : '');
    if (d.result) return String(d.result);
  }
  if (command === 'execute_crafting' && d.craftCount) return d.craftCount + '회 제작 완료';
  if (command === 'execute_altering') return '가공 큐 등록됨';
  if (d.message) return String(d.message);
  if (Array.isArray(d)) return d.length + '건';
  return '성공';
}

function logCall(command, r) {
  const box = $('#call-log');
  const d = document.createElement('div');
  const t = new Date().toLocaleTimeString('ko-KR');
  const why = r.ok ? '' : ' · ' + esc(r.ko ? r.ko.text : r.error || '');
  d.innerHTML =
    '<span class="t">' + t + '</span>' +
    '<span class="' + (r.ok ? 'mark-ok' : 'mark-bad') + '">' + (r.ok ? '✔' : '✘') + '</span> ' +
    esc(command) + ' <span class="muted">' + r.durationMs + 'ms' + why +
    (r.ok || !r.error ? '' : ' <span class="sub">[' + esc(r.error) + ']</span>') + '</span>';
  box.insertBefore(d, box.firstChild);
  while (box.children.length > 200) box.removeChild(box.lastChild);
}
