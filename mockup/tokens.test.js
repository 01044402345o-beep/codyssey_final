// 색 리터럴 가드 (반응형 전략 P0): 색은 styles.css 의 :root 토큰에만 둔다.
// 다크 모드(P3)는 :root 만 재정의하므로, 규칙·인라인 style 에 색 리터럴이 있으면 다크에서 그 자리만 라이트 색으로 남는다.
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('fs'), path = require('path');
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8');
const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/g;

test('styles.css: :root 밖에는 색 리터럴이 없다', () => {
  const css = read('styles.css');
  const rootEnd = css.indexOf('\n}\n', css.indexOf(':root {')) + 3;
  const outside = css.slice(rootEnd).replace(/\/\*[\s\S]*?\*\//g, '');
  const found = outside.match(COLOR) || [];
  assert.deepEqual(found, [], '토큰으로 바꿔야 할 리터럴: ' + found.join(', '));
});

test('styles.css: 정의되지 않은 var(--토큰) 참조가 없다', () => {
  const css = read('styles.css') + read('app.js');
  const defined = new Set([...read('styles.css').matchAll(/(--[a-z0-9-]+)\s*:/g)].map(m => m[1]));
  const used = [...new Set([...css.matchAll(/var\((--[a-z0-9-]+)/g)].map(m => m[1]))];
  assert.deepEqual(used.filter(u => !defined.has(u)), []);
});

test('app.js: 색 리터럴은 Google 로고(브랜드 고정색)뿐이다', () => {
  const lines = read('app.js').split('\n').filter(l => new RegExp(COLOR.source).test(l) && !/^\s*google:/.test(l));
  assert.deepEqual(lines.map(l => l.trim().slice(0, 80)), []);
});
