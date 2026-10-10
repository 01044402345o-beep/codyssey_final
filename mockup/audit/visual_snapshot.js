// 시각 회귀 스냅샷. 같은 상태에서 화면별 PNG 를 만들고, 폴더 둘을 비교한다.
//   node mockup/audit/visual_snapshot.js <출력폴더> [scheme]     scheme: light(기본) | dark
//   node mockup/audit/visual_snapshot.js --compare <폴더A> <폴더B>   (바이트 단위 비교, 다른 파일 목록 출력)
// 환경 변수: BASE_URL(기본 http://localhost:8000), PW_PATH, CHROME_PATH
const fs = require('fs'), path = require('path'), crypto = require('crypto');
if (process.argv[2] === '--compare') {
  const [A, B] = process.argv.slice(3);
  const h = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
  const names = [...new Set([...fs.readdirSync(A), ...fs.readdirSync(B)])].filter(n => n.endsWith('.png')).sort();
  const diff = names.filter(n => !fs.existsSync(path.join(A, n)) || !fs.existsSync(path.join(B, n)) || h(path.join(A, n)) !== h(path.join(B, n)));
  console.log(`비교 ${names.length}개 · 다름 ${diff.length}개`); diff.forEach(n => console.log('  ≠ ' + n));
  process.exit(diff.length ? 1 : 0);
}
const { chromium } = require(process.env.PW_PATH || 'playwright');
const BASE = process.env.BASE_URL || 'http://localhost:8000';
const OUT = process.argv[2]; const SCHEME = process.argv[3] || 'light';
fs.mkdirSync(OUT, { recursive: true });
const SCREENS = ['u-login', 'u-input', 'u-gen', 'u-report', 'u-route', 'u-home', 'u-sched', 'u-study', 'u-coll', 'u-end', 'a-metrics', 'a-jobs', 'a-common', 'a-users'];
const VIEWPORTS = [[1280, 900], [390, 844]];
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, args: ['--no-sandbox'] });
  for (const [w, h] of VIEWPORTS) {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, colorScheme: SCHEME, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    await page.addInitScript(() => { let x = 12345; Math.random = () => (x = (x * 1664525 + 1013904223) % 4294967296) / 4294967296; });   // 여행 id 등 난수 고정
    await page.route(/^https?:\/\/(?!localhost|127\.0\.0\.1)/, r => r.abort());   // 외부 폰트 CDN 차단 → 로드 타이밍에 따른 흔들림 제거
    await page.goto(BASE + (process.env.QS || '/'));
    await page.evaluate(() => document.fonts.ready);
    await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}.toast{display:none!important}' });
    await page.evaluate(() => preset('default'));
    const shot = async name => { await page.waitForTimeout(60); await page.screenshot({ path: path.join(OUT, `${w}_${name}.png`) }); };
    for (const id of SCREENS) {
      await page.evaluate(i => {
        S.user = DEMO_USER;
        if (i === 'u-study') { const r = S.sched.find(r => r.ids && r.ids.length); S.studyDate = r.date; S.card = { date: r.date, i: 0, flipped: new Set() }; }
        if (i === 'u-end') { S.today = Dt.add(S.trip.cities[S.trip.cities.length - 1].end, 2); }
        go(i);
      }, id);
      await shot(id);
      if (id === 'u-study') { await page.evaluate(() => { S.card.flipped = new Set([S.card.i]); render(); }); await page.addStyleTag({ content: '.flip-inner{transform:rotateY(180deg)!important}' }).catch(() => {}); await shot('u-study-back'); }
    }
    // 모달·동의·말하기 상태
    await page.evaluate(() => { S.today = BASE_TODAY; preset('default'); go('u-login'); }); await shot('login-again');
    await ctx.close();
  }
  await b.close();
  console.log('저장:', OUT, fs.readdirSync(OUT).length, '개');
})().catch(e => { console.error(e); process.exit(2); });
