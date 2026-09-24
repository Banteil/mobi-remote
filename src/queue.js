'use strict';
/**
 * 작업 큐 저장.
 *
 * 큐를 돌리는 판단은 전부 화면 쪽에 있다. 여기는 **껐다 켜도 목록이 남게** 하는 일만 한다.
 * 목표를 열 개쯤 걸어 두고 자리를 비우는 쓰임이라, 앱을 다시 켤 때 목록이 사라지면
 * 처음부터 다시 걸어야 한다.
 *
 * 진행 중이던 항목은 다시 켤 때 대기로 되돌린다 — 앱이 꺼진 동안 진행됐을 리가 없다.
 * 그 처리는 읽는 쪽(renderer)이 한다. 여기서는 준 대로 담고 준 대로 돌려준다.
 */
const fs = require('fs');
const path = require('path');
const paths = require('./paths');

const FILE = paths.dataPath('queue.json');

/** 한 항목이 가질 수 있는 필드. 화면이 보내는 값을 그대로 믿지 않고 걸러 담는다. */
const FIELDS = ['id', 'via', 'name', 'label', 'recipe', 'target', 'status', 'note',
  'spent', 'steps', 'have', 'startHave', 'per', 'runs', 'wings', 'partial', 'base', 'made'];

function load() {
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    return { items: Array.isArray(d.items) ? d.items : [] };
  } catch (_) {
    return { items: [] };
  }
}

function save(state) {
  const items = (state && Array.isArray(state.items) ? state.items : []).map((x) => {
    const o = {};
    for (const k of FIELDS) if (x[k] !== undefined) o[k] = x[k];
    return o;
  });
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify({ items: items }, null, 2), 'utf8');
  } catch (_) {
    /* 저장에 실패해도 진행 중인 큐는 계속 돌아야 한다 */
  }
  return { items: items };
}

module.exports = { load, save, FILE };
