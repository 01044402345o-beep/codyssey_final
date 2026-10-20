/* 마디(MADI) 목업 — prd.md v2 기준 동작 시뮬레이션
   계산 규칙(R)은 PRD FR-TRIP-02, FR-SENT-02, FR-SCHED-01·02, FR-STUDY-03을 그대로 구현한다. */
'use strict';

/* ================= 기본 유틸 ================= */
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const phHtml = (s, lang = 'ko') => esc(lang === 'en' ? slotText(s) : s)
  .replace(/\[[^\[\]]+\]/g, m => `<span class="ph">${m}</span>`);

const Dt = {
  parse(s) { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d); },
  str(t) { return new Date(t).toISOString().slice(0, 10); },
  add(s, n) { return Dt.str(Dt.parse(s) + n * 864e5); },
  diff(a, b) { return Math.round((Dt.parse(a) - Dt.parse(b)) / 864e5); },
  range(a, b) { const out = []; for (let d = a; d <= b; d = Dt.add(d, 1)) out.push(d); return out; },
  md(s) { const t = new Date(Dt.parse(s)); return `${t.getUTCMonth() + 1}/${t.getUTCDate()}`; },
  dow(s) { return '일월화수목금토'[new Date(Dt.parse(s)).getUTCDay()]; },
  full(s) { return `${Dt.md(s)} (${Dt.dow(s)})`; },
};

function josa(w, withB, withoutB) {
  const code = String(w).trim().slice(-1).charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7a3) return w + ((code - 0xac00) % 28 ? withB : withoutB);
  return w + withoutB;
}

const I = {
  back: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  next: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>',
  check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>',
  x: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  speaker: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4V5z" fill="currentColor"/><path d="M15.5 8.5a5 5 0 010 7"/><path d="M19 5a10 10 0 010 14"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5L12 3l9 7.5V20a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
  cards: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="14" height="15" rx="2"/><path d="M7 3h12a2 2 0 012 2v13"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5z"/><path d="M4 19.5A2.5 2.5 0 006.5 22H20v-5"/></svg>',
  google: '<svg width="20" height="20" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>',
};

/* ================= 상수 ================= */
const DAYTYPE = {
  arrival: { label: '도착일', cls: 't-arr' },
  normal: { label: '일반일', cls: 't-norm' },
  transfer: { label: '이동일', cls: 't-tr' },
  departure: { label: '귀국일', cls: 't-dep' },
};
const SIT_BY_TYPE = { arrival: ['airport', 'immigration', 'hotel'], transfer: ['transit', 'hotel'], departure: ['hotel', 'airport'], normal: [] };
/* 날짜별 학습량에 들어가는 묶음(6 × 5 = 30)과 참고용 묶음. data.js 의 countsTowardPlan 으로만 나눈다 */
const SIT_ORDER = COMMON_SITUATIONS.filter(g => g.countsTowardPlan).map(g => g.key);
const REF_ORDER = COMMON_SITUATIONS.filter(g => !g.countsTowardPlan).map(g => g.key);
const KIND = {
  new: { label: '새 문장', cls: 'k-new' },
  review: { label: '복습', cls: 'k-review' },
  final: { label: '총복습', cls: 'k-final' },
  trip: { label: '여행 중', cls: 'k-trip' },
  free: { label: '자유 일정', cls: 'k-free' },
  drill: { label: '상황별 연습', cls: 'k-review' },
};
const ENGLISH_COUNTRIES = ['미국', '영국', '캐나다', '호주', '뉴질랜드', '아일랜드', '싱가포르', '필리핀', '몰타'];
const STAGE_OBJ = { report: '보고서를', route: '방문 순서를', sentences: '문장과 일정표를' };
const STAGE_NAME = { report: '보고서', route: '방문 순서', sentences: '문장·일정표' };
const STATUS_KO = {
  input_done: '입력 완료', report_requested: '보고서 요청', report_generating: '보고서 생성 중', report_done: '장소 선택 중', report_failed: '보고서 실패',
  route_requested: '방문 순서 요청', route_generating: '방문 순서 생성 중', route_failed: '방문 순서 실패',
  sentences_requested: '문장 요청', sentences_generating: '문장 생성 중', sentences_failed: '문장 실패', studying: '학습 중',
};
const STALE_MS = 15 * 60 * 1000;
const BASE_TODAY = '2026-09-22';
const DEMO_USER = { name: '김여행', email: 'demo.traveler@gmail.com' };
/* 로그인 없이 시작한 사용자. uid 가 없으니 서버에 올리지 않고 이 브라우저(공용 칸)에만 남는다(accountUid → '').
   Firebase 로그인을 붙인 뒤(a672c53) 가짜 로그인 문이 진짜 문이 되어 가입 없이는 앱을 볼 수 없었다 — 그 입구를 다시 연다. */
const GUEST_USER = { name: '손님', email: '로그인하지 않음 · 이 브라우저에만 저장', guest: true };
const isGuest = () => !!(S.user && S.user.guest);
const authDraft = { email: '', name: '' };   // 이메일 폼 입력 — 로그인 전환 화면이 폼을 다시 그려도 남긴다(비밀번호는 담지 않는다)
const fbOn = () => !!(window.FirebaseAuth && FirebaseAuth.enabled);
function userName() { return (S.user && S.user.name) || DEMO_USER.name; }
function userEmail() { return (S.user && S.user.email) || DEMO_USER.email; }

/* ================= 계산 규칙 (shared/rules) ================= */
const R = {
  /* FR-TRIP-02 날짜 종류 */
  buildDays(cities) {
    const start = cities[0].start, end = cities[cities.length - 1].end;
    return Dt.range(start, end).map(date => {
      let idx = cities.findIndex((c, i) => date >= c.start && (date < c.end || (i === cities.length - 1 && date <= c.end)));
      if (idx < 0) idx = 0;
      const types = [];
      if (date === start) types.push('arrival');
      if (idx > 0 && date === cities[idx].start) types.push('transfer');
      if (date === end) types.push('departure');
      if (!types.length) types.push('normal');
      const cap = types.includes('normal') ? { attr: 2, rest: 2 } : { attr: 1, rest: 1 };
      return { date, city: cities[idx].name, types, cap, placeIds: [] };
    });
  },
  cityBase(days) {
    const m = {};
    days.forEach(d => { m[d.city] ??= { attr: 0, rest: 0 }; m[d.city].attr += d.cap.attr; m[d.city].rest += d.cap.rest; });
    return m;
  },
  /* FR-TRIP-01 입력 검사 (화면·서버 공용) */
  validate(tr, today) {
    const e = {}, w = [];
    if (!tr.country.trim()) e.country = '나라를 입력해 주세요.';
    if (tr.cities.length < 1) e.cities = '도시를 1곳 이상 입력해 주세요.';
    if (tr.cities.length > 5) e.cities = '도시는 최대 5곳까지 입력할 수 있어요.';
    const names = new Set();
    tr.cities.forEach((c, i) => {
      const nm = c.name.trim();
      if (!nm) e['cn' + i] = '도시 이름을 입력해 주세요.';
      else if (names.has(nm)) e['cn' + i] = '같은 도시를 두 번 입력했어요.';
      names.add(nm);
      if (!c.start || !c.end) { e['cd' + i] = '체류 날짜를 입력해 주세요.'; return; }
      if (c.start > c.end) e['cd' + i] = '체류 종료일이 시작일보다 빠를 수 없어요.';
      else if (c.start === c.end && tr.cities.length > 1) e['cd' + i] = '도시마다 최소 1박이 필요해요. (도시 1곳 당일치기만 예외)';
      const prev = tr.cities[i - 1];
      if (i > 0 && prev.end && !e['cd' + i]) {
        if (c.start > prev.end) e['cd' + i] = `${Dt.md(prev.end)}와 ${Dt.md(c.start)} 사이에 빈 날이 있어요. 앞 도시 종료일과 같은 날로 맞춰 주세요.`;
        else if (c.start < prev.end) e['cd' + i] = '앞 도시와 날짜가 겹쳐요. 앞 도시 종료일과 같은 날이어야 해요.';
      }
    });
    const first = tr.cities[0]?.start, last = tr.cities[tr.cities.length - 1]?.end;
    if (first && first < today && !e.cd0) e.cd0 = '여행 시작일은 오늘 또는 그 이후여야 해요.';
    if (!tr.studyStart) e.studyStart = '학습 시작일을 입력해 주세요.';
    else if (tr.studyStart < today) e.studyStart = '학습 시작일은 오늘 또는 그 이후여야 해요.';
    else if (last && tr.studyStart > last) e.studyStart = '학습 시작일은 여행 종료일보다 늦을 수 없어요.';
    const ok = !Object.keys(e).length;
    if (ok) {
      const pre = R.preDays(tr.studyStart, first).length;
      if (pre <= 3) w.push(`여행 전 학습일이 ${pre}일이에요. 학습 기간이 짧아 하루 학습량과 여행 중 새 문장이 많아져요.`);
    }
    return { errors: e, warnings: w, ok };
  },
  preDays(studyStart, tripStart) {
    if (!studyStart || !tripStart || studyStart >= tripStart) return [];
    return Dt.range(studyStart, Dt.add(tripStart, -1));
  },
  /* FR-SCHED-01 복습일 규칙 */
  kinds(N) {
    if (N >= 7) {
      const a = [];
      for (let i = 0; i < N - 2; i++) a.push(i % 4 === 3 ? 'review' : 'new');
      return a.concat(['final', 'final']);
    }
    if (N >= 4) return Array(N - 1).fill('new').concat(['final']);
    return Array(N).fill('new');
  },
  /* FR-SENT-02 문장 수 자동 조절 (확정 알고리즘) */
  counts(D, n) {
    const C = 30;
    if (D === 0) { const per = Array(n).fill(3); return { per, T: C + 3 * n, A: null, P: null }; }
    const P = D * 5 - C;
    let per;
    if (P <= 3 * n) per = Array(n).fill(3);
    else {
      const base = Math.floor(P / n), r = P - base * n; // % 연산자 사용 금지 (음수 대비)
      per = base >= 10 ? Array(n).fill(10) : Array.from({ length: n }, (_, i) => (i < r ? base + 1 : base));
    }
    const T = C + per.reduce((a, b) => a + b, 0);
    const A = Math.min(10, Math.max(5, Math.ceil(T / D)));
    return { per, T, A, P };
  },
  /* FR-ROUTE-01 방문 순서 검증 함수 */
  validateRoute(days, places) {
    const errs = [], seen = new Map();
    const byId = Object.fromEntries(places.map(p => [p.id, p]));
    days.forEach(d => {
      if (d.placeIds.length > d.cap.attr + d.cap.rest) errs.push(`${Dt.md(d.date)} 하루 장소 수 초과`);
      d.placeIds.forEach(id => {
        if (byId[id]?.city !== d.city) errs.push(`${Dt.md(d.date)} 다른 도시 장소 배치`);
        seen.set(id, (seen.get(id) || 0) + 1);
      });
    });
    places.filter(p => p.selected).forEach(p => {
      const n = seen.get(p.id) || 0;
      if (n === 0) errs.push(`${p.name} 누락`);
      if (n > 1) errs.push(`${p.name} 중복`);
    });
    return errs;
  },
  /* 코드 배치: 지역 이름 순 정렬 → 날짜 앞에서부터 기본 장소 수만큼 채움 */
  placeByCode(days, places) {
    days.forEach(d => (d.placeIds = []));
    const cities = [...new Set(days.map(d => d.city))];
    cities.forEach(city => {
      const ps = places.filter(p => p.selected && p.city === city)
        .sort((a, b) => a.area.localeCompare(b.area, 'ko') || (a.kind === b.kind ? 0 : a.kind === 'attraction' ? -1 : 1));
      let i = 0;
      days.filter(d => d.city === city).forEach(d => {
        const cap = d.cap.attr + d.cap.rest;
        while (d.placeIds.length < cap && i < ps.length) {
          d.placeIds.push(ps[i].id);
          ps[i].visitDate = d.date; ps[i].visitOrder = d.placeIds.length;
          i++;
        }
      });
    });
    return days;
  },
};

/* ================= 상태 ================= */
let S;
let genTimer = null, genToken = 0, placeSeq = 0, genAbort = null;
const API = AI.apiBase(location);            // 서버 주소(저장하지 않음). base === null 이면 폴백 전용
if (window.FirebaseAuth) FirebaseAuth.start();
/* window.localStorage 는 사이트 데이터 차단 시 접근만 해도 SecurityError 를 던진다. 그러면 null — AI.* 저장 함수는 null 을 "저장 불가"로 처리한다 */
const STORE = (() => { try { return window.localStorage; } catch (e) { return null; } })();
/* ---------- A3: 새로고침해도 학습 진도가 남는다 ----------
   담는 필드는 v, at, done, screen, studyDate, card 의 date·i·back·flipped 다.
   복습 목록(cd_weak), 말하기 동의(cd_consent), 여행 입력(cd_trip)도 같은 계정 칸에 둔다.
   여행 입력은 나라·도시별 체류 날짜·학습 시작일만이다. 장소·문장 본문은 담지 않는다.
   uid 가 없으면 기존 키 그대로라 데모·검사의 기록이 남는다. uid 가 있으면 ':uid' 를 붙인다.
   로그인 계정의 진도·복습·동의·여행 입력은 서버에도 올린다. 테마·배너·스와이프 안내는 계정과 무관하다.
   저장소가 막힌 브라우저(STORE === null)에서는 기능만 조용히 꺼진다. */
const SESSION_KEY = 'cd_session';
const SESSION_V = 1;
const SESSION_MAX_AGE = 30 * 24 * 60 * 60 * 1000;   /* 30일 지난 기록은 버린다 */
const PROG = { done: {}, pre: {} };                 /* done: 'YYYY-MM-DD' → 완료 시각(ms). pre: 미리 학습을 마친 날짜 — 그날이 되면 done 으로 옮긴다(settlePre) */
const RESTORE = { screen: null, studyDate: null, card: null, trip: null };
let SESS_READY = false;                             /* 복원이 끝나기 전에는 저장하지 않는다 — 빈 진도로 덮어쓰지 않기 위해 */
let skipStateWrite = false;                         /* 계정을 갈아 끼우는 동안 이전 기록을 새 칸에 쓰지 않는다 */
let stateTimer = null;
let accountEpoch = 0;
let accountClosed = false;   /* 서버가 '탈퇴한 계정'이라 답한 뒤 반복 처리하지 않게 */

function accountUid() {
  const u = S && S.user;
  if (!u || u.provider === 'anonymous') return '';
  const uid = u.uid;
  if (typeof uid !== 'string' || !uid || uid.length > 128 || /[:/\\\s?#]/.test(uid)) return '';
  return uid;
}
function personalStore() { return AI.scopedStorage(STORE, accountUid()); }
/* 여행 입력(온보딩 1단계)도 같은 계정 칸에 둔다. 장소·문장 본문은 담지 않는다 — 화면이 규칙으로 다시 만든다. */
function loadTripHere() { return AI.loadTrip(personalStore()); }
function saveTripHere(t) {
  const ok = AI.saveTrip(personalStore(), t ? tripInputOf(t) : null);
  scheduleStatePush();
  return ok;
}
const weakList = () => AI.loadWeak(personalStore());
function saveWeakList(list) {
  const ok = AI.saveWeak(personalStore(), list);
  scheduleStatePush();
  return ok;
}
function saveConsentHere(voice) {
  const ok = AI.saveConsent(personalStore(), voice);
  scheduleStatePush();
  return ok;
}
function withdrawHere() {
  const ok = AI.withdrawConsent(personalStore());
  scheduleStatePush();
  return ok;
}

function sessionRead() {
  const box = personalStore();
  if (!box) return null;
  try {
    const d = JSON.parse(box.getItem(SESSION_KEY) || 'null');
    if (!d || d.v !== SESSION_V || typeof d.at !== 'number' || Date.now() - d.at > SESSION_MAX_AGE) return null;
    return d;
  } catch (e) { return null; }
}
/* 학습 카드를 연 적 없으면 date 가 null 이다. 서버는 그 객체를 거절하므로, 그때는 카드 없음(null)으로 보낸다. */
function sessionCard(card) {
  if (!card || typeof card.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(card.date)) return null;
  const flipped = card.flipped instanceof Set ? [...card.flipped] : (Array.isArray(card.flipped) ? card.flipped : []);
  return { date: card.date, i: card.i, back: Number.isInteger(card.back) ? card.back : null, flipped };
}
function sessionWrite() {
  const box = personalStore();
  if (!box || !SESS_READY || skipStateWrite) return;
  try {
    box.setItem(SESSION_KEY, JSON.stringify({
      v: SESSION_V, at: Date.now(), done: PROG.done, ...(Object.keys(PROG.pre).length ? { pre: PROG.pre } : {}), screen: S.screen, studyDate: S.studyDate,
      card: sessionCard(S.card),
    }));
  } catch (e) { /* 저장 불가(시크릿 모드·용량 초과): 이번 방문 동안만 유지 */ }
  scheduleStatePush();
}
function sessionClear() {
  const box = personalStore();
  if (!box) return;
  try { box.removeItem(SESSION_KEY); } catch (e) { /* 저장소 막힘 */ }
  scheduleStatePush();
}

function localState() {
  const box = personalStore();
  const empty = { session: null, weak: [], consent: null, trip: null };
  if (!box) return empty;
  let session = null;
  try {
    const d = JSON.parse(box.getItem(SESSION_KEY) || 'null');
    if (d && d.v === SESSION_V) session = { ...d, card: sessionCard(d.card) };
  } catch (e) { session = null; }
  let consent = null;
  try {
    const c = JSON.parse(box.getItem(AI.CONSENT_KEY) || 'null');
    if (c && c.version === AI.CONSENT_VERSION && c.voice === true && typeof c.at === 'string')
      consent = { version: c.version, voice: true, at: c.at };
  } catch (e) { consent = null; }
  return { session, weak: AI.loadWeak(box), consent, trip: AI.loadTrip(box) };
}
function stateHas(state) {
  if (!state) return false;
  if (state.session) return true;
  if (Array.isArray(state.weak) && state.weak.length) return true;
  if (state.trip) return true;
  return !!(state.consent && state.consent.voice === true);
}
function writeLocalState(state) {
  const box = personalStore();
  if (!box || !state) return;
  try {
    if (state.session) box.setItem(SESSION_KEY, JSON.stringify(state.session));
    else box.removeItem(SESSION_KEY);
  } catch (e) { /* 저장소 막힘 */ }
  AI.saveWeak(box, Array.isArray(state.weak) ? state.weak : []);
  AI.saveTrip(box, state.trip || null);
  try {
    if (state.consent && state.consent.voice === true)
      box.setItem(AI.CONSENT_KEY, JSON.stringify({ version: state.consent.version, voice: true, at: state.consent.at }));
    else box.removeItem(AI.CONSENT_KEY);
  } catch (e) { /* 저장소 막힘 */ }
}
async function pushPayload(uid, payload) {
  const epoch = accountEpoch;   // 응답이 늦게 와도 다른 계정을 건드리지 않게 지금 시점을 기억한다
  if (!uid || !payload || API.base === null || !window.FirebaseAuth || !FirebaseAuth.idToken) return;
  let token = '';
  try { token = await FirebaseAuth.idToken(); } catch (e) { token = ''; }
  if (!token) return;
  // 토큰을 받는 사이에 계정이 바뀌었거나 탈퇴·초기화가 시작됐으면 올리지 않는다(지운 기록을 되살리지 않게).
  if (skipStateWrite || accountUid() !== uid) return;
  const live = FirebaseAuth.account && FirebaseAuth.account.uid;
  if (live && live !== uid) return;
  try {
    const res = await fetch((API.base || '') + '/user/state', {
      method: 'PUT',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    });
    if (!res.ok) {
      let code = '';
      try { code = (await res.json()).detail; } catch (e) { code = ''; }
      // 다른 기기에서 탈퇴한 계정: 이 기기의 토큰이 아직 살아 있어도 서버가 거부한다.
      if (res.status === 403 && code === 'account_deleted') handleAccountDeleted(uid, epoch).catch(() => {});
    }
  } catch (e) { /* 서버가 막혀도 이 브라우저 기록은 남는다 */ }
}
/* 서버가 '탈퇴한 계정'이라 답했을 때(다른 기기에서 탈퇴) — 로컬을 비우고 로그인 화면으로 보낸다.
   uid·epoch 를 함께 받아 **늦게 도착한 응답이 다른 계정을 지우지 않게** 한다(계정을 갈아 끼운 뒤 도착).
   계정이 아직 살아 있으면(관리자 경로가 도중 실패해 흔적만 남은 경우) 지우지 않고 알린다 — 로컬 기록 손실을 막는다. */
async function handleAccountDeleted(uid, epoch) {
  if (accountClosed) return;
  if (uid && accountUid() !== uid) return;                                  // 이미 다른 계정이다
  if (epoch !== undefined && epoch !== accountEpoch) return;                // 계정을 갈아 끼운 뒤 도착한 응답
  if (window.FirebaseAuth && FirebaseAuth.enabled && FirebaseAuth.stillAlive && FirebaseAuth.account) {
    let alive = false;
    try { alive = await FirebaseAuth.stillAlive(); } catch (e) { alive = false; }
    if (accountClosed) return;
    if (uid && accountUid() !== uid) return;
    if (epoch !== undefined && epoch !== accountEpoch) return;
    if (alive) {
      // 서버는 '탈퇴한 계정'이라 했는데 계정이 살아 있다 = 부분 실패. 증거를 남기도록 보고한다.
      reportWithdrawIssue('still_alive', true).catch(() => {});
      toast('계정 저장이 잠시 막혔어요. 잠시 뒤 다시 시도해 주세요.');
      return;
    }
  }
  accountClosed = true;
  try { clearAccountStorage(); } catch (e) { /* 저장소 막힘 */ }
  if (window.FirebaseAuth && FirebaseAuth.enabled) { try { FirebaseAuth.signOut(); } catch (e) { /* 화면 상태는 비운다 */ } }
  SESS_READY = false;
  S.user = null;
  S.trip = null; resetDerived();
  S.archived = [];
  PROG.done = {}; PROG.pre = {};
  RESTORE.screen = null; RESTORE.studyDate = null; RESTORE.card = null; RESTORE.trip = null;
  aiRefreshKey = null;
  SESS_READY = true;
  // skipStateWrite 는 건드리지 않는다 — 탈퇴가 진행 중이었다면 그 불변식을 깨고 업로드를 되살린다.
  // (S.user 가 비었으므로 이후 업로드는 uid 가 없어 스스로 멈춘다. 다음 로그인에서 adoptAccount 가 되돌린다.)
  toast('이 계정은 탈퇴되어 이 기기에서도 로그아웃했어요.');
  go('u-login');
}
/* 탈퇴가 예상 밖 상태로 끝났음을 서버에 보고한다(증거 봉인 트리거).
   개인정보·토큰은 보내지 않는다 — 상태 코드와 화면 이름뿐이다. 실패해도 조용히 넘어간다. */
/* 반환: 'sent' | 'no_login'(서버는 로그인한 사용자의 보고만 받는다) | 'failed'.
   예전에는 결과를 돌려주지 않아, 로그아웃 상태에서 아무것도 보내지 않고도 '보고했어요'라고 안내했다. */
async function reportWithdrawIssue(reason, serverSaidErased) {
  const uid = accountUid();
  if (!uid || API.base === null || !window.FirebaseAuth || !FirebaseAuth.idToken) return 'no_login';
  let token = '';
  try { token = await FirebaseAuth.idToken(); } catch (e) { token = ''; }
  if (!token) return 'no_login';
  try {
    const res = await fetch((API.base || '') + '/diagnostics/withdraw', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        reason: String(reason || '').slice(0, 200),
        screen: String(S.screen || '').slice(0, 40),
        has_account: !!accountUid(),
        server_said_erased: !!serverSaidErased,
      }),
      keepalive: true,
    });
    return res && res.ok ? 'sent' : 'failed';
  } catch (e) { return 'failed'; }   // 보고 실패는 사용자 흐름을 막지 않는다
}
function scheduleStatePush() {  const uid = accountUid();
  if (!uid || !personalStore() || API.base === null || !SESS_READY || skipStateWrite) return;
  const payload = localState();
  if (stateTimer) clearTimeout(stateTimer);
  stateTimer = setTimeout(() => { stateTimer = null; pushPayload(uid, payload); }, 600);
}
function pushStateNow() {
  if (stateTimer) { clearTimeout(stateTimer); stateTimer = null; }
  const uid = accountUid();
  if (!uid || !SESS_READY || skipStateWrite) return Promise.resolve();
  return pushPayload(uid, localState());
}
async function pullAccount(epoch) {
  const uid = accountUid();
  if (!uid || API.base === null || !window.FirebaseAuth || !FirebaseAuth.idToken) return { failed: true };
  let token = '';
  try { token = await FirebaseAuth.idToken(); } catch (e) { token = ''; }
  if (epoch !== accountEpoch) return { dropped: true };
  if (!token) return { failed: true };
  try {
    const res = await fetch((API.base || '') + '/user/state', {
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' },
      cache: 'no-store',
    });
    if (epoch !== accountEpoch) return { dropped: true };
    if (res.status === 403) {
      let code = '';
      try { code = (await res.json()).detail; } catch (e) { code = ''; }
      if (code === 'account_deleted') return { gone: true };   // 탈퇴한 계정 — 기록이 없는 것으로 오인해 다시 올리지 않게
    }
    if (!res.ok) return { failed: true };
    return { failed: false, remote: await res.json() };
  } catch (e) { return { failed: true }; }
}
function fillProgress(d) {
  if (!d) return;
  if (d.done && typeof d.done === 'object')
    Object.keys(d.done).forEach(k => { if (/^\d{4}-\d{2}-\d{2}$/.test(k) && typeof d.done[k] === 'number') PROG.done[k] = d.done[k]; });
  if (d.pre && typeof d.pre === 'object')
    Object.keys(d.pre).forEach(k => { if (/^\d{4}-\d{2}-\d{2}$/.test(k) && typeof d.pre[k] === 'number') PROG.pre[k] = d.pre[k]; });
  RESTORE.screen = typeof d.screen === 'string' ? d.screen : null;
  RESTORE.studyDate = typeof d.studyDate === 'string' ? d.studyDate : null;
  const c = d.card;
  if (c && typeof c.date === 'string' && Number.isInteger(c.i) && c.i >= 0 && Array.isArray(c.flipped))
    RESTORE.card = { date: c.date, i: c.i, back: Number.isInteger(c.back) ? c.back : null, flipped: c.flipped.filter(k => Number.isInteger(k) && k >= 0) };
  else RESTORE.card = null;
}
function resumeScreen() {
  /* 저장해 둔 여행 입력으로 실제 여행을 되살린다. 계획은 그 화면에 들어갈 때 규칙으로 다시 만들어진다. */
  if (RESTORE.trip && !S.trip) S.trip = tripFromInput(RESTORE.trip);
  let dest = RESTORE.screen && RESTORE.screen !== 'u-login' && RESTORE.screen !== 'u-auth' && SCR[RESTORE.screen] ? RESTORE.screen : null;   // 로그인 단계는 되살리지 않는다
  /* 만들던 보고서·문장 생성은 메모리에서 진행돼 새로고침으로 이어지지 않는다 — 실제 여행이 있으면 홈으로 보낸다. */
  if (dest && S.trip && (dest === 'u-gen' || dest === 'u-report')) dest = 'u-home';
  /* 계정 없이 저장된 화면이 있으면 손님으로 이어서 연다. 그대로 두면 화면 준비(ensure)가 데모 사용자 '김여행'으로 채운다. */
  if (dest && !S.user && fbOn()) S.user = GUEST_USER;
  if (!dest) {
    /* 첫 렌더는 FirebaseAuth.ready 전이라 로그인 화면이 아직 이메일 폼을 모른다.
       준비가 끝난 지금 다시 그려야 Firebase 가 켜진 환경에서 이메일 로그인이 보인다. */
    render();
    SESS_READY = true;
    skipStateWrite = false;
    return;
  }
  navFromMenu(dest);
  if (RESTORE.studyDate) S.studyDate = RESTORE.studyDate;
  if (RESTORE.card) S.card = { date: RESTORE.card.date, i: RESTORE.card.i, back: RESTORE.card.back, flipped: new Set(RESTORE.card.flipped) };
  render();
  SESS_READY = true;
  skipStateWrite = false;
  if (RESTORE.trip) refreshAiSentences();   // 규칙으로 다시 만든 틀 문장을 AI 문장으로 채운다(백그라운드)
}
async function adoptAccount(account, opts) {
  const epoch = ++accountEpoch;
  accountClosed = false;   // 새 로그인/계정 전환 — 탈퇴 감지 상태를 초기화
  const navigate = !opts || opts.navigate !== false;
  skipStateWrite = true;
  SESS_READY = false;
  if (stateTimer) { clearTimeout(stateTimer); stateTimer = null; }
  S.user = account || null;
  S.trip = null; resetDerived();          // 계정을 갈아 끼우면 이전 계정의 여행·계획을 들고 가지 않는다
  PROG.done = {}; PROG.pre = {};
  RESTORE.screen = null;
  RESTORE.studyDate = null;
  RESTORE.card = null;
  RESTORE.trip = null;
  fillProgress(sessionRead());
  const hadLocal = stateHas(localState());
  const pulled = await pullAccount(epoch);
  if (pulled.dropped || epoch !== accountEpoch) return;
  if (pulled.gone) {
    // 서버가 '탈퇴한 계정'이라 답했다: 여는 김에 정리하고 로그인 화면으로 보낸다(계정이 살아 있으면 알림만).
    SESS_READY = true;
    skipStateWrite = false;
    await handleAccountDeleted(account && account.uid, epoch);
    return;
  }
  if (!pulled.failed && stateHas(pulled.remote)) {
    const remote = pulled.remote;
    const remoteTrip = AI.cleanTrip(remote.trip);
    remote.trip = AI.preferTrip(remote.trip, loadTripHere());
    writeLocalState(remote);
    PROG.done = {}; PROG.pre = {};
    RESTORE.screen = null;
    RESTORE.studyDate = null;
    RESTORE.card = null;
    fillProgress(sessionRead());
    // 서버 문서에 여행 입력이 없고 이 브라우저에만 있으면, 그 입력을 서버로 올려 다음 로그인에서 지워지지 않게 한다.
    if (!remoteTrip && remote.trip) {
      SESS_READY = true;
      skipStateWrite = false;
      await pushStateNow();
      if (epoch !== accountEpoch) return;
      skipStateWrite = true;
      SESS_READY = false;
    }
  } else if (!pulled.failed && hadLocal) {
    SESS_READY = true;
    skipStateWrite = false;
    await pushStateNow();
    if (epoch !== accountEpoch) return;
    skipStateWrite = true;
    SESS_READY = false;
  }
  RESTORE.trip = loadTripHere();
  if (navigate) resumeScreen();
  else {
    SESS_READY = true; skipStateWrite = true;
    // 로그인 직후(navigate:false): 계정에 실제 여행이 있으면 계획을 다시 만들어 곧바로 홈으로 갈 수 있게 한다.
    if (RESTORE.trip && !S.trip) { S.trip = tripFromInput(RESTORE.trip); ensure('plan'); }
    if (RESTORE.trip) refreshAiSentences();   // 틀 문장을 AI 문장으로 채운다(백그라운드)
  }
}
/* S.sched 는 매번 새로 만들어지므로, 저장해 둔 완료 기록을 날짜로 다시 붙인다 */
function applyProgress() {
  if (!S || !S.sched) return;
  S.sched.forEach(r => {
    if (r.kind === 'free') return;
    const at = PROG.done[r.date];
    if (at) { r.completed = true; r.completedAt = at; }
    else { r.completed = false; r.completedAt = null; }
  });
}
/* 생성 취소: 토큰을 올려 오래된 응답이 상태를 덮어쓰지 못하게 하고, 진행 중 요청도 중단한다 */
function cancelGen() { genToken++; clearTimeout(genTimer); if (genAbort) { genAbort.abort(); genAbort = null; } }

function defaultDraft(base) {
  return {
    country: '미국',
    cities: [
      { name: '뉴욕', start: Dt.add(base, 49), end: Dt.add(base, 52) },
      { name: '보스턴', start: Dt.add(base, 52), end: Dt.add(base, 54) },
    ],
    studyStart: Dt.add(base, 9),
  };
}

function initState() {
  cancelGen();
  const today = AI.calendarToday(new Date());
  S = {
    screen: 'u-login', user: null, authMode: null, today,
    flags: { fail: false, stuck: false, routeInvalid: false, noTts: false },
    draft: defaultDraft(today), showErrors: false,
    trip: null, places: [], reportMeta: {}, reportMode: 'example', routeView: 'code', itineraryBlocks: null,
    days: [], sents: [], smap: {}, sched: [], plan: null, aiPools: {}, aiBy: {},
    archived: [], gen: null, cityTab: null, showCand: {},
    studyDate: null, drill: null, card: { date: null, i: 0, flipped: new Set() }, justCompleted: null,
    coll: { tab: 'common', filter: 'all' }, schedFilter: 'all', ttsRate: 0.95,
    commons: JSON.parse(JSON.stringify(COMMON_SITUATIONS)), commonsDraft: null,
    jobFilter: 'all', mockTrips: JSON.parse(JSON.stringify(MOCK_TRIPS)), modal: null, lastScreen: null,
    sheet: false,   // 학습 화면 하단 '회화 연습' 시트가 열려 있는지
  };
}

const tripTitle = t => `${t.country} · ${t.cities.map(c => c.name).join(' → ')}`;
const mark = k => { S.trip.stageAt[k] ??= Date.now(); };
const isStale = () => S.trip?.genStartedAt && /_generating$/.test(S.trip.status) && Date.now() - S.trip.genStartedAt > STALE_MS;

function createTrip(d) {
  if (S.trip && !S.trip.archived) archiveTrip();
  S.trip = tripFromInput(d);
  resetDerived();
  saveTripHere(S.trip);
}
/* 여행 입력만 뽑는다 — 저장하는 값. 장소·문장 본문은 담지 않는다(화면이 규칙으로 다시 만든다). */
function tripInputOf(t) {
  return { country: t.country, cities: t.cities.map(c => ({ name: c.name, start: c.start, end: c.end })), studyStart: t.studyStart };
}
function tripFromInput(d, id) {
  const cities = d.cities.map(c => ({ ...c, name: String(c.name || '').trim() }));
  return {
    id: id || 'tr_' + Math.random().toString(16).slice(2, 6), country: String(d.country || '').trim(), cities,
    studyStart: d.studyStart, tripStart: cities[0].start, tripEnd: cities[cities.length - 1].end,
    status: 'input_done', regenerateCount: 0, reportRound: 0, failStreak: 0, genStartedAt: null, error: null,
    routeFallback: false, stageAt: { input_done: Date.now() }, requests: 0, fails: 0, reportSec: null, requestedAt: null, archived: false,
  };
}
/* 입력이 바뀌면 여행에서 파생된 것(장소·방문 순서·문장·일정표)을 모두 버린다. 계획은 다시 만들어야 한다. */
function resetDerived() {
  S.places = []; S.reportMeta = {}; S.reportMode = 'example'; S.routeView = 'code'; S.itineraryBlocks = null;
  S.days = []; S.sents = []; S.refs = []; S.smap = {}; S.sched = []; S.plan = null;
  S.aiPools = {}; S.aiBy = {};   // 지난 여행의 AI 문장을 물려받지 않는다(전체 재생성 때 이전 문장이 섞이지 않게)
  S.cityTab = S.trip ? S.trip.cities[0].name : null; S.showCand = {}; S.studyDate = null; S.justCompleted = null; resetCard();
}
/* 여행 설정 수정: id 와 진행 기록은 두고 입력만 바꾼 뒤 보고서·방문 순서·문장을 다시 만든다. */
function editTrip(d) {
  const t = S.trip;
  if (!t) return createTrip(d);
  Object.assign(t, tripFromInput(d, t.id));
  resetDerived();
  saveTripHere(t);
}
/* 날짜만 바뀐 경우: 도시·문장은 그대로 두고 여행 날짜와 학습 일정표만 다시 계산한다. */
function applyTripDates(d) {
  const t = S.trip;
  t.studyStart = d.studyStart;
  t.cities = d.cities.map(c => ({ ...c, name: String(c.name || '').trim() }));
  t.tripStart = t.cities[0].start; t.tripEnd = t.cities[t.cities.length - 1].end;
  const ok = saveTripHere(t);
  S.days = S.itineraryBlocks
    ? AI.placeBlocksOnDays(R.buildDays(t.cities), S.places, t.cities, S.itineraryBlocks)
    : makeRoute().days;
  buildPlan();
  return ok;
}
/* 도시 이름 목록(순서 포함)이 같은가. 같으면 장소·문장을 다시 만들 필요가 없다(날짜만 다시 계산). */
function sameTripCities(a, b) {
  if (a.length !== b.length) return false;
  return a.every((c, i) => String(c.name || '').trim() === b[i].name);
}
/* 날짜만 바꿀 때 만들어질 일정표의 날짜 집합. 완료한 날이 일정에서 빠지는지 저장 전에 확인하는 데 쓴다.
   buildPlan 의 일정 구성과 같은 규칙(여행 전 날짜 + studyStart 이후의 여행 날짜)을 따른다. */
function tripSchedDates(d) {
  const cities = d.cities.map(c => ({ ...c, name: String(c.name || '').trim() }));
  const pre = R.preDays(d.studyStart, cities[0].start);
  const from = d.studyStart > cities[0].start ? d.studyStart : cities[0].start;
  const trip = R.buildDays(cities).map(x => x.date).filter(dt => dt >= from);
  return new Set([...pre, ...trip]);
}
/* 홈 D-Day 카드·사이드바에서 여행 설정 수정 화면을 연다. 현재 여행 입력을 초안으로 채운다. */
function openTripEdit() {
  if (!S.trip) { navFromMenu('u-input'); return; }
  S.draft = tripInputOf(S.trip);
  S.showErrors = false;
  go('u-edit');
}

function archiveTrip() {
  S.trip.archived = true;
  S.archived.unshift({ id: S.trip.id, route: tripTitle(S.trip), dates: `${Dt.md(S.trip.tripStart)}~${Dt.md(S.trip.tripEnd)}` });
}
function resetCard(date = null) { S.card = { date, i: 0, flipped: new Set() }; S.sheet = false; }

/* ---------- 보고서 (AI-01 흉내) ---------- */
function genReport(t, round) {
  const base = R.cityBase(R.buildDays(t.cities));
  const out = []; S.reportMeta = {};
  const rot = (a, k) => { k = k % a.length; return a.slice(k).concat(a.slice(0, k)); };
  t.cities.forEach(c => {
    const b = base[c.name]; if (!b) return;
    const pool = PLACE_POOLS[c.name] || genericPool(c.name);
    let found = 0;
    const take = (arr, need, kind) => rot(arr, round * 2).slice(0, need + 2).forEach((p, i) => {
      const cand = i >= need; if (!cand) found++;
      out.push({
        id: 'p' + (++placeSeq), city: c.name, kind, name: p.name, en: p.en || p.name, area: p.area, desc: p.desc, reason: p.reason,
        cuisine: p.cuisine || null, menuEn: p.menuEn || null, menuKo: p.menuKo || null, sources: p.sources || [],
        isCandidate: cand, selected: !cand, visitDate: null, visitOrder: null, count: 0,
      });
    });
    take(pool.attr, b.attr, 'attraction');
    take(pool.rest, b.rest, 'restaurant');
    S.reportMeta[c.name] = { base: b.attr + b.rest, found };
  });
  return out;
}
const selCount = city => S.places.filter(p => p.city === city && p.selected).length;

/* ---------- 문장 + 일정표 (AI-03 흉내 + FR-SENT-02, FR-SCHED-01·02) ---------- */
function placeSentences(p, n) {
  const fill = s => s.replace('{menuEn}', p.menuEn || '').replace('{menuKo}', p.menuKo || '').replace('{en}', p.en || p.name).replace('{name}', p.name);
  const ai = (S.aiBy[p.id] || []).slice(0, n).map(s => ({
    situation: s.situation, en: s.en, ko: s.ko, categoryId: s.categoryId, situationId: s.situationId, targetsWeak: s.targetsWeak,
    ai: s.kind === 'ai', sample: s.kind === 'sample',
  }));
  const used = new Set(ai.map(s => s.en.toLowerCase()));
  const bank = PLACE_TEMPLATES[p.kind] || (p.kind === 'cafe' ? PLACE_TEMPLATES.restaurant : []);
  const usable = bank.filter(t => !p.live || !(t.en + t.ko).includes('{menu'));
  const rest = usable.map(t => ({ situation: t.situation, en: fill(t.en), ko: fill(t.ko) }))
    .filter(t => !used.has(t.en.toLowerCase())).slice(0, Math.max(0, n - ai.length));
  return [...ai, ...rest];
}

/* AI 풀 키: 도시 + 카테고리 (카테고리가 없으면 AI 대상 아님) */
const aiKey = (city, cat) => cat ? city + '|' + cat : null;

function buildPlan() {
  const t = S.trip;
  const ordered = S.places.filter(p => p.selected).sort((a, b) => a.visitDate.localeCompare(b.visitDate) || a.visitOrder - b.visitOrder);
  const pre = R.preDays(t.studyStart, t.tripStart);
  const kinds = R.kinds(pre.length);
  const D = kinds.filter(k => k === 'new').length;
  const { per, T, A, P } = R.counts(D, ordered.length);
  ordered.forEach((p, i) => (p.count = per[i]));
  // AI 풀은 여러 번 buildPlan 해도 같은 결과가 나오도록 복사해서 쓴다 (공통 풀은 한 번 쓰면 빠진다)
  const cityPools = {};
  S.aiBy = {};
  ordered.forEach(p => {
    const key = aiKey(p.city, AI.categoryOfKind(p.kind));
    const e = S.aiPools[key]; if (!e) return;
    const pools = cityPools[key] ??= { byPlace: e.pools.byPlace, common: e.pools.common.slice() };
    S.aiBy[p.id] = AI.takeForPlace(pools, p.id, p.count).map(s => ({ ...s, kind: e.kind }));
  });

  const sents = [];
  SIT_ORDER.forEach(key => {
    const g = S.commons.find(x => x.key === key);
    g.items.forEach((it, j) => sents.push({ id: `c-${key}-${j}`, source: 'common', sit: key, sitLabel: g.label, ...it }));
  });
  ordered.forEach(p => placeSentences(p, p.count).forEach((s, j) => sents.push({ id: `${p.id}-${j}`, source: 'place', placeId: p.id, ...s })));
  sents.forEach((s, i) => { s.order = i; s.learnPhase = 'none'; });
  // 참고용 묶음은 sents(일정 계산 대상)에 넣지 않는다. 카드·듣기가 id 로 찾도록 smap 에만 둔다.
  const refs = REF_ORDER.flatMap(key => {
    const g = S.commons.find(x => x.key === key);
    return g.items.map((it, j) => ({ id: `r-${key}-${j}`, source: 'ref', sit: key, sitLabel: g.label, learnPhase: 'none', ...it }));
  });
  const smap = Object.fromEntries([...sents, ...refs].map(s => [s.id, s]));

  const sched = [];
  let preList = [];
  if (D > 0) {
    preList = sents.slice(0, Math.min(T, D * A));
    const usedNew = Math.ceil(preList.length / A);
    const rows = pre.map((date, i) => ({ date, phase: 'pre', kind: kinds[i], ids: [], newIds: [], completed: false }));
    let ni = 0, lastNew = -1;
    rows.forEach((r, i) => {
      if (r.kind !== 'new') return;
      if (ni < usedNew) { r.ids = preList.slice(ni * A, (ni + 1) * A).map(s => s.id); ni++; lastNew = i; }
      else r.kind = 'extra';
    });
    let since = [];
    rows.forEach((r, i) => {
      if (i > lastNew) return;
      if (r.kind === 'new') since.push(...r.ids);
      else if (r.kind === 'review') { r.ids = since; since = []; }
    });
    const tail = rows.filter((r, i) => i > lastNew);
    const all = preList.map(s => s.id);
    tail.forEach((r, j) => { r.kind = 'final'; r.ids = all.slice(Math.floor(j * all.length / tail.length), Math.floor((j + 1) * all.length / tail.length)); });
    preList.forEach(s => (s.learnPhase = 'pre'));
    sched.push(...rows);
  }

  const deferred = new Set(sents.slice(preList.length).map(s => s.id));
  const from = t.studyStart > t.tripStart ? t.studyStart : t.tripStart;
  const seenSit = new Set();
  S.days.forEach(d => {
    if (d.date < from) return;
    const sits = SIT_ORDER.filter(k => d.types.some(ty => SIT_BY_TYPE[ty].includes(k)));
    const com = sents.filter(s => s.source === 'common' && sits.includes(s.sit));
    const pls = d.placeIds.flatMap(pid => sents.filter(s => s.placeId === pid));
    const newIds = [];
    com.forEach(s => { if (deferred.has(s.id) && !seenSit.has(s.sit)) newIds.push(s.id); });
    sits.forEach(k => seenSit.add(k));
    pls.forEach(s => { if (deferred.has(s.id)) newIds.push(s.id); });
    newIds.forEach(id => (smap[id].learnPhase = 'trip'));
    const ids = [...com, ...pls].map(s => s.id);
    sched.push({ date: d.date, phase: 'trip', kind: ids.length ? 'trip' : 'free', ids, newIds, completed: false, day: d });
  });

  const kc = k => sched.filter(r => r.kind === k).length;
  S.sents = sents; S.refs = refs; S.smap = smap; S.sched = sched;
  S.plan = {
    N: pre.length, D, A, T, P, per,
    usedNew: kc('new'), review: kc('review'), final: kc('final'),
    deferred: deferred.size, tripNew: sents.filter(s => s.learnPhase === 'trip').length, none: sents.filter(s => s.learnPhase === 'none').length,
  };
  resetCard();
  applyProgress();   /* 계획을 다시 만들어도 저장해 둔 완료 기록이 다시 붙는다 */
}

function makeRoute() {
  const days = R.placeByCode(R.buildDays(S.trip.cities), S.places);
  return { days, fallback: S.flags.routeInvalid, errs: R.validateRoute(days, S.places) };
}

/* ================= 생성 흐름 (FR-GEN-01~03) ================= */
function stepsFor(stage) {
  const t = S.trip, cs = t.cities.map(c => c.name);
  if (stage === 'report') return [`${t.country} 여행 정보를 확인하고 있어요`, ...cs.flatMap(c => [`${josa(c, '의', '의')} 관광지를 고르고 있어요`, `${josa(c, '의', '의')} 맛집과 대표 메뉴를 고르고 있어요`]), '출처를 정리하고 있어요'];
  if (stage === 'route') return ['선택한 장소의 지역을 확인하고 있어요', '날짜별로 장소를 배치하고 있어요', '방문 순서 규칙을 검사하고 있어요'];
  return ['문장 수를 계산하고 있어요', '장소별 영어 문장을 만들고 있어요', '맛집 대표 메뉴 주문 문장을 확인하고 있어요', '학습 일정표를 계산하고 있어요'];
}

function request(stage, byUser = true) {
  const t = S.trip; if (!t) return;
  if (t.status === stage + '_generating' && !isStale()) { toast('이미 생성 중이에요. 같은 요청은 무시돼요.'); return; }
  if (byUser) t.requests++;
  if (stage === 'report') t.requestedAt = Date.now();
  t.status = stage + '_requested'; t.error = null;
  S.gen = { stage, step: 0, steps: stepsFor(stage), stuck: false };
  S.screen = 'u-gen'; render();
  cancelGen(); const tok = genToken;
  genTimer = setTimeout(() => {
    if (tok !== genToken || t.status !== stage + '_requested') return;
    t.status = stage + '_generating'; t.genStartedAt = Date.now();
    render(); tick(tok, stage);
  }, 500);
}
function tick(tok, stage) {
  genTimer = setTimeout(async () => {
    if (tok !== genToken) return;
    const g = S.gen;
    if (g.step < g.steps.length - 1) { g.step++; if (S.screen === 'u-gen') render(); tick(tok, stage); return; }
    if (S.flags.stuck) { g.stuck = true; if (S.screen === 'u-gen') render(); return; }
    if (S.flags.fail) { failStage(stage); return; }
    if (stage === 'sentences') { await runAi(tok); if (tok !== genToken) return; }
    if (stage === 'report') { await runReport(tok); if (tok !== genToken) return; }
    succeed(stage);
  }, 700);
}

/* 실제 장소는 맛집만 /generate 로 보낸다. 카페·관광지는 문장 요청에 넣지 않는다.
   예시 장소는 기존과 같이 categoryOfKind 가 있는 종류만 보낸다. 관광지는 null 이라 빠진다. */
function sentenceCategory(p) {
  if (p.live && p.kind !== 'restaurant') return null;
  return AI.categoryOfKind(p.kind);
}
/* 선택한 맛집의 문장만 /generate 로 만든다. 일정·문장 수 계산(R.counts)은 그대로 코드가 한다.
   성공한 도시는 살리고 실패·degraded·형식 불일치 도시만 로컬 템플릿으로 폴백한다. 자동 재시도 없음. */
async function runAi(tok) {
  if (genAbort) genAbort.abort();
  const ctl = genAbort = new AbortController();
  S.aiPools = {}; S.aiBy = {};                 // 새 생성 시작: 이전 결과 폐기
  // 한 도시에 맛집과 숙소가 섞일 수 있으니 (도시, 카테고리)마다 따로 요청한다.
  const groups = {};
  S.places.filter(p => p.selected && sentenceCategory(p)).forEach(p => {
    const cat = sentenceCategory(p);
    (groups[aiKey(p.city, cat)] ??= { name: p.city, categoryId: cat, places: [] }).places.push({ id: p.id, name: p.name, en: p.en, kind: p.kind });
  });
  const cities = Object.values(groups);
  if (!cities.length) return;
  const slow = setTimeout(() => {
    if (tok === genToken && S.gen) { S.gen.waitNote = '첫 요청은 시간이 걸릴 수 있어요. 서버를 깨우는 중일 수 있어요.'; if (S.screen === 'u-gen') render(); }
  }, 10000);
  let out = [];
  try {
    out = await AI.generateByCity({ fetchImpl: (u, o) => fetch(u, o), base: API.base, cities, weakIds: AI.weakIdsFor(weakList(), cities.map(c => c.categoryId)), signal: ctl.signal, timeoutMs: AI.GEN_TIMEOUT_MS });
  } finally { clearTimeout(slow); }
  if (tok !== genToken || ctl.signal.aborted) return;   // 오래된 요청은 상태를 덮어쓰지 못한다
  out.forEach(o => { if (o.pools) S.aiPools[aiKey(o.city, o.categoryId)] = { kind: o.kind, pools: o.pools }; });
}
/* 새로고침·재로그인으로 계획을 규칙으로 다시 만들면 /generate 로 만든 AI 문장이 사라진다.
   저장된 여행을 되살린 경우에만, 서버가 살아 있으면 한 번 더 생성해 AI 문장을 채운다.
   문장 본문을 저장하지 않는 원칙은 지키고, 화면만 복구한다(응답이 늦어도 학습을 막지 않는다). */
let aiRefreshKey = null;
async function refreshAiSentences() {
  const trip = S.trip;
  if (!trip || !S.plan || API.base === null) return;                 // 계획이 없으면 채울 대상도 없다
  if (Object.keys(S.aiPools).length) return;                         // 이번 세션에 이미 만든 결과가 있으면 그대로
  if (!S.places.some(p => p.selected && sentenceCategory(p))) return;   // AI 대상 장소가 없으면(예: 관광지만) 그만
  const key = [trip.id, trip.studyStart, trip.cities.map(c => c.name + c.start).join(',')].join('|');
  if (aiRefreshKey === key) return;                                  // 같은 여행은 한 번만
  aiRefreshKey = key;
  const groups = {};
  S.places.filter(p => p.selected && sentenceCategory(p)).forEach(p => {
    const cat = sentenceCategory(p);
    (groups[aiKey(p.city, cat)] ??= { name: p.city, categoryId: cat, places: [] }).places.push({ id: p.id, name: p.name, en: p.en, kind: p.kind });
  });
  const cities = Object.values(groups);
  let out;
  try {
    out = await AI.generateByCity({ fetchImpl: (u, o) => fetch(u, o), base: API.base, cities, weakIds: AI.weakIdsFor(weakList(), cities.map(c => c.categoryId)), signal: null, timeoutMs: AI.GEN_TIMEOUT_MS });
  } catch (e) { return; }
  if (S.trip !== trip || !S.plan) return;                            // 응답 사이에 여행이 바뀌면 버린다
  const got = out.filter(o => o.pools);
  if (!got.length) return;                                           // 폴백뿐이면 틀 문장을 그대로 둔다
  got.forEach(o => { S.aiPools[aiKey(o.city, o.categoryId)] = { kind: o.kind, pools: o.pools }; });
  // 뒤집은 카드·보던 카드를 잃지 않도록 학습 화면에서는 다시 그리지 않는다(다음 계획 재계산 때 반영).
  if (['u-home', 'u-sched', 'u-coll', 'u-route'].includes(S.screen)) { buildPlan(); render(); }
}
function failStage(stage) {
  const t = S.trip; cancelGen();
  t.status = stage + '_failed'; t.failStreak++; t.fails++;
  t.error = stage === 'report' ? 'AI 응답이 정해진 형식에 맞지 않았어요. (2번 다시 요청했지만 실패)' : stage === 'route' ? '방문 순서를 만드는 중 오류가 났어요.' : '일부 장소의 문장을 만들지 못했어요.';
  if (S.gen) S.gen.failed = true;
  S.screen = 'u-gen'; render();
}
/* 보고서 요청만 /itinerary 를 부른다. 메뉴로 연 화면(ensure)은 예시 데이터를 유지한다.
   플래그가 꺼졌거나 모든 도시가 실패하면 genReport 로 돌아간다. */
async function runReport(tok) {
  S.reportMode = 'example';
  S.itineraryBlocks = null;
  S.reportPlaces = null;
  S.reportMetaLive = null;
  if (API.base === null || !S.trip) return;
  if (genAbort) genAbort.abort();
  const ctl = genAbort = new AbortController();
  const caps = {};
  const baseDays = R.cityBase(R.buildDays(S.trip.cities));
  S.trip.cities.forEach(c => { const b = baseDays[c.name]; caps[c.name] = b ? b.attr + b.rest : 0; });
  try {
    const results = await AI.collectItinerary({
      fetchImpl: (u, o) => fetch(u, o), base: API.base, cities: S.trip.cities, signal: ctl.signal, timeoutMs: AI.GEN_TIMEOUT_MS,
    });
    if (tok !== genToken || ctl.signal.aborted) return;
    const folded = AI.foldItinerary(S.trip.cities, results, caps);
    if (tok !== genToken || ctl.signal.aborted) return;
    if (!folded || folded.mode === 'example') return;
    S.reportMode = folded.mode;
    S.reportPlaces = folded.places;
    S.reportMetaLive = folded.meta;
    S.itineraryBlocks = folded.blocksByCity;
  } catch (e) {
    if (tok !== genToken) return;
    S.reportMode = 'example';
  }
}
function succeed(stage) {
  const t = S.trip; t.failStreak = 0;
  if (stage === 'report') {
    if (t.reportRound >= 1) t.regenerateCount++;
    if (S.reportMode === 'example') S.places = genReport(t, t.reportRound);
    else { S.places = S.reportPlaces || []; S.reportMeta = S.reportMetaLive || {}; }
    t.reportRound++;
    t.status = 'report_done'; mark('report_done');
    t.reportSec = Math.round((Date.now() - t.requestedAt) / 1000);
    S.cityTab = t.cities[0].name; S.showCand = {};
    S.screen = 'u-report'; render();
    const again = t.reportRound > 1 ? `보고서를 다시 만들었어요. 남은 다시 생성 ${3 - t.regenerateCount}번` : '보고서가 준비됐어요. 가지 않을 장소를 빼 주세요.';
    toast(S.reportMode === 'empty' ? '확인된 장소가 없어요.' : S.reportMode === 'live' ? '확인한 장소를 골랐어요. 가지 않을 장소를 빼 주세요.' : again);
  } else if (stage === 'route') {
    if (S.itineraryBlocks) {
      S.days = AI.placeBlocksOnDays(R.buildDays(t.cities), S.places, t.cities, S.itineraryBlocks);
      t.routeFallback = false;
      S.routeView = 'blocks';
    } else {
      const res = makeRoute(); S.days = res.days; t.routeFallback = res.fallback;
      S.routeView = 'code';
    }
    mark('route_done');
    request('sentences', false); // 서버가 이어서 요청
  } else {
    buildPlan(); t.status = 'studying'; mark('studying');
    S.screen = 'u-route'; render();
    toast('방문 순서와 학습 일정표가 만들어졌어요.');
  }
}
function retry() {
  const t = S.trip; const stage = t.status.split('_')[0];
  if (/_failed$/.test(t.status) || isStale()) request(stage);
}

/* 메뉴에서 바로 화면을 열 때 필요한 데이터를 채움.
   저장된 여행 입력이 있으면 그것으로 다시 만들고(데모 여행으로 덮지 않는다), 없을 때만 데모 여행을 만든다.
   해시로 화면을 바로 열어도(#u-home) 저장된 여행을 덮어쓰지 않는다 — SESS_READY 가 아니므로 저장도 하지 않는다. */
function ensure(level) {
  let did = false;
  if (!S.user) { S.user = DEMO_USER; did = true; }
  if (level === 'user') return did;
  if (!S.trip) {
    const saved = loadTripHere();
    if (saved) { S.trip = tripFromInput(saved); resetDerived(); }
    else { createTrip(defaultDraft(S.today)); did = true; }
  }
  const t = S.trip;
  if (!S.places.length) {
    cancelGen();
    S.reportMode = 'example';
    S.itineraryBlocks = null;
    S.routeView = 'code';
    S.places = genReport(t, t.reportRound); t.reportRound++;
    t.status = 'report_done'; mark('report_done'); t.reportSec = 42; did = true;
  }
  if (level === 'plan' && !S.plan) {
    cancelGen();
    if (S.itineraryBlocks) {
      S.days = AI.placeBlocksOnDays(R.buildDays(t.cities), S.places, t.cities, S.itineraryBlocks);
      S.routeView = 'blocks';
    } else {
      S.days = makeRoute().days;
      S.routeView = 'code';
    }
    mark('route_done'); buildPlan();
    t.status = 'studying'; t.failStreak = 0; mark('studying'); did = true;
  }
  return did;
}

/* ================= 날짜·진도 ================= */
function phase() {
  const t = S.trip; if (!t) return null;
  if (S.today > t.tripEnd) return 'ended';
  if (S.today >= t.tripStart) return 'trip';
  if (S.today < t.studyStart) return 'before';
  return 'pre';
}
function rowStatus(r) {
  if (r.kind === 'free') return 'free';
  if (r.kind === 'drill') return 'drill';
  if (r.completed) return 'done';
  if (r.date === S.today) return 'today';
  if (r.date < S.today) return 'miss';
  return 'future';
}
const canComplete = r => r.kind !== 'free' && !r.completed && r.date <= S.today && S.today <= S.trip.tripEnd;
function progress() {
  const den = S.sched.filter(r => r.kind !== 'free').length;
  const done = S.sched.filter(r => r.completed).length;
  const miss = S.sched.filter(r => rowStatus(r) === 'miss').length;
  const learned = new Set(S.sched.filter(r => r.completed).flatMap(r => r.ids)).size;
  return { den, done, miss, learned, rate: den ? done / den : 0, free: S.sched.length - den };
}
function describe(r) {
  if (r.kind === 'free') return '장소 없음 · 문장 모음에서 복습';
  const m = new Map();
  r.ids.forEach(id => {
    const s = S.smap[id];
    const k = s.source !== 'place' ? `공통 ${s.sitLabel}` : S.places.find(p => p.id === s.placeId)?.name;
    m.set(k, (m.get(k) || 0) + 1);
  });
  const parts = [...m].map(([k, n]) => `${k} ${n}`);
  if (r.kind === 'review') return `직전 새 문장 ${r.ids.length}개 복습`;
  if (r.kind === 'final') return `여행 전 문장 ${r.ids.length}개 나눠 복습`;
  return parts.join(' · ');
}
function pickRow() {
  if (S.drill && S.screen === 'u-study') return S.drill;   // 문장 모음에서 고른 상황 묶음 — 날짜 일정과 따로 논다
  const rows = S.sched; if (!rows.length) return null;
  return rows.find(r => r.date === S.studyDate) || rows.find(r => r.date === S.today) ||
    (S.today < rows[0].date ? rows[0] : rows[rows.length - 1]);
}

/* ================= TTS ================= */
const TTS = { voices: [] };
const ttsSupported = () => 'speechSynthesis' in window;
function loadVoices() { if (ttsSupported()) TTS.voices = speechSynthesis.getVoices(); }
function enVoice() {
  const v = TTS.voices;
  return v.find(x => /en[-_]US/i.test(x.lang) && /(Google|Samantha|Aria|Jenny|Guy|Zira|Natural)/i.test(x.name)) ||
    v.find(x => /en[-_]US/i.test(x.lang)) || v.find(x => /^en/i.test(x.lang));
}
function ttsState() {
  if (S.flags.noTts || !ttsSupported()) return 'unsupported';
  if (TTS.voices.length && !enVoice()) return 'novoice';
  return 'ok';
}
/* 듣기가 안 될 때 안내: 되는 것도 함께 알린다(녹음이 가능할 때만 '말하기' 언급). 카톡(Android)이면 카톡 자체 메뉴도 안내 — 배너를 닫은 뒤에도 막히지 않게 */
const ttsOffMsg = () => `이 브라우저는 듣기를 지원하지 않아요. ${API.base !== null && canRecord() ? '말하기와 ' : ''}카드 학습은 계속할 수 있어요.`
  + ((typeof INAPP_INFO !== 'undefined' && INAPP_INFO && INAPP_INFO.name === '카카오톡' && INAPP_INFO.os === 'android') ? " ⋮ 메뉴에서 '다른 브라우저로 열기'를 누르면 듣기도 돼요." : '');
/* 화면과 음성의 자리표시자는 여기서 한 번만 펼친다. 두 곳에서 각각 펼치면 반드시 어긋난다. */
const DETERMINER = { name: 'your name', destination: 'your destination' };
const slotText = s => String(s).replace(/\[(name|destination)\]/g, (_, k) => `[${DETERMINER[k]}]`);
/* 대괄호만 벗긴다. 펼침은 slotText 한 곳이다. */
const ttsText = shown => String(shown).replace(/[\[\]]/g, '');
/* 따라 읽기(NaturalReaders 처럼): 영어 문장을 단어 단위 span 으로 그린다. data-c 는 '실제로 읽는 문장'(ttsText) 안의
   단어 시작 위치다 — 대괄호를 빼고 읽으므로 그만큼 당겨 센다. 자리표시자 단어에는 ph 를 붙여 기존 강조를 유지한다. */
function enHtml(text) {
  let out = '', pos = 0, inPh = false;
  for (const part of slotText(text).split(/(\s+)/)) {
    if (!part) continue;
    if (/^\s+$/.test(part)) { out += part; pos += part.length; continue; }
    const opens = part.includes('['), closes = part.includes(']');
    out += `<span class="w${inPh || opens ? ' ph' : ''}" data-c="${pos}">${esc(part)}</span>`;
    if (opens) inPh = true; if (closes) inPh = false;
    pos += part.replace(/[\[\]]/g, '').length;
  }
  return out;
}
let readTimer = null;
function readMark(target, at) {   // at = 읽는 문장 안 글자 위치. 그 위치를 지난 마지막 단어를 칠한다
  if (!target) return;
  let cur = null;
  target.querySelectorAll('.w').forEach(w => { if (+w.dataset.c <= at) cur = w; });
  target.querySelectorAll('.w.now').forEach(w => w !== cur && w.classList.remove('now'));
  if (cur) cur.classList.add('now');
}
function readClear() { clearTimeout(readTimer); readTimer = null; document.querySelectorAll('.w.now').forEach(w => w.classList.remove('now')); }
/* 브라우저가 단어 경계(boundary) 이벤트를 주지 않으면(Android 의 일부 음성) 글자 수로 시간을 어림해 따라간다.
   진짜 경계 이벤트가 한 번이라도 오면 어림은 멈춘다. */
function readEstimate(target, spoken, rate) {
  const words = [...target.querySelectorAll('.w')].map(w => +w.dataset.c);
  const msPerChar = 62 / (rate || 1);
  let k = 0;
  const step = () => {
    if (k >= words.length) return;
    readMark(target, words[k]);
    const next = k + 1 < words.length ? words[k + 1] : spoken.length;
    const wait = Math.max(160, (next - words[k]) * msPerChar);
    k++; readTimer = setTimeout(step, wait);
  };
  step();
}
const readTarget = el => { const box = el && el.closest('.talk-line, .talk-me, .face, .sent'); return box ? box.querySelector('[data-read]') : null; };
function speak(text, btn, target, o = {}) {   // o = { rate, onend } — 대화하기가 쓴다
  if (ttsState() !== 'ok') { toast(ttsOffMsg()); return; }
  speechSynthesis.cancel();
  if (mineAudio) { try { mineAudio.pause(); } catch (e) { /* 이미 멈춤 */ } }   // 내 발음과 겹치지 않게
  document.querySelectorAll('.playing').forEach(e => e.classList.remove('playing'));
  // 호출부는 저장 문장(.en, 편집 input)을 넘긴다. 화면과 같으려면 여기서 slotText 를 먼저 거친다.
  const u = new SpeechSynthesisUtterance(ttsText(slotText(text)));
  u.lang = 'en-US';
  const v = enVoice(); if (v) u.voice = v;
  u.rate = o.rate || S.ttsRate;
  readClear();
  const tgt = target && target.querySelector('.w') ? target : null;
  let gotBoundary = false;
  u.onstart = () => {
    if (btn) btn.classList.add('playing');
    if (tgt) readTimer = setTimeout(() => { if (!gotBoundary) readEstimate(tgt, u.text, u.rate); }, 350);
  };
  u.onboundary = e => {
    if (!tgt || (e.name && e.name !== 'word')) return;
    if (!gotBoundary) { gotBoundary = true; clearTimeout(readTimer); readTimer = null; }
    readMark(tgt, e.charIndex);
  };
  u.onend = u.onerror = () => { if (btn) btn.classList.remove('playing'); readClear(); if (o.onend) o.onend(); };
  speechSynthesis.speak(u);
}
if (ttsSupported()) {
  loadVoices();
  speechSynthesis.onvoiceschanged = () => { loadVoices(); renderInAppBanner(); if (['u-study', 'u-sched', 'u-coll'].includes(S?.screen)) render(); };
}

/* ================= 화면 정의 ================= */
const SCREENS = [
  { group: '사용자 화면', id: 'u-login', no: 'SCR-01', name: '로그인', fr: ['FR-AUTH-01', 'FR-AUTH-02'],
    tips: ['"Google로 계속하기"를 누르면 로그인돼요.', '여행이 없으면 여행 입력, 있으면 홈으로 이동해요.', '로그인 상태에서는 로그아웃할 수 있어요.'] },
  { id: 'u-auth', no: 'SCR-01b', name: '이메일 로그인', fr: ['FR-AUTH-01'],
    tips: ['로그인 화면의 "로그인"으로 들어와요(Firebase 가 켜진 배포에서만).', '"이미 계정이 있어요" / "아직 계정이 없어요"를 고르면 그 폼만 보여요.'] },
  { id: 'u-input', no: 'SCR-02', name: '여행 입력', fr: ['FR-TRIP-01', 'FR-TRIP-03', 'FR-TRIP-04', 'FR-TRIP-05'],
    tips: ['도시 날짜를 비우거나 겹치게 바꾼 뒤 "보고서 만들기"로 오류를 확인하세요.', '나라를 "일본"으로 바꾸면 영어권이 아닌 나라 안내가 나와요.', '학습 시작일을 여행 3일 전 이후로 두면 짧은 학습 경고가 나와요.', '진행 중인 여행이 있으면 보관 확인 창이 떠요.'],
    demos: [['빈 날 오류 예시 넣기', 'demo-gap'], ['짧은 학습(3일) 예시 넣기', 'demo-short'], ['여행 당일 시작 예시 넣기', 'demo-zero'], ['기본 예시로 되돌리기', 'demo-default']] },
  { id: 'u-gen', no: 'SCR-03', name: '생성 중 · 실패', fr: ['FR-GEN-01', 'FR-GEN-02', 'FR-GEN-03'],
    tips: ['생성은 요청 → 생성 중 → 완료/실패 순서로 진행돼요.', '생성 중에 메뉴를 옮겼다 돌아와도 상태가 그대로예요.', '실패가 3번 이어지면 "잠시 후 다시 시도" 안내가 나와요.', '멈춤 상태에서 15분이 지나면 다시 시도할 수 있어요.'],
    demos: [['생성 흐름 처음부터 보기', 'demo-gen'], ['실패 화면 보기', 'demo-gen-fail'], ['멈춤 화면 보기', 'demo-gen-stuck'], ['⏱ 16분 경과시키기', 'demo-age']] },
  { id: 'u-report', no: 'SCR-04', name: '보고서 · 장소 선택', fr: ['FR-REPORT-01', 'FR-REPORT-02', 'FR-REPORT-03', 'FR-PLACE-01'],
    tips: ['기본 장소를 체크 해제한 뒤 "후보 더 보기"에서 후보를 체크해 바꿔 보세요.', '최대 수를 넘겨 체크하면 막혀요.', '절반 미만으로 줄이면 빈 날 안내가 나와요.', '다시 생성은 성공한 경우에만 횟수가 줄어요 (최대 3번).', '"Levain Bakery"는 출처 없음 예시예요.'] },
  { id: 'u-route', no: 'SCR-05', name: '추천 방문 순서', fr: ['FR-ROUTE-01', 'FR-SENT-02'],
    tips: ['도착일·이동일·귀국일은 장소가 최대 2곳이에요.', '장소를 많이 빼면 "자유 일정"이 생겨요.', '위쪽 요약에서 문장 수 계산 결과를 확인하세요.', '사이드바의 "방문 순서 AI 규칙 위반"을 켜고 다시 만들면 코드 배치 안내가 나와요.'] },
  { id: 'u-home', no: 'SCR-06', name: '홈', fr: ['FR-STUDY-03', 'FR-END-01'],
    tips: ['사이드바의 날짜 버튼으로 "오늘"을 바꿔 보세요.', '여행 전: D-N, 여행 중: N일차 · 오늘 도시, 종료 후: 결과 요약', '완료율 분모에서 자유 일정 날은 빠져요.'],
    demos: [['지난 날 일부를 완료로 채우기', 'demo-fill']] },
  { id: 'u-sched', no: 'SCR-07', name: '일정표', fr: ['FR-SCHED-01', 'FR-SCHED-02', 'FR-STUDY-04'],
    tips: ['날짜를 누르면 그날 카드로 이동해요.', '지난 날짜 중 안 한 날은 "미완료"로 표시돼요.', '새 문장 3일 + 복습 1일, 출발 전 2일 총복습 규칙을 확인하세요.'],
    demos: [['지난 날 일부를 완료로 채우기', 'demo-fill']] },
  { id: 'u-study', no: 'SCR-08', name: '학습 카드', fr: ['FR-STUDY-01', 'FR-STUDY-02', 'FR-STUDY-04'],
    tips: ['카드를 눌러 뒤집고 "듣기"로 영어 발음을 들어 보세요.', '모든 카드를 한 번 이상 뒤집어야 완료 버튼이 켜져요.', '[your name]·[your destination]는 채울 자리예요. 듣기도 그대로 읽어요.', '사이드바의 "TTS 미지원"을 켜면 듣기 버튼 대신 안내가 나와요.'] },
  { id: 'u-coll', no: 'SCR-09', name: '문장 모음', fr: ['FR-STUDY-05', 'FR-SENT-01'],
    tips: ['공통 상황과 장소별 문장을 골라 볼 수 있어요.', '"문장 모음 전용"은 일정에 넣지 않은 문장이에요.', '모든 문장에 듣기 버튼이 있어요.'] },
  { id: 'u-end', no: 'SCR-06', name: '여행 종료 요약', fr: ['FR-END-01', 'FR-TRIP-04'],
    tips: ['이 메뉴를 누르면 "오늘"이 여행 종료 다음 날로 바뀌어요.', '종료 후에는 완료 처리를 할 수 없어요.', '"새 여행 만들기"는 이 여행을 보관(비활성화)해요.'] },
  { id: 'u-edit', no: 'SCR-10', name: '여행 설정 수정', fr: ['FR-TRIP-01', 'FR-SENT-02'],
    tips: ['홈의 D-Day 카드를 눌러도 이 화면이 열려요.', '날짜만 바꾸면 문장은 그대로 두고 학습 일정표만 다시 계산해요.', '도시나 나라를 바꾸면 보고서·방문 순서·문장을 다시 만들어요.'] },
  { group: '관리자 화면', tag: 'PRD 외 제안', id: 'a-metrics', no: 'ADM-01', name: '운영 지표', fr: ['PRD 2-2', 'stageAt'], prop: true,
    tips: ['PRD 성공 지표 4개를 stageAt 기반으로 계산해요.', '데모 여행 진행 상태도 함께 반영돼요.'] },
  { id: 'a-jobs', no: 'ADM-02', name: '생성 작업 모니터', fr: ['FR-GEN-01', 'FR-GEN-02', 'FR-GEN-03'], prop: true,
    tips: ['15분 넘게 멈춘 작업은 "멈춤"으로 강조돼요.', '"실패로 처리"를 누르면 사용자가 다시 시도할 수 있게 돼요.', '데모 여행의 생성 작업도 이 목록에 나타나요.'] },
  { id: 'a-common', no: 'ADM-03', name: '공통 문장 관리', fr: ['FR-SENT-01', 'PRD 14 미결'], prop: true,
    tips: ['30개 원문을 고치고 듣기로 확인하세요.', '저장하면 다음 문장 생성부터 반영돼요.', '[name], [destination] 빈칸 표기를 유지하세요.'] },
  { id: 'a-users', no: 'ADM-04', name: '사용자 · 여행', fr: ['FR-TRIP-04', 'FR-TRIP-05'], prop: true,
    tips: ['사용자별 현재 여행과 보관된 여행을 봐요.', '데모 사용자에서 새 여행을 만들면 보관 목록이 늘어나요.'] },
];
const SCR = Object.fromEntries(SCREENS.map(s => [s.id, s]));

/* ================= 렌더링: 셸 ================= */
/* ================= 화면 테마 (P3) ================= */
const THEME_KEY = 'cd_theme';   // 'light' | 'dark' — 없으면 시스템. 개인정보가 아닌 화면 설정이다.
function getTheme() { try { const t = localStorage.getItem(THEME_KEY); return t === 'light' || t === 'dark' ? t : 'system'; } catch (e) { return document.documentElement.dataset.theme || 'system'; } }
function themeIsDark() { const t = getTheme(); return t === 'dark' || (t === 'system' && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches); }
const THEME_COLOR = { light: '#fbf8f1', dark: '#12151c' };   // 브라우저 주소창 색(meta theme-color). CSS 토큰 --bg 와 같은 값이어야 한다
function syncThemeColor() { const m = document.getElementById('theme-color'); if (m) m.setAttribute('content', themeIsDark() ? THEME_COLOR.dark : THEME_COLOR.light); }
function setTheme(v) {
  try { if (v === 'light' || v === 'dark') localStorage.setItem(THEME_KEY, v); else localStorage.removeItem(THEME_KEY); } catch (e) { /* 저장 불가(시크릿 모드 등): 이번 접속에서만 적용 */ }
  if (v === 'light' || v === 'dark') document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme;
  syncThemeColor();
}
if (window.matchMedia) { const mq = matchMedia('(prefers-color-scheme: dark)'); (mq.addEventListener ? mq.addEventListener.bind(mq, 'change') : mq.addListener.bind(mq))(() => { syncThemeColor(); }); }
function themeCard() {
  const t = getTheme(), b = (v, l) => `<button class="${t === v ? 'on' : ''}" data-act="theme" data-v="${v}" aria-pressed="${t === v}">${l}</button>`;
  return `<div class="sec-title"><h4>화면 모드</h4></div><div class="card theme-card"><div class="seg" role="group" aria-label="화면 모드">${b('system', '시스템')}${b('light', '라이트')}${b('dark', '다크')}</div>
    <p class="small" style="margin-top:8px">시스템은 기기의 라이트·다크 설정을 따라요. 이 선택은 이 브라우저에만 저장돼요.</p></div>`;
}

const MODE = document.documentElement.dataset.mode || 'product';   // product | demo | legacy (index.html 인라인 스크립트)
const LEGACY = MODE === 'legacy';
/* P4 마스터-디테일: 900px 이상(제품·데모 모드)에서 일정표·학습·문장 모음은 2열(목록 + 상세)로 그린다. 폭이 바뀌면 다시 그린다. */
const wideMq = window.matchMedia ? window.matchMedia('(min-width: 900px)') : null;
const isWide = () => !LEGACY && !!wideMq && wideMq.matches;
if (wideMq) { const onWide = () => { try { if (typeof S !== 'undefined' && S && S.plan) render(); } catch (e) { /* 첫 렌더 전 */ } }; (wideMq.addEventListener ? wideMq.addEventListener.bind(wideMq, 'change') : wideMq.addListener.bind(wideMq))(onWide); }
const studyShown = () => S.screen === 'u-study' || (S.screen === 'u-sched' && isWide());   // 학습 카드가 화면에 있는가(말하기·TTS 상태 갱신 대상)
function renderSide() {
  let html = `<div class="side-brand"><div class="mark"><img src="icon-192.png" alt="" width="22" height="22">마디 목업</div><p>prd.md v2 기준 · 왼쪽 메뉴로 화면을 고르고, 화면 안 버튼으로 실제 흐름을 따라가 보세요.</p></div><nav class="side-nav">`;
  SCREENS.forEach(s => {
    if (s.group) html += `<div class="nav-group">${s.group}${s.tag ? `<span class="tag">${s.tag}</span>` : ''}</div>`;
    html += `<button class="nav-item" data-act="nav" data-id="${s.id}"><span class="no">${s.no}</span><span>${s.name}</span></button>`;
  });
  html += `</nav><div id="side-notes"></div><div class="demo" id="demo"></div>`;
  $('#side').innerHTML = html;
}
function renderDemo() {
  const t = S.trip, ref = t || { studyStart: S.draft.studyStart, tripStart: S.draft.cities[0].start, tripEnd: S.draft.cities[S.draft.cities.length - 1].end, cities: S.draft.cities };
  const transfer = ref.cities[1]?.start;
  const chips = [
    ['가입일', BASE_TODAY], ['학습 시작', ref.studyStart], ['출발 전날', ref.tripStart && Dt.add(ref.tripStart, -1)],
    ['여행 첫날', ref.tripStart], transfer ? ['이동일', transfer] : null, ['종료 다음 날', ref.tripEnd && Dt.add(ref.tripEnd, 1)],
  ].filter(c => c && c[1]);
  const tg = (k, label) => `<label class="toggle"><span>${label}</span><input type="checkbox" data-flag="${k}" ${S.flags[k] ? 'checked' : ''}><span class="sw"></span></label>`;
  $('#demo').classList.toggle('closed', !!S.demoClosed);
  $('#demo').innerHTML = `
    <h4>데모 조작 <span><button data-act="reset">전체 초기화</button> · <button data-act="demo-toggle">${S.demoClosed ? '펼치기 ▴' : '접기 ▾'}</button></span></h4>
    <div class="demo-date"><span style="color:var(--inv-text-3)">오늘</span><input type="date" id="demo-date" value="${S.today}"></div>
    <div class="demo-chips">${chips.map(([l, d]) => `<button data-act="set-today" data-date="${d}">${l} ${Dt.md(d)}</button>`).join('')}</div>
    ${tg('fail', 'AI 생성 실패')}${tg('stuck', '생성 멈춤 (응답 없음)')}${tg('routeInvalid', '방문 순서 AI 규칙 위반')}${tg('noTts', 'TTS 미지원 브라우저')}
    <div class="demo-actions"><button data-act="preset" data-kind="short">짧은 학습 3일</button><button data-act="preset" data-kind="zero">당일 시작 0일</button></div>
    <div class="demo-actions"><button data-act="weak-demo">데모 학습 기록 불러오기</button><button data-act="weak-clear">복습 목록 비우기</button></div>
    <div class="small" style="margin-top:6px;color:var(--inv-text-3)">복습 목록 ${weakList().length}개 (데모 ${weakList().filter(w => w.demo).length}개) · 데모 기록은 실제 학습 기억이 아니에요</div>`;
}
function updateSideActive() {
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.id === S.screen));
}

/* 미리 학습한 날이 오면 완료로 옮긴다. 안내("카드를 모두 뒤집어 두면 그날 자동으로 완료돼요")가 사실이 되게 한다.
   예전 안내("미리 학습해 두면 그날 바로 완료돼요")는 기록을 남기지 않아 지켜지지 않았다. */
function settlePre() {
  if (!S.trip || S.today > S.trip.tripEnd) return;
  let moved = false;
  Object.keys(PROG.pre).forEach(k => {
    if (k <= S.today) { if (!PROG.done[k]) PROG.done[k] = PROG.pre[k]; delete PROG.pre[k]; moved = true; }
  });
  if (moved) applyProgress();
}
/* 폰 하단 탭은 화면에 고정(position: fixed)이라 문서 흐름에서 빠진다. 실제 탭 높이만큼 아래를 비워
   마지막 내용이 가려지지 않게 한다(글자 확대로 탭이 높아져도 맞는다). 레일·사이드에서는 CSS 가 0 으로 둔다. */
function syncNavSpace() {
  const n = !LEGACY && $('.pnav');
  if (n && getComputedStyle(n).position === 'fixed') document.documentElement.style.setProperty('--nav-space', n.offsetHeight + 'px');
}
window.addEventListener('resize', () => syncNavSpace());
function render() {
  settlePre();
  if (TALK.on && (!S.sheet || !studyShown())) cancelTalk();   // 시트를 닫는 모든 경로(닫기·카드 넘김·화면 이동)
  if (!studyShown() && SPK.state !== 'idle') cancelSpeak();
  const app = $('.app'), same = S.lastScreen === S.screen;
  const prevTop = LEGACY ? (app ? app.scrollTop : 0) : window.scrollY;   // 제품·데모 모드는 문서 스크롤
  const prevList = $('.split-list'), prevListTop = prevList ? prevList.scrollTop : 0;   // 마스터-디테일 목록의 스크롤
  updateSideActive(); renderDemo();
  const sc = SCR[S.screen];
  const t = S.trip;
  const status = t ? (t.archived ? '보관됨' : STATUS_KO[t.status]) : '여행 없음';
  const cls = t && /_failed$/.test(t.status) ? 'bad' : t && /_(generating|requested)$/.test(t.status) ? 'warn' : '';
  $('#topbar').innerHTML = `<span class="id">${sc.no}</span><h1>${sc.name}</h1>${sc.prop ? '<span class="fr prop">PRD 외 제안 화면</span>' : ''}<span class="spacer"></span>
    <span class="pill"><span class="dot"></span>오늘 <b>${S.today}</b> (${Dt.dow(S.today)})</span>
    <span class="pill ${cls}"><span class="dot"></span>여행 상태 <b>${status}</b></span>
    ${API.external ? `<span class="pill bad" title="?api= 로 지정한 외부 서버에 요청하고 녹음을 전송합니다"><span class="dot"></span>외부 서버 <b>${esc(API.host)}</b></span>` : ''}`;
  const body = S.screen.startsWith('a-') ? adminScreen() : userScreen();
  $('#stage').className = 'stage ' + (S.screen.startsWith('a-') ? 'is-admin' : 'is-user');
  $('#stage').innerHTML = body + (LEGACY ? notes(sc) : '');
  if (MODE === 'demo') $('#side-notes').innerHTML = notes(sc);
  syncNavSpace();
  const ab = $('#api-banner');
  if (ab) { ab.hidden = !API.external; if (API.external) ab.innerHTML = `외부 서버 연결 중: <b>${esc(API.host)}</b> — 이 주소로 요청하고 녹음을 전송합니다`; }
  if (LEGACY) { const na = $('.app'); if (na && same) na.scrollTop = prevTop; }
  else window.scrollTo(0, same ? prevTop : 0);
  { const nl = $('.split-list'); if (nl && prevListTop) nl.scrollTop = prevListTop; }
  S.lastScreen = S.screen;
  sessionWrite();   /* 진도·보던 화면 저장 — 모든 상태 변화가 여기를 지난다 */
}

function notes(sc) {
  return `<aside class="notes">
    <div class="note-card"><h3>관련 요구사항</h3><div class="fr-list">${sc.fr.map(f => `<span class="fr ${sc.prop ? 'prop' : ''}">${f}</span>`).join('')}</div></div>
    <div class="note-card"><h3>이 화면에서 해 볼 것</h3><ul>${sc.tips.map(x => `<li>${x}</li>`).join('')}</ul></div>
    ${sc.demos ? `<div class="note-card"><h3>데모 버튼</h3><div class="demo-btns">${sc.demos.map(([l, a]) => `<button data-act="${a}">${l}</button>`).join('')}</div></div>` : ''}
    ${planNote()}
  </aside>`;
}
function planNote() {
  if (!S.plan || !S.screen.startsWith('u-')) return '';
  const p = S.plan;
  return `<div class="note-card"><h3>현재 계산 결과 (FR-SENT-02)</h3><p style="font-family:var(--mono);font-size:0.75rem;line-height:1.8">
    여행 전 학습일 N = ${p.N}<br>새 문장 학습일 D = ${p.D}<br>목표 P = ${p.P === null ? '— (D = 0)' : `${p.D}×5−30 = ${p.P}`}<br>
    장소 ${p.per.length}곳 · 장소당 ${[...new Set(p.per)].sort((a, b) => b - a).join('/')}문장<br>전체 T = ${p.T} · 하루 A = ${p.A ?? '없음'}<br>
    여행 중 새 문장 ${p.tripNew} · 문장 모음 전용 ${p.none}</p></div>`;
}

/* ================= 렌더링: 사용자 화면 ================= */
function frame(inner, o = {}) {
  if (!LEGACY) return pframe(inner, o);
  const tabs = [['u-home', '홈', I.home], ['u-sched', '일정표', I.cal], ['u-study', '학습', I.cards], ['u-coll', '문장 모음', I.book]];
  const tabActive = o.tab || S.screen;
  return `<div class="device"><div class="screen">
    <div class="statusbar"><span>9:41</span><span class="sim">${Dt.full(S.today)}</span></div>
    ${o.appbar || ''}
    <div class="app">${inner}</div>
    ${o.bottom ? `<div class="bottombar">${o.bottom}</div>` : ''}
    ${o.tabbar ? `<nav class="tabbar">${tabs.map(([id, l, ic]) => `<button class="${tabActive === id ? 'on' : ''}" data-act="tab" data-id="${id}">${ic}${l}</button>`).join('')}</nav>` : ''}
    ${sheetHtml()}${modalHtml()}
  </div></div>`;
}
/* 제품 셸: 폰 프레임·상태바 없이 뷰포트 전체를 쓴다. 내비는 CSS 가 탭바 → 레일 → 사이드로 바꾼다(docs/RESPONSIVE_STRATEGY.md §3). */
function pframe(inner, o = {}) {
  const tabs = [['u-home', '홈', I.home], ['u-sched', '일정표', I.cal], ['u-study', '학습', I.cards], ['u-coll', '문장 모음', I.book]];
  const tabActive = o.tab || S.screen;
  const nav = o.tabbar ? `<nav class="pnav" aria-label="주 메뉴">${tabs.map(([id, l, ic]) => `<button class="${tabActive === id ? 'on' : ''}" data-act="tab" data-id="${id}" ${tabActive === id ? 'aria-current="page"' : ''}>${ic}<span>${l}</span></button>`).join('')}</nav>` : '';
  return `<div class="pframe ${o.tabbar ? 'has-nav' : ''}">${nav}<div class="pmain"><div class="pcol ${o.wide ? 'wide' : ''}">
    ${o.appbar || ''}
    <div class="app">${inner}</div>
    ${o.bottom ? `<div class="bottombar">${o.bottom}</div>` : ''}
  </div></div>${sheetHtml()}${modalHtml()}</div>`;
}
const appbar = (title, o = {}) => `<div class="appbar">${o.back ? `<button class="back" data-act="tab" data-id="${o.back}">${I.back}</button>` : ''}<h2>${title}</h2>${o.step ? `<span class="step">${o.step}</span>` : ''}</div>`;
const notice = (html, kind = '') => `<div class="notice ${kind}">${kind === 'warn' || kind === 'bad' ? I.alert : I.info}<div>${html}</div></div>`;
function modalHtml(center = false) {
  if (S.entering) return enteringHtml();           // 로그인 전환 화면(로그인 화면을 덮는다)
  if (S.withdrawing) return withdrawModalHtml();   // 탈퇴 진행 창이 다른 창보다 앞선다
  const m = S.modal; if (!m) return '';
  return `<div class="modal-wrap ${center ? 'center' : ''}" data-act="modal-bg"><div class="modal" data-act="noop"><h3>${m.title}</h3><p>${m.body}</p>
    <div class="acts"><button class="btn soft" data-act="modal-cancel">${m.cancel || '취소'}</button><button class="btn ${m.danger ? 'accent' : 'primary'}" data-act="modal-ok">${m.ok}</button></div></div></div>`;
}
let modalFn = null;
const previewOk = new Set();   // 이번 접속에서 '미리 학습하기'를 고른 날짜
function confirmBox(title, body, ok, fn, o = {}) { S.modal = { title, body, ok, ...o }; modalFn = fn; pushOverlay('modal'); render(); }
/* 확인 창을 닫는다. o.onCancel 이 있으면(예: 미래 날짜 확인 → 일정표로) 그것을 부른다 — 취소·바깥 클릭·뒤로가기 공통. */
function closeModal() { const m = S.modal; S.modal = null; modalFn = null; if (m && typeof m.onCancel === 'function') m.onCancel(); else render(); }

function userScreen() {
  switch (S.screen) {
    case 'u-login': return scrLogin();
    case 'u-auth': return scrAuth();
    case 'u-input': return scrInput();
    case 'u-gen': return scrGen();
    case 'u-report': return scrReport();
    case 'u-route': return scrRoute();
    case 'u-home': return scrHome();
    case 'u-sched': return scrSched();
    case 'u-study': return scrStudy();
    case 'u-coll': return scrColl();
    case 'u-edit': return scrEdit();
    case 'u-end': return frame(`<div class="app-pad">${endBody()}</div>`, { tabbar: true, tab: 'u-home' });
  }
  return '';
}

/* SCR-01 */
function scrLogin() {
  const initial = esc(userName().slice(0, 1) || '김');
  const signed = `<div class="card" style="display:flex;align-items:center;gap:12px"><div style="width:40px;height:40px;border-radius:50%;background:var(--sea);color:var(--on-sea);display:grid;place-items:center;font-weight:700">${initial}</div>
        <div style="flex:1"><b>${esc(userName())}</b><div class="small">${esc(userEmail())}</div></div></div>
       <div style="display:flex;gap:8px;margin-top:10px"><button class="btn soft" style="flex:1" data-act="logout">로그아웃</button><button class="btn primary" style="flex:2" data-act="after-login">계속하기</button></div>`;
  // 첫 화면은 고르기만 한다(10/20 피드백 "로그인 화면이 너무 복잡하다"): 로그인 → 이메일 화면, Google,
  // 그 아래 작은 회색 '로그인 없이 시작'. 이메일 입력 폼은 '로그인'을 눌러 여는 별도 화면(u-auth)에 있다.
  const choices = fbOn()
    ? `<button class="btn primary block" type="button" data-act="auth-open">로그인</button>
      <button class="gbtn" style="margin-top:10px" data-act="login">${I.google}Google로 계속하기</button>
      <button class="guest-btn" type="button" data-act="guest">로그인 없이 시작</button>`
    : `<button class="gbtn" data-act="login">${I.google}Google로 계속하기</button>`;
  const body = (S.user && !isGuest() ? signed : choices) + withdrawProofBlock();
  const gate = fbOn() ? '로그인하지 않아도 쓸 수 있어요. 기록은 이 브라우저에만 남아요.' : '로그인하지 않으면 다른 화면에 들어갈 수 없어요.';
  return frame(`<div class="login">
    <div class="stamp" aria-hidden="true">MADI · 마디<br>TRAVEL ENGLISH<br>— 2026 —</div>
    <div class="brand-row"><img src="icon-192.png" alt="" width="48" height="48"><div><b class="brand-name">마디 <span>MADI</span></b><div class="brand-tag">여행을 잇는 한마디</div></div></div>
    <div class="eyebrow" style="margin-top:74px">Travel English, planned</div>
    <h1 style="margin-top:10px">Speak where<br>you'll <em>actually</em><br>be.</h1>
    <p class="sub">여행지와 일정을 입력하면, 실제로 갈 관광지와 맛집에서 쓸 영어 문장을 만들어 출발 전부터 매일 학습하게 해 드려요.</p>
    <div class="ticket">${body}<p class="small" style="text-align:center;margin-top:12px">${gate}</p>
      <p class="small" style="text-align:center;margin-top:8px">맛집 문장은 AI가 만들고 'AI 생성' 표시가 붙어요 · 문장을 만들 때 도시·장소명과 복습 상황 이름이 Google Gemini API로 전송돼요 · 장소 목록은 예시 데이터예요 · 로그인하면 학습 진도·복습 목록·여행 설정이 계정에 저장되고, 로그인하지 않으면 이 브라우저에만 남아요 · 말하기 연습에서의 녹음 데이터를 사용자가 동의한 뒤에만 서버로 보내요.</p></div>
  </div>`);
}

/* SCR-01b 이메일 로그인: 먼저 두 갈래만 보여 주고, 고른 쪽의 폼을 연다. */
function scrAuth() {
  const mode = S.authMode;   // null = 고르기, 'login' | 'signup' = 폼
  let inner;
  if (!mode) {
    inner = `<div class="app-pad auth-pick">
      <div class="title-lg">이메일로 계속하기</div>
      <p class="sub" style="margin-bottom:18px">계정이 있으면 로그인하고, 없으면 가입해요. 기록이 다른 기기에서도 이어져요.</p>
      <button class="auth-choice" type="button" data-act="auth-pick" data-v="login"><b>이미 계정이 있어요</b><span>이메일로 로그인할래요</span></button>
      <button class="auth-choice" type="button" data-act="auth-pick" data-v="signup"><b>아직 계정이 없어요</b><span>새로 가입할래요</span></button>
    </div>`;
  } else {
    const signup = mode === 'signup';
    inner = `<div class="app-pad">
      <div class="title-lg">${signup ? '가입하기' : '이메일로 로그인'}</div>
      <p class="sub" style="margin-bottom:18px">${signup ? '이름·이메일·비밀번호(6자 이상)로 가입해요.' : '가입할 때 쓴 이메일과 비밀번호를 입력해요.'}</p>
      <form data-act="noop" style="display:flex;flex-direction:column;gap:8px" autocomplete="on">
        ${signup ? `<input class="input" data-auth="name" placeholder="이름" autocomplete="name" maxlength="40" value="${esc(authDraft.name)}">` : ''}
        <input class="input" type="email" data-auth="email" placeholder="이메일" autocomplete="username" value="${esc(authDraft.email)}">
        <input class="input" type="password" data-auth="password" placeholder="비밀번호 (6자 이상)" autocomplete="${signup ? 'new-password' : 'current-password'}">
        <button class="btn primary block" type="button" data-act="login-email">${signup ? '가입하기' : '로그인'}</button>
      </form>
      <button class="guest-btn" type="button" data-act="auth-pick" data-v="${signup ? 'login' : 'signup'}">${signup ? '이미 계정이 있어요 · 로그인' : '아직 계정이 없어요 · 가입하기'}</button>
    </div>`;
  }
  return frame(inner, { appbar: appbar(mode ? (mode === 'signup' ? '가입' : '로그인') : '로그인', { back: 'u-login' }) });
}

/* SCR-02 */
function scrInput() {
  const d = S.draft, v = R.validate(d, S.today), E = S.showErrors ? v.errors : {};
  const inner = `<div class="app-pad">
    <div class="eyebrow">New trip</div>
    <div class="title-lg">어디로 떠나세요?</div>
    <p class="sub" style="margin-bottom:18px">도시별 체류 날짜와 학습 시작일만 정하면 나머지는 자동으로 계산돼요.</p>
    ${S.trip && !S.trip.archived ? notice(`진행 중인 여행 <b>${esc(tripTitle(S.trip))}</b>이 있어요. 새 여행을 만들면 기존 여행은 보관돼요.`, 'warn') + '<div style="height:12px"></div>' : ''}
    ${tripFields(d, E, v)}
  </div>`;
  return frame(inner, { appbar: appbar('여행 입력', { step: 'STEP 1/3' }), bottom: `<button class="btn primary block" data-act="submit-trip">보고서 만들기</button>` });
}
/* 나라·도시·학습 시작일 입력 묶음. 여행 입력(SCR-02)과 여행 설정 수정(SCR-10)이 같은 마크업을 쓴다.
   [data-bind] 는 S.draft 를 고치고 updateInputLive 가 요약·경고·오류를 갱신한다. */
function tripFields(d, E, v) {
  const cities = d.cities.map((c, i) => `
    <div class="city-card"><span class="num">CITY ${i + 1}</span>
      ${d.cities.length > 1 ? `<button class="del" data-act="del-city" data-i="${i}" title="삭제">${I.x}</button>` : ''}
      <input class="input name-input" data-bind="city.${i}.name" value="${esc(c.name)}" placeholder="도시 이름">
      <div class="err" data-err="cn${i}">${E['cn' + i] || ''}</div>
      <div class="row2">
        <div><span class="lbl">체류 시작일</span><input type="date" class="input" data-bind="city.${i}.start" value="${c.start}"></div>
        <div><span class="lbl">체류 종료일 (떠나는 날)</span><input type="date" class="input" data-bind="city.${i}.end" value="${c.end}"></div>
      </div>
      <div class="err" data-err="cd${i}">${E['cd' + i] || ''}</div>
    </div>`).join('');
  return `<div class="field"><label>나라</label><input class="input" data-bind="country" value="${esc(d.country)}" placeholder="예: 미국">
      <div class="err" data-err="country">${E.country || ''}</div>
      <div data-live="noneng" style="margin-top:8px;${d.country.trim() && !ENGLISH_COUNTRIES.includes(d.country.trim()) ? '' : 'display:none'}">${notice('현지에서 영어가 통하지 않을 수 있어요. 문장은 여행자가 흔히 쓰는 쉬운 영어로 만들어요.', 'warn')}</div>
    </div>
    <div class="field"><label>도시와 체류 날짜 <span class="small">(1~5곳)</span></label>
      ${cities}
      <div class="err" data-err="cities">${E.cities || ''}</div>
      ${d.cities.length < 5 ? `<button class="add-city" data-act="add-city">+ 도시 추가</button>` : `<button class="add-city" data-act="add-city">+ 도시 추가 (최대 5곳)</button>`}
      <div class="hint">앞 도시의 체류 종료일과 다음 도시의 시작일은 같은 날(이동일)이어야 해요.</div>
    </div>
    <div class="field"><label>학습 시작일</label><input type="date" class="input" data-bind="studyStart" value="${d.studyStart}">
      <div class="err" data-err="studyStart">${E.studyStart || ''}</div>
      <div class="hint">학습 종료일은 여행 종료일로 자동 설정돼요.</div>
    </div>
    <div class="summary-strip" data-live="summary">${inputSummary(d)}</div>
    <div data-live="warn" style="margin-top:10px">${v.warnings.map(w => notice(w, 'warn')).join('')}</div>`;
}
/* SCR-10: 홈 D-Day 카드에서 여는 여행 설정 수정. 저장하면 날짜만인지에 따라 계획을 다시 만든다. */
function scrEdit() {
  const d = S.draft, v = R.validate(d, S.today), E = S.showErrors ? v.errors : {};
  const inner = `<div class="app-pad">
    <div class="eyebrow">Trip settings</div>
    <div class="title-lg">여행 설정 수정</div>
    <p class="sub" style="margin-bottom:18px">처음 입력한 여행 정보를 고칠 수 있어요. 날짜만 바꾸면 문장은 그대로 두고 학습 일정표만 다시 계산해요. 보고서·문장까지 새로 만들고 싶으면 아래 버튼을 쓰세요.</p>
    ${tripFields(d, E, v)}
  </div>`;
  return frame(inner, {
    appbar: appbar('여행 설정 수정', { back: 'u-home' }),
    bottom: `<button class="btn primary block" data-act="save-trip">저장</button>
      <button class="btn ghost block" data-act="save-trip-regen">보고서·문장까지 새로 만들기</button>`,
  });
}
function inputSummary(d) {
  const first = d.cities[0]?.start, last = d.cities[d.cities.length - 1]?.end;
  const okDates = first && last && first <= last;
  const nights = okDates ? Dt.diff(last, first) : null;
  const pre = okDates && d.studyStart ? R.preDays(d.studyStart, first).length : null;
  return `<div><span>여행 기간</span><b>${okDates ? `${Dt.md(first)}~${Dt.md(last)}` : '—'}</b><span>${okDates ? `${nights}박 ${nights + 1}일` : ''}</span></div>
    <div><span>학습 종료일</span><b>${last ? Dt.md(last) : '—'}</b><span>자동</span></div>
    <div><span>여행 전 학습</span><b>${pre ?? '—'}${pre !== null ? '일' : ''}</b><span>${pre !== null && pre <= 3 ? '짧음' : ''}</span></div>`;
}
function updateInputLive() {
  const d = S.draft, v = R.validate(d, S.today);
  const s = $('[data-live=summary]'); if (s) s.innerHTML = inputSummary(d);
  const n = $('[data-live=noneng]'); if (n) n.style.display = d.country.trim() && !ENGLISH_COUNTRIES.includes(d.country.trim()) ? '' : 'none';
  const w = $('[data-live=warn]'); if (w) w.innerHTML = v.warnings.map(x => notice(x, 'warn')).join('');
  if (S.showErrors) document.querySelectorAll('[data-err]').forEach(el => (el.textContent = v.errors[el.dataset.err] || ''));
}

/* SCR-03 */
function scrGen() {
  const t = S.trip;
  if (!t || !/_(requested|generating|failed)$/.test(t.status)) {
    return frame(`<div class="app-pad"><div class="empty" style="padding-top:120px"><div class="ico">${I.info}</div>
      <b style="color:var(--text);font-size:1rem">진행 중인 생성 작업이 없어요</b><p>보고서, 방문 순서, 문장을 만드는 동안 이 화면이 나타나요. (맛집 문장은 AI가 만들어요)<br>오른쪽 데모 버튼으로 생성·실패·멈춤 화면을 확인할 수 있어요.</p>
      ${t ? `<button class="btn soft" data-act="tab" data-id="${t.status === 'studying' ? 'u-home' : t.status === 'report_done' ? 'u-report' : 'u-input'}">현재 단계로 돌아가기</button>` : `<button class="btn soft" data-act="tab" data-id="u-input">여행 입력으로</button>`}
      </div></div>`);
  }
  const stage = t.status.split('_')[0];
  const g = S.gen && S.gen.stage === stage ? S.gen : { steps: stepsFor(stage), step: 0 };
  const failed = /_failed$/.test(t.status), stale = isStale(), requested = /_requested$/.test(t.status);
  const stepList = `<ul class="steps">${g.steps.map((s, i) => {
    const st = failed || stale ? (i < g.step ? 'done' : '') : requested ? '' : i < g.step || (g.stuck && i === g.step) ? (g.stuck && i === g.step ? 'now' : 'done') : i === g.step ? 'now' : '';
    return `<li class="${st}"><span class="ic">${st === 'done' ? '✓' : ''}</span>${s}</li>`;
  }).join('')}</ul>`;
  let head, extra = '', bottom = '';
  if (failed) {
    head = `<div class="orbit failed stopped"><div class="plane"><i></i></div><div class="core">FAIL</div></div>
      <div class="eyebrow" style="text-align:center;color:var(--bad-text)">Generation failed</div><div class="title-lg" style="text-align:center">${josa(STAGE_NAME[stage], '을', '를')} 만들지 못했어요</div>`;
    extra = notice(esc(t.error), 'bad') + (t.failStreak >= 3 ? '<div style="height:8px"></div>' + notice(`같은 단계에서 ${t.failStreak}번 연속 실패했어요. <b>잠시 후 다시 시도해 주세요.</b>`, 'warn') : '') +
      '<div style="height:8px"></div>' + notice('이전 단계까지의 결과는 그대로 남아 있어요.', 'plain');
    bottom = `<button class="btn primary block" data-act="retry">다시 시도</button>`;
  } else if (stale) {
    head = `<div class="orbit stopped"><div class="plane"><i></i></div><div class="core">15:00+</div></div>
      <div class="eyebrow" style="text-align:center;color:var(--bad-text)">Stalled</div><div class="title-lg" style="text-align:center">생성이 멈춘 것 같아요</div>`;
    extra = notice(`생성을 시작한 지 15분이 지났어요. 서버 작업이 중간에 멈췄을 수 있어요. 다시 시도할 수 있어요.`, 'bad');
    bottom = `<button class="btn primary block" data-act="retry">다시 시도</button>`;
  } else {
    head = `<div class="orbit"><div class="plane"><i></i></div><div class="core" data-live="elapsed">${elapsed()}</div></div>
      <div class="eyebrow" style="text-align:center">${requested ? 'Requested' : 'Generating'}</div>
      <div class="title-lg" style="text-align:center">${STAGE_OBJ[stage]} 만들고 있어요</div>
      <p class="sub" style="text-align:center">화면을 닫거나 새로고침해도 이어서 진행돼요.</p>`;
    bottom = `<button class="btn soft block" disabled>생성 중에는 다시 요청할 수 없어요</button>`;
    if (g.stuck) extra = notice('서버 응답이 오지 않고 있어요. (데모: 오른쪽 "16분 경과시키기"로 멈춤 처리를 확인하세요)', 'plain');
    else if (g.waitNote) extra = notice(esc(g.waitNote), 'plain');
  }
  return frame(`<div class="gen">${head}${stepList}<div style="margin-top:14px">${extra}</div></div>`, { bottom });
}
function elapsed() {
  const t = S.trip; if (!t?.genStartedAt || !/_generating$/.test(t.status)) return '00:00';
  const s = Math.max(0, Math.floor((Date.now() - t.genStartedAt) / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

/* SCR-04 */
function scrReport() {
  const t = S.trip, locked = t.status !== 'report_done';
  const city = S.cityTab && t.cities.some(c => c.name === S.cityTab) ? S.cityTab : t.cities[0].name;
  const meta = S.reportMeta[city] || { base: 0, found: 0, mode: S.reportMode === 'example' ? 'example' : 'empty' };
  const sel = selCount(city);
  const base = S.places.filter(p => p.city === city && !p.isCandidate), cands = S.places.filter(p => p.city === city && p.isCandidate);
  const nonEng = !ENGLISH_COUNTRIES.includes(t.country);
  const total = S.places.filter(p => p.selected).length;
  const open = S.showCand[city] || cands.some(p => p.selected);
  const tabCount = c => `${selCount(c.name)}/${(S.reportMeta[c.name] || { base: 0 }).base}`;
  let lead = '';
  if (locked) lead += notice('장소를 확정했어요. 이제 선택을 바꿀 수 없어요.', 'plain');
  if (S.reportMode === 'example') {
    lead += notice('이 장소 목록은 <b>미리 준비한 예시 데이터</b>예요. (AI 웹 검색은 아직 연결 전이에요) 영업시간과 메뉴는 바뀔 수 있으니 방문 전에 확인해 주세요.');
    if (meta.found < meta.base) lead += notice(`추천할 장소를 충분히 찾지 못했어요. 기본 ${meta.base}곳 중 ${meta.found}곳만 찾았어요. 후보로 채울 수 있어요.`, 'warn');
  } else if (meta.mode === 'live') {
    lead += notice('Google Maps에서 확인한 장소예요. 한국어 설명, 메뉴, 영업시간, 평점, 가격은 없어요.');
    const failed = (meta.queries || []).filter(q => q && q.status && q.status !== 'verified');
    if (failed.length) lead += notice('일부 종류는 비어 있어요. ' + failed.map(q => `${esc(q.included_type || '')}${q.reason ? ' (' + esc(q.reason) + ')' : ''}`).join(', '), 'warn');
  } else {
    lead += notice(meta.reason === 'no_verified_places' ? '확인된 장소가 없어요. 예시 장소로 채우지 않아요.' : '이 도시의 장소를 가져오지 못했어요. 예시 장소로 채우지 않아요.', 'warn');
  }
  if (nonEng) lead += notice('현지에서 영어가 통하지 않을 수 있어요.', 'warn');
  if (meta.base && sel < meta.base / 2) lead += notice('장소가 적어 비어 있는 날(자유 일정)이 생길 수 있어요.', 'warn');
  const inner = `<div class="app-pad">
    <div class="city-tabs">${t.cities.map(c => `<button class="${c.name === city ? 'on' : ''}" data-act="city-tab" data-city="${esc(c.name)}">${esc(c.name)} <b>${tabCount(c)}</b></button>`).join('')}</div>
    <div class="stack" style="margin-bottom:14px">
      ${lead}
    </div>
    <div class="city-head"><h3>${esc(city)}</h3><span class="cnt"><b>${sel}</b> / 최대 ${meta.base}곳</span></div>
    ${base.map(p => placeCard(p, locked)).join('')}
    ${cands.length ? `<button class="cand-toggle" data-act="cand" data-city="${esc(city)}">${open ? '후보 접기' : `후보 더 보기 (${cands.length})`}</button>${open ? cands.map(p => placeCard(p, locked)).join('') : ''}` : ''}
  </div>`;
  const left = 3 - t.regenerateCount;
  const bottom = locked ? `<button class="btn primary block" data-act="tab" data-id="${t.status === 'studying' ? 'u-route' : 'u-gen'}">${t.status === 'studying' ? '방문 순서 보기' : '진행 상황 보기'}</button>`
    : `<div style="display:flex;gap:8px"><button class="btn soft" style="flex:1" data-act="regen" ${left <= 0 ? 'disabled' : ''}>다시 생성 · ${left}</button>
       <button class="btn primary" style="flex:2" data-act="confirm-places" ${total === 0 ? 'disabled' : ''}>${total}곳으로 확정하기</button></div>
       <div class="small" style="text-align:center">다시 생성은 성공한 경우에만 횟수가 줄어요 · 남은 횟수 ${left}번</div>`;
  return frame(inner, { appbar: appbar('보고서 · 장소 선택', { step: 'STEP 2/3' }), bottom });
}
function placeCard(p, locked) {
  if (p.live) {
    const tone = p.kind === 'attraction' ? 'attraction' : 'restaurant';
    const chip = p.primaryType || (p.kind === 'cafe' ? '카페' : p.kind === 'attraction' ? '관광지' : '맛집');
    const link = (p.sources || []).map(s => `<a href="${esc(s.url)}" data-act="link">${esc(s.title)}</a>`).join('');
    const when = p.fetchedAt ? ` · ${esc(p.fetchedAt)}` : '';
    return `<div class="place ${p.selected ? 'on' : 'off'} ${locked ? 'locked' : ''}" data-act="place" data-id="${esc(p.id)}">
      <div class="check">${p.selected ? I.check : ''}</div>
      <div><div class="nm"><span class="kind ${tone}">${esc(chip)}</span>${esc(p.name)}</div>
        ${p.area ? `<div class="meta">${esc(p.area)}</div>` : ''}
        <div class="src">${link}${link ? ' · ' : ''}${esc(p.attribution || 'Google Maps')}${when}</div></div></div>`;
  }
  const src = p.sources.length ? p.sources.map(s => `<a href="${s.url}" data-act="link">${esc(s.title)}</a>`).join('') : '<span>출처 없음</span>';
  return `<div class="place ${p.selected ? 'on' : 'off'} ${locked ? 'locked' : ''}" data-act="place" data-id="${p.id}">
    <div class="check">${p.selected ? I.check : ''}</div>
    <div><div class="nm"><span class="kind ${p.kind}">${p.kind === 'attraction' ? '관광지' : '맛집'}</span>${esc(p.name)}${p.isCandidate ? '<span class="badge b-only">후보</span>' : ''}</div>
      <div class="meta">${esc(p.area)}${p.cuisine ? ` · ${esc(p.cuisine)}` : ''}</div>
      <div class="desc">${esc(p.desc)} <span style="color:var(--text-3)">— ${esc(p.reason)}</span></div>
      ${p.menuKo ? `<div class="menu">대표 메뉴 · ${esc(p.menuKo)}</div>` : ''}
      <div class="src">${src}</div></div></div>`;
}

/* SCR-05 */
const TIME_KO = { morning: '오전', afternoon: '오후', evening: '저녁' };
function scrDayBlocks() {
  const t = S.trip, p = S.plan;
  const errs = R.validateRoute(S.days, S.places);
  const groups = {}; p.per.forEach(n => (groups[n] = (groups[n] || 0) + 1));
  const perTxt = Object.entries(groups).sort((a, b) => b[0] - a[0]).map(([n, c]) => `${n}문장 ${c}곳`).join(' · ');
  const oneBlock = b => {
    const pl = S.places.find(x => x.id === b.placeId);
    if (!pl) return '';
    const chip = pl.primaryType || (pl.kind === 'cafe' ? '카페' : pl.kind === 'attraction' ? '관광지' : '맛집');
    const tone = pl.kind === 'attraction' ? 'attraction' : 'restaurant';
    const link = (pl.sources || []).map(s => `<a href="${esc(s.url)}" data-act="link">${esc(s.title)}</a>`).join('');
    return `<div><span class="badge t-norm">${esc(TIME_KO[b.time] || b.time)}</span><span class="kind ${tone}">${esc(chip)}</span>${esc(pl.name)}
      ${pl.area ? `<span class="ar">${esc(pl.area)}</span>` : ''}
      ${b.ko ? `<div class="desc">${esc(b.ko)}</div>` : ''}
      <span class="ar">${link}${pl.attribution ? ` · ${esc(pl.attribution)}` : ''}</span></div>`;
  };
  const inner = `<div class="app-pad">
    <div class="card" style="background:var(--inv-bg);color:var(--inv-text);border:0">
      <div class="eyebrow" style="color:var(--sun)">Plan summary</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;font-size:0.78125rem;color:var(--inv-text-2)">
        <div>전체 문장<b style="display:block;color:var(--inv-text);font-size:1.25rem;font-family:var(--display)">${p.T}개</b>공통 30 + 장소 ${p.T - 30}</div>
        <div>하루 학습량<b style="display:block;color:var(--inv-text);font-size:1.25rem;font-family:var(--display)">${p.A ? p.A + '문장' : '없음'}</b>${p.A ? `새 문장 ${p.usedNew}일` : '여행 전 학습 없음'}</div>
        <div>여행 전 학습<b style="display:block;color:var(--inv-text);font-size:1rem">${p.N}일</b>복습 ${p.review} · 총복습 ${p.final}</div>
        <div>여행 중 새 문장<b style="display:block;color:var(--inv-text);font-size:1rem">${p.tripNew}개</b>문장 모음 전용 ${p.none}개</div>
      </div>
      <div style="margin-top:10px;font-size:0.75rem;color:var(--inv-text-3)">장소당 ${perTxt}</div>
    </div>
    <div class="stack" style="margin:12px 0 16px">
      ${notice('서버가 나눠 준 하루 블록이에요. 빼 둔 장소는 빠졌어요. 이동 시간, 지도, 영업시간, 평점, 가격은 없어요.')}
      ${errs.length ? notice('검증 실패: ' + errs.join(', '), 'bad') : ''}
    </div>
    <div class="timeline">${S.days.map(d => {
      const blocks = d.blocks || [];
      const timed = new Set(blocks.map(b => b.placeId));
      const extra = d.placeIds.filter(id => !timed.has(id)).map(id => {
        const pl = S.places.find(x => x.id === id);
        return pl ? `<div><span class="badge t-norm">시간 없음</span>${esc(pl.name)}</div>` : '';
      }).join('');
      const rows = blocks.map(oneBlock).join('') + extra;
      return `<div class="tl-day ${d.placeIds.length ? '' : 'free'}">
        <div class="d">${Dt.full(d.date)} <span class="city">${esc(d.city)}</span>${d.types.map(ty => `<span class="badge ${DAYTYPE[ty].cls}">${DAYTYPE[ty].label}</span>`).join('')}</div>
        ${rows || `<div class="freebox">이 날은 블록이 없어요</div>`}
      </div>`;
    }).join('')}</div>
  </div>`;
  return frame(inner, { appbar: appbar('하루 블록', { step: 'STEP 3/3' }), bottom: `<button class="btn primary block" data-act="tab" data-id="u-home">학습 시작하러 가기</button>` });
}
function scrRoute() {
  if (S.routeView === 'blocks') return scrDayBlocks();
  const t = S.trip, p = S.plan;
  const errs = R.validateRoute(S.days, S.places);
  const groups = {}; p.per.forEach(n => (groups[n] = (groups[n] || 0) + 1));
  const perTxt = Object.entries(groups).sort((a, b) => b[0] - a[0]).map(([n, c]) => `${n}문장 ${c}곳`).join(' · ');
  const inner = `<div class="app-pad">
    <div class="card" style="background:var(--inv-bg);color:var(--inv-text);border:0">
      <div class="eyebrow" style="color:var(--sun)">Plan summary</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;font-size:0.78125rem;color:var(--inv-text-2)">
        <div>전체 문장<b style="display:block;color:var(--inv-text);font-size:1.25rem;font-family:var(--display)">${p.T}개</b>공통 30 + 장소 ${p.T - 30}</div>
        <div>하루 학습량<b style="display:block;color:var(--inv-text);font-size:1.25rem;font-family:var(--display)">${p.A ? p.A + '문장' : '없음'}</b>${p.A ? `새 문장 ${p.usedNew}일` : '여행 전 학습 없음'}</div>
        <div>여행 전 학습<b style="display:block;color:var(--inv-text);font-size:1rem">${p.N}일</b>복습 ${p.review} · 총복습 ${p.final}</div>
        <div>여행 중 새 문장<b style="display:block;color:var(--inv-text);font-size:1rem">${p.tripNew}개</b>문장 모음 전용 ${p.none}개</div>
      </div>
      <div style="margin-top:10px;font-size:0.75rem;color:var(--inv-text-3)">장소당 ${perTxt}</div>
    </div>
    <div class="stack" style="margin:12px 0 16px">
      ${notice('지도 기반 최적 경로가 아니라, 장소의 지역을 기준으로 정한 <b>추천 방문 순서</b>예요.')}
      ${t.routeFallback ? notice('AI가 만든 방문 순서가 규칙을 2번 어겨 <b>코드 규칙으로 배치</b>했어요. (같은 지역끼리 묶어 날짜 순서대로 채움)', 'warn') : ''}
      ${errs.length ? notice('검증 실패: ' + errs.join(', '), 'bad') : `<div class="small" style="display:flex;gap:6px;align-items:center;color:var(--ok-text)">${I.check} 검증 통과 · 도시 일치 · 하루 장소 수 · 누락·중복 없음</div>`}
    </div>
    <div class="timeline">${S.days.map(d => `
      <div class="tl-day ${d.placeIds.length ? '' : 'free'}">
        <div class="d">${Dt.full(d.date)} <span class="city">${esc(d.city)}</span>${d.types.map(ty => `<span class="badge ${DAYTYPE[ty].cls}">${DAYTYPE[ty].label}</span>`).join('')}</div>
        ${d.placeIds.length ? `<div class="pl">${d.placeIds.map(id => { const pl = S.places.find(x => x.id === id); return `<div><span class="kind ${pl.kind}">${pl.kind === 'attraction' ? '관광' : '맛집'}</span>${esc(pl.name)}<span class="ar">${esc(pl.area)} · ${pl.count}문장</span></div>`; }).join('')}</div>`
        : `<div class="freebox">자유 일정 · 배치할 장소가 없어요</div>`}
      </div>`).join('')}</div>
  </div>`;
  return frame(inner, { appbar: appbar('추천 방문 순서', { step: 'STEP 3/3' }), bottom: `<button class="btn primary block" data-act="tab" data-id="u-home">학습 시작하러 가기</button>` });
}

/* SCR-06 */
function scrHome() {
  const t = S.trip, ph = phase();
  if (ph === 'ended') return frame(`<div class="app-pad">${endBody()}${themeCard()}${privacyCard()}${accountCard()}</div>`, { tabbar: true });
  const pr = progress();
  let hero;
  if (ph === 'trip') {
    const day = S.days.find(d => d.date === S.today);
    hero = `<button type="button" class="hero trip" data-act="edit-trip" aria-label="여행 설정 수정"><div class="route">${esc(tripTitle(t))}</div><div class="big">${Dt.diff(S.today, t.tripStart) + 1}<small>일차</small></div>
      <div class="dates">오늘 도시 · ${esc(day?.city || '')} ${day ? day.types.map(ty => DAYTYPE[ty].label).join('·') : ''}</div><span class="hero-edit">여행 설정 수정 ›</span></button>`;
  } else if (ph === 'before') {
    hero = `<button type="button" class="hero" data-act="edit-trip" aria-label="여행 설정 수정"><div class="route">${esc(tripTitle(t))}</div><div class="big">D-${Dt.diff(t.studyStart, S.today)}<small>학습 시작까지</small></div>
      <div class="dates">학습 ${Dt.md(t.studyStart)} → 여행 ${Dt.md(t.tripStart)}~${Dt.md(t.tripEnd)}</div><span class="hero-edit">여행 설정 수정 ›</span></button>`;
  } else {
    hero = `<button type="button" class="hero" data-act="edit-trip" aria-label="여행 설정 수정"><div class="route">${esc(tripTitle(t))}</div><div class="big">D-${Dt.diff(t.tripStart, S.today)}<small>여행까지</small></div>
      <div class="dates">여행 ${Dt.md(t.tripStart)}~${Dt.md(t.tripEnd)} · 학습 종료 ${Dt.md(t.tripEnd)}</div><span class="hero-edit">여행 설정 수정 ›</span></button>`;
  }
  const r = S.sched.find(x => x.date === S.today);
  let today;
  if (!r) {
    const first = S.sched[0];
    today = `<div class="today-card"><div class="top"><span class="badge k-free">학습 전</span></div><h3>학습은 ${Dt.full(first.date)}부터 시작해요</h3>
      <p class="sub" style="font-size:0.8125rem">첫날 학습 · ${describe(first)}문장</p><button class="btn soft block" style="margin-top:12px" data-act="study-date" data-date="${first.date}">첫날 카드 미리 보기</button></div>`;
  } else {
    const st = rowStatus(r), n = r.ids.length;
    const title = r.kind === 'free' ? '오늘은 자유 일정이에요' : r.kind === 'new' ? `새 문장 ${n}개` : r.kind === 'trip' ? `오늘 장소 문장 ${n}개` : `${KIND[r.kind].label} · 문장 ${n}개`;
    today = `<div class="today-card"><div class="top"><span class="badge ${KIND[r.kind].cls}">${KIND[r.kind].label}</span>${st === 'done' ? '<span class="st done">완료</span>' : ''}</div>
      <h3>${title}</h3><p class="sub" style="font-size:0.8125rem">${describe(r)}</p>
      ${r.newIds.length ? `<div style="margin-top:8px"><span class="badge b-new">새 문장 ${r.newIds.length}개 포함</span></div>` : ''}
      ${r.kind === 'free' ? `<button class="btn soft block" style="margin-top:12px" data-act="tab" data-id="u-coll">문장 모음에서 복습하기</button>`
        : `<button class="btn ${st === 'done' ? 'soft' : 'accent'} block" style="margin-top:12px" data-act="study-date" data-date="${r.date}">${st === 'done' ? '완료했어요 · 다시 보기' : '오늘 학습 시작'}</button>`}</div>`;
  }
  const upcoming = S.sched.filter(x => x.date > S.today).slice(0, 3);
  const inner = `<div class="app-pad">
    <div style="display:flex;justify-content:space-between;align-items:center;margin:4px 0 12px"><div><div class="small">안녕하세요</div><b style="font-size:1.125rem">${esc(userName())}${isGuest() ? '' : '님'}</b></div><span class="badge t-norm">${STATUS_KO[t.status]}</span></div>
    ${hero}<div style="height:12px"></div>${today}
    ${pr.miss ? `<div style="height:10px"></div>${notice(`지난 학습 ${pr.miss}일이 미완료예요. 일정표에서 여행 종료일까지 언제든 채울 수 있어요.`, 'warn')}` : ''}
    <div class="sec-title"><h4>진도</h4><button data-act="tab" data-id="u-sched">일정표 ›</button></div>
    <div class="card progress-row">${ring(pr.rate)}
      <div class="mini-stats"><div><span>완료한 날</span><b>${pr.done}일</b></div><div><span>학습 날짜</span><b>${pr.den}일</b></div>
      <div class="${pr.miss ? 'bad' : ''}"><span>미완료</span><b>${pr.miss}일</b></div><div><span>자유 일정 (제외)</span><b>${pr.free}일</b></div></div></div>
    ${upcoming.length ? `<div class="sec-title"><h4>다가오는 일정</h4></div>${upcoming.map(srow).join('')}` : ''}
    ${themeCard()}
    ${privacyCard()}
    ${accountCard()}
  </div>`;
  return frame(inner, { tabbar: true });
}
function ring(rate) {
  const r = 40, c = 2 * Math.PI * r;
  return `<div class="ring"><svg width="96" height="96"><circle cx="48" cy="48" r="${r}" fill="none" stroke="var(--surface-seg)" stroke-width="9"/>
    <circle cx="48" cy="48" r="${r}" fill="none" stroke="var(--accent)" stroke-width="9" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - rate)}"/></svg>
    <div class="v"><div><b>${Math.round(rate * 100)}%</b><span>완료율</span></div></div></div>`;
}
function srow(r, sel = false) {
  const st = rowStatus(r);
  const stLabel = { done: '완료', miss: '미완료', today: '오늘', future: '예정', free: '—' }[st];
  const extra = r.phase === 'trip' ? `${r.day.types.map(ty => `<span class="badge ${DAYTYPE[ty].cls}">${DAYTYPE[ty].label}</span>`).join('')}<span class="small">${esc(r.day.city)}</span>` : '';
  return `<button class="srow ${r.date === S.today ? 'today' : ''} ${sel ? 'sel' : ''}" data-act="study-date" data-date="${r.date}" ${sel ? 'aria-current="true"' : ''}>
    <span class="dt">${Dt.md(r.date)}<small>${Dt.dow(r.date)}요일</small></span>
    <span class="ct"><span class="line1"><span class="badge ${KIND[r.kind].cls}">${KIND[r.kind].label}</span>${extra}${r.newIds.length ? `<span class="badge b-new">새 ${r.newIds.length}</span>` : ''}</span>
      <span class="line2">${r.kind === 'free' ? '자유 일정 · 완료율 계산 제외' : `${r.ids.length}문장 · ${esc(describe(r))}`}</span></span>
    <span class="st ${st}">${stLabel}</span></button>`;
}

/* SCR-07 */
function schedListHtml(selDate = null) {
  const pr = progress();
  let rows = S.sched;
  if (S.schedFilter === 'miss') rows = rows.filter(r => rowStatus(r) === 'miss');
  const pre = rows.filter(r => r.phase === 'pre'), trip = rows.filter(r => r.phase === 'trip');
  const one = r => srow(r, r.date === selDate);
  return `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div class="seg"><button class="${S.schedFilter === 'all' ? 'on' : ''}" data-act="sched-filter" data-v="all">전체</button><button class="${S.schedFilter === 'miss' ? 'on' : ''}" data-act="sched-filter" data-v="miss">미완료 ${pr.miss}</button></div>
      <span class="small">완료율 <b style="color:var(--text)">${Math.round(pr.rate * 100)}%</b> (${pr.done}/${pr.den})</span></div>
    ${pre.length ? `<div class="phase-label">여행 전 · ${S.plan.N}일</div>${pre.map(one).join('')}` : ''}
    ${trip.length ? `<div class="phase-label">여행 중</div>${trip.map(one).join('')}` : ''}
    ${!rows.length ? `<div class="empty"><div class="ico">${I.check}</div>미완료 날짜가 없어요</div>` : ''}`;
}
function scrSched() {
  if (isWide()) return scrSplit('u-sched');
  return frame(`<div class="app-pad">${schedListHtml()}</div>`, { appbar: appbar('일정표'), tabbar: true });
}
/* P4: 넓은 화면의 일정표·학습 = 왼쪽 일정 목록 + 오른쪽 선택한 날의 학습 카드. 날짜를 눌러도 화면은 그대로이고 오른쪽만 바뀐다. */
function scrSplit(tab) {
  const r = pickRow();
  let detail = `<div class="empty">일정이 없어요</div>`;
  if (r) { const v = studyView(r, { inline: true }); detail = `${v.inner}${v.bottom ? `<div class="bottombar">${v.bottom}</div>` : ''}`; }
  return frame(`<div class="split"><div class="split-list">${schedListHtml(r ? r.date : null)}</div><div class="split-detail">${detail}</div></div>`,
    { appbar: appbar(tab === 'u-study' ? '학습' : '일정표'), tabbar: true, tab, wide: true });
}

/* SCR-08 */
function studyView(r, opts = {}) {
  if (S.card.date !== r.date) resetCard(r.date);
  const st = rowStatus(r), ended = S.today > S.trip.tripEnd;
  const head = r.kind === 'drill'
    ? `<div class="study-head"><div><div class="small">문장 모음에서 고른 묶음 · 완료율에는 들어가지 않아요</div><b style="font-size:1.1875rem">${esc(r.label)}</b></div><span class="badge ${KIND.drill.cls}">${KIND.drill.label}</span></div>`
    : `<div class="study-head"><div><div class="small">${r.phase === 'trip' ? `${esc(r.day.city)} · ${r.day.types.map(ty => DAYTYPE[ty].label).join('·')}` : '여행 전 학습'}</div>
    <b style="font-size:1.1875rem">${Dt.full(r.date)}</b></div><span class="badge ${KIND[r.kind].cls}">${KIND[r.kind].label}</span></div>`;
  let banner = '';
  if (r.kind === 'drill') banner = '';
  else if (ended) banner = notice('여행이 끝나 더 이상 완료 처리할 수 없어요.', 'plain');
  else if (r.completed) banner = notice('완료한 날이에요. 다시 학습해도 완료 상태는 유지돼요.', 'plain');
  /* 미래 날짜 안내는 아래 완료 버튼 옆으로 옮겼다 — 같은 말을 두 곳에서 하지 않는다 */
  else if (st === 'miss') banner = notice('지난 날짜예요. 지금 학습하면 완료로 기록돼요.', 'warn');

  // 미래 날짜: 카드를 보여 주기 전에 확인 창(팀 요청 — 안내문이 눈에 띄지 않아 사용자 흐름이 끊겼다).
  // '미리 학습하기'를 고른 날·이미 미리 학습을 마친 날은 다시 묻지 않는다.
  if (r.kind !== 'drill' && r.kind !== 'free' && !r.completed && !ended && r.date > S.today && !PROG.pre[r.date] && !previewOk.has(r.date)) {
    const gateBody = `${Dt.full(r.date)} 학습이에요. 지금 학습한 기록은 완료율에 바로 들어가지 않아요. <b>카드를 모두 뒤집어 두면 그날 자동으로 완료</b>돼요.`;
    if (opts.inline) {   // 넓은 화면 2열: 일정표를 여는 것만으로 창이 뜨지 않게, 오른쪽 상세 안에 같은 안내를 둔다
      return { inner: `<div class="app-pad">${head}<div class="card" style="margin-top:12px"><b>아직 학습일이 아니에요</b><p class="small" style="margin:8px 0 12px;line-height:1.6">${gateBody}</p>
        <button class="btn primary block" data-act="preview-ok" data-date="${r.date}">미리 학습하기</button></div></div>`, bottom: '', tabbar: true };
    }
    if (!S.modal) {
      S.modal = { title: '아직 학습일이 아니에요',
        body: gateBody,
        ok: '미리 학습하기', cancel: '일정표로', onCancel: () => go('u-sched') };
      modalFn = () => { previewOk.add(r.date); S.modal = null; render(); };
    }
    return { inner: `<div class="app-pad">${head}<div class="empty" style="padding-top:60px"><div class="ico">⏳</div><p>미리 학습할지 고르면 카드가 열려요.</p></div></div>`, bottom: '', tabbar: true };
  }

  if (r.kind === 'free') {
    return { inner: `<div class="app-pad">${head}<div class="empty" style="padding-top:70px"><div class="ico">☼</div><b style="color:var(--text);font-size:1.0625rem">오늘은 자유 일정이에요</b>
      <p>배치된 장소가 없어 카드가 없어요.<br>문장 모음에서 복습해 보세요. (완료율 계산에서 제외돼요)</p><button class="btn soft" data-act="tab" data-id="u-coll">문장 모음 열기</button></div></div>`, bottom: '', tabbar: true };
  }
  if (S.justCompleted === r.date) {
    const pr = progress();
    return { inner: `<div class="app-pad">${head}<div class="done-banner"><div class="seal">DONE<br>${Dt.md(r.date)}</div>
      <div class="title-lg">학습 완료!</div><p class="sub">문장 ${r.ids.length}개를 모두 확인했어요. 완료율이 <b>${Math.round(pr.rate * 100)}%</b>로 갱신됐어요.</p></div>
      <button class="btn primary block" data-act="tab" data-id="u-home">홈으로</button><div style="height:8px"></div>
      <button class="btn soft block" data-act="restudy">다시 보기</button></div>`, bottom: '', tabbar: true };
  }
  const i = Math.min(S.card.i, r.ids.length - 1), s = S.smap[r.ids[i]];
  const isNew = r.kind === 'new' || (r.newIds || []).includes(s.id);
  const pl = s.placeId ? S.places.find(p => p.id === s.placeId) : null;
  const tag = s.source !== 'place' ? `<span class="badge t-norm">공통 · ${s.sitLabel}</span>` : `<span class="badge ${pl.kind === 'attraction' ? 't-dep' : 't-arr'}">${esc(pl.name)}</span>`;
  const ts = ttsState();
  const tts = ts === 'ok'
    ? `<div class="tts-row"><button class="tts-btn" data-act="speak-card">${I.speaker}듣기</button><button class="tts-rate" data-act="rate">${S.ttsRate < 0.9 ? '느리게' : '보통 속도'}</button></div>`
    : `<div class="tts-off">${ttsOffMsg()}</div>`;
  // 완료 안내는 위(제목 아래)로 옮겼다 — 아래쪽은 '회화 연습' 시트 자리다(목업 #97).
  const inner = `<div class="app-pad">${head}<div class="study-status" data-live="status">${completeBtn(r)}</div>${banner ? banner + '<div style="height:10px"></div>' : ''}
    <div class="flip ${S.card.back === S.card.i ? 'flipped' : ''}" data-act="flip">
      <div class="flip-inner">
        <div class="face front"><div class="ctx">${tag}${aiBadges(s)}${isNew ? '<span class="badge b-new">새 문장</span>' : ''}</div><div class="sit" style="margin-top:8px">${esc(s.situation)}</div>
          <div class="ko">${phHtml(s.ko)}</div><div class="hint">탭해서 영어 문장 보기 ↻</div></div>
        <div class="face back"><div class="ctx">${tag}${aiBadges(s)}</div><div class="sit" style="margin-top:8px">${esc(s.situation)}</div>
          <div class="en" data-read>${enHtml(s.en)}</div><div class="ko-s">${phHtml(s.ko)}</div>${tts}</div>
      </div>
    </div>
    <div class="card-nav"><button class="round" data-act="card-prev" ${i === 0 ? 'disabled' : ''}>${I.back}</button>
      <div style="text-align:center"><div class="dots">${r.ids.map((_, k) => `<i class="${S.card.flipped.has(k) ? 'seen' : ''} ${k === i ? 'cur' : ''}"></i>`).join('')}</div>
      <div class="small" style="margin-top:6px" data-live="flipcount">${i + 1} / ${r.ids.length} · 뒤집은 카드 ${S.card.flipped.size}</div></div>
      <button class="round" data-act="card-next" ${i === r.ids.length - 1 ? 'disabled' : ''}>${I.next}</button></div>
  </div>`;
  return { inner, bottom: `<button class="btn accent block" data-act="sheet-open" aria-haspopup="dialog">↑ 회화 연습 열기</button>`, tabbar: false };
}
/* 하단 '회화 연습' 시트(Leechangjin 님 목업 #97): 내 문장 + 말해보기, 상대의 예상 답변, 내가 이어서 할 말.
   공통 문장에만 예상 답변(talk)이 있다. 장소 문장은 말해보기만 보인다. */
const curSent = () => { const r = studyShown() && pickRow(); return r ? S.smap[r.ids[Math.min(S.card.i, r.ids.length - 1)]] : null; };
function talkLine(t, k) {
  if (!t) return null;
  if (k === 'ask') return t.ask || null;
  if (k === 'next') return t.next || null;
  const m = /^r(\d)$/.exec(k);
  return m ? (t.replies || [])[+m[1]] || null : null;
}
function sheetHtml() {
  const s = S.sheet && curSent();
  if (!s) return '';
  if (TALK.on && TALK.sid === s.id) return talkSheetHtml(s);
  const t = s.talk, tts = ttsState() === 'ok';
  const line = (k, label) => {
    const L = talkLine(t, k);
    return L ? `<div class="talk-line">${label ? `<span class="talk-pill">${esc(label)}</span>` : ''}<b lang="en" data-read>${enHtml(L.en)}</b><p>${esc(L.ko)}</p>
      ${tts ? `<button class="talk-say" data-act="say-line" data-k="${k}">${I.speaker}듣기</button>` : ''}</div>` : '';
  };
  const body = t
    ? `<h4>상대방의 예상 답변</h4>${(t.replies || []).map((r, j) => line('r' + j, r.label)).join('')}<h4>내가 이어서</h4>${line('next')}`
    : `<p class="small">이 문장은 예상 답변이 아직 없어요. 공통 문장에만 있어요.</p>`;
  return `<div class="sheet-wrap" data-act="sheet-bg"><section class="sheet" role="dialog" aria-modal="true" aria-label="회화 연습" data-act="noop">
    <div class="sheet-handle"></div><h3>회화 연습</h3>
    ${AI.talkTurns(t, s).length ? `<button class="btn accent block talk-start" data-act="talk-start">대화하기 <span class="small">상대가 영어로 말하면 말로 답해요</span></button>` : ''}
    ${t && t.ask ? `<h4>상대가 먼저</h4>${line('ask')}<h4>내가 대답하기</h4>` : ''}
    <div class="talk-me"><b lang="en" data-read>${enHtml(s.en)}</b><div>${phHtml(s.ko)}</div>${tts ? `<button class="talk-say" data-act="speak-card">${I.speaker}듣기</button>` : ''}</div>
    <div class="speak" data-live="speak">${speakHtml(s)}</div>
    ${body}
    <button class="btn primary block" data-act="sheet-close">↓ 회화 연습 닫기</button>
  </section></div>`;
}
function closeSheet() {
  S.sheet = false;
  if (SPK.state === 'recording' || SPK.state === 'requesting') cancelSpeak();   // 닫으면 녹음도 멈춘다
  render();
}
function scrStudy() {
  if (S.drill) {   // 상황별 연습: 넓은 화면에서도 일정 목록 없이 카드만 (뒤로 → 문장 모음)
    const v = studyView(S.drill);
    return frame(v.inner, { appbar: appbar('상황별 연습', { back: 'u-coll' }), bottom: v.bottom, tabbar: false, tab: 'u-study' });
  }
  if (isWide()) return scrSplit('u-study');
  const r = pickRow();
  if (!r) return frame(`<div class="empty">일정이 없어요</div>`, { tabbar: true });
  const v = studyView(r);
  return frame(v.inner, { appbar: appbar('학습', { back: 'u-sched' }), bottom: v.bottom || undefined, tabbar: v.tabbar, tab: 'u-study' });
}
/* 모든 카드를 뒤집으면 버튼을 누르지 않아도 끝난다(팀 요청 10/19). 날짜에 따라 완료·미리 학습·연습 축하 창을 띄운다. */
function allFlipped(r) {
  const n = r.ids.length, md = Dt.md(r.date);
  if (r.kind === 'drill') {
    confirmBox('이 상황을 다 봤어요', `${esc(r.label)} 문장 ${n}개를 모두 확인했어요. 상황별 연습은 날짜별 완료율에 들어가지 않아요.`,
      '다른 상황 고르기', () => { S.modal = null; endDrill(); go('u-coll'); }, { cancel: '계속 보기' });
    return;
  }
  if (r.completed) return;                                   // 이미 완료한 날을 다시 본 경우
  if (canComplete(r)) {
    r.completed = true; r.completedAt = Date.now(); PROG.done[r.date] = r.completedAt; S.studyDate = r.date;
    const rate = Math.round(progress().rate * 100);
    confirmBox('학습 완료! 🎉', `${md} 문장 ${n}개를 모두 확인했어요. 완료율이 <b>${rate}%</b>로 올랐어요.`,
      '홈으로', () => { S.modal = null; go('u-home'); }, { cancel: '계속 보기', celebrate: true });
    return;
  }
  if (r.date > S.today && S.today <= S.trip.tripEnd) {
    PROG.pre[r.date] = Date.now();
    confirmBox('미리 학습을 마쳤어요', `${Dt.full(r.date)}이 되면 자동으로 완료로 기록돼요. 그 전까지는 완료율에 들어가지 않아요.`,
      '일정표로', () => { S.modal = null; go('u-sched'); }, { cancel: '계속 보기', celebrate: true });
    render();
    return;
  }
  toast('여행이 끝난 뒤에는 완료로 기록되지 않아요.');
}
function completeBtn(r) {
  const all = S.card.flipped.size >= r.ids.length;
  if (r.kind === 'drill') return `<button class="btn ${all ? 'accent' : 'soft'} block" data-act="tab" data-id="u-coll">${all ? '다 봤어요 · 다른 상황 고르기' : `문장 모음으로 (${S.card.flipped.size}/${r.ids.length})`}</button>`;
  if (r.completed) return `<button class="btn soft block" disabled>완료한 날이에요</button>`;
  if (S.today > S.trip.tripEnd) return `<button class="btn soft block" disabled>여행 종료 후에는 완료할 수 없어요</button>`;
  const cnt = `${S.card.flipped.size}/${r.ids.length}`;
  if (r.date > S.today) return PROG.pre[r.date]
    ? `<button class="btn soft block" disabled>미리 학습 완료 · ${Dt.md(r.date)}에 자동으로 완료돼요</button>`
    : `<button class="btn soft block" disabled>미리 학습 중 (${cnt})</button>
    <div class="small" style="text-align:center">카드를 모두 뒤집어 두면 ${Dt.md(r.date)}에 자동으로 완료돼요</div>`;
  return `<button class="btn soft block" disabled>카드를 모두 뒤집으면 자동으로 완료돼요 (${cnt})</button>`;
}
function updateStudyLive() {
  const r = pickRow(); if (!r) return;
  const dots = document.querySelectorAll('.dots i');
  dots.forEach((d, k) => d.classList.toggle('seen', S.card.flipped.has(k)));
  const fc = $('[data-live=flipcount]'); if (fc) fc.textContent = `${Math.min(S.card.i, r.ids.length - 1) + 1} / ${r.ids.length} · 뒤집은 카드 ${S.card.flipped.size}`;
  const st = $('[data-live=status]'); if (st) st.innerHTML = completeBtn(r);
}

/* SCR-09 */
function scrColl() {
  const tab = S.coll.tab, f = S.coll.filter;
  const learnBadge = s => s.learnPhase === 'none' ? '<span class="badge b-only">문장 모음 전용</span>' : s.learnPhase === 'trip' ? '<span class="badge b-new">여행 중 새 문장</span>' : '';
  const item = s => `<div class="sent"><div><div class="tags">${learnBadge(s)}${aiBadges(s)}<span class="small">${esc(s.situation)}</span></div><div class="en" data-read>${enHtml(s.en)}</div><div class="ko">${phHtml(s.ko)}</div></div>
    <button class="play" data-act="speak" data-id="${s.id}">${I.speaker}</button></div>`;
  /* 묶음 머리에 '카드로 연습' — 사용자 피드백: 날짜별 말고 상황별로 모아서 연습하고 싶다 */
  const drillBtn = (by, v, n) => `<button class="drill-btn" data-act="drill" data-by="${by}" data-v="${esc(v)}">${I.cards}카드로 연습 ${n}</button>`;
  let chipsHtml, listHtml;
  if (tab === 'common') {
    const order = [...SIT_ORDER, ...REF_ORDER];
    const chips = [['all', '전체'], ...order.map(k => [k, S.commons.find(g => g.key === k).label])];
    const list = [...S.sents.filter(s => s.source === 'common'), ...(S.refs || [])].filter(s => f === 'all' || s.sit === f);
    chipsHtml = `<div class="chips">${chips.map(([k, l]) => `<button class="${f === k ? 'on' : ''}" data-act="coll-filter" data-v="${k}">${l}</button>`).join('')}</div>`;
    listHtml = `${order.filter(k => f === 'all' || k === f).map(k => { const g = list.filter(s => s.sit === k); return g.length ? `<div class="phase-label">${g[0].sitLabel}${drillBtn('sit', k, g.length)}</div>${g.map(item).join('')}` : ''; }).join('')}`;
  } else {
    const cities = S.trip.cities.map(c => c.name);
    const cf = cities.includes(f) ? f : 'all';
    const places = S.places.filter(p => p.selected && (cf === 'all' || p.city === cf)).sort((a, b) => a.visitDate.localeCompare(b.visitDate) || a.visitOrder - b.visitOrder);
    chipsHtml = `<div class="chips">${[['all', '전체'], ...cities.map(c => [c, c])].map(([k, l]) => `<button class="${cf === k ? 'on' : ''}" data-act="coll-filter" data-v="${esc(k)}">${esc(l)}</button>`).join('')}</div>`;
    listHtml = `${places.map(p => { const g = S.sents.filter(s => s.placeId === p.id); return `<div class="phase-label">${esc(p.name)} · ${Dt.md(p.visitDate)} 방문${g.length ? drillBtn('place', p.id, g.length) : ''}</div>${g.map(item).join('')}`; }).join('')}`;
  }
  const ts = ttsState();
  const segHtml = `<div class="seg" style="margin-bottom:12px"><button class="${tab === 'common' ? 'on' : ''}" data-act="coll-tab" data-v="common">공통 상황 ${30 + (S.refs || []).length}</button><button class="${tab === 'place' ? 'on' : ''}" data-act="coll-tab" data-v="place">장소별 ${S.sents.length - 30}</button></div>`;
  const ttsNote = ts !== 'ok' ? notice(ttsOffMsg(), 'warn') + '<div style="height:10px"></div>' : '';
  if (isWide()) {   // P4: 왼쪽 = 탭·상황/도시 필터, 오른쪽 = 문장
    return frame(`<div class="split coll"><div class="split-list">${segHtml}${chipsHtml}</div><div class="split-detail">${ttsNote}${listHtml}</div></div>`, { appbar: appbar('문장 모음'), tabbar: true, wide: true });
  }
  return frame(`<div class="app-pad">${segHtml}${ttsNote}${chipsHtml}${listHtml}</div>`, { appbar: appbar('문장 모음'), tabbar: true });
}

/* SCR-06 (종료) */
function endBody() {
  const t = S.trip, pr = progress();
  return `<div class="end-hero"><div class="seal">TRIP COMPLETE<b>${Math.round(pr.rate * 100)}%</b>${Dt.md(t.tripEnd)}</div>
      <div class="eyebrow">Welcome back</div><div class="title-lg">여행이 끝났어요</div><p class="sub">${esc(tripTitle(t))} · ${Dt.md(t.tripStart)}~${Dt.md(t.tripEnd)}</p></div>
    <div class="stat3" style="margin:18px 0 12px"><div><b>${Math.round(pr.rate * 100)}%</b><span>완료율</span></div><div><b>${pr.learned}</b><span>학습한 문장</span></div><div><b>${pr.done}/${pr.den}</b><span>완료한 날</span></div></div>
    ${notice('여행이 끝나 더 이상 완료 처리할 수 없어요. 요약은 저장된 학습 기록으로 계산해요.', 'plain')}
    <div style="height:14px"></div>
    <button class="btn soft block" data-act="tab" data-id="u-coll">문장 모음 보기</button><div style="height:8px"></div>
    <button class="btn primary block" data-act="new-trip">새 여행 만들기</button>`;
}

/* ================= 렌더링: 관리자 화면 ================= */
function adminScreen() {
  const nav = SCREENS.filter(s => s.id.startsWith('a-')).map(s => `<button class="${S.screen === s.id ? 'on' : ''}" data-act="nav" data-id="${s.id}">${s.name}</button>`).join('');
  const path = { 'a-metrics': 'metrics', 'a-jobs': 'jobs', 'a-common': 'common-sentences', 'a-users': 'users' }[S.screen];
  const body = { 'a-metrics': admMetrics, 'a-jobs': admJobs, 'a-common': admCommon, 'a-users': admUsers }[S.screen]();
  if (!LEGACY) return `<div class="admin-shell"><div class="admin"><nav class="admin-nav"><div class="brand">마디 <span>ADMIN</span></div>${nav}</nav><div class="admin-main">${body}</div></div>${modalHtml(true)}</div>`;
  return `<div class="window"><div class="win-bar"><i></i><i></i><i></i><div class="url">admin.trip-english.web.app/${path}</div></div>
    <div class="admin"><nav class="admin-nav"><div class="brand">마디 <span>ADMIN</span></div>${nav}</nav><div class="admin-main">${body}</div></div>${modalHtml(true)}</div>`;
}
function allTripsForAdmin() {
  const rows = S.mockTrips.map(m => ({ ...m, me: false }));
  const t = S.trip;
  if (t) {
    const lv = t.stageAt.studying ? 4 : t.stageAt.route_done ? 3 : t.stageAt.report_done ? 2 : 1;
    const pr = S.sched.length ? progress() : null;
    rows.unshift({
      id: t.id, user: 'demo.traveler', route: tripTitle(t), status: t.status, reached: lv, reportSec: t.reportSec, requests: t.requests, fails: t.fails,
      completion: phase() === 'ended' && pr ? pr.rate : null, failStreak: t.failStreak, regen: t.regenerateCount,
      genMinAgo: t.genStartedAt ? Math.floor((Date.now() - t.genStartedAt) / 60000) : null, me: true,
    });
  }
  return rows;
}
function admMetrics() {
  const rows = allTripsForAdmin(), lv = r => Math.max(1, r.reached);
  const n1 = rows.length, cnt = k => rows.filter(r => lv(r) >= k).length;
  const sched = cnt(4) / n1;
  const comp = rows.filter(r => r.completion !== null && r.completion !== undefined);
  const avg = comp.length ? comp.reduce((a, r) => a + r.completion, 0) / comp.length : 0;
  const req = rows.reduce((a, r) => a + r.requests, 0), fl = rows.reduce((a, r) => a + r.fails, 0);
  const secs = rows.map(r => r.reportSec).filter(x => x != null).sort((a, b) => a - b);
  const p90 = secs.length ? secs[Math.ceil(secs.length * 0.9) - 1] : 0;
  const kpi = (lb, val, target, pass) => `<div class="kpi ${pass ? 'pass' : 'fail'}"><div class="lb">${lb}</div><div class="val">${val}</div><div class="tg"><span>${target}</span><span class="badge ${pass ? 'b-ok' : 'b-bad'}">${pass ? '달성' : '미달'}</span></div></div>`;
  const funnel = [['여행 입력', 1], ['보고서 완료', 2], ['방문 순서 완료', 3], ['일정표 완료', 4]];
  const failedRows = rows.filter(r => /_failed$/.test(r.status));
  return `<h2>운영 지표</h2><p class="desc">여행 문서의 <code>stageAt</code>(단계별 도달 시각)으로 계산해요. 별도 분석 도구는 쓰지 않아요. (PRD 2-2)</p>
    <div class="kpis">
      ${kpi('일정표 생성 완료율', Math.round(sched * 100) + '%', '목표 70% 이상', sched >= 0.7)}
      ${kpi('평균 학습 완료율', Math.round(avg * 100) + '%', `종료 여행 ${comp.length}건 · 목표 50%`, avg >= 0.5)}
      ${kpi('AI 생성 실패율', (req ? (fl / req * 100).toFixed(1) : 0) + '%', `${fl}/${req} 요청 · 목표 5% 미만`, req ? fl / req < 0.05 : true)}
      ${kpi('보고서 생성 p90', p90 + '초', '도시 3곳 이하 · 목표 90초', p90 <= 90)}
    </div>
    <div class="grid2">
      <div class="panel funnel"><h3>단계별 도달 (여행 ${n1}건)</h3>${funnel.map(([l, k]) => `<div class="fr-row"><span>${l}</span><div class="bar"><i style="width:${cnt(k) / n1 * 100}%"></i></div><span class="n">${cnt(k)}</span></div>`).join('')}
        <p class="small" style="margin:8px 0 0">여행 입력(input_done)에 도달한 여행 기준. 데모 여행이 맨 위 행으로 포함돼요.</p></div>
      <div class="panel"><h3>최근 최종 실패</h3>${failedRows.length ? failedRows.map(r => `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border-faint);font-size:0.78125rem">
        <span><b>${esc(r.route)}</b><br><span class="small">${r.user}</span></span><span class="st-chip fail">${r.status}</span></div>`).join('') : '<div class="empty">실패한 작업이 없어요</div>'}
        <p class="small" style="margin:10px 0 0">실패율은 사용자 요청 기준이에요. 서버 자동 재요청(최대 2번)은 따로 세지 않아요.</p></div>
    </div>`;
}
function admJobs() {
  const rows = allTripsForAdmin().filter(r => r.status !== 'input_done');
  const isGen = r => /_(generating|requested)$/.test(r.status);
  const stale = r => /_generating$/.test(r.status) && r.genMinAgo != null && r.genMinAgo >= 15;
  const f = S.jobFilter;
  const list = rows.filter(r => f === 'all' || (f === 'gen' && isGen(r) && !stale(r)) || (f === 'stale' && stale(r)) || (f === 'fail' && /_failed$/.test(r.status)));
  const chip = r => `<span class="st-chip ${stale(r) ? 'fail' : isGen(r) ? 'gen' : /_failed$/.test(r.status) ? 'fail' : r.status === 'studying' ? 'ok' : ''}">${stale(r) ? 'STALLED · ' : ''}${r.status}</span>`;
  const count = k => rows.filter(r => (k === 'gen' ? isGen(r) && !stale(r) : k === 'stale' ? stale(r) : /_failed$/.test(r.status))).length;
  return `<h2>생성 작업 모니터</h2><p class="desc">생성 중 15분이 지나면 멈춘 작업으로 봐요 (FR-GEN-02). 여행 1개에는 동시에 하나의 작업만 있어서 여행 상태가 곧 작업 상태예요.</p>
    <div class="filters">${[['all', `전체 ${rows.length}`], ['gen', `생성 중 ${count('gen')}`], ['stale', `멈춤 ${count('stale')}`], ['fail', `실패 ${count('fail')}`]].map(([k, l]) => `<button class="${f === k ? 'on' : ''}" data-act="job-filter" data-v="${k}">${l}</button>`).join('')}</div>
    <div class="panel" style="padding:6px 8px"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>여행</th><th>사용자</th><th>상태</th><th>경과</th><th>failStreak</th><th>다시 생성</th><th></th></tr></thead><tbody>
    ${list.map(r => `<tr class="${stale(r) ? 'stale' : ''} ${r.me ? 'me' : ''}"><td><b>${esc(r.route)}</b><div class="mono" style="color:var(--text-3)">${r.id}${r.me ? ' · 데모 여행' : ''}</div></td>
      <td class="mono">${r.user}</td><td>${chip(r)}</td><td class="mono">${isGen(r) && r.genMinAgo != null ? r.genMinAgo + '분' : '—'}</td>
      <td class="mono">${r.failStreak}</td><td class="mono">${r.regen}/3</td>
      <td>${stale(r) ? `<button class="btn soft sm" data-act="job-fail" data-id="${r.id}">실패로 처리</button>` : /_failed$/.test(r.status) ? '<span class="small">사용자 재시도 대기</span>' : ''}</td></tr>`).join('') || `<tr><td colspan="7"><div class="empty">해당하는 작업이 없어요</div></td></tr>`}
    </tbody></table></div></div>
    <p class="small" style="margin-top:10px">데모: 사이드바에서 "생성 멈춤"을 켜고 여행을 만든 뒤, SCR-03의 "16분 경과시키기"를 누르면 데모 여행이 멈춤으로 표시돼요.</p>`;
}
function admCommon() {
  S.commonsDraft ??= JSON.parse(JSON.stringify(S.commons));
  const dirty = JSON.stringify(S.commonsDraft) !== JSON.stringify(S.commons);
  return `<div class="adm-head" style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px"><div><h2>공통 상황 문장 관리</h2>
    <p class="desc">6개 상황 × 5문장 = 30개. 모든 여행에 똑같이 들어가요 (FR-SENT-01). '응급 전화'는 참고용이라 날짜별 학습량에 들어가지 않아요. 저장하면 <b>다음 문장 생성부터</b> 반영돼요.</p></div>
    <div style="display:flex;gap:6px;flex:none"><button class="btn soft sm" data-act="cs-reset" ${dirty ? '' : 'disabled'}>되돌리기</button><button class="btn primary sm" data-act="cs-save" ${dirty ? '' : 'disabled'}>변경 사항 저장</button></div></div>
    ${notice('이름·목적지는 <b>[name]</b>·<b>[destination]</b> 빈칸으로 적어요. 학습 화면에서는 <b>[your name]</b>·<b>[your destination]</b>으로 보이고, 듣기도 그대로 읽어요.')}
    <div style="height:14px"></div>
    ${S.commonsDraft.map((g, gi) => `<div class="cs-group panel"><h4>${g.label} <span class="small">${g.key}</span></h4>
      <div class="cs-row cs-head" style="font-size:0.6875rem;color:var(--text-3)"><span>#</span><span>상황</span><span>영어 문장</span><span>한국어 뜻</span><span></span></div>
      ${g.items.map((it, ii) => { const o = S.commons[gi].items[ii]; return `<div class="cs-row"><span class="i">${ii + 1}</span>
        <input data-cs="${gi}.${ii}.situation" aria-label="상황" value="${esc(it.situation)}" class="${it.situation !== o.situation ? 'dirty' : ''}">
        <input data-cs="${gi}.${ii}.en" aria-label="영어 문장" value="${esc(it.en)}" class="${it.en !== o.en ? 'dirty' : ''}">
        <input data-cs="${gi}.${ii}.ko" aria-label="한국어 뜻" value="${esc(it.ko)}" class="${it.ko !== o.ko ? 'dirty' : ''}">
        <button class="play" data-act="cs-play" data-k="${gi}.${ii}">${I.speaker}</button></div>`; }).join('')}</div>`).join('')}`;
}
function admUsers() {
  const t = S.trip;
  const demoTrips = [
    ...(t ? [{ route: tripTitle(t), state: phase() === 'ended' ? '종료' : STATUS_KO[t.status], cur: true }] : []),
    ...S.archived.map(a => ({ route: a.route, state: '보관' })),
  ];
  const me = S.user && S.user.uid ? S.user : DEMO_USER;
  const users = [{ email: me.email, name: me.name + (me.uid ? '' : ' (데모)'), trips: demoTrips, me: true }, ...MOCK_USERS];
  return `<h2>사용자 · 여행</h2><p class="desc">현재 여행 = <code>archived = false</code>인 내 여행 (FR-TRIP-05). 새 여행을 만들면 이전 여행은 삭제하지 않고 보관해요 (FR-TRIP-04).</p>
    <div class="panel" style="padding:4px 10px">
      <div class="user-row" style="font-size:0.71875rem;color:var(--text-3)"><span>이름</span><span>이메일</span><span>여행</span></div>
      ${users.map(u => `<div class="user-row" style="${u.me ? 'background:var(--me-bg)' : ''}"><b>${esc(u.name)}</b><span class="mono" style="font-family:var(--mono);font-size:0.75rem">${esc(u.email)}</span>
        <div class="trips">${u.trips.length ? u.trips.map((tr, i) => `<span class="trip-chip ${tr.state === '보관' ? 'arch' : 'cur'}">${esc(tr.route)} · ${tr.state}</span>`).join('') : '<span class="small">여행 없음</span>'}</div></div>`).join('')}
    </div>`;
}

/* ================= 이벤트 ================= */
let toastTimer;
function toast(msg) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

/* 상황별 연습은 카드 상태(S.card)를 잠시 빌려 쓴다 — 끝낼 때 날짜별 학습의 카드 위치·뒤집은 카드를 그대로 돌려놓는다 */
function endDrill() { if (S.drill) { S.card = S.drill.savedCard; S.drill = null; } }
function go(id) {
  skipStateWrite = false;
  cancelSpeak(); S.card.back = null; if (id !== 'u-study') endDrill();
  S.screen = id; S.modal = null; S.sheet = false; pushScreen(id); render();
}

/* ================= 화면 히스토리 (안드로이드 하단 뒤로가기) =================
   예전에는 pushState·popstate 가 하나도 없어서 하단 < 를 누르면 이전 화면이 아니라
   브라우저가 앱을 닫았다(2차 사용자 피드백). 화면 이동을 히스토리에 쌓고 되돌린다.
   오버레이(확인 상자·서랍)는 열 때 한 칸 쌓아서, 뒤로가기가 그것만 먼저 닫게 한다. */
const NAV_MAX = 6;      // 이 길이에 닿으면 pushState 대신 현재 항목을 바꾼다. 브라우저 기록은 더 늘지 않는다.
const navStack = [];
let navQuiet = false;   // popstate 처리 중에는 push 하지 않는다(무한 루프 방지)

function canHist() { return typeof history !== 'undefined' && typeof history.pushState === 'function'; }
function pushScreen(id) {
  if (!canHist() || navQuiet) return;
  if (navStack[navStack.length - 1] === id) return;   // 같은 화면 재진입은 쌓지 않는다(탭 연타)
  const capped = navStack.length >= NAV_MAX;
  if (capped) navStack.shift();
  navStack.push(id);
  try {
    const state = { screen: id };
    if (capped) history.replaceState(state, '');   // 현재 항목만 바뀐다. 가장 오래된 항목은 그대로다.
    else history.pushState(state, '');
  } catch (e) { /* 상태 객체 제한 등 */ }
}
function pushOverlay(kind) {
  if (!canHist() || navQuiet) return;
  try { history.pushState({ screen: S.screen, overlay: kind }, ''); } catch (e) { /* 무시 */ }
}
function resetHistory(id) {
  navStack.length = 0; navStack.push(id);
  if (canHist()) { try { history.replaceState({ screen: id }, ''); } catch (e) { /* 무시 */ } }
}
function sideOpen() { const el = $('#side'); return !!(el && el.classList.contains('open')); }
function closeSide() { const el = $('#side'); if (el) el.classList.remove('open'); }

function onPop(state) {
  // 탈퇴가 진행 중이면 뒤로가기로 화면을 떠나지 않는다(서버가 지우는 도중에 화면만 바뀌면 상태가 엇갈린다).
  if (wdRunning() || S.entering) { try { history.pushState({ screen: S.screen, overlay: 'busy' }, ''); } catch (e) { /* 무시 */ } return; }   // 로그인 전환 중도 같다
  if (S.withdrawing) { wdEnd(); render(); return; }                  // 실패·완료 창은 뒤로가기로 닫는다
  // 열려 있는 것부터 닫는다. 사용자가 '취소'를 기대하는 순서다.
  if (S.modal) { navQuiet = true; try { closeModal(); } finally { navQuiet = false; } return; }   // 창의 onCancel 이동이 기록을 더 쌓지 않게
  if (S.screen === 'u-auth' && S.authMode) { S.authMode = null; render(); return; }   // 이메일 폼 → 두 갈래 고르기
  if (S.sheet) { closeSheet(); return; }                             // 회화 연습 시트
  if (sideOpen()) { closeSide(); return; }
  const target = (state && typeof state.screen === 'string') ? state.screen : null;
  if (!target || target === S.screen) return;         // 같은 화면이면 히스토리만 되감는다
  if (navStack.indexOf(target) < 0) return;           // 스택에서 빠진 기록(초기화 전 화면)은 되살리지 않는다
  while (navStack.length > 1 && navStack[navStack.length - 1] !== target) navStack.pop();
  navQuiet = true;
  try { go(target); } finally { navQuiet = false; }   // 되돌아가는 이동은 다시 쌓지 않는다
}
if (canHist()) {
  window.addEventListener('popstate', e => onPop(e.state || null));
  resetHistory('u-login');
}

function navFromMenu(id) {
  S.modal = null;
  let did = false;
  if (id.startsWith('a-')) { if (id === 'a-common') S.commonsDraft = null; go(id); return; }
  if (id === 'u-login') { go(id); return; }
  if (id === 'u-edit') { ensure('plan'); openTripEdit(); return; }   // 여행 설정 수정: 현재 여행 입력을 초안으로 채운다
  if (id === 'u-input' || id === 'u-gen') did = ensure('user');
  if (id === 'u-report') did = ensure('report');
  if (['u-route', 'u-home', 'u-sched', 'u-study', 'u-coll', 'u-end'].includes(id)) did = ensure('plan');
  if (id === 'u-end' && phase() !== 'ended') { S.today = Dt.add(S.trip.tripEnd, 1); toast(`데모: 오늘을 여행 종료 다음 날(${Dt.md(S.today)})로 바꿨어요.`); }
  else if (did) toast('데모: 이 화면에 필요한 데이터를 자동으로 준비했어요.');
  if (id === 'u-study') { S.studyDate = null; endDrill(); }
  S.justCompleted = null;
  go(id);
}

/* 새로고침 복원: 저장해 둔 진도·화면·카드를 되살린다. 저장분이 없거나 못 쓰면 첫 화면 그대로 뜬다 */
function sessionResume() {
  PROG.done = {}; PROG.pre = {};
  RESTORE.screen = null;
  RESTORE.studyDate = null;
  RESTORE.card = null;
  RESTORE.trip = null;
  fillProgress(sessionRead());
  RESTORE.trip = loadTripHere();
  resumeScreen();                                      /* 필요한 데이터를 채우고 그 화면으로 — 여기서 S.sched 가 다시 만들어진다 */
}

function applyDraftPreset(kind) {
  const d = defaultDraft(S.today < BASE_TODAY ? BASE_TODAY : S.today);
  if (kind === 'gap') d.cities[1].start = Dt.add(d.cities[0].end, 1);
  if (kind === 'short') d.studyStart = Dt.add(d.cities[0].start, -3);
  if (kind === 'zero') d.studyStart = d.cities[0].start;
  S.draft = d; S.showErrors = kind === 'gap';
  render();
}

function demoGen(mode) {
  PROG.done = {}; PROG.pre = {}; sessionClear();   // 새 데모 여행 — 날짜가 같아도 이전 완료가 다시 붙지 않게
  ensure('user');
  S.flags.fail = mode === 'fail'; S.flags.stuck = mode === 'stuck';
  createTrip(defaultDraft(S.today));
  request('report');
  toast(mode === 'fail' ? '데모: "AI 생성 실패"를 켜고 새 여행으로 보고서를 요청했어요.' : mode === 'stuck' ? '데모: "생성 멈춤"을 켜고 요청했어요. 끝까지 진행 후 멈춰요.' : '새 데모 여행으로 보고서 생성을 요청했어요.');
}

function preset(kind) {
  cancelGen();
  pushStateNow();                   // 계정에 남아 있던 진도를 데모 키로 옮기지 않고 먼저 올린다
  S.user = DEMO_USER;
  PROG.done = {}; PROG.pre = {}; sessionClear();   // 예시 여행은 직전 완료를 이어받지 않는다. 데모 키만 지운다.
  const base = BASE_TODAY;
  const d = defaultDraft(base);
  d.studyStart = kind === 'short' ? Dt.add(d.cities[0].start, -3) : d.cities[0].start;
  S.flags.fail = false; S.flags.stuck = false;
  createTrip(d);
  S.today = d.studyStart;
  ensure('plan');
  S.screen = 'u-route'; S.modal = null; render();
  toast(kind === 'short' ? '짧은 학습 예시: 여행 전 3일 → 하루 10문장, 장소 문장은 여행 중 학습' : '당일 시작 예시: 여행 전 학습 0일 → 모든 문장을 여행 중에 학습');
}

/* ================= 말하기 연습 (녹음 → /speak-check) =================
   작업 토큰(SPK.tok)으로 취소·늦은 응답을 구분한다. 카드 이동·화면 전환·재진입 시 cancelSpeak(). */
const SPK = { state: 'idle', tok: 0, rec: null, stream: null, ctl: null, timer: null, sid: null, result: null, clip: null };
/* 내 발음 다시 듣기(설문 Q14 "내가 연습한 발음을 들어볼 수 있으면"). 녹음은 이 탭 메모리에만 둔다 —
   서버에 따로 저장하지 않고, 다시 녹음하거나 카드를 넘기면(cancelSpeak) 재생 주소를 해제한다. */
let mineAudio = null;
function dropClip() {
  if (mineAudio) { try { mineAudio.pause(); } catch (e) { /* 이미 멈춤 */ } mineAudio = null; }
  if (SPK.clip) { try { URL.revokeObjectURL(SPK.clip.url); } catch (e) { /* 이미 해제 */ } SPK.clip = null; }
}
const stopTracks = st => { try { st && st.getTracks().forEach(t => t.stop()); } catch (e) { /* 이미 종료 */ } };
const canRecord = () => typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;   // 기능 감지(UA 아님)
const speakAvailable = () => API.base !== null && canRecord();
/* 외부 브라우저 안내 문구: 어떤 브라우저가 맞는지는 OS 로 정하고, "무엇이 안 되는지"는 기능 감지로 정한다 */
const betterBrowser = () => { const o = (AI.inAppBrowser(navigator.userAgent, location.href) || {}).os || (/iPhone|iPad|iPod/i.test(navigator.userAgent) ? 'ios' : /Android/i.test(navigator.userAgent) ? 'android' : 'other'); return o === 'ios' ? 'Safari' : o === 'android' ? 'Chrome' : 'Chrome 또는 Safari'; };
function aiBadges(s) {
  let h = '';
  if (s.ai) h += '<span class="badge b-ai">AI 생성</span>';
  else if (s.sample) h += '<span class="badge b-sample">샘플</span>';
  const w = AI.weakReviewOf(s, weakList());
  if (w) h += `<span class="badge b-weak">복습 목록 상황${w.demo ? ' · 데모 학습 기록' : ''}</span>`;
  return h;
}
function speakHtml(s) {
  if (API.base !== null && !canRecord()) return `<div class="tts-off">이 브라우저에서는 녹음이 안 돼요. ${betterBrowser()}에서 열면 말하기 연습을 쓸 수 있어요. 카드 학습은 계속할 수 있어요.</div>`;
  if (!speakAvailable()) return '';
  const mine = SPK.sid === s.id;
  const st = mine ? SPK.state : 'idle';
  const label = st === 'requesting' ? '마이크 확인 중…' : st === 'recording' ? '■ 녹음 끝내기' : st === 'uploading' ? '채점 중…' : '🎤 말해보기';
  const host = API.host || location.host;
  let res = '';
  if (mine && SPK.result) {
    const r = SPK.result;
    const parts = r.error ? [r.error]
      : r.usable !== true ? [r.mock ? '샘플 응답이에요(채점 안 됨).' : (r.reason || '평가하지 못했어요. 다시 시도해 주세요.'), '복습 목록에 저장하지 않았어요.']
      : r.limited ? [r.heard ? `들린 문장: ${r.heard}` : '', r.reason || '음성 확인이 제한되어 점수와 자동 복습 저장을 제공하지 않습니다.',
         r.saved ? '복습 목록에 저장했어요(직접 선택)' : '']   // 제한 모드: 검증 못 한 전사라 점수·일치율을 보이지 않는다
      : [typeof r.score === 'number' ? (r.score_kind === 'word_match' ? `단어 일치 ${r.score}% (발음 점수 아님)` : `점수 ${r.score}`) : '', r.heard ? `들린 문장: ${r.heard}` : '', r.fix_one ? `고칠 한 가지: ${r.fix_one}` : '', r.tip || '', r.saved ? (r.savedBy === 'user' ? '복습 목록에 저장했어요(직접 선택)' : '복습 목록에 자동 저장했어요(점수 기반 임시 규칙)') : '',
         r.offer && r.coverage !== null ? `참고: 목표 문장 단어 ${Math.round(r.coverage * 100)}% 일치 (실력 판정이 아니에요)` : ''];
    res = `<div class="speak-res">${parts.filter(Boolean).map(esc).join(' · ')}</div>`;
    if (r.offer) res += `<button class="speak-btn" data-act="weak-save">이 상황을 복습 목록에 저장</button>`;
  }
  // 결과가 나온 뒤(오류·말소리 없음 포함) 방금 녹음을 다시 들을 수 있다 — 원어민 '듣기'와 비교하라고
  if (mine && SPK.clip && SPK.clip.sid === s.id && st === 'idle') res += `<button class="speak-btn" data-act="play-mine">▶ 내 발음 듣기</button>`;
  return `<button class="speak-btn ${st === 'recording' ? 'rec' : ''}" data-act="speak-rec" ${st === 'requesting' || st === 'uploading' ? 'disabled' : ''}>${label}</button>${res}
    <div class="speak-note">녹음은 ${esc(host)} 서버로 가고, 말소리가 있을 때만 전사·교차검증 AI(Groq·AssemblyAI)로 전송돼요. 다시 듣기용 녹음은 이 화면에만 있어요.${voiceConsent().voice ? ' (동의함 · 홈에서 철회)' : ' 처음 녹음할 때 동의를 받아요.'}</div>`;
}
/* 말하기 연습 동의 — 녹음이 서버와 Google 로 나가고 복습 목록이 쌓이므로 첫 녹음 전에 받는다.
   저장소가 막힌 브라우저에서는 이번 접속 동안만 기억한다(consentMem). */
let consentMem = false;
const voiceConsent = () => { const c = AI.loadConsent(personalStore()); return c.voice ? c : consentMem ? { voice: true, at: null } : c; };
function askVoiceConsent(after) {
  const host = esc(API.host || location.host);
  confirmBox('말하기 연습 전에 확인해 주세요',
    `<b>보내는 것</b> · 녹음한 목소리(최대 15초)와 연습 중인 영어 문장<br>
     <b>받는 곳</b> · ① 이 서비스 서버(${host}) — 말소리가 있는지 신경망(VAD)으로 확인 서버 안의 두 신경망(Silero·pyannote)이 <b>모두</b> 말소리를 찾으면 ② 그 구간의 녹음이 서로 다른 전사 AI 둘에 동시에: Groq Whisper(실패 시 OpenAI Whisper), 교차검증용 AssemblyAI ③ 받아쓴 문장·목표 문장·상황 이름(글만)이 피드백용 Google Gemini API로<br>
     <b>처리</b> · 전사 AI들은 목표 문장을 모른 채 <b>받아쓰기만</b> 하고, 두 전사에서 <b>모두</b> 들린 단어만 코드가 점수로 계산해요. 교차검증이 안 되면 채점하지 않아요.<br>
     <b>목적</b> · 말하기 연습 피드백 (피드백 문장은 AI가 만든 결과예요)<br>
     <b>보관</b> · 이 서비스 서버는 녹음을 저장하지 않아요. 전사 AI 회사의 처리·보관은 각 회사 약관을 따라요.<br>
     <b>Google 처리</b> · 무료 등급 API에서는 Google이 전송된 내용을 제품 개선에 사용하고 사람 검토자가 읽을 수 있어요(계정·키와는 분리돼요). <b>민감한 개인정보는 말하지 마세요.</b><br>
     <b>이 브라우저에 저장</b> · 채점 결과로 고른 '어려워한 상황'(복습 목록). 다음 문장을 만들 때 상황 이름만 서버로 보내요. 로그인한 계정은 학습 진도·복습 목록·여행 설정·이 동의를 그 계정 기록으로 서버에 올려요. 녹음 파일은 올리지 않아요.<br><br>
     동의하지 않아도 카드 학습과 듣기는 그대로 쓸 수 있어요. 동의는 홈 화면에서 언제든 철회할 수 있고, 철회하면 복습 목록도 지워져요.`,
    '동의하고 녹음하기', () => {
      S.modal = null;
      if (!saveConsentHere(true)) consentMem = true;
      render(); (after || (() => toggleSpeak()))();
    }, { cancel: '동의하지 않기' });
}
function privacyCard() {
  const c = voiceConsent(), n = weakList().length;
  const when = c.at ? Dt.full(c.at.slice(0, 10)) : '이번 접속';
  return `<div class="sec-title"><h4>AI · 개인정보</h4></div><div class="card">
    <p class="small" style="line-height:1.7">· 'AI 생성' 표시가 붙은 문장과 말하기 채점은 AI가 만든 결과예요. 틀릴 수 있어요.<br>
      · AI 문장을 만들 때 도시·장소명과 복습 상황 이름이 Google Gemini API로 전송돼요.<br>
      · 말하기 연습 동의: <b>${c.voice ? `동의함 (${when})` : '동의하지 않음'}</b>${c.voice ? '' : ' — 처음 녹음할 때 물어봐요'}<br>
      · 복습 목록: <b>${n}개</b> · ${accountUid() ? '이 계정에 저장돼요' : '이 브라우저에만 저장돼요'}<br>
      · 여행 설정(나라·도시·날짜): ${accountUid() ? '이 계정에 저장돼요' : '이 브라우저에만 저장돼요'}</p>
    ${c.voice || n ? `<div style="display:flex;gap:8px;margin-top:10px">
      ${c.voice ? '<button class="btn soft" style="flex:1" data-act="consent-withdraw">동의 철회</button>' : ''}
      ${n ? '<button class="btn soft" style="flex:1" data-act="weak-delete">복습 목록 삭제</button>' : ''}</div>` : ''}
  </div>`;
}
/* 홈 맨 아래 계정 블록. 로그아웃 버튼과 안내를 하나의 카드(.card = 패딩 한 곳)에 담는다.
   탈퇴하기는 카드 '패딩 밖'(카드 아래)에 작고 연한 글씨로 둔다. */
function accountCard() {
  const signed = !!S.user && !isGuest();
  const initial = esc(userName().slice(0, 1) || '김');
  return `<div class="sec-title"><h4>계정</h4></div><div class="card account-card">
    <div class="acc-row"><span class="acc-avatar">${initial}</span>
      <span class="acc-who"><b>${esc(userName())}</b><span class="small">${esc(userEmail())}</span></span></div>
    <p class="small acc-note">${signed
      ? '학습 진도와 여행 설정은 계정에 저장돼요. 로그아웃하면 이 브라우저에서만 나가고, 다시 로그인하면 이어서 할 수 있어요.'
      : '로그인하면 학습 진도·복습 목록·여행 설정이 계정에 저장돼요.'}</p>
    ${signed
      ? '<button class="btn soft block" data-act="logout-home">로그아웃</button>'
      : '<button class="btn primary block" data-act="tab" data-id="u-login">로그인</button>'}
  </div>
  ${signed ? '<button type="button" class="withdraw" data-act="withdraw">탈퇴하기</button>' : ''}`;
}
const weakItem = s => ({ category_id: s.categoryId, id: s.situationId, situation: s.situation, en: s.en, ko: s.ko });
function updateSpeakUi() {
  if (TALK.on) updateTalkUi();
  const el = $('[data-live=speak]'); const r = studyShown() && pickRow();
  if (!el || !r) return;
  const s = S.smap[r.ids[Math.min(S.card.i, r.ids.length - 1)]];
  if (s) el.innerHTML = speakHtml(s);
}
function cancelSpeak() {
  SPK.tok++;
  clearTimeout(SPK.timer); SPK.timer = null;
  if (SPK.rec) { SPK.rec.cancelled = true; try { if (SPK.rec.state !== 'inactive') SPK.rec.stop(); } catch (e) { /* 이미 종료 */ } }
  stopTracks(SPK.stream); SPK.stream = null; SPK.rec = null;
  if (SPK.ctl) { SPK.ctl.abort(); SPK.ctl = null; }
  SPK.state = 'idle'; SPK.result = null;
  dropClip();
}
function stopSpeak() { clearTimeout(SPK.timer); SPK.timer = null; if (SPK.rec && SPK.rec.state === 'recording') SPK.rec.stop(); }
/* opt = { target, onResult } — 대화하기는 턴마다 목표 문장이 다르고(내 문장·이어서), 결과를 카드가 아니라 대화로 넘긴다. */
async function toggleSpeak(opt) {
  if (SPK.state === 'requesting' || SPK.state === 'uploading') return;      // 중복 요청 방지
  if (SPK.state === 'recording') { stopSpeak(); return; }
  if (!voiceConsent().voice) { askVoiceConsent(opt ? () => toggleSpeak(opt) : null); return; }   // 동의 전에는 마이크도 열지 않는다
  const r = pickRow(); const s = r && S.smap[r.ids[Math.min(S.card.i, r.ids.length - 1)]]; if (!s) return;
  cancelSpeak();
  const tok = SPK.tok; SPK.sid = s.id; SPK.state = 'requesting'; updateSpeakUi();
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) {
    if (tok === SPK.tok) {
      SPK.state = 'idle';
      const err = { error: `마이크를 사용할 수 없어요. 권한을 확인하거나 ${betterBrowser()}에서 열어 주세요. 카드 학습은 계속할 수 있어요.` };
      if (opt && opt.onResult) opt.onResult(err); else SPK.result = err;
      updateSpeakUi();
    }
    return;
  }
  if (tok !== SPK.tok) { stopTracks(stream); return; }                      // 취소 뒤에 늦게 허용된 권한: 바로 해제
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(m => MediaRecorder.isTypeSupported?.(m));
  let rec;
  try { rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined); }
  catch (e) {
    stopTracks(stream); SPK.state = 'idle';
    const err = { error: `이 브라우저에서는 녹음을 시작할 수 없어요. ${betterBrowser()}에서 열어 주세요.` };
    if (opt && opt.onResult) opt.onResult(err); else SPK.result = err;
    updateSpeakUi(); return;
  }
  const chunks = [];
  SPK.stream = stream; SPK.rec = rec;
  rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
  rec.onstop = () => {
    stopTracks(stream);
    if (tok !== SPK.tok || rec.cancelled) return;                            // 취소는 업로드하지 않는다
    // 말소리 여부는 서버의 Silero 신경망 VAD 가 판정한다(음량·데시벨 기준이 아님). 말이 없으면 외부 AI 로 보내지 않는다.
    const blob = new Blob(chunks, { type: rec.mimeType || mime || 'audio/webm' });
    dropClip();
    try { SPK.clip = { sid: s.id, url: URL.createObjectURL(blob) }; } catch (e) { SPK.clip = null; }   // 다시 듣기용(메모리)
    uploadSpeech(tok, blob, s, opt);
  };
  rec.start();
  SPK.state = 'recording'; SPK.timer = setTimeout(stopSpeak, 15000); updateSpeakUi();
}
async function uploadSpeech(tok, blob, s, opt) {
  SPK.state = 'uploading'; SPK.rec = null; SPK.stream = null;
  if (opt && opt.onUpload) opt.onUpload();   // 대화하기: '말을 마친 뒤' 3초 안내는 여기서부터 잰다
  updateSpeakUi();
  const ctl = SPK.ctl = new AbortController();
  let res;
  try { res = await AI.speakCheck({ fetchImpl: (u, o) => fetch(u, o), base: API.base, blob, target: (opt && opt.target) || s.en, situation: s.situation, signal: ctl.signal }); }
  catch (e) {
    if (tok !== SPK.tok) return;
    SPK.state = 'idle'; SPK.ctl = null;
    const err = { error: e.message === 'too-large' || e.status === 413 ? '녹음이 너무 길어요. 짧게 다시 말해 주세요.' : e.message === 'empty-audio' || e.status === 400 ? '녹음된 소리가 없어요. 다시 시도해 주세요.' : e.status === 429 ? '요청이 너무 많아요. 잠시 후 다시 시도해 주세요.' : e.status === 415 ? '이 브라우저의 녹음 형식은 지원되지 않아요.' : '채점 서버에 연결하지 못했어요. 카드 학습은 계속할 수 있어요.' };
    if (opt && opt.onResult) { opt.onResult(err); updateSpeakUi(); return; }
    SPK.result = err;
    updateSpeakUi(); return;
  }
  if (tok !== SPK.tok) return;                                               // 늦은 응답: 표시도 저장도 하지 않는다
  SPK.state = 'idle'; SPK.ctl = null;
  if (opt && opt.onResult) { opt.onResult(res); updateSpeakUi(); return; }   // 대화 중에는 점수·자동 저장 없음(끝난 뒤 요약)
  const decision = AI.weakDecision(s, res);
  const save = decision === 'auto';
  if (save) saveWeakList(AI.upsertWeak(weakList(), weakItem(s)));
  SPK.result = { ...res, saved: save, savedBy: save ? 'auto' : null, offer: decision === 'ask', coverage: typeof res.heard === 'string' ? AI.heardCoverage(s.en, res.heard) : null };
  updateSpeakUi(); renderDemo();
}

/* ================= 대화하기 (실시간 회화 1a — 스크립트, AI 호출 0회) =================
   docs/research/realtime-agent/README.md 4절 1a. 상대 대사는 검수된 talk 데이터만, 소리는 브라우저 TTS.
   상대가 먼저(ask) → 내 답 녹음(/speak-check) → 상대(replies[nextFor]) → 내가 이어서(next) → 끝난 뒤 요약.
   대화 중에는 점수를 보이지 않고, 고칠 점은 끝난 뒤 한 가지만. 서버·마이크가 없으면 채점 없이 '다음'으로 진행한다.
   주요 버튼은 내 차례 줄의 힌트·마이크·넘어가기 셋이고(맨 아래), 상대 대사의 다시 듣기·Sorry? 는 작은 보조 버튼이다.
   아직 없음(후속): 침묵 8·15·25초 처리, 한국어 답 감지, 검수된 쉬운 말 바꿔 말하기, 정적 음성 파일(카톡 인앱). */
const TALK = { on: false, sid: null, turns: [], i: 0, hint: 0, again: {}, results: {}, note: '', slow: false, tok: 0, timer: null, say: 0 };
const talkCur = () => TALK.turns[TALK.i] || null;
function cancelTalk() {
  TALK.tok++; clearTimeout(TALK.timer); TALK.timer = null;
  if (ttsSupported()) { try { speechSynthesis.cancel(); } catch (e) { /* 이미 멈춤 */ } }
  if (TALK.on) cancelSpeak();
  Object.assign(TALK, { on: false, sid: null, turns: [], i: 0, hint: 0, again: {}, results: {}, note: '', slow: false });
}
function startTalk() {
  const s = curSent(); const turns = s ? AI.talkTurns(s.talk, s) : [];
  if (!turns.length) return;
  cancelTalk(); cancelSpeak();
  Object.assign(TALK, { on: true, sid: s.id, turns, i: 0 });
  render(); talkEnter();
}
/* 현재 턴에 들어설 때: 상대 턴이면 자막과 함께 읽고, 다 읽으면 내 차례로 넘어간다(녹음은 버튼으로 시작). */
function talkEnter() {
  const t = talkCur(); TALK.hint = 0; TALK.note = ''; TALK.slow = false;
  if (!t) { updateTalkUi(); return; }
  if (t.who === 'ai') talkSay(TALK.i, true);
  updateTalkUi();
}
function talkSay(idx, advance) {
  const t = TALK.turns[idx]; if (!t || t.who !== 'ai') return;
  const tok = TALK.tok, rep = AI.talkRepeat(S.ttsRate, TALK.again[idx] || 0), say = ++TALK.say;
  // 다시 듣기가 앞 발화를 끊으면 그 onend 도 불린다 — 마지막 발화만 턴을 넘긴다
  const go = () => { if (advance && say === TALK.say && tok === TALK.tok && TALK.i === idx) TALK.timer = setTimeout(() => { if (tok === TALK.tok && TALK.i === idx) talkNext(); }, 250); };
  if (ttsState() !== 'ok') { updateTalkUi(); return; }   // 소리가 없으면 자막을 읽고 '다음'을 누른다
  speak(t.en, $(`[data-act="talk-say"][data-i="${idx}"]`), null, { rate: rep.rate, onend: go });
}
function talkNext() {
  if (!TALK.on) return;
  if (SPK.state !== 'idle') cancelSpeak();
  clearTimeout(TALK.timer); TALK.timer = null;
  TALK.i = Math.min(TALK.turns.length, TALK.i + 1);
  talkEnter();
}
function talkRecord() {
  const t = talkCur(); if (!t || t.who !== 'me') return;
  if (SPK.state === 'requesting' || SPK.state === 'uploading') return;
  if (ttsSupported()) { try { speechSynthesis.cancel(); } catch (e) { /* 이미 멈춤 */ } }   // 상대 목소리가 녹음에 섞이지 않게
  if (SPK.state === 'recording') { stopSpeak(); return; }
  const tok = TALK.tok, idx = TALK.i;
  TALK.note = ''; TALK.slow = false;
  toggleSpeak({ target: t.en,
    // 말을 마친 뒤(전송 시작) 3초가 넘으면 한국어로 이유를 알린다(멈춘 화면 없음, 조사 3절)
    onUpload: () => {
      clearTimeout(TALK.timer);
      TALK.timer = setTimeout(() => { if (tok === TALK.tok && TALK.i === idx && SPK.state === 'uploading') { TALK.slow = true; updateTalkUi(); } }, 3000);
    },
    onResult: res => {
      clearTimeout(TALK.timer); TALK.timer = null;
      if (tok !== TALK.tok || TALK.i !== idx) return;
      TALK.slow = false;
      if (res && res.error) { TALK.note = res.error.replace(/ ?카드 학습은 계속할 수 있어요\./, '') + ' 넘어가기로 대화를 이어 갈 수 있어요.'; updateTalkUi(); return; }
      const heard = res && typeof res.heard === 'string' ? res.heard.trim() : '';
      TALK.results[t.key] = res;
      // 점수 없이 되받기만 한다. 들린 말이 있으면 잠깐 보여 주고 상대 차례로 넘어간다.
      TALK.note = heard ? `들렸어요: “${heard}”` : (res && res.reason) || '잘 안 들렸어요. 다시 말하거나 넘어가도 돼요.';
      updateTalkUi();
      if (heard) TALK.timer = setTimeout(() => { if (tok === TALK.tok && TALK.i === idx) talkNext(); }, 1200);
    } });
}
function talkStateText() {
  const t = talkCur();
  if (!t) return '대화가 끝났어요';
  if (t.who === 'ai') return ttsState() === 'ok' ? '상대가 말하고 있어요' : '자막을 읽고 다음을 눌러요';
  if (SPK.state === 'requesting') return '마이크를 확인하고 있어요';
  if (SPK.state === 'recording') return '듣고 있어요 — 다 말하면 버튼을 눌러요';
  if (SPK.state === 'uploading') return TALK.slow ? '조금만 기다려 주세요 — 서버가 깨어나는 중일 수 있어요' : '알아듣는 중이에요…';
  return '내 차례예요 — 영어로 답해 보세요';
}
function talkLineHtml(t, idx) {
  if (t.who === 'ai') {
    const last = idx === TALK.i || (idx === TALK.i - 1 && talkCur() && talkCur().who === 'me');
    const rep = AI.talkRepeat(S.ttsRate, TALK.again[idx] || 0), off = SPK.state !== 'idle' ? 'disabled' : '';
    return `<div class="talk-bubble ai"><span class="talk-who">상대</span><b lang="en">${esc(t.en)}</b>
      ${rep.rephrase ? `<p>${esc(t.ko)}</p>` : ''}
      ${last ? `<div class="talk-acts">${ttsState() === 'ok' ? `<button class="talk-say sub" data-act="talk-say" data-i="${idx}" ${off}>${I.speaker}다시 듣기</button>
        <button class="talk-say sub" data-act="talk-sorry" data-i="${idx}" ${off}>Sorry? 천천히</button>` : ''}</div>` : ''}</div>`;
  }
  const r = TALK.results[t.key];
  const said = r && typeof r.heard === 'string' && r.heard.trim() ? r.heard.trim() : '';
  return idx < TALK.i ? `<div class="talk-bubble me"><span class="talk-who">나</span><b lang="en">${esc(said || t.en)}</b>${said ? '' : '<p>(녹음 없이 넘어감)</p>'}</div>` : '';
}
function talkMeHtml(t) {
  const hints = AI.talkHint(TALK.turns, TALK.i, TALK.hint);
  const busy = SPK.state === 'requesting' || SPK.state === 'uploading';
  const mic = speakAvailable()
    ? `<button class="talk-mic ${SPK.state === 'recording' ? 'rec' : ''}" data-act="talk-rec" ${busy ? 'aria-disabled="true"' : ''} aria-label="${SPK.state === 'recording' ? '녹음 끝내기' : '말하기'}">${SPK.state === 'recording' ? '■' : '🎤'}</button>`
    : `<p class="small">${API.base !== null && !canRecord() ? `이 브라우저에서는 녹음이 안 돼요. ${betterBrowser()}에서 열면 말로 답할 수 있어요.` : '소리 내어 말해 본 뒤 다음을 눌러요.'} 채점은 하지 않아요.</p>`;
  return `<div class="talk-turn">
    <div class="talk-hints">${hints.map(h => `<p class="talk-hint ${h.kind}" ${h.kind === 'en' || h.kind === 'first' ? 'lang="en"' : ''}>${esc(h.text)}</p>`).join('')}</div>
    ${TALK.note ? `<p class="talk-note">${esc(TALK.note)}</p>` : ''}
    <div class="talk-ctl">
      <button class="btn soft" data-act="talk-hint" ${TALK.hint >= AI.TALK_HINT_MAX ? 'disabled' : ''}>힌트${TALK.hint ? ` ${TALK.hint}/${AI.TALK_HINT_MAX}` : ''}</button>
      ${mic}
      <button class="btn soft" data-act="talk-next" ${busy || SPK.state === 'recording' ? 'disabled' : ''}>${TALK.results[t.key] ? '다음' : '넘어가기'}</button>
    </div></div>`;
}
function talkSummaryHtml() {
  const sum = AI.talkSummary(TALK.turns, TALK.results);
  const rows = sum.lines.map(l => `<li><b lang="en">${esc(l.en)}</b>
    <span class="small">${l.heard ? `들린 문장: ${esc(l.heard)}` : '녹음 없음'}${l.score !== null ? ` · ${l.kind === 'word_match' || l.kind === 'word_match_consensus' ? `단어 일치 ${l.score}% (발음 점수 아님)` : `점수 ${l.score}`}` : ''}</span></li>`).join('');
  return `<div class="talk-done"><h4>대화를 마쳤어요</h4>
    <p class="small">내 차례 ${sum.myTurns}번 중 ${sum.spoken}번 말했어요.</p>
    <ul class="talk-sum">${rows}</ul>
    ${sum.fix ? `<div class="talk-fix"><span class="talk-who">고칠 점 한 가지</span><b lang="en">${esc(sum.fix.en)}</b><p>${esc(sum.fix.text)}</p></div>` : ''}
    <div class="talk-ctl"><button class="btn soft" data-act="talk-start">다시 해보기</button><button class="btn primary" data-act="talk-exit">회화 연습으로</button></div></div>`;
}
function talkBodyHtml() {
  const t = talkCur(), shown = TALK.turns.slice(0, Math.min(TALK.i + 1, TALK.turns.length));
  const total = TALK.turns.filter(x => x.who === 'me').length, done = TALK.turns.slice(0, TALK.i).filter(x => x.who === 'me').length;
  return `<div class="talk-log">${shown.map((x, k) => talkLineHtml(x, k)).join('')}</div>
    ${!t ? talkSummaryHtml() : t.who === 'me' ? talkMeHtml(t) : `<div class="talk-ctl"><button class="btn soft" data-act="talk-next">다음</button></div>`}
    ${t ? `<p class="small talk-prog">내 차례 ${done + 1} / ${total} · 대화 중에는 점수를 보여 주지 않아요</p>` : ''}`;
}
function talkSheetHtml(s) {
  return `<div class="sheet-wrap" data-act="sheet-bg"><section class="sheet talk" role="dialog" aria-modal="true" aria-label="대화하기" data-act="noop">
    <div class="sheet-handle"></div>
    <div class="talk-head"><h3>대화하기 <span class="small">${esc(s.situation)}</span></h3><button class="talk-exit" data-act="talk-exit">그만하기</button></div>
    <p class="talk-state" role="status" aria-live="polite" tabindex="-1">${esc(talkStateText())}</p>
    <div data-live="talk">${talkBodyHtml()}</div>
  </section></div>`;
}
/* 상태 문구는 고정된 role=status 의 글자만 바꾼다(스크린리더가 바뀐 상태를 읽게). 다시 그린 뒤 같은 버튼으로 포커스를 돌린다. */
function updateTalkUi() {
  const el = $('[data-live=talk]'); if (!el || !TALK.on) return;
  const st = $('.talk-state'); if (st) { const v = talkStateText(); if (st.textContent !== v) st.textContent = v; }
  const f = document.activeElement && el.contains(document.activeElement) ? document.activeElement.dataset.act : null;
  el.innerHTML = talkBodyHtml();
  if (f) {   // 같은 버튼 → 내 차례의 마이크 → 상태 문구 순으로 포커스를 돌려 <body> 로 빠지지 않게
    const b = el.querySelector(`[data-act="${f}"]:not([disabled])`) || el.querySelector('[data-act="talk-rec"]') || $('.talk-state');
    if (b) b.focus();
  }
}

/* 이 계정의 브라우저 기록을 모두 지운다. 계정 칸(:uid)과, 로그인 전에 이 브라우저에 남은
   같은 이름의 공용 칸(uid 없음)을 함께 지운다 — 안내 문구("이 브라우저에 저장된 같은 기록")와 맞춘다. */
function clearAccountStorage() {
  const keys = [SESSION_KEY, AI.WEAK_KEY, AI.CONSENT_KEY, AI.TRIP_KEY];
  const box = personalStore();
  if (box) keys.forEach(k => { try { box.removeItem(k); } catch (e) { /* 저장소 막힘 */ } });
  if (STORE && box !== STORE) keys.forEach(k => { try { STORE.removeItem(k); } catch (e) { /* 저장소 막힘 */ } });
}
/* 탈퇴 증명 — **사전 커밋먼트**. 요청을 보내기 **전에** 챌린지를 만들어 이 기기에 저장한다.
   서버가 기록을 생략하면(앱 침해·부분 실패) 이 챌린지가 관리자의 앵커된 체인에 없으므로,
   관리자가 `verify-chain --challenge` 로 대조하면 누락이 드러난다. 계정이 지워진 뒤에도 남아야 하므로
   계정 칸이 아니라 기기 공용 칸(STORE)에 둔다. CSPRNG 가 없으면 만들지 않는다(추측 가능한 값은 증거가 못 된다). */
const WITHDRAW_PROOF_KEY = 'cd_withdraw_proof';
function newChallenge() {
  const box = window.crypto;
  if (!box || !box.getRandomValues) return '';
  const bytes = new Uint8Array(16);
  box.getRandomValues(bytes);
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}
function saveWithdrawProof(proof) {
  try { if (STORE) STORE.setItem(WITHDRAW_PROOF_KEY, JSON.stringify(proof)); } catch (e) { /* 저장소 막힘 */ }
}
function withdrawProof() {
  try { const raw = STORE && STORE.getItem(WITHDRAW_PROOF_KEY); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
}
/* 증명 상태: none(요청한 적 없음) · unknown(요청했는데 영수증이 없다 = **상태 불명**) · confirmed(영수증 받음) */
function withdrawProofState() {
  const proof = withdrawProof();
  if (!proof || !proof.challenge) return { state: 'none', proof: null };
  return { state: proof.receipt ? 'confirmed' : 'unknown', proof: proof };
}
function proofWhen(ms) {
  try { return new Date(ms).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }); }
  catch (e) { return ''; }
}
/* 탈퇴 증명 카드 — 사용자가 자기 눈으로 "영수증을 받았는지"를 볼 수 있게 한다.
   영수증이 없으면 조용히 넘어가지 않고 "상태 불명"으로 보여주고, 보관·보고·삭제를 제공한다.
   (사전 커밋먼트는 사용자가 챌린지를 들고 있어야 의미가 있다 — 기기를 잃으면 증거도 잃는다.) */
function withdrawProofBlock() {
  const info = withdrawProofState();
  if (info.state === 'none') return '';
  const when = proofWhen(info.proof.at);
  const confirmed = info.state === 'confirmed';
  const receipt = info.proof.receipt || {};
  const title = confirmed ? '탈퇴 증명: 영수증 받음' : '탈퇴 증명: 상태 불명';
  const detail = confirmed
    ? `이 기기에서 탈퇴를 요청했고 서버가 영수증을 돌려줬어요(${esc(when)}). 관리자가 앵커된 기록과 대조할 수 있어요.`
    : `이 기기에서 탈퇴를 요청했는데 <b>서버 영수증을 받지 못했어요</b>(${esc(when)}). 탈퇴가 끝났는지 확인되지 않은 상태예요 — 다시 시도하거나, 증명을 내려받아 관리자에게 보여 주세요.`;
  const seq = (receipt.seq === undefined || receipt.seq === null) ? '-' : String(receipt.seq);
  return `<div class="card" style="margin-top:10px">
    <b>${title}</b>
    <div class="small" style="margin:6px 0">${detail}</div>
    <div class="small" style="opacity:.75">챌린지 ${esc(String(info.proof.challenge).slice(0, 16))}… · 순번 ${esc(seq)} · 결과 ${esc(String(receipt.outcome || '-'))}</div>
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
      <button class="btn soft" data-act="proof-download">증명 내려받기</button>
      ${confirmed ? '' : '<button class="btn soft" data-act="proof-report">서버에 보고</button>'}
      <button class="btn soft" data-act="proof-clear">이 기기에서 지우기</button>
    </div></div>`;
}
function downloadWithdrawProof() {
  const info = withdrawProofState();
  if (info.state === 'none') return;
  const payload = JSON.stringify({
    schema: 'SEAL-RECEIPT-v1', exported_at: new Date().toISOString(),
    challenge: info.proof.challenge, requested_at: new Date(info.proof.at).toISOString(),
    receipt: info.proof.receipt || null,
    note: info.proof.receipt
      ? '이 파일을 보관하세요. 관리자가 앵커된 기록과 대조할 수 있습니다.'
      : '서버 영수증을 받지 못했습니다(상태 불명). 관리자에게 이 파일을 보여 주세요.',
  }, null, 2);
  try {
    const url = URL.createObjectURL(new Blob([payload], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'withdraw-proof-' + String(info.proof.challenge).slice(0, 12) + '.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('증명 파일을 내려받았어요. 기기를 바꾸기 전에 보관해 두세요.');
  } catch (e) { toast('이 브라우저에서는 파일로 저장할 수 없어요.'); }
}
function clearWithdrawProof() {
  try { if (STORE) STORE.removeItem(WITHDRAW_PROOF_KEY); } catch (e) { /* 저장소 막힘 */ }
  toast('이 기기에서 증명을 지웠어요.');
  render();
}
function reportSavedProof() {
  const info = withdrawProofState();
  if (info.state !== 'unknown') return Promise.resolve('nothing');
  // 서버에 "영수증을 못 받았다"고 보고한다(증거 봉인 트리거). 로그인 상태에서만 가능하다.
  return reportWithdrawIssue('no_receipt', true);
}
/* 관리자 경로: 서버가 서비스 계정으로 탈퇴 흔적·토큰 취소·기록 삭제·계정 삭제를 한 번에 한다.
   반환: { status: 'ok'|'unavailable'|'failed', receipt: {...}|null }
   200 이어도 본문 계약(erased:true)을 확인한다 — 프록시·CDN 의 200 을 성공으로 오인하지 않게. */
async function eraseOnServer(token, challenge) {
  try {
    const headers = { Authorization: 'Bearer ' + token, Accept: 'application/json' };
    if (challenge) headers['X-Withdraw-Challenge'] = challenge;
    const res = await fetch((API.base || '') + '/account/erase', { method: 'POST', headers });
    if (res.status === 404 || res.status === 405) return { status: 'unavailable', receipt: null };
    if (res.status !== 200) {
      let code = ''; try { code = (await res.json()).detail; } catch (e) { code = ''; }
      return { status: (res.status === 503 && code === 'admin_unavailable') ? 'unavailable' : 'failed', receipt: null };
    }
    const body = await res.json().catch(() => null);
    return { status: (body && body.erased === true) ? 'ok' : 'failed',
             receipt: (body && body.receipt) || null };
  } catch (e) { return { status: 'failed', receipt: null }; }
}
/* 기존 경로: 규칙 삭제(DELETE /user/state)로 서버 기록만 지운다. 계정은 화면이 deleteUser 로 지운다.
   200 이고 본문이 deleted:true 일 때만 성공으로 본다. */
async function deleteStateOnServer(token) {
  try {
    const res = await fetch((API.base || '') + '/user/state', { method: 'DELETE', headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' } });
    if (res.status !== 200) return false;
    const body = await res.json().catch(() => null);
    return !!(body && body.deleted === true);
  } catch (e) { return false; }
}
/* 탈퇴 진행 창. 확인을 누른 뒤 서버 응답(수 초)을 기다리는 동안 화면이 멈춘 것처럼 보였다(사용자 신고).
   확인 창 자리에 스피너·경과 시간·단계 목록을 띄우고, 실제 처리 순서대로 갱신한다.
   진행 중에는 닫히지 않는다 — 바깥 클릭(noop)·뒤로가기(onPop)·새로고침(beforeunload 경고). */
const WD_SERVER_DETAIL = '증거 기록 → 토큰 취소 → 기록 삭제 → 계정 삭제';
const WD_STEPS = {
  admin: ['로그인 정보 확인', '탈퇴 증명(챌린지) 준비', '서버에서 계정·기록 삭제', '이 기기의 기록 정리', '로그아웃'],
  rules: ['로그인 정보 확인', '탈퇴 증명(챌린지) 준비', '서버의 저장 기록 삭제', '이 기기의 기록 정리', '계정 삭제'],
  local: ['이 기기의 기록 정리'],
};
let wdTimer = null;
const wdRunning = () => !!(S.withdrawing && !S.withdrawing.done && !S.withdrawing.error);
const wdSecs = () => Math.floor((Date.now() - S.withdrawing.started) / 1000);
function wdStart(steps) {
  S.modal = null; modalFn = null;
  S.withdrawing = { steps: steps.slice(), step: 0, detail: '', error: '', done: false, started: Date.now() };
  clearInterval(wdTimer);
  wdTimer = setInterval(() => {            // 경과 시간만 고친다(화면 전체를 다시 그리지 않는다)
    const el = $('[data-live=wd-elapsed]');
    if (!wdRunning()) { clearInterval(wdTimer); wdTimer = null; return; }
    if (el) el.textContent = wdSecs() + '초';
  }, 250);
  render();
}
function wdStep(i, detail = '') { if (!S.withdrawing) return; S.withdrawing.step = i; S.withdrawing.detail = detail; render(); }
function wdFail(msg) { if (!S.withdrawing) { toast(msg); return; } S.withdrawing.error = msg; render(); }
function wdEnd() { clearInterval(wdTimer); wdTimer = null; S.withdrawing = null; }
function withdrawModalHtml() {
  const w = S.withdrawing;
  const items = w.steps.map((label, i) => {
    const st = w.error ? (i < w.step ? 'done' : i === w.step ? 'fail' : '') : (w.done || i < w.step) ? 'done' : i === w.step ? 'now' : '';
    const detail = st === 'now' && w.detail ? `<span class="small wd-detail">${w.detail}</span>` : '';
    return `<li class="${st}" data-wd-step="${i}"><span class="ic">${st === 'done' ? '✓' : st === 'fail' ? '!' : ''}</span><span>${label}${detail}</span></li>`;
  }).join('');
  const state = w.error ? 'fail' : w.done ? 'done' : 'run';
  const title = w.error ? '탈퇴를 멈췄어요' : w.done ? '탈퇴를 마쳤어요' : '탈퇴하는 중이에요';
  const foot = w.error
    ? `<p class="wd-err">${esc(w.error)}</p><p class="small">계정과 기록은 그대로예요.</p><div class="acts"><button class="btn primary" data-act="wd-close">닫기</button></div>`
    : w.done ? '<p class="small">로그인 화면으로 이동해요.</p>'
      : '<p class="small">창을 닫거나 새로고침하지 마세요. 끝나면 자동으로 넘어가요.</p>';
  return `<div class="modal-wrap" data-act="noop"><div class="modal wd" data-act="noop" role="dialog" aria-modal="true" aria-labelledby="wd-title" aria-busy="${state === 'run'}">
    <div class="wd-head"><span class="wd-spin ${state}" aria-hidden="true"></span><h3 id="wd-title">${title}</h3><span class="wd-time" data-live="wd-elapsed">${wdSecs()}초</span></div>
    <ul class="steps wd-steps" aria-live="polite">${items}</ul>${foot}</div></div>`;
}
window.addEventListener('beforeunload', e => { if (wdRunning()) { e.preventDefault(); e.returnValue = ''; } });

/* 로그인 전환 화면. 구글 창이 닫힌 뒤(이메일은 누른 뒤) 서버 확인·계정 기록 불러오기를 기다리는 동안
   로그인 화면에 멈춰 보였고, 완료 안내가 화면 이동보다 먼저 떴다(사용자 신고 10/19).
   로그인 화면을 불투명하게 덮고 단계를 보여 준 뒤, **다음 화면으로 먼저 넘어가고 나서** 안내를 띄운다.
   실패하면 덮개를 걷고 로그인 화면에서 이유를 알린다(입력한 이메일은 그대로). */
const EN_STEPS = {
  google: ['구글 로그인', '계정 확인', '저장된 기록 불러오기', '화면 준비'],
  email: ['이메일·비밀번호 확인', '저장된 기록 불러오기', '화면 준비'],
};
function enStart(steps, step = 0) {
  // 로그인 화면은 히스토리의 첫 항목이라, 항목을 하나 쌓지 않으면 뒤로가기가 앱이 막기 전에 사이트를 떠난다.
  if (!S.entering) pushOverlay('entering');
  S.entering = { steps: steps.slice(), step }; render();
}
function enStep(i) { if (S.entering) { S.entering.step = i; render(); } }
function enEnd() { S.entering = null; }
function enteringHtml() {
  const e = S.entering;
  const items = e.steps.map((label, i) => {
    const st = i < e.step ? 'done' : i === e.step ? 'now' : '';
    return `<li class="${st}"><span class="ic">${st === 'done' ? '✓' : ''}</span><span>${label}</span></li>`;
  }).join('');
  return `<div class="modal-wrap entering" data-act="noop"><div class="modal wd en" data-act="noop" role="status" aria-live="polite" aria-busy="true">
    <div class="wd-head"><span class="wd-spin run" aria-hidden="true"></span><h3>로그인하는 중이에요</h3></div>
    <ul class="steps wd-steps">${items}</ul></div></div>`;
}
/* 계정을 받은 뒤: 기록 불러오기(adoptAccount) → 화면 준비·이동(after-login) → 덮개 걷기 → 안내. */
async function finishLogin(account, doneMsg, loadStep) {
  enStep(loadStep);
  try {
    await adoptAccount(account, { navigate: false });
  } catch (e) {
    enEnd(); render(); toast('계정 기록을 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.'); return;
  }
  if (!S.user) { enEnd(); render(); return; }   // 탈퇴한 계정 등: adoptAccount 가 이미 정리하고 안내했다
  enStep(loadStep + 1);
  ACT['after-login']();                         // 다음 화면으로 먼저 넘어간다(덮개는 아직 위에 있다)
  enEnd(); render();
  toast(doneMsg);
}

/* 탈퇴: 서버(관리자 또는 규칙) → 브라우저 → (폴백이면) 클라이언트 deleteUser. 되돌릴 수 없다.
   서버 단계가 확정된 뒤에 브라우저 기록을 지운다 — 중간에 멈추면 계정·기록을 그대로 두고,
   나중에 화면을 다시 그려도 빈 기록이 서버로 올라가 지워지지 않게 한다. */
async function doWithdraw() {
  const uid = accountUid();
  const fb = !!(window.FirebaseAuth && FirebaseAuth.enabled);
  const accountUser = fb && !!uid;
  const stop = m => { skipStateWrite = false; wdFail(m); };   // 진행 창에 멈춘 단계와 이유를 보여 준다
  if (stateTimer) { clearTimeout(stateTimer); stateTimer = null; }   // 예약된 업로드가 지운 기록을 되살리지 않게
  cancelGen();                                                       // 진행 중인 생성 응답도 상태를 덮지 않게
  skipStateWrite = true;

  let msg = accountUser ? '탈퇴했어요. 계정과 저장된 기록을 모두 지웠어요.' : '이 브라우저에 저장된 기록을 모두 지웠어요.';
  if (accountUser && API.base !== null) {
    wdStart(WD_STEPS.admin);
    let token = '';
    try { token = await FirebaseAuth.idToken(); } catch (e) { token = ''; }
    if (!token) return stop('로그인 정보를 확인하지 못해 탈퇴를 멈췄어요. 잠시 뒤 다시 시도해 주세요.');
    wdStep(1);
    const challenge = newChallenge();
    if (challenge) saveWithdrawProof({ challenge: challenge, at: Date.now(), receipt: null });
    wdStep(2, WD_SERVER_DETAIL);                                     // 가장 오래 걸리는 단계(서버 응답 대기)
    const admin = await eraseOnServer(token, challenge);
    if (accountClosed) { wdEnd(); return; }    // 기다리는 사이 다른 경로가 '탈퇴한 계정'을 감지해 이미 정리했다(이중 처리 금지)
    if (admin.status === 'ok') {
      saveWithdrawProof({ challenge: challenge, at: Date.now(), receipt: admin.receipt });
      wdStep(3);
      clearAccountStorage();                   // 서버가 계정·토큰·기록을 지웠다 — 이제 로컬만 정리
      wdStep(4);
      try { await FirebaseAuth.signOut(); } catch (e) { /* 화면 상태는 비운다 */ }
    } else if (admin.status === 'unavailable') {
      // 서비스 계정 키가 없는 환경: 규칙 삭제 + 클라이언트 deleteUser 로 되돌아간다.
      S.withdrawing.steps = WD_STEPS.rules.slice(); wdStep(2);
      if (!await deleteStateOnServer(token)) return stop('저장된 계정 기록을 지우지 못해 탈퇴를 멈췄어요. 잠시 뒤 다시 시도해 주세요.');
      if (accountClosed) { wdEnd(); return; }
      wdStep(3);
      clearAccountStorage();                   // 서버 기록이 지워진 뒤에 로컬도 지운다
      wdStep(4);
      const r = await FirebaseAuth.deleteAccount();
      if (accountClosed) { wdEnd(); return; }
      if (!r.ok) {
        msg = r.code === 'auth/requires-recent-login'
          ? '저장된 기록은 지웠어요. 보안을 위해 다시 로그인한 뒤 탈퇴를 다시 눌러 주세요.'
          : (FirebaseAuth.koreanError({ code: r.code }) || '계정 삭제에 실패했어요. 잠시 뒤 다시 시도해 주세요.');
      }
    } else {
      return stop('탈퇴를 완료하지 못했어요. 잠시 뒤 다시 시도해 주세요.');   // 계정·기록을 그대로 둔다
    }
  } else {
    wdStart(WD_STEPS.local);
    clearAccountStorage();                     // 서버를 쓰지 않는(데모) 경우: 로컬만
  }

  SESS_READY = false;
  S.user = null;
  S.trip = null; resetDerived();
  S.archived = [];                           // 보관한 여행 제목도 메모리에서 지운다(관리자 화면에 남지 않게)
  PROG.done = {}; PROG.pre = {};
  RESTORE.screen = null; RESTORE.studyDate = null; RESTORE.card = null; RESTORE.trip = null;
  aiRefreshKey = null;                       // 다음 여행에서 복원 시 AI 문장 채우기가 다시 돌게
  SESS_READY = true;
  skipStateWrite = false;
  // 모든 단계를 체크로 바꿔 '마쳤어요'를 잠깐 보여 준 뒤 닫는다. 뒤에는 이미 로그인 화면이 열려 있다.
  const w = S.withdrawing;
  if (w) { w.done = true; w.step = w.steps.length; }
  go('u-login');
  setTimeout(() => { if (S.withdrawing === w) { wdEnd(); render(); } toast(msg); }, 1200);   // 그사이 새 진행 창이면 건드리지 않는다
}

const ACT = {
  nav: el => { navFromMenu(el.dataset.id); if (!LEGACY) $('#side').classList.remove('open'); },
  drawer: () => {
    const el = $('#side'), opening = !el.classList.contains('open');
    el.classList.toggle('open');
    if (opening) pushOverlay('side');   // 뒤로가기가 서랍만 닫게
  },
  theme: el => { setTheme(el.dataset.v); render(); },
  tab: el => {
    const id = el.dataset.id;
    if (['u-home', 'u-sched', 'u-study', 'u-coll', 'u-route'].includes(id) && !S.plan) { navFromMenu(id); return; }
    if (id === 'u-study') { S.studyDate = null; endDrill(); }
    S.justCompleted = null; go(id);
  },
  noop: () => {},
  link: el => window.open(el.getAttribute('href'), '_blank', 'noopener'),
  reset: () => {
    const c = S.demoClosed;
    PROG.done = {}; PROG.pre = {};
    // 여행을 먼저 지운 뒤에 진도를 비워야 한다. sessionClear 가 지금 저장소를 서버로 올리므로, 순서가 반대면 지운 여행이 다시 올라간다.
    AI.saveTrip(personalStore(), null);
    sessionClear();
    initState();
    S.demoClosed = c;
    resetHistory(S.screen);
    render();
    toast('처음 상태로 되돌렸어요.');
  },
  'demo-toggle': () => { S.demoClosed = !S.demoClosed; renderDemo(); },
  'set-today': el => { S.today = el.dataset.date; S.justCompleted = null; render(); toast(`오늘을 ${Dt.full(S.today)}로 바꿨어요.`); },
  preset: el => preset(el.dataset.kind),
  'weak-demo': () => { saveWeakList(DEMO_WEAK.reduce((l, w) => AI.upsertWeak(l, w), weakList())); renderDemo(); toast('데모 학습 기록을 불러왔어요. 실제 학습에서 생긴 기록이 아니에요.'); },
  'weak-clear': () => { saveWeakList([]); renderDemo(); toast('복습 목록을 비웠어요.'); },
  'speak-rec': () => toggleSpeak(),
  'consent-withdraw': () => confirmBox('동의를 철회할까요?',
    `말하기 연습을 다시 쓰려면 새로 동의해야 해요. ${accountUid() ? '이 계정' : '이 브라우저'}에 저장된 복습 목록 ${weakList().length}개도 함께 지워요.`,
    '철회하고 지우기', () => {
      S.modal = null; cancelSpeak(); consentMem = false;
      const ok = withdrawHere();
      render(); renderDemo();
      toast(ok ? '동의를 철회하고 복습 목록을 지웠어요.' : '브라우저 저장소에 접근하지 못했어요. 브라우저 설정에서 이 사이트 데이터를 지워 주세요.');
    }, { danger: true }),
  'weak-delete': () => confirmBox('복습 목록을 지울까요?',
    `${accountUid() ? '이 계정' : '이 브라우저'}에 저장된 어려워한 상황 ${weakList().length}개를 지워요. 다음 문장 생성부터 반영돼요.`,
    '지우기', () => {
      S.modal = null;
      const ok = saveWeakList([]);
      render(); renderDemo(); toast(ok ? '복습 목록을 지웠어요.' : '브라우저 저장소에 접근하지 못했어요.');
    }, { danger: true }),
  'weak-save': () => {
    const r = pickRow(); const s = r && S.smap[r.ids[Math.min(S.card.i, r.ids.length - 1)]];
    if (!s || SPK.sid !== s.id || !SPK.result || !SPK.result.offer) return;       // 다른 카드·취소된 결과에는 저장하지 않는다
    saveWeakList(AI.upsertWeak(weakList(), weakItem(s)));
    SPK.result = { ...SPK.result, offer: false, saved: true, savedBy: 'user' }; updateSpeakUi(); renderDemo(); toast('복습 목록에 저장했어요.');
  },

  login: () => {
    if (window.FirebaseAuth && FirebaseAuth.enabled) {
      // 구글 창이 닫히는 순간 전환 화면을 띄운다(창을 닫아 취소하면 띄우지 않는다).
      FirebaseAuth.signInGoogle(() => enStart(EN_STEPS.google, 1)).then(account => {
        if (!account || account.provider === 'anonymous') { enEnd(); render(); return; }
        return finishLogin(account, '구글 로그인을 완료했어요.', 2);
      }).catch(err => { enEnd(); render(); const msg = FirebaseAuth.koreanError(err); if (msg) toast(msg); });
      return;
    }
    S.user = DEMO_USER; ACT['after-login'](); toast('구글 로그인을 완료했어요.');   // 다음 화면으로 넘어간 뒤 안내
  },
  'login-email': () => {
    if (!window.FirebaseAuth || !FirebaseAuth.enabled) { toast('이 환경에서는 이메일 로그인을 쓸 수 없어요.'); return; }
    const email = (document.querySelector('[data-auth="email"]') || {}).value || '';
    const password = (document.querySelector('[data-auth="password"]') || {}).value || '';
    const name = (document.querySelector('[data-auth="name"]') || {}).value || '';
    if (!email.trim() || !password) { toast('이메일과 비밀번호를 입력해 주세요.'); return; }
    const signup = S.authMode === 'signup';
    authDraft.email = email; authDraft.name = name;   // 전환 화면이 폼을 다시 그려도(실패 시) 입력한 이메일·이름을 남긴다
    enStart(EN_STEPS.email, 0);
    FirebaseAuth.signInEmail(email.trim(), password, name.trim(), signup).then(account => {
      if (!account || account.provider === 'anonymous') { enEnd(); render(); return; }
      return finishLogin(account, signup ? '가입했어요.' : '로그인했어요.', 1);
    }).catch(err => { enEnd(); render(); const msg = FirebaseAuth.koreanError(err); if (msg) toast(msg); });
  },
  guest: () => { S.user = GUEST_USER; toast('로그인 없이 시작해요. 기록은 이 브라우저에만 남아요.'); ACT['after-login'](); },
  'auth-open': () => { S.authMode = null; go('u-auth'); },
  'auth-pick': el => {   // 두 갈래 중 하나를 고르면 폼을 연다. 폼에서 뒤로가기는 고르기로 돌아간다(오버레이 한 칸)
    const v = el.dataset.v || null;
    if (v && !S.authMode) pushOverlay('auth-form');
    S.authMode = v; render();
  },
  'after-login': () => {
    // 저장된 여행이 있으면 계획을 다시 만들어 곧바로 홈까지 보낸다(새로고침·재로그인 뒤 메인화면 도달).
    if (!S.trip || S.trip.archived) {
      const saved = loadTripHere();
      if (saved) { S.trip = tripFromInput(saved); resetDerived(); }
    }
    if (S.trip && !S.trip.archived) {
      if (!S.plan && !S.places.length) ensure('plan');
      go(S.plan ? 'u-home' : S.places.length ? 'u-report' : 'u-gen');
      return;
    }
    go('u-input');
  },
  logout: () => {
    const finish = () => {
      SESS_READY = false;
      skipStateWrite = true;
      S.user = null;
      S.trip = null;
      resetDerived();
      PROG.done = {}; PROG.pre = {};
      RESTORE.screen = null;
      RESTORE.studyDate = null;
      RESTORE.card = null;
      RESTORE.trip = null;
      fillProgress(sessionRead());
      SESS_READY = true;
      skipStateWrite = false;
      toast('로그아웃했어요. 로그인 화면 외에는 들어갈 수 없어요.');
      go('u-login');
    };
    const run = async () => {
      try { await pushStateNow(); } catch (e) { /* 올리지 못해도 이 브라우저 기록은 계정 칸에 남는다 */ }
      if (window.FirebaseAuth && FirebaseAuth.enabled) {
        try { await FirebaseAuth.signOut(); } catch (e) { /* 화면 상태는 비운다 */ }
      }
      finish();
    };
    run();
  },
  // 홈 맨 아래 계정 카드의 로그아웃 — 실수로 눌리지 않게 한 번 확인한다.
  'logout-home': () => confirmBox('로그아웃할까요?',
    '학습 진도와 여행 설정은 계정에 저장돼 있어요. 다시 로그인하면 이어서 할 수 있어요.',
    '로그아웃', () => { S.modal = null; ACT.logout(); }, { danger: true }),
  // 탈퇴 증명 카드 동작
  'proof-download': () => downloadWithdrawProof(),
  // 실제로 보낸 결과대로 안내한다(예전에는 보내지 못해도 늘 '보고했어요').
  'proof-report': () => {
    reportSavedProof().then(r => toast(
      r === 'sent' ? '관리자에게 보고했어요.'
        : r === 'no_login' ? '로그인한 뒤에 보고할 수 있어요. 지금은 증명 파일을 내려받아 관리자에게 보여 주세요.'
          : r === 'nothing' ? '보고할 \'상태 불명\' 탈퇴 기록이 없어요.'
            : '보고하지 못했어요. 잠시 뒤 다시 시도하거나 증명 파일을 내려받아 관리자에게 보여 주세요.'
    )).catch(() => toast('보고하지 못했어요. 증명 파일을 내려받아 관리자에게 보여 주세요.'));
  },
  'proof-clear': () => clearWithdrawProof(),
  // 탈퇴: 계정과 저장된 기록을 모두 지운다(되돌릴 수 없음).
  'withdraw': () => confirmBox('탈퇴하면 계정과 기록이 모두 지워져요',
    `학습 진도·복습 목록·말하기 동의·여행 설정이 계정에서 지워지고, 이 브라우저에 저장된 같은 기록도 함께 지워져요. <b>되돌릴 수 없어요.</b>`,
    '탈퇴하기', () => { S.modal = null; doWithdraw(); }, { danger: true }),

  // 홈 D-Day 카드·사이드바에서 여행 설정 수정 화면을 연다.
  'edit-trip': () => openTripEdit(),
  // 수정 내용 저장: 날짜만 바뀌면 계획만 다시 계산하고, 도시·나라가 바뀌면 보고서부터 다시 만든다.
  'save-trip': () => {
    S.showErrors = true;
    const v = R.validate(S.draft, S.today);
    if (!v.ok) { render(); toast('입력 내용을 확인해 주세요.'); return; }
    const t = S.trip;
    if (!t) { go('u-input'); return; }
    const d = S.draft;
    const sameCities = String(d.country || '').trim() === t.country && sameTripCities(d.cities, t.cities);
    if (sameCities) {
      // 날짜가 바뀌어 완료한 날이 일정에서 빠지면 조용히 지우지 않고 먼저 확인한다.
      const keep = tripSchedDates(d);
      const lost = (S.sched || []).filter(r => r.kind !== 'free' && r.completed && !keep.has(r.date)).length;
      const saveDates = () => {
        S.modal = null;
        const ok = applyTripDates(d);
        S.draft = defaultDraft(S.today); S.showErrors = false;
        go('u-home');
        toast(ok ? '여행 설정을 저장하고 학습 일정표를 다시 계산했어요.' : '학습 일정표는 다시 계산했지만, 이 브라우저에 저장하지 못했어요.');
      };
      if (lost > 0) {
        confirmBox('학습 시작일을 바꿀까요?',
          `바꾸면 완료한 날 <b>${lost}일</b>이 일정에서 빠져 완료 표시가 사라져요. 계속할까요?`,
          '저장하기', saveDates, { danger: true });
        return;
      }
      saveDates();
      return;
    }
    confirmBox('여행을 다시 만들까요?',
      '도시나 나라가 바뀌면 장소와 문장을 처음부터 다시 만들어요. 학습 진도는 날짜가 같으면 이어지고, 다르면 다시 학습해야 해요.',
      '다시 만들기', () => {
        S.modal = null;
        editTrip(d);
        S.draft = defaultDraft(S.today); S.showErrors = false;
        request('report');
      }, { danger: true });
  },
  // 여행지·일정을 바꾸고 보고서와 문장을 통째로 다시 만든다(도시가 같아도 강제 재생성).
  'save-trip-regen': () => {
    S.showErrors = true;
    const v = R.validate(S.draft, S.today);
    if (!v.ok) { render(); toast('입력 내용을 확인해 주세요.'); return; }
    const t = S.trip;
    if (!t) { go('u-input'); return; }
    const d = S.draft;
    const keep = tripSchedDates(d);
    const lost = (S.sched || []).filter(r => r.kind !== 'free' && r.completed && !keep.has(r.date)).length;
    confirmBox('보고서와 문장을 새로 만들까요?',
      '장소 보고서와 영어 문장을 처음부터 다시 만들어요. 지금 보고서·문장은 사라져요.' +
      (lost > 0 ? ` 완료한 날 <b>${lost}일</b>이 일정에서 빠져 완료 표시가 사라져요.` : ' 학습 진도는 날짜가 같으면 이어져요.'),
      '새로 만들기', () => {
        S.modal = null;
        editTrip(d);
        S.draft = defaultDraft(S.today); S.showErrors = false;
        request('report');
      }, { danger: true });
  },

  'add-city': () => {
    if (S.draft.cities.length >= 5) { toast('도시는 최대 5곳까지 입력할 수 있어요.'); return; }
    const last = S.draft.cities[S.draft.cities.length - 1];
    S.draft.cities.push({ name: '', start: last.end, end: last.end ? Dt.add(last.end, 2) : '' });
    render();
  },
  'del-city': el => { S.draft.cities.splice(+el.dataset.i, 1); render(); },
  'submit-trip': () => {
    S.showErrors = true;
    const v = R.validate(S.draft, S.today);
    if (!v.ok) { render(); toast('입력 내용을 확인해 주세요.'); return; }
    const doCreate = () => { S.modal = null; createTrip(S.draft); S.draft = defaultDraft(S.today); S.showErrors = false; request('report'); };
    if (S.trip && !S.trip.archived) confirmBox('새 여행을 만들까요?', `진행 중인 여행 <b>${esc(tripTitle(S.trip))}</b>은 보관되고 더 이상 보이지 않아요. (삭제되지는 않아요)`, '보관하고 만들기', doCreate, { danger: true });
    else doCreate();
  },
  'demo-gap': () => applyDraftPreset('gap'),
  'demo-short': () => applyDraftPreset('short'),
  'demo-zero': () => applyDraftPreset('zero'),
  'demo-default': () => applyDraftPreset('default'),

  'demo-gen': () => demoGen('ok'),
  'demo-gen-fail': () => demoGen('fail'),
  'demo-gen-stuck': () => demoGen('stuck'),
  'demo-age': () => {
    const t = S.trip;
    if (!t || !/_generating$/.test(t.status)) { toast('생성 중인 작업이 없어요. 먼저 "멈춤 화면 보기"를 눌러 주세요.'); return; }
    t.genStartedAt -= 16 * 60 * 1000; render(); toast('생성 시작 시각을 16분 전으로 옮겼어요.');
  },
  retry: () => retry(),

  'city-tab': el => { S.cityTab = el.dataset.city; render(); },
  cand: el => { const c = el.dataset.city; S.showCand[c] = !(S.showCand[c] || S.places.some(p => p.city === c && p.isCandidate && p.selected)); render(); },
  place: el => {
    const t = S.trip, p = S.places.find(x => x.id === el.dataset.id);
    if (t.status !== 'report_done') { toast('장소를 확정한 뒤에는 바꿀 수 없어요.'); return; }
    if (p.selected) p.selected = false;
    else {
      const cap = S.reportMeta[p.city].base;
      if (selCount(p.city) >= cap) { toast(`${josa(p.city, '은', '는')} 최대 ${cap}곳까지 고를 수 있어요. 다른 장소를 먼저 빼 주세요.`); return; }
      p.selected = true;
    }
    render();
  },
  regen: () => {
    const t = S.trip, left = 3 - t.regenerateCount;
    if (left <= 0) return;
    confirmBox('보고서를 다시 만들까요?', `지금 보고서와 체크 상태가 초기화돼요. 성공하면 남은 횟수가 ${left}번에서 ${left - 1}번으로 줄어요.`, '다시 만들기', () => { S.modal = null; request('report'); });
  },
  'confirm-places': () => {
    const n = S.places.filter(p => p.selected).length;
    confirmBox('장소를 확정할까요?', `선택한 ${n}곳으로 방문 순서와 문장을 만들어요. 확정한 뒤에는 장소를 바꿀 수 없어요.`, '확정하기', () => { S.modal = null; S.trip.status = 'route_requested'; request('route'); });
  },

  'study-date': el => {
    S.studyDate = el.dataset.date; S.justCompleted = null; endDrill();
    if (isWide() && (S.screen === 'u-sched' || S.screen === 'u-study')) { go(S.screen); window.scrollTo(0, 0); }   // 2열: 화면은 그대로, 오른쪽 상세만 바뀐다
    else go('u-study');
  },
  flip: el => {
    el.classList.toggle('flipped');
    // 보고 있는 면을 기억한다. 동의 창 등으로 화면을 다시 그려도 카드가 앞면으로 돌아가지 않게.
    S.card.back = el.classList.contains('flipped') ? S.card.i : null;
    if (el.classList.contains('flipped')) {
      const r = pickRow(), before = S.card.flipped.size;
      S.card.flipped.add(S.card.i); updateStudyLive();
      if (r && before < r.ids.length && S.card.flipped.size >= r.ids.length) allFlipped(r);   // 방금 다 뒤집었다
    }
    else if (ttsSupported()) speechSynthesis.cancel();
    sessionWrite();   /* 뒤집은 카드·보던 카드 위치를 남긴다 — 여기만 render 를 거치지 않는다 */
  },
  'play-mine': el => {
    if (!SPK.clip) return;
    try { speechSynthesis.cancel(); } catch (e) { /* 듣기 미지원 */ }
    if (mineAudio) { try { mineAudio.pause(); } catch (e) { /* 이미 멈춤 */ } }
    mineAudio = new Audio(SPK.clip.url);
    el.classList.add('playing');
    const done = () => el.classList.remove('playing');
    mineAudio.onended = mineAudio.onpause = mineAudio.onerror = done;
    mineAudio.play().catch(() => { done(); toast('이 브라우저에서는 녹음을 다시 재생하지 못했어요.'); });
  },
  'card-prev': () => { cancelSpeak(); S.sheet = false; S.card.i = Math.max(0, S.card.i - 1); render(); },
  'card-next': () => { cancelSpeak(); S.sheet = false; const r = pickRow(); S.card.i = Math.min(r.ids.length - 1, S.card.i + 1); render(); },
  'speak-card': el => { const r = pickRow(); speak(S.smap[r.ids[S.card.i]].en, el, readTarget(el)); },
  speak: el => speak(S.smap[el.dataset.id].en, el, readTarget(el)),
  'sheet-open': () => { S.sheet = true; pushOverlay('sheet'); render(); },
  'sheet-close': () => closeSheet(),
  'talk-start': () => startTalk(),
  'talk-exit': () => { cancelTalk(); render(); },
  'talk-next': () => talkNext(),
  'talk-rec': () => talkRecord(),
  'talk-hint': () => { TALK.hint = Math.min(AI.TALK_HINT_MAX, TALK.hint + 1); updateTalkUi(); },
  'talk-say': el => { if (SPK.state !== 'idle') return; const i = +el.dataset.i; talkSay(i, i === TALK.i); },   // 녹음에 TTS 가 섞이지 않게
  'talk-sorry': el => { if (SPK.state !== 'idle') return; const i = +el.dataset.i; TALK.again[i] = (TALK.again[i] || 0) + 1; updateTalkUi(); talkSay(i, i === TALK.i); },
  'sheet-bg': (el, e) => { if (e.target === el) closeSheet(); },
  'say-line': el => { const s = curSent(); const L = s && talkLine(s.talk, el.dataset.k); if (L) speak(L.en, el, readTarget(el)); },
  rate: el => { S.ttsRate = S.ttsRate < 0.9 ? 0.95 : 0.75; el.textContent = S.ttsRate < 0.9 ? '느리게' : '보통 속도'; },
  complete: () => {
    const r = pickRow();
    if (!canComplete(r) || S.card.flipped.size < r.ids.length) return;
    r.completed = true; r.completedAt = Date.now(); PROG.done[r.date] = r.completedAt; S.justCompleted = r.date; S.studyDate = r.date;
    render(); toast('학습 완료! 완료율이 갱신됐어요.');
  },
  restudy: () => { S.justCompleted = null; resetCard(); render(); },
  'sched-filter': el => { S.schedFilter = el.dataset.v; render(); },
  'demo-fill': () => {
    if (!S.plan) ensure('plan');
    let n = 0;
    S.sched.forEach((r, i) => { if (r.date < S.today && r.kind !== 'free' && !r.completed && i % 3 !== 2) { r.completed = true; r.completedAt = Date.now(); PROG.done[r.date] = r.completedAt; n++; } });
    render(); toast(n ? `지난 날 ${n}일을 완료로 채웠어요. 나머지는 미완료로 남아요.` : '채울 지난 날이 없어요. 사이드바에서 오늘 날짜를 뒤로 옮겨 보세요.');
  },
  'coll-tab': el => { S.coll = { tab: el.dataset.v, filter: 'all' }; render(); },
  'coll-filter': el => { S.coll.filter = el.dataset.v; render(); },
  drill: el => {
    const by = el.dataset.by, v = el.dataset.v;
    const ids = [...S.sents, ...(S.refs || [])].filter(s => by === 'sit' ? s.source !== 'place' && s.sit === v : s.placeId === v).map(s => s.id);
    if (!ids.length) return;
    const label = by === 'sit' ? S.commons.find(g => g.key === v).label : S.places.find(p => p.id === v).name;
    endDrill();
    S.drill = { kind: 'drill', date: `drill:${by}:${v}`, label, ids, newIds: [], completed: false, savedCard: S.card };
    S.justCompleted = null; resetCard(S.drill.date); go('u-study'); window.scrollTo(0, 0);
  },
  'new-trip': () => confirmBox('새 여행을 만들까요?', '이 여행은 보관되고 더 이상 보이지 않아요. (삭제되지는 않아요)', '보관하고 새로 만들기', () => {
    PROG.done = {}; PROG.pre = {};
    archiveTrip();
    // 저장해 둔 여행 입력을 먼저 지운 뒤 진도를 비운다. 반대로 하면 서버에 이전 여행이 다시 올라간다.
    AI.saveTrip(personalStore(), null);
    sessionClear();
    S.trip = null; S.places = []; S.sched = []; S.plan = null; S.sents = []; S.refs = []; S.days = [];
    S.draft = defaultDraft(S.today); S.showErrors = false; S.modal = null; go('u-input'); toast('이전 여행을 보관했어요.');
  }, { danger: true }),

  'modal-ok': () => { const fn = modalFn; modalFn = null; fn && fn(); },
  'modal-cancel': () => closeModal(),
  'preview-ok': el => { previewOk.add(el.dataset.date); render(); },   // 2열 상세의 '미리 학습하기'
  'wd-close': () => { if (!wdRunning()) { wdEnd(); render(); } },   // 실패했을 때만 보인다
  'modal-bg': (el, e) => { if (e.target === el) closeModal(); },

  'job-filter': el => { S.jobFilter = el.dataset.v; render(); },
  'job-fail': el => {
    const id = el.dataset.id;
    if (S.trip && id === S.trip.id) { failStage(S.trip.status.split('_')[0]); S.screen = 'a-jobs'; render(); toast('데모 여행 작업을 실패로 처리했어요. 사용자 화면에 다시 시도 버튼이 나타나요.'); return; }
    const m = S.mockTrips.find(x => x.id === id);
    m.status = m.status.replace('_generating', '_failed'); m.failStreak++; m.fails++; render(); toast('작업을 실패로 처리했어요.');
  },
  'cs-play': el => { const [gi, ii] = el.dataset.k.split('.').map(Number); speak(S.commonsDraft[gi].items[ii].en, el); },
  'cs-save': () => {
    for (const g of S.commonsDraft) for (const it of g.items) if (!it.en.trim() || !it.ko.trim()) { toast('영어 문장과 한국어 뜻은 비워 둘 수 없어요.'); return; }
    S.commons = JSON.parse(JSON.stringify(S.commonsDraft)); render(); toast('저장했어요. 다음 문장 생성부터 반영돼요. (진행 중인 여행은 그대로)');
  },
  'cs-reset': () => { S.commonsDraft = JSON.parse(JSON.stringify(S.commons)); render(); },
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const fn = ACT[el.dataset.act];
  if (!fn) return;
  if (el.tagName === 'A') e.preventDefault();
  if (el.dataset.act === 'noop') { e.stopPropagation(); return; }
  fn(el, e);
});
document.addEventListener('input', e => {
  const el = e.target;
  if (el.dataset.bind) {
    const k = el.dataset.bind.split('.');
    if (k[0] === 'city') S.draft.cities[+k[1]][k[2]] = el.value; else S.draft[k[0]] = el.value;
    updateInputLive();
  }
  if (el.dataset.cs) {
    const [gi, ii, f] = el.dataset.cs.split('.');
    S.commonsDraft[+gi].items[+ii][f] = el.value;
    el.classList.toggle('dirty', el.value !== S.commons[+gi].items[+ii][f]);
    const dirty = JSON.stringify(S.commonsDraft) !== JSON.stringify(S.commons);
    document.querySelectorAll('[data-act=cs-save],[data-act=cs-reset]').forEach(b => (b.disabled = !dirty));
  }
});
document.addEventListener('change', e => {
  const el = e.target;
  if (el.dataset.flag) { S.flags[el.dataset.flag] = el.checked; render(); toast(`${el.closest('label').querySelector('span').textContent}: ${el.checked ? '켜짐' : '꺼짐'}`); }
  if (el.id === 'demo-date' && el.value) { S.today = el.value; S.justCompleted = null; render(); }
});
/* 경과 시간 표시와 멈춤(15분) 판정을 1초마다 갱신 */
setInterval(() => {
  if (S.screen !== 'u-gen') return;
  const el = $('[data-live=elapsed]');
  if (isStale() && el) { render(); return; }
  if (el) el.textContent = elapsed();
}, 1000);
/* 앱이 다시 보일 때 화면 갱신 (NFR-03) */
document.addEventListener('visibilitychange', () => { if (!document.hidden) render(); });
window.addEventListener('pagehide', () => { pushStateNow(); });

/* 배너는 판정이 바뀌면 다시 그린다 — 음성 목록(speechSynthesis.getVoices)은 늦게 채워져서 첫 판정은 'ok' 로 나올 수 있다 */
const INAPP_INFO = AI.inAppBrowser(navigator.userAgent, location.href);
function renderInAppBanner() {
  const el = $('#inapp-banner'); if (!el) return;
  const info = INAPP_INFO;
  try { if (sessionStorage.getItem('cd_inapp_closed') === '1') { el.hidden = true; return; } } catch (e) { /* 저장소 막힘: 매번 안내 */ }   // 닫으면 이번 방문 동안 다시 안 띄움
  /* 무엇이 안 되는지는 기능 감지로만 정한다(UA 추정 아님). UA 는 안내 문구(카톡 메뉴 이름)에만 쓴다. */
  const noRec = API.base !== null && !canRecord(), noTts = ttsState() !== 'ok';
  if (!info && !noRec && !noTts) { el.hidden = true; return; }   // 일반 브라우저이고 기능도 다 되면 아무것도 띄우지 않는다
  const lack = noRec && noTts ? '듣기와 녹음이' : noRec ? '녹음이' : noTts ? "'듣기'(음성 재생)가" : '';
  const where = info ? `${esc(info.name)}에서는` : '이 브라우저에서는';
  /* 카톡에는 자체 메뉴 '다른 브라우저로 열기'가 있다(Android 스크린샷으로 확인) — 우리가 만든 버튼보다 확실하므로 이것을 먼저 안내한다 */
  const kakaoAnd = !!info && info.name === '카카오톡' && info.os === 'android';
  const how = kakaoAnd ? "오른쪽 아래 ⋮ → '다른 브라우저로 열기'를 눌러 주세요." : `${betterBrowser()}에서 열어 주세요.`;
  /* 안 되는 것만 말하면 앱을 닫아 버린다(P2) — 여기서도 되는 것을 함께 알린다 */
  const works = noRec && noTts ? '카드 학습은' : noRec ? '듣기와 카드 학습은' : noTts ? (API.base !== null ? '말하기와 카드 학습은' : '카드 학습은') : '';
  const msg = lack ? `<b>${where} ${lack} 안 돼요.</b> ${how}${works ? ` ${works} 여기서도 돼요.` : ''}`
                   : `<b>${esc(info.name)} 안에서 열려 있어요.</b> 듣기·말하기가 안 되면 ${how}`;   // 기능은 있어 보이지만 앱 안 웹뷰는 실행 중 막힐 수 있다
  const open = info && info.scheme ? `<button type="button" data-inapp="open">브라우저에서 열기</button>` : '';
  el.innerHTML = `<span>${msg}</span>${open}<button type="button" data-inapp="copy">링크 복사</button><button type="button" data-inapp="close">닫기</button>`;
  el.hidden = false;
}
function initInAppBanner() {
  const el = $('#inapp-banner'); if (!el) return;
  el.addEventListener('click', async e => {   // 한 번만 연결(재판정으로 내용만 바뀐다)
    const b = e.target.closest('[data-inapp]'); if (!b) return;
    if (b.dataset.inapp === 'open') { if (INAPP_INFO && INAPP_INFO.scheme) location.href = INAPP_INFO.scheme; return; }
    if (b.dataset.inapp === 'close') { el.hidden = true; try { sessionStorage.setItem('cd_inapp_closed', '1'); } catch (err) { /* 무시 */ } return; }
    try { await navigator.clipboard.writeText(location.href); toast(`링크를 복사했어요. ${betterBrowser()}에 붙여넣어 열어 주세요.`); }
    catch (err) { toast(`주소창의 링크를 길게 눌러 복사한 뒤 ${betterBrowser()}에서 열어 주세요.`); }
  });
  renderInAppBanner();
}

initState();
renderSide();
/* 서버 미리 깨우기: Render 무료 플랜은 15분 놀면 잠들고, 깨어나는 데 수십 초 걸린다. 사용자가 여행을 입력하는 동안 /health 한 번으로
   깨워 두면 첫 생성·말하기가 그 시간을 기다리지 않는다. 개인정보는 보내지 않는다. 사용자가 ?api= 로 지정한 외부 서버에는 부르지 않는다. */
if (API.base !== null && !API.external) { try { fetch(API.base + '/health', { cache: 'no-store' }).catch(() => {}); } catch (e) { /* 폴백 전용 */ } }
$('#demo-fab').hidden = MODE === 'product';
initInAppBanner();
render();
/* 주소 뒤에 화면 ID(#u-home)를 붙이면 그 화면으로 바로 열린다. 없으면 지난번 보던 화면과 진도로 돌아간다(A3: 새로고침 진도 유지) */
const startId = location.hash.slice(1);
function bootScreen() {
  if (SCR[startId]) navFromMenu(startId);
  else sessionResume();
}
/* 로그인 계정이 있으면 그 칸을 읽기 전에 공용 기록을 화면에 올리지 않는다.
   계정이 없거나 설정이 없으면 기존처럼 공용 키를 바로 복원한다. */
if (window.FirebaseAuth && API.base !== null) {
  FirebaseAuth.ready.then(account => {
    if (account && account.provider !== 'anonymous' && account.uid) {
      adoptAccount(account, { navigate: !SCR[startId] }).then(() => {
        // 탈퇴 감지로 로그아웃한 뒤에는 화면을 옮기지 않는다 — 그러면 데모 사용자로 홈이 열려 로그아웃이 되돌아간다.
        if (SCR[startId] && S.user) navFromMenu(startId);
      });
    } else bootScreen();
  });
} else bootScreen();

/* ===== 카드 좌우로 밀어 넘기기 (cardSwipe) =====
   가로로 확정된 제스처만 앞/뒤 카드로 넘긴다 — 세로 스크롤은 브라우저가 그대로 처리한다.
   손을 떼면 곧바로 카드를 바꾸고, 바뀐 사실은 새 카드가 옆에서 들어오는 움직임으로 보여 준다.
   나가고 들어오는 2단 구성은 손을 뗀 뒤 기다리는 시간(체감 지연)을 만들어 '뚝뚝 끊기는' 느낌을 줬다.
   새 CSS 토큰을 만들지 않는다 — 이동은 카드의 inline transform 하나로 처리한다. */
(function () {
  var LOCK_X = 12;   /* 이만큼 가로로 움직이면 스와이프로 확정 */
  var ABORT_Y = 60;  /* 확정 전에 이보다 세로로 움직이면 스크롤에 양보 */
  var GO = 40;       /* 손을 뗄 때 넘어가는 최소 이동량 */
  var FREE = 40;     /* 여기까지는 손가락을 1:1 로 따라간다 */
  var CAP = 96;      /* 따라오는 최대 거리 */
  var CURVE = 0.35;  /* 끝에서 무거워지는 정도 */
  var IN = 240;      /* 새 카드가 들어오는 시간 — styles.css 의 cardInNext·cardInPrev 와 맞춘다 */
  var swallowUntil = 0, own = false, cur = null, lastIdx = null;
  var slow = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function card() { return document.querySelector('.flip'); }
  function navBtn(dir) {
    var n = document.querySelector('.card-nav');
    return n ? n.querySelector(dir > 0 ? '[data-act="card-next"]' : '[data-act="card-prev"]') : null;
  }
  function curIdx() {
    var list = document.querySelectorAll('.dots i');
    for (var i = 0; i < list.length; i++) if (list[i].classList.contains('cur')) return i;
    return null;
  }
  function amp(dx) {
    var a = Math.abs(dx);
    if (a > FREE) a = FREE + (a - FREE) * CURVE;
    return Math.min(a, CAP);
  }
  /* 끝 카드 전용 — 고무줄을 덜 조여 빈 자리를 넓게 연다(안내 문구가 들어갈 폭). */
  function edgeAmp(dx) {
    var a = Math.abs(dx);
    if (a > FREE) a = FREE + (a - FREE) * 0.6;
    return Math.min(a, 168);
  }
  function back(el) {                /* 넘기지 못했다 — 부드럽게 제자리로 */
    if (!el) return;
    el.style.transform = 'translateX(0px)';
    el.style.opacity = '';
    setTimeout(function () { el.style.removeProperty('transform'); }, 220);
  }
  /* ===== 끝 카드에서 밀면 드러나는 자리에 안내와 가장자리 그늘 =====
     .flip-wrap 은 가만히 있고 .flip 만 미끄러지므로 카드가 있던 자리가 비고 그 자리에 이 층이 보인다.
     그늘은 카드 쪽이 진하고 바깥으로 옅어진다(카드가 드리우는 그림자처럼). */
  /* ===== 끝 카드에서 밀면 드러나는 자리에 안내와 가장자리 그늘 =====
     .flip-wrap 은 가만히 있고 .flip 만 미끄러지므로 카드가 있던 자리가 비고 그 자리에 이 층이 보인다.
     문구는 JS 가 직접 넣는다("첫 카드예요" / "마지막 카드예요") — 클래스·속성 전환에 기대지 않아
     표시 전환이 어긋날 여지가 없다.
     마크업에 .flip-wrap·.flip-edge 가 없으면 여기서 만들어 준다 — HTML 을 손대지 않아도 동작한다. */
  var TXT_FIRST = '첫 카드예요', TXT_LAST = '마지막 카드예요';
  var edgeSide = null;
  function ensureEdge() {
    var c = document.querySelector('.flip');
    if (!c || !c.parentNode) return null;
    var e = document.querySelector('.flip-edge');
    var w = c.parentElement;
    if (e && w && w.classList.contains('flip-wrap') && w.contains(e)) return e;   /* 이미 있음 */
    if (e && e.parentNode) e.parentNode.removeChild(e);                            /* 엉뚱한 자리에 있으면 버린다 */
    if (!w || !w.classList || !w.classList.contains('flip-wrap')) {
      w = document.createElement('div'); w.className = 'flip-wrap';
      c.parentNode.insertBefore(w, c); w.appendChild(c);
    }
    e = document.createElement('div');
    e.className = 'flip-edge'; e.setAttribute('aria-hidden', 'true');
    e.appendChild(document.createElement('span'));
    w.appendChild(e);
    return e;
  }
  function edgeHide() {
    edgeSide = null;
    var e = document.querySelector('.flip-edge');
    if (!e) return;
    e.classList.remove('shown', 'side-left', 'side-right');
    e.style.clipPath = '';
    var sp = e.querySelectorAll('span');
    for (var q = 0; q < sp.length; q++) { sp[q].style.width = ''; }
  }
  function edgeShow(dx, amount) {
    var e = ensureEdge();
    if (!e) return;
    var side = dx < 0 ? 'side-right' : 'side-left';   /* 카드가 왼쪽으로 갔으면 빈 자리는 오른쪽 */
    if (edgeSide && edgeSide !== side) return;         /* 방향이 뒤집히는 도중에는 그리지 않는다 */
    edgeSide = side;
    e.classList.add('shown');
    e.classList.toggle('side-left', side === 'side-left');
    e.classList.toggle('side-right', side === 'side-right');
    var box = e.getBoundingClientRect().width || 1;
    var w = Math.max(0, Math.min(100, amount / box * 100));   /* 드러난 폭(px)을 층 폭에 대한 % 로 */
    e.style.clipPath = side === 'side-left' ? 'inset(0 ' + (100 - w) + '% 0 0)' : 'inset(0 0 0 ' + (100 - w) + '%)';
    /* 드러난 자리 폭과 같은 폭을 주고 그 쪽으로 붙인다 — 문구가 그 자리 한가운데에 온다. */
    e.style.justifyContent = side === 'side-left' ? 'flex-start' : 'flex-end';
    var sp = e.querySelectorAll('span');
    for (var q = 0; q < sp.length; q++) {
      sp[q].textContent = (side === 'side-left') ? TXT_FIRST : TXT_LAST;   /* 문구 전환은 여기서 끝난다 */
      sp[q].style.width = amount.toFixed(0) + 'px';
    }
    e.style.opacity = String(Math.min(1, amount / 60));
  }
  function advance(dir) {
    var b = navBtn(dir);
    /* 넘어갈 곳이 없는 끝 카드(첫 카드에서 오른쪽, 마지막 카드에서 왼쪽)는 제자리로 되돌린다.
       여기서 그냥 돌아가면 드래그로 옮겨 놓은 위치와 투명도가 그대로 남아,
       카드가 어긋난 채 멈춘다 — 넘어가지도 않고 돌아오지도 않는 상태가 된다. */
    edgeHide();
    if (!b || b.disabled) { back(card()); return; }
    if (slow) { b.click(); return; }
    swallowUntil = Date.now() + 420;   /* 손 떼며 브라우저가 합성하는 클릭을 막는다 */
    b.click();                         /* 기다리지 않고 곧바로 — 지연이 곧 끊김이다 */
  }
  /* 손 떼며 브라우저가 만드는 클릭이 카드를 뒤집지 않게 한 번 먹는다.
     카드 밖(하단 버튼·말하기 버튼)은 그대로 누를 수 있어야 하므로 카드 위 클릭만 먹는다. */
  document.addEventListener('click', function (e) {
    if (own || Date.now() >= swallowUntil) return;
    var t = e.target;
    if (!t || !t.closest || !t.closest('.flip')) return;
    e.stopPropagation(); e.preventDefault();
  }, true);

  function begin(target, x, y) {
    if (!target || !target.closest) return;
    if (target.closest('.tts-btn, button, a, input, select, textarea')) return;
    var el = target.closest('.flip');
    if (!el) return;
    cur = { x: x, y: y, dx: 0, dy: 0, card: el, on: false };
  }
  function drag(x, y, ev) {
    if (!cur) return;
    cur.dx = x - cur.x; cur.dy = y - cur.y;
    var ax = Math.abs(cur.dx), ay = Math.abs(cur.dy);
    if (!cur.on) {
      if (ay > ABORT_Y && ay > ax) { cur = null; return; }        /* 세로 스크롤에 양보 */
      if (ax >= LOCK_X && ax >= ay) { cur.on = true; cur.card.classList.add('dragging'); }
      else return;
    }
    if (ay > ABORT_Y && ay > ax) {
      var g = cur; cur = null; g.card.classList.remove('dragging'); back(g.card); return;
    }
    if (ev && ev.cancelable) ev.preventDefault();
    var a = amp(cur.dx), dx = cur.dx < 0 ? -a : a;
    var nb = navBtn(cur.dx < 0 ? 1 : -1);
    var stop = !!(nb && nb.disabled);                  /* 넘어갈 카드가 없다 = 끝 */
    if (stop) a = edgeAmp(cur.dx);                     /* 끝에서는 더 넓게 드러나야 문구가 읽힌다 */
    var dx2 = cur.dx < 0 ? -a : a;
    cur.card.style.transform = 'translateX(' + dx2 + 'px)';
    cur.card.style.opacity = String(1 - Math.min(a, 96) / 420);
    if (stop) edgeShow(cur.dx, a);
    else edgeHide();
  }
  function finish() {
    if (!cur) return;
    var c = cur; cur = null;
    c.card.classList.remove('dragging');
    edgeHide();
    if (c.on && Math.abs(c.dx) >= GO) { advance(c.dx < 0 ? 1 : -1); return; }
    back(c.card);
  }

  document.addEventListener('touchstart', function (e) {
    if (e.touches.length !== 1) return;
    begin(e.target, e.touches[0].clientX, e.touches[0].clientY);
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (e.touches.length !== 1) return;
    drag(e.touches[0].clientX, e.touches[0].clientY, e);
  }, { passive: false });
  document.addEventListener('touchend', finish, { passive: true });
  document.addEventListener('touchcancel', function () {
    if (!cur) return;
    var c = cur; cur = null; c.card.classList.remove('dragging'); edgeHide(); back(c.card);
  }, { passive: true });

  /* 마우스(데스크톱) — 끌어서 넘기기 */
  document.addEventListener('pointerdown', function (e) {
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    begin(e.target, e.clientX, e.clientY);
  }, { passive: true });
  document.addEventListener('pointermove', function (e) {
    if (e.pointerType !== 'mouse' || !cur) return;
    drag(e.clientX, e.clientY, null);
  }, { passive: true });
  document.addEventListener('pointerup', function (e) {
    if (e.pointerType !== 'mouse') return;
    finish();
  }, { passive: true });

  /* 내용이 바뀐 뒤 새 카드를 들여보낸다.
     스와이프와 버튼 탭이 모두 이 한 곳을 지나가므로 넘어가는 움직임이 한 곳에서만 정의된다. */
  function settle() {
    var v = curIdx();
    if (lastIdx === null) { lastIdx = v; return; }
    if (v === null || v === lastIdx) return;
    var dir = v > lastIdx ? 1 : -1;
    lastIdx = v;
    var c = card();
    if (!c || slow) return;
    c.style.removeProperty('transform'); c.style.opacity = '';
    c.classList.add(dir > 0 ? 'in-next' : 'in-prev');
    setTimeout(function () { c.classList.remove('in-next', 'in-prev'); }, IN);
  }
  new MutationObserver(function () { window.requestAnimationFrame(settle); })
    .observe(document.body, { childList: true, subtree: true });
  window.requestAnimationFrame(settle);
})();
/* ===== 처음 한 번만, 카드가 좌우로 흔들려 스와이프를 알려 준다 (cardHint) =====
   다음 카드 버튼이 화면 밖일 때만 띄운다 — 그때가 스와이프가 유일한 길인 상황이다.
   사용자가 만지거나 카드가 바뀌면 곧바로 끝내고 다시는 띄우지 않는다.
   (끝내지 않으면 카드가 넘어갈 때마다 다시 흔들려 넘김 움직임과 뒤엉킨다.) */
(function () {
  var KEY = 'cd_hint_swipe';
  var TXT = '좌우로 밀어 넘겨 보세요 ↔';
  var SETTLE = 450;      /* 이만큼 다시 그리지 않으면 붙인다 */
  var MS = 3200;         /* 처음 붙인 뒤 이만큼 지나면 끝낸다 */
  var ack = false, baseIdx = null, settleT = null, endT = null, orig = null, front = null;
  try { if (localStorage.getItem(KEY)) ack = true; } catch (e) {}

  function curIdx() {
    var list = document.querySelectorAll('.dots i');
    for (var i = 0; i < list.length; i++) if (list[i].classList.contains('cur')) return i;
    return null;
  }
  function reachable() {              /* 다음 카드 버튼이 온전히 보이는가 */
    var b = document.querySelector('.card-nav [data-act="card-next"]');
    if (!b || b.disabled) return true;
    var r = b.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= window.innerHeight;
  }
  function onTop(card) {              /* 동의 모달 같은 것이 덮여 있으면 띄우지 않는다 */
    var r = card.getBoundingClientRect();
    var x = r.left + r.width / 2, y = r.top + Math.min(60, r.height / 2);
    if (y < 0 || y > window.innerHeight) return false;
    var top = document.elementFromPoint(x, y);
    return !!top && card.contains(top);
  }
  function detach() {
    var list = document.querySelectorAll('.flip.hint-swipe');
    for (var i = 0; i < list.length; i++) list[i].classList.remove('hint-swipe');
    if (front && orig !== null) {
      var h = front.querySelector('.face .hint');
      if (h) h.textContent = orig;
    }
    orig = null; front = null;
  }
  function done() {                   /* 끝: 저장하고 다시는 띄우지 않는다 */
    if (settleT) { clearTimeout(settleT); settleT = null; }
    if (endT) { clearTimeout(endT); endT = null; }
    detach();
    if (!ack) { ack = true; try { localStorage.setItem(KEY, '1'); } catch (e) {} }
  }
  function attach() {
    settleT = null;
    if (ack) return;
    var v = curIdx();
    if (baseIdx !== null && v !== baseIdx) { done(); return; }   /* 카드가 넘어갔다 — 안내 끝 */
    if (baseIdx === null) baseIdx = v;
    var card = document.querySelector('.flip');
    if (!card || card.classList.contains('flipped') || !onTop(card) || reachable()) return;
    if (card.classList.contains('hint-swipe')) return;
    front = card;
    var h = card.querySelector('.face .hint');
    if (h) { orig = h.textContent; h.textContent = TXT; }
    card.classList.add('hint-swipe');
    if (!endT) endT = setTimeout(done, MS);
  }
  function schedule() {               /* 다시 그려질 때마다 미룬다 → 잠잠해지면 붙인다 */
    if (ack) return;
    if (settleT) clearTimeout(settleT);
    settleT = setTimeout(attach, SETTLE);
  }

  document.addEventListener('touchstart', function () { if (front) done(); }, { capture: true, passive: true });
  document.addEventListener('pointerdown', function () { if (front) done(); }, { capture: true, passive: true });
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  schedule();
})();
