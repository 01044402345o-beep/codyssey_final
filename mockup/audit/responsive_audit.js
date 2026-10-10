// 반응형 기준선 감사. 사용법: node mockup/audit/responsive_audit.js
// 환경 변수: BASE_URL(기본 http://localhost:8000), PW_PATH(playwright 모듈 경로), CHROME_PATH(chromium 실행 파일)
// 현재(제품 셸 분리 전) 코드에서는 가로 스크롤 실패가 정상이며, docs/RESPONSIVE_STRATEGY.md 의 단계별 개선을 숫자로 확인하는 용도다.
const { chromium } = require(process.env.PW_PATH || 'playwright');
const BASE = process.env.BASE_URL || 'http://localhost:8000';
const WIDTHS = [[320, 640], [360, 740], [390, 844], [768, 1024], [1024, 768], [1280, 800], [1920, 1080]];
const SCREENS = ['u-login', 'u-input', 'u-report', 'u-route', 'u-home', 'u-sched', 'u-study', 'u-coll', 'a-metrics', 'a-jobs', 'a-common', 'a-users'];

(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, args: ['--no-sandbox'] });
  const rows = [];
  for (const [w, h] of WIDTHS) {
    const page = await b.newPage({ viewport: { width: w, height: h } });
    await page.goto(BASE + (process.env.QS || '/'));
    await page.evaluate(() => preset('default'));
    for (const id of SCREENS) {
      await page.evaluate(i => {
        S.user = DEMO_USER;
        if (i === 'u-study') { const r = S.sched.find(r => r.ids && r.ids.length); S.studyDate = r.date; S.card = { date: r.date, i: 0, flipped: new Set() }; }
        go(i);
      }, id);
      const m = await page.evaluate(() => {
        const de = document.documentElement;
        const scope = document.querySelector('.pframe') || document.querySelector('.admin-shell') || document.querySelector('.device') || document.querySelector('.window') || document.body;
        let small = 0, tiny = 0, texts = 0;
        scope.querySelectorAll('button,a,input,select,[data-act]').forEach(e => { const q = e.getBoundingClientRect(); if (q.width && q.height && (q.height < 44 || q.width < 44)) small++; });
        scope.querySelectorAll('*').forEach(e => {
          if (e.getBoundingClientRect().width && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) { texts++; if (parseFloat(getComputedStyle(e).fontSize) < 12) tiny++; }
        });
        const wide = [...document.querySelectorAll('body *')].filter(e => { const q = e.getBoundingClientRect(); return q.width && q.right > de.clientWidth + 1 && !e.closest('.tbl-wrap,.chips,.city-tabs,.admin-nav'); }).slice(0, 3).map(e => e.tagName + '.' + String(e.className).split(' ')[0] + '@' + Math.round(e.getBoundingClientRect().right));
        return { wide, hscroll: de.scrollWidth > de.clientWidth, scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, small, tiny, texts };
      });
      rows.push({ w, id, ...m });
      if (m.hscroll || m.wide.length) console.log(`  ! w=${w} ${id} scrollWidth=${m.scrollWidth} 넘침 요소: ${m.wide.join(', ')}`);
    }
    await page.close();
  }
  await b.close();
  let fail = 0;
  for (const [w] of WIDTHS) {
    const r = rows.filter(x => x.w === w);
    const hs = r.filter(x => x.hscroll).length; fail += hs;
    console.log(`w=${w}: 가로스크롤 ${hs}/${r.length} | 44px 미만 타깃 합 ${r.reduce((a, x) => a + x.small, 0)} | 12px 미만 텍스트 ${r.reduce((a, x) => a + x.tiny, 0)}/${r.reduce((a, x) => a + x.texts, 0)}`);
  }
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
