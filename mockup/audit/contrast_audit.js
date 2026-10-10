// 글자 대비 감사: 화면별로 모든 텍스트 요소의 (글자색, 실제 배경색) 대비를 WCAG 상대 휘도로 계산한다.
//   node mockup/audit/contrast_audit.js [light|dark] [폭=390]
// 환경 변수: BASE_URL, PW_PATH, CHROME_PATH, QS(기본 '/'). 실패(일반 4.5 미만·큰 글자 3 미만)가 있으면 exit 1.
// 한계: 배경 이미지·그라데이션 위의 글자는 건너뛴다. 불투명도(opacity)는 글자색과 배경을 섞어 반영한다. 데모 패널(#side, .topbar)은 제외.
const { chromium } = require(process.env.PW_PATH || 'playwright');
const BASE = process.env.BASE_URL || 'http://localhost:8000';
const SCHEME = process.argv[2] || 'light', W = +(process.argv[3] || 390);
const SCREENS = ['u-login', 'u-input', 'u-report', 'u-route', 'u-home', 'u-sched', 'u-study', 'u-study-back', 'u-coll', 'a-metrics', 'a-jobs', 'a-common', 'a-users'];
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: W, height: 900 }, colorScheme: SCHEME, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.route(/^https?:\/\/(?!localhost|127\.0\.0\.1)/, r => r.abort());
  await page.goto(BASE + (process.env.QS || '/'));
  await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important}.toast{display:none!important}' });
  await page.evaluate(() => preset('default'));
  const found = new Map();
  for (const id of SCREENS) {
    await page.evaluate(i => {
      S.user = DEMO_USER;
      if (i.startsWith('u-study')) { const r = S.sched.find(r => r.ids && r.ids.length); S.studyDate = r.date; S.card = { date: r.date, i: 0, flipped: new Set() }; go('u-study'); if (i === 'u-study-back') document.querySelector('.flip').classList.add('flipped'); }
      else go(i);
    }, id);
    await page.waitForTimeout(500);
    const rows = await page.evaluate(() => {
      const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
      const over = (f, bgc) => ({ r: f.r * f.a + bgc.r * (1 - f.a), g: f.g * f.a + bgc.g * (1 - f.a), b: f.b * f.a + bgc.b * (1 - f.a), a: 1 });
      const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
      const out = [];
      const rootBg = parse(getComputedStyle(document.documentElement).backgroundColor); const bodyBg = parse(getComputedStyle(document.body).backgroundColor);
      const canvas = (bodyBg && bodyBg.a > 0 ? bodyBg : (rootBg && rootBg.a > 0 ? rootBg : { r: 255, g: 255, b: 255, a: 1 }));
      for (const e of document.querySelectorAll('body *')) {
        if (e.closest('#side,.topbar,#demo-fab,#toast,.toast,svg,[aria-hidden=true]')) continue;
        const q = e.getBoundingClientRect(); if (!q.width || !q.height) continue;
        if (![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
        const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || e.disabled) continue;
        let fg = parse(cs.color); if (!fg) continue;
        // 배경: 조상으로 올라가며 합성
        const stack = []; let skip = false, op = 1;
        for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
          const c = getComputedStyle(n); op *= parseFloat(c.opacity);
          if (c.backgroundImage && c.backgroundImage !== 'none') { skip = true; break; }
          const bg = parse(c.backgroundColor); if (bg && bg.a > 0) { stack.push(bg); if (bg.a >= 1) break; }
        }
        if (skip) continue;
        let bg = stack.length && stack[stack.length - 1].a >= 1 ? stack.pop() : canvas;
        while (stack.length) bg = over(stack.pop(), bg);
        let f = fg; if (fg.a < 1) f = over(fg, bg);
        if (op < 1) f = over({ ...f, a: op }, bg);
        const L1 = lum(f), L2 = lum(bg), ratio = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
        const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700, large = size >= 24 || (size >= 18.66 && bold);
        if (ratio < (large ? 3 : 4.5)) {
          const hex = c => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
          out.push({ sel: e.tagName.toLowerCase() + '.' + [...e.classList].join('.') + ' < ' + (e.parentElement ? e.parentElement.tagName.toLowerCase() + '.' + [...e.parentElement.classList].join('.') : ''), text: e.textContent.trim().slice(0, 14), fg: hex(f), bg: hex(bg), ratio: Math.round(ratio * 100) / 100, size, large, op });
        }
      }
      return out;
    });
    for (const r of rows) { const k = `${r.sel}|${r.fg}|${r.bg}`; const o = found.get(k) || { ...r, screens: new Set(), n: 0 }; o.screens.add(id); o.n++; found.set(k, o); }
  }
  await b.close();
  const list = [...found.values()].sort((a, b) => a.ratio - b.ratio);
  console.log(`${SCHEME} ${W}px · 대비 미달 ${list.length}종 (${list.reduce((a, o) => a + o.n, 0)}개 요소)`);
  for (const o of list) console.log(`  ${String(o.ratio).padEnd(5)} ${o.fg} on ${o.bg}${o.op < 1 ? ' (opacity ' + o.op.toFixed(2) + ')' : ''}  ${o.sel}  "${o.text}"  [${[...o.screens].join(',')}]`);
  process.exit(list.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
