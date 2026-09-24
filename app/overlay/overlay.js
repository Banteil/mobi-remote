'use strict';
/**
 * 게임 위에 겹쳐 그리는 창.
 *
 * 스스로는 아무것도 판단하지 않는다. 메인이 보내 준 것을 그리기만 하고,
 * 그리는 방법은 draw.js 에 있다 — 리모콘의 미리보기가 같은 코드를 쓴다.
 *
 * 화면 전체를 덮고 클릭은 전부 통과시키므로, 사용자 입장에서는 게임 위에 그림만 얹힌다.
 */

const cv = document.getElementById('art');
const ctx = cv.getContext('2d');
let last = null;

/**
 * 캔버스를 창에 정확히 맞춘다.
 *
 * CSS 크기도 여기서 픽셀로 박는다. vw/vh 로 두면 스크롤바 자리까지 폭에 들어가
 * 창 가장자리에 스크롤 막대가 생긴다 — 게임 위에 얹히는 창이라 그것까지 다 보인다.
 */
function fit() {
  const r = window.devicePixelRatio || 1;
  const w = window.innerWidth, h = window.innerHeight;
  cv.style.width = w + "px";
  cv.style.height = h + "px";
  cv.width = Math.round(w * r);
  cv.height = Math.round(h * r);
  ctx.setTransform(r, 0, 0, r, 0, 0);
  if (last) draw(last);
}
fit();
window.addEventListener('resize', fit);

function draw(p) {
  last = p;
  window.dyeDraw.draw(ctx, window.innerWidth, window.innerHeight, p, 1);
}

function clear() {
  last = null;
  ctx.clearRect(0, 0, cv.width, cv.height);
}

window.__dyeDraw = draw;
window.__dyeClear = clear;
