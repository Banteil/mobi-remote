'use strict';
/**
 * 게임 문자열에 섞여 오는 Unity rich text 처리.
 *
 * 현재 확인된 것은 get_items의 DisplayName뿐이고, 태그는 <color=#RRGGBB>…</color> 하나다.
 *   "인챈트 스크롤: 활기(<color=#FFFFFF>★8</color>)"
 *   "<color=#FFC448>★10</color> 초월의 정수 조각"
 * 색이 등급을 나타내므로 GUI에서는 살리고, 터미널·검색·비교에서는 벗긴다.
 *
 * 주의: DisplayName은 명령 본문으로 되돌려 보내는 식별자이기도 하다.
 * 화면에 쓸 값과 게임에 보낼 값을 반드시 구분할 것 — 보낼 때는 항상 원문 그대로.
 */

// 여는 태그는 색상값을 갖고, 닫는 태그는 없다. 그 외 태그는 통째로 지운다.
const ANY_TAG = /<\/?[a-zA-Z][^>]*>/g;
// hasTags 전용. /g 가 붙은 정규식에 test()를 쓰면 lastIndex가 남아
// **같은 문자열인데도 호출할 때마다 결과가 달라진다** (true, true, false, true…).
// 그러면 태그가 있는 이름이 색 없이 그려지거나, 없는 이름을 있다고 판정한다.
const HAS_TAG = /<\/?[a-zA-Z][^>]*>/;
const COLOR_OPEN = /^<color\s*=\s*(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)\s*>$/;
const TAG_SCAN = /<\/?[a-zA-Z][^>]*>/g;

/** 태그를 모두 제거한 순수 텍스트 */
function strip(s) {
  if (typeof s !== 'string') return s;
  if (s.indexOf('<') < 0) return s;
  return s.replace(ANY_TAG, '');
}

/** 태그가 들어 있는지 */
function hasTags(s) {
  return typeof s === 'string' && HAS_TAG.test(s);
}

/**
 * 색 구간으로 쪼갠다. 렌더러가 안전하게 HTML을 만들 수 있도록
 * 문자열을 직접 넘기지 않고 { text, color } 조각으로 준다.
 * @returns {Array<{text: string, color: string|null}>}
 */
function segments(s) {
  if (typeof s !== 'string') return [{ text: String(s === undefined || s === null ? '' : s), color: null }];
  if (s.indexOf('<') < 0) return [{ text: s, color: null }];

  const out = [];
  const stack = [];
  let last = 0;
  let m;
  TAG_SCAN.lastIndex = 0;

  const push = (text) => {
    if (!text) return;
    const color = stack.length ? stack[stack.length - 1] : null;
    const prev = out[out.length - 1];
    if (prev && prev.color === color) prev.text += text;
    else out.push({ text: text, color: color });
  };

  while ((m = TAG_SCAN.exec(s)) !== null) {
    push(s.slice(last, m.index));
    const tag = m[0];
    const open = COLOR_OPEN.exec(tag);
    if (open) stack.push(open[1]);
    else if (/^<\/color\s*>$/i.test(tag)) stack.pop();
    // 그 밖의 태그는 무시하고 버린다
    last = m.index + tag.length;
  }
  push(s.slice(last));

  return out.length ? out : [{ text: '', color: null }];
}

module.exports = { strip, hasTags, segments };
