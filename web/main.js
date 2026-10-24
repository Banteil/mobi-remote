'use strict';
/* 시작 — 모든 스크립트가 읽힌 뒤 마지막에 돈다. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 시작 ───────────────────────────────────────── */

(async function start() {
  wire();

  // 표를 그리기 전에 정렬 기준과 즐겨찾기를 읽어 둔다.
  // 나중에 읽으면 기본 순서로 한 번 그렸다가 튄다.
  await loadSortPrefs();
  await loadFavorites();
  try {
    const c = await mm.cfg.get();
    worksFolded = c.alterWorksFolded === true;
    queueFolded = c.queueFolded === true;
  } catch (_) { /* 설정을 못 읽어도 펼친 채로 돈다 */ }
  applyQueueFold();
  // 접힌 채로 뜬다면 창도 그만큼 좁혀 둔다. 창 크기는 저장하지 않으므로 기본 폭으로 뜬다.
  if (queueFolded) {
    const now = $('#queue').getBoundingClientRect().width;
    const wide = queueWideWidth();
    if (wide > now) {
      pinContent($('#content').getBoundingClientRect().width);
      try { await mm.win.narrow(wide - now); } catch (_) {}
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      unpinContent();
    }
  }
  await loadQueue();

  // 1단계 — 캐시만으로 화면을 즉시 띄운다.
  // 게임이 꺼져 있으면 CLI가 연결 실패를 판정하는 데만 약 5초가 걸린다.
  // 그 사이 빈 창을 보여주지 않으려고, 먼저 오프라인으로 가정하고 그린다.
  online = false;
  say('마지막 정보로 표시 중…');
  await showTab('chars');

  // 2단계 — 실제 연결 상태를 확인한다 (연결돼 있으면 100ms, 아니면 약 5초)
  const ok = await refreshTopbar();
  if (!ok) {
    say('게임에 연결되지 않았습니다.');
    toast('연결 안 됨', '게임 실행 및 "MM AI 에이전트 활성화" 설정을 확인하세요.', 'bad');
  }

  // 게임이 꺼져 있으면 capabilities를 새로 받을 수 없으므로 캐시된 목록으로 검사한다
  await startupCompatCheck({ refresh: ok });

  // 3단계 — 연결돼 있으면 실시간 값으로 다시 채운다 (바뀐 부분만 다시 그려진다)
  if (ok) {
    await refreshActive();
    say('준비됨');
  }

  // 가공이 칸 부족으로 막히면 메인이 칸 수를 확정하고 알려 준다.
  // 날개가 이미 나간 실패지만, 최소한 다음부터는 헛되이 넘치지 않는다.
  mm.onFacilityLevel((d) => {
    toast(d.facility + ' — 레벨 ' + d.level + ' 확인',
      '칸이 꽉 차서 막혔습니다. 최대 ' + d.slots + '칸으로 기록했습니다. 틀렸다면 Lv 배지에서 고치세요.', 'ok');
    if (activeTab === 'alter') loadAlter(true);
  });

  initAuto();
})();
