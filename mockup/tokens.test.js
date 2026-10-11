// 색 리터럴 가드 (반응형 전략 P0): 색은 styles.css 의 :root 토큰에만 둔다.
// 다크 모드(P3)는 :root 만 재정의하므로, 규칙·인라인 style 에 색 리터럴이 있으면 다크에서 그 자리만 라이트 색으로 남는다.
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('fs'), path = require('path');
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8');
// :root 토큰 블록(라이트·다크 둘 다)을 걷어낸다. 색 리터럴은 여기에만 있어야 한다.
function tokenBlocks(css) {
  const light = css.match(/:root \{\n  color-scheme: light;[\s\S]*?\n\}\n/);
  const darkMq = css.match(/@media \(prefers-color-scheme: dark\) \{\n  :root:not\(\[data-theme="light"\]\) \{\n([\s\S]*?)\n  \}\n\}\n/);
  const darkAttr = css.match(/:root\[data-theme="dark"\] \{\n([\s\S]*?)\n\}\n/);
  return { light, darkMq, darkAttr };
}
function stripTokenBlocks(css) { const b = tokenBlocks(css); return [b.light, b.darkMq, b.darkAttr].reduce((c, m) => (m ? c.replace(m[0], '') : c), css); }
const decls = body => Object.fromEntries([...body.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/g;

test('styles.css: :root 밖에는 색 리터럴이 없다', () => {
  const css = read('styles.css');
  const outside = stripTokenBlocks(css).replace(/\/\*[\s\S]*?\*\//g, '');
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
  const lines = read('app.js').split('\n').filter(l => new RegExp(COLOR.source).test(l) && !/^\s*google:/.test(l) && !/THEME_COLOR =/.test(l));
  assert.deepEqual(lines.map(l => l.trim().slice(0, 80)), []);
});

// ---- 다크 모드 (P3) ----
const lumOf = h => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; const n = parseInt(h.slice(1), 16); return .2126 * f(n >> 16) + .7152 * f((n >> 8) & 255) + .0722 * f(n & 255); };
const ratio = (a, b) => { const [x, y] = [lumOf(a), lumOf(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };

test('다크: 두 블록(시스템 감지·수동 선택)이 같은 내용이고, 모든 키가 라이트에 존재한다', () => {
  const b = tokenBlocks(read('styles.css'));
  assert.ok(b.light && b.darkMq && b.darkAttr, '토큰 블록을 찾지 못함');
  const mq = decls(b.darkMq[1]), at = decls(b.darkAttr[1]), li = decls(b.light[0]);
  assert.deepEqual(mq, at, '다크 블록 두 개가 달라졌다 — 같이 고쳐야 한다');
  assert.deepEqual(Object.keys(at).filter(k => !(k in li)), [], '라이트에 없는 다크 토큰');
});

test('대비: 라이트·다크 모두 글자 토큰 조합이 WCAG AA(4.5:1)를 넘는다', () => {
  const b = tokenBlocks(read('styles.css'));
  const li = decls(b.light[0]); const dk = { ...li, ...decls(b.darkAttr[1]) };
  // [글자, 배경들]
  const PAIRS = [
    ['--text', ['--bg', '--surface', '--surface-2', '--surface-3', '--bg-canvas']],
    ['--text-2', ['--bg', '--surface']],
    ['--text-soft', ['--bg', '--surface', '--surface-3']],
    ['--text-3', ['--bg', '--surface', '--surface-2', '--surface-3', '--surface-4', '--surface-admin', '--stale-bg', '--me-bg']],
    ['--accent-text', ['--bg', '--surface', '--surface-2']],
    ['--on-accent', ['--accent']], ['--on-fill', ['--fill-strong']], ['--on-sea', ['--sea']],
    ['--ok-text', ['--ok-soft', '--bg', '--surface']], ['--bad-text', ['--bad-soft', '--bg', '--surface']],
    ['--sea-text', ['--sea-soft', '--surface']], ['--plum-text', ['--plum-soft']],
    ['--on-sun-soft', ['--sun-soft']], ['--on-sun-soft-2', ['--sun-soft']], ['--on-accent-soft', ['--accent-soft']],
    ['--on-bad-soft', ['--bad-soft']], ['--on-sea-soft', ['--sea-soft']],
    ['--inv-text', ['--inv-bg', '--sea']], ['--inv-text-1', ['--inv-bg', '--sea']], ['--inv-text-2', ['--inv-bg']], ['--inv-text-3', ['--inv-bg']],
  ];
  const bad = [];
  for (const [name, set] of [['라이트', li], ['다크', dk]])
    for (const [fg, bgs] of PAIRS) for (const bg of bgs) {
      const f = set[fg], g = set[bg];
      if (!/^#[0-9a-f]{6}$/i.test(f) || !/^#[0-9a-f]{6}$/i.test(g)) { bad.push(`${name} ${fg} on ${bg}: 값을 읽을 수 없음 (${f}, ${g})`); continue; }
      const r = ratio(f, g); if (r < 4.5) bad.push(`${name} ${fg} ${f} on ${bg} ${g} = ${r.toFixed(2)}`);
    }
  assert.deepEqual(bad, []);
});

test('대비: 입력 경계·포커스 링은 비텍스트 3:1', () => {
  const b = tokenBlocks(read('styles.css')); const li = decls(b.light[0]); const dk = { ...li, ...decls(b.darkAttr[1]) };
  for (const [n, set] of [['라이트', li], ['다크', dk]]) for (const bg of ['--bg', '--surface']) for (const fg of ['--focus', '--border-input']) assert.ok(ratio(set[fg], set[bg]) >= 3, `${n} ${fg} on ${bg}`);
});

test('THEME_COLOR(주소창 색)가 --bg 토큰과 같다', () => {
  const b = tokenBlocks(read('styles.css')); const li = decls(b.light[0]), dk = decls(b.darkAttr[1]);
  const m = read('app.js').match(/THEME_COLOR = \{ light: '(#[0-9a-f]{6})', dark: '(#[0-9a-f]{6})' \}/);
  assert.ok(m); assert.equal(m[1], li['--bg']); assert.equal(m[2], dk['--bg']);
  const html = read('index.html'); assert.ok(html.includes(`content="${li['--bg']}" id="theme-color"`));
});
