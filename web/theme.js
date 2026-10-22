'use strict';
/**
 * 테마를 첫 페인트 전에 붙인다.
 *
 * <head>에서 동기로 실행되는 유일한 스크립트다. app.js처럼 늦게 돌면
 * 다크 화면이 한 번 그려졌다가 라이트로 바뀌어 눈에 띄게 깜빡인다.
 * CSP가 인라인 스크립트를 막으므로(script-src 'self') 별도 파일로 둔다.
 */
(function () {
  var t = 'dark';
  try {
    if (window.mm && window.mm.initialTheme === 'light') t = 'light';
  } catch (_) { /* preload가 없으면 기본값 */ }
  document.documentElement.setAttribute('data-theme', t);
})();
