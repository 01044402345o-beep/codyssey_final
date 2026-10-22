/* 첫 그림 전에 실행되는 부팅 스크립트 — index.html 의 <head> 에서 스타일시트보다 먼저 동기로 불린다.
   예전에는 index.html 안의 인라인 <script> 두 개였다. CSP 에서 script-src 'unsafe-inline' 을 빼려고 파일로 옮겼다
   (보안 헤더: backend/app/security_headers.py). 내용은 그대로다. */

/* 화면 테마: cd_theme = light | dark (없으면 시스템 설정을 따른다). CSS 가 그려지기 전에 data-theme 을 정해 깜빡임을 막는다 */
(function () {
  var t = null; try { t = localStorage.getItem('cd_theme'); } catch (e) {}
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
  var dark = t === 'dark' || (t !== 'light' && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  var m = document.getElementById('theme-color'); if (m) m.setAttribute('content', dark ? '#12151c' : '#fbf8f1');
})();

/* 화면 모드: 기본=제품(반응형 셸) · ?demo=1(또는 예전 주소 ?menu=1)=제품+데모 서랍 · ?demo=1&frame=1=예전 데모 레이아웃(폰 프레임+사이드 패널) */
(function () { var q = new URLSearchParams(location.search); document.documentElement.dataset.mode = q.get('demo') === '1' || q.get('menu') === '1' ? (q.get('frame') === '1' ? 'legacy' : 'demo') : 'product'; })();
