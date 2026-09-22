/* 여행영어 목업 — prd.md v2 기준 동작 시뮬레이션
   계산 규칙(R)은 PRD FR-TRIP-02, FR-SENT-02, FR-SCHED-01·02, FR-STUDY-03을 그대로 구현한다. */
'use strict';

/* ================= 기본 유틸 ================= */
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const phHtml = s => esc(s).replace(/\[(name|destination)\]/g, '<span class="ph">[$1]</span>');

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
const SIT_ORDER = ['airport', 'immigration', 'hotel', 'transit', 'shopping', 'emergency'];
const KIND = {
  new: { label: '새 문장', cls: 'k-new' },
  review: { label: '복습', cls: 'k-review' },
  final: { label: '총복습', cls: 'k-final' },
  trip: { label: '여행 중', cls: 'k-trip' },
  free: { label: '자유 일정', cls: 'k-free' },
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
let genTimer = null, genToken = 0, placeSeq = 0;

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
  clearTimeout(genTimer); genToken++;
  S = {
    screen: 'u-login', user: null, today: BASE_TODAY,
    flags: { fail: false, stuck: false, routeInvalid: false, noTts: false },
    draft: defaultDraft(BASE_TODAY), showErrors: false,
    trip: null, places: [], reportMeta: {}, days: [], sents: [], smap: {}, sched: [], plan: null,
    archived: [], gen: null, cityTab: null, showCand: {},
    studyDate: null, card: { date: null, i: 0, flipped: new Set() }, justCompleted: null,
    coll: { tab: 'common', filter: 'all' }, schedFilter: 'all', ttsRate: 0.95,
    commons: JSON.parse(JSON.stringify(COMMON_SITUATIONS)), commonsDraft: null,
    jobFilter: 'all', mockTrips: JSON.parse(JSON.stringify(MOCK_TRIPS)), modal: null, lastScreen: null,
  };
}

const tripTitle = t => `${t.country} · ${t.cities.map(c => c.name).join(' → ')}`;
const mark = k => { S.trip.stageAt[k] ??= Date.now(); };
const isStale = () => S.trip?.genStartedAt && /_generating$/.test(S.trip.status) && Date.now() - S.trip.genStartedAt > STALE_MS;

function createTrip(d) {
  if (S.trip && !S.trip.archived) archiveTrip();
  const cities = d.cities.map(c => ({ ...c, name: c.name.trim() }));
  S.trip = {
    id: 'tr_' + Math.random().toString(16).slice(2, 6), country: d.country.trim(), cities,
    studyStart: d.studyStart, tripStart: cities[0].start, tripEnd: cities[cities.length - 1].end,
    status: 'input_done', regenerateCount: 0, reportRound: 0, failStreak: 0, genStartedAt: null, error: null,
    routeFallback: false, stageAt: { input_done: Date.now() }, requests: 0, fails: 0, reportSec: null, requestedAt: null, archived: false,
  };
  S.places = []; S.reportMeta = {}; S.days = []; S.sents = []; S.smap = {}; S.sched = []; S.plan = null;
  S.cityTab = cities[0].name; S.showCand = {}; S.studyDate = null; S.justCompleted = null; resetCard();
}
function archiveTrip() {
  S.trip.archived = true;
  S.archived.unshift({ id: S.trip.id, route: tripTitle(S.trip), dates: `${Dt.md(S.trip.tripStart)}~${Dt.md(S.trip.tripEnd)}` });
}
function resetCard(date = null) { S.card = { date, i: 0, flipped: new Set() }; }

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
  const fill = s => s.replace('{menuEn}', p.menuEn).replace('{menuKo}', p.menuKo).replace('{en}', p.en).replace('{name}', p.name);
  return PLACE_TEMPLATES[p.kind].slice(0, n).map(t => ({ situation: t.situation, en: fill(t.en), ko: fill(t.ko) }));
}

function buildPlan() {
  const t = S.trip;
  const ordered = S.places.filter(p => p.selected).sort((a, b) => a.visitDate.localeCompare(b.visitDate) || a.visitOrder - b.visitOrder);
  const pre = R.preDays(t.studyStart, t.tripStart);
  const kinds = R.kinds(pre.length);
  const D = kinds.filter(k => k === 'new').length;
  const { per, T, A, P } = R.counts(D, ordered.length);
  ordered.forEach((p, i) => (p.count = per[i]));

  const sents = [];
  SIT_ORDER.forEach(key => {
    const g = S.commons.find(x => x.key === key);
    g.items.forEach((it, j) => sents.push({ id: `c-${key}-${j}`, source: 'common', sit: key, sitLabel: g.label, ...it }));
  });
  ordered.forEach(p => placeSentences(p, p.count).forEach((s, j) => sents.push({ id: `${p.id}-${j}`, source: 'place', placeId: p.id, ...s })));
  sents.forEach((s, i) => { s.order = i; s.learnPhase = 'none'; });
  const smap = Object.fromEntries(sents.map(s => [s.id, s]));

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
  S.sents = sents; S.smap = smap; S.sched = sched;
  S.plan = {
    N: pre.length, D, A, T, P, per,
    usedNew: kc('new'), review: kc('review'), final: kc('final'),
    deferred: deferred.size, tripNew: sents.filter(s => s.learnPhase === 'trip').length, none: sents.filter(s => s.learnPhase === 'none').length,
  };
  resetCard();
}

function makeRoute() {
  const days = R.placeByCode(R.buildDays(S.trip.cities), S.places);
  return { days, fallback: S.flags.routeInvalid, errs: R.validateRoute(days, S.places) };
}

/* ================= 생성 흐름 (FR-GEN-01~03) ================= */
function stepsFor(stage) {
  const t = S.trip, cs = t.cities.map(c => c.name);
  if (stage === 'report') return [`${t.country} 여행 정보를 확인하고 있어요`, ...cs.flatMap(c => [`${josa(c, '의', '의')} 관광지를 웹에서 찾고 있어요`, `${josa(c, '의', '의')} 맛집과 대표 메뉴를 찾고 있어요`]), '출처와 응답 형식을 확인하고 있어요'];
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
  const tok = ++genToken; clearTimeout(genTimer);
  genTimer = setTimeout(() => {
    if (tok !== genToken || t.status !== stage + '_requested') return;
    t.status = stage + '_generating'; t.genStartedAt = Date.now();
    render(); tick(tok, stage);
  }, 500);
}
function tick(tok, stage) {
  genTimer = setTimeout(() => {
    if (tok !== genToken) return;
    const g = S.gen;
    if (g.step < g.steps.length - 1) { g.step++; if (S.screen === 'u-gen') render(); tick(tok, stage); return; }
    if (S.flags.stuck) { g.stuck = true; if (S.screen === 'u-gen') render(); return; }
    if (S.flags.fail) { failStage(stage); return; }
    succeed(stage);
  }, 700);
}
function failStage(stage) {
  const t = S.trip; genToken++; clearTimeout(genTimer);
  t.status = stage + '_failed'; t.failStreak++; t.fails++;
  t.error = stage === 'report' ? 'AI 응답이 정해진 형식에 맞지 않았어요. (2번 다시 요청했지만 실패)' : stage === 'route' ? '방문 순서를 만드는 중 오류가 났어요.' : '일부 장소의 문장을 만들지 못했어요.';
  if (S.gen) S.gen.failed = true;
  S.screen = 'u-gen'; render();
}
function succeed(stage) {
  const t = S.trip; t.failStreak = 0;
  if (stage === 'report') {
    if (t.reportRound >= 1) t.regenerateCount++;
    S.places = genReport(t, t.reportRound); t.reportRound++;
    t.status = 'report_done'; mark('report_done');
    t.reportSec = Math.round((Date.now() - t.requestedAt) / 1000);
    S.cityTab = t.cities[0].name; S.showCand = {};
    S.screen = 'u-report'; render();
    toast(t.reportRound > 1 ? `보고서를 다시 만들었어요. 남은 다시 생성 ${3 - t.regenerateCount}번` : '보고서가 준비됐어요. 가지 않을 장소를 빼 주세요.');
  } else if (stage === 'route') {
    const res = makeRoute(); S.days = res.days; t.routeFallback = res.fallback;
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

/* 메뉴에서 바로 화면을 열 때 필요한 데이터를 데모로 채움 */
function ensure(level) {
  let did = false;
  if (!S.user) { S.user = DEMO_USER; did = true; }
  if (level === 'user') return did;
  if (!S.trip) { createTrip(defaultDraft(S.today)); did = true; }
  const t = S.trip;
  if (!S.places.length) {
    genToken++; clearTimeout(genTimer);
    S.places = genReport(t, t.reportRound); t.reportRound++;
    t.status = 'report_done'; mark('report_done'); t.reportSec = 42; did = true;
  }
  if (level === 'plan' && !S.plan) {
    genToken++; clearTimeout(genTimer);
    S.days = makeRoute().days; mark('route_done'); buildPlan();
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
    const k = s.source === 'common' ? `공통 ${s.sitLabel}` : S.places.find(p => p.id === s.placeId)?.name;
    m.set(k, (m.get(k) || 0) + 1);
  });
  const parts = [...m].map(([k, n]) => `${k} ${n}`);
  if (r.kind === 'review') return `직전 새 문장 ${r.ids.length}개 복습`;
  if (r.kind === 'final') return `여행 전 문장 ${r.ids.length}개 나눠 복습`;
  return parts.join(' · ');
}
function pickRow() {
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
const ttsText = s => s.replace(/\[name\]/g, 'your name').replace(/\[destination\]/g, 'your destination');
function speak(text, btn) {
  if (ttsState() !== 'ok') { toast('이 브라우저는 듣기를 지원하지 않아요. 카드 학습은 계속할 수 있어요.'); return; }
  speechSynthesis.cancel();
  document.querySelectorAll('.playing').forEach(e => e.classList.remove('playing'));
  const u = new SpeechSynthesisUtterance(ttsText(text));
  u.lang = 'en-US';
  const v = enVoice(); if (v) u.voice = v;
  u.rate = S.ttsRate;
  u.onstart = () => btn && btn.classList.add('playing');
  u.onend = u.onerror = () => btn && btn.classList.remove('playing');
  speechSynthesis.speak(u);
}
if (ttsSupported()) {
  loadVoices();
  speechSynthesis.onvoiceschanged = () => { loadVoices(); if (['u-study', 'u-coll'].includes(S?.screen)) render(); };
}

/* ================= 화면 정의 ================= */
const SCREENS = [
  { group: '사용자 화면', id: 'u-login', no: 'SCR-01', name: '로그인', fr: ['FR-AUTH-01', 'FR-AUTH-02'],
    tips: ['"Google로 계속하기"를 누르면 로그인돼요.', '여행이 없으면 여행 입력, 있으면 홈으로 이동해요.', '로그인 상태에서는 로그아웃할 수 있어요.'] },
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
    tips: ['카드를 눌러 뒤집고 "듣기"로 영어 발음을 들어 보세요.', '모든 카드를 한 번 이상 뒤집어야 완료 버튼이 켜져요.', '[name], [destination]은 "your name", "your destination"으로 읽어요.', '사이드바의 "TTS 미지원"을 켜면 듣기 버튼 대신 안내가 나와요.'] },
  { id: 'u-coll', no: 'SCR-09', name: '문장 모음', fr: ['FR-STUDY-05', 'FR-SENT-01'],
    tips: ['공통 상황과 장소별 문장을 골라 볼 수 있어요.', '"문장 모음 전용"은 일정에 넣지 않은 문장이에요.', '모든 문장에 듣기 버튼이 있어요.'] },
  { id: 'u-end', no: 'SCR-06', name: '여행 종료 요약', fr: ['FR-END-01', 'FR-TRIP-04'],
    tips: ['이 메뉴를 누르면 "오늘"이 여행 종료 다음 날로 바뀌어요.', '종료 후에는 완료 처리를 할 수 없어요.', '"새 여행 만들기"는 이 여행을 보관(비활성화)해요.'] },
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
function renderSide() {
  let html = `<div class="side-brand"><div class="mark"><i>EN</i>여행영어 목업</div><p>prd.md v2 기준 · 왼쪽 메뉴로 화면을 고르고, 화면 안 버튼으로 실제 흐름을 따라가 보세요.</p></div><nav class="side-nav">`;
  SCREENS.forEach(s => {
    if (s.group) html += `<div class="nav-group">${s.group}${s.tag ? `<span class="tag">${s.tag}</span>` : ''}</div>`;
    html += `<button class="nav-item" data-act="nav" data-id="${s.id}"><span class="no">${s.no}</span><span>${s.name}</span></button>`;
  });
  html += `</nav><div class="demo" id="demo"></div>`;
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
    <div class="demo-date"><span style="color:#9aa0ad">오늘</span><input type="date" id="demo-date" value="${S.today}"></div>
    <div class="demo-chips">${chips.map(([l, d]) => `<button data-act="set-today" data-date="${d}">${l} ${Dt.md(d)}</button>`).join('')}</div>
    ${tg('fail', 'AI 생성 실패')}${tg('stuck', '생성 멈춤 (응답 없음)')}${tg('routeInvalid', '방문 순서 AI 규칙 위반')}${tg('noTts', 'TTS 미지원 브라우저')}
    <div class="demo-actions"><button data-act="preset" data-kind="short">짧은 학습 3일</button><button data-act="preset" data-kind="zero">당일 시작 0일</button></div>`;
}
function updateSideActive() {
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.id === S.screen));
}

function render() {
  const app = $('.app'), prevTop = app ? app.scrollTop : 0, same = S.lastScreen === S.screen;
  updateSideActive(); renderDemo();
  const sc = SCR[S.screen];
  const t = S.trip;
  const status = t ? (t.archived ? '보관됨' : STATUS_KO[t.status]) : '여행 없음';
  const cls = t && /_failed$/.test(t.status) ? 'bad' : t && /_(generating|requested)$/.test(t.status) ? 'warn' : '';
  $('#topbar').innerHTML = `<span class="id">${sc.no}</span><h1>${sc.name}</h1>${sc.prop ? '<span class="fr prop">PRD 외 제안 화면</span>' : ''}<span class="spacer"></span>
    <span class="pill"><span class="dot"></span>오늘 <b>${S.today}</b> (${Dt.dow(S.today)})</span>
    <span class="pill ${cls}"><span class="dot"></span>여행 상태 <b>${status}</b></span>`;
  const body = S.screen.startsWith('a-') ? adminScreen() : userScreen();
  $('#stage').className = 'stage ' + (S.screen.startsWith('a-') ? 'is-admin' : 'is-user');
  $('#stage').innerHTML = body + notes(sc);
  const na = $('.app'); if (na && same) na.scrollTop = prevTop;
  S.lastScreen = S.screen;
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
  return `<div class="note-card"><h3>현재 계산 결과 (FR-SENT-02)</h3><p style="font-family:var(--mono);font-size:12px;line-height:1.8">
    여행 전 학습일 N = ${p.N}<br>새 문장 학습일 D = ${p.D}<br>목표 P = ${p.P === null ? '— (D = 0)' : `${p.D}×5−30 = ${p.P}`}<br>
    장소 ${p.per.length}곳 · 장소당 ${[...new Set(p.per)].sort((a, b) => b - a).join('/')}문장<br>전체 T = ${p.T} · 하루 A = ${p.A ?? '없음'}<br>
    여행 중 새 문장 ${p.tripNew} · 문장 모음 전용 ${p.none}</p></div>`;
}

/* ================= 렌더링: 사용자 화면 ================= */
function frame(inner, o = {}) {
  const tabs = [['u-home', '홈', I.home], ['u-sched', '일정표', I.cal], ['u-study', '학습', I.cards], ['u-coll', '문장 모음', I.book]];
  const tabActive = o.tab || S.screen;
  return `<div class="device"><div class="screen">
    <div class="statusbar"><span>9:41</span><span class="sim">${Dt.full(S.today)}</span></div>
    ${o.appbar || ''}
    <div class="app">${inner}</div>
    ${o.bottom ? `<div class="bottombar">${o.bottom}</div>` : ''}
    ${o.tabbar ? `<nav class="tabbar">${tabs.map(([id, l, ic]) => `<button class="${tabActive === id ? 'on' : ''}" data-act="tab" data-id="${id}">${ic}${l}</button>`).join('')}</nav>` : ''}
    ${modalHtml()}
  </div></div>`;
}
const appbar = (title, o = {}) => `<div class="appbar">${o.back ? `<button class="back" data-act="tab" data-id="${o.back}">${I.back}</button>` : ''}<h2>${title}</h2>${o.step ? `<span class="step">${o.step}</span>` : ''}</div>`;
const notice = (html, kind = '') => `<div class="notice ${kind}">${kind === 'warn' || kind === 'bad' ? I.alert : I.info}<div>${html}</div></div>`;
function modalHtml(center = false) {
  const m = S.modal; if (!m) return '';
  return `<div class="modal-wrap ${center ? 'center' : ''}" data-act="modal-bg"><div class="modal" data-act="noop"><h3>${m.title}</h3><p>${m.body}</p>
    <div class="acts"><button class="btn soft" data-act="modal-cancel">${m.cancel || '취소'}</button><button class="btn ${m.danger ? 'accent' : 'primary'}" data-act="modal-ok">${m.ok}</button></div></div></div>`;
}
let modalFn = null;
function confirmBox(title, body, ok, fn, o = {}) { S.modal = { title, body, ok, ...o }; modalFn = fn; render(); }

function userScreen() {
  switch (S.screen) {
    case 'u-login': return scrLogin();
    case 'u-input': return scrInput();
    case 'u-gen': return scrGen();
    case 'u-report': return scrReport();
    case 'u-route': return scrRoute();
    case 'u-home': return scrHome();
    case 'u-sched': return scrSched();
    case 'u-study': return scrStudy();
    case 'u-coll': return scrColl();
    case 'u-end': return frame(`<div class="app-pad">${endBody()}</div>`, { tabbar: true, tab: 'u-home' });
  }
  return '';
}

/* SCR-01 */
function scrLogin() {
  const body = S.user
    ? `<div class="card" style="display:flex;align-items:center;gap:12px"><div style="width:40px;height:40px;border-radius:50%;background:var(--sea);color:#fff;display:grid;place-items:center;font-weight:700">김</div>
        <div style="flex:1"><b>${DEMO_USER.name}</b><div class="small">${DEMO_USER.email}</div></div></div>
       <div style="display:flex;gap:8px;margin-top:10px"><button class="btn soft" style="flex:1" data-act="logout">로그아웃</button><button class="btn primary" style="flex:2" data-act="after-login">계속하기</button></div>`
    : `<button class="gbtn" data-act="login">${I.google}Google로 계속하기</button>`;
  return frame(`<div class="login">
    <div class="stamp">TRIP · ENGLISH<br>PASSPORT<br>— 2026 —</div>
    <div class="eyebrow" style="margin-top:130px">Travel English, planned</div>
    <h1 style="margin-top:10px">Speak where<br>you'll <em>actually</em><br>be.</h1>
    <p class="sub">여행지와 일정을 입력하면, 실제로 갈 관광지와 맛집에서 쓸 영어 문장을 만들어 출발 전부터 매일 학습하게 해 드려요.</p>
    <div class="ticket">${body}<p class="small" style="text-align:center;margin-top:12px">로그인하지 않으면 다른 화면에 들어갈 수 없어요.</p></div>
  </div>`);
}

/* SCR-02 */
function scrInput() {
  const d = S.draft, v = R.validate(d, S.today), E = S.showErrors ? v.errors : {};
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
  const inner = `<div class="app-pad">
    <div class="eyebrow">New trip</div>
    <div class="title-lg">어디로 떠나세요?</div>
    <p class="sub" style="margin-bottom:18px">도시별 체류 날짜와 학습 시작일만 정하면 나머지는 자동으로 계산돼요.</p>
    ${S.trip && !S.trip.archived ? notice(`진행 중인 여행 <b>${esc(tripTitle(S.trip))}</b>이 있어요. 새 여행을 만들면 기존 여행은 보관돼요.`, 'warn') + '<div style="height:12px"></div>' : ''}
    <div class="field"><label>나라</label><input class="input" data-bind="country" value="${esc(d.country)}" placeholder="예: 미국">
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
    <div data-live="warn" style="margin-top:10px">${v.warnings.map(w => notice(w, 'warn')).join('')}</div>
  </div>`;
  return frame(inner, { appbar: appbar('여행 입력', { step: 'STEP 1/3' }), bottom: `<button class="btn primary block" data-act="submit-trip">보고서 만들기</button>` });
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
      <b style="color:var(--ink);font-size:16px">진행 중인 생성 작업이 없어요</b><p>AI가 보고서, 방문 순서, 문장을 만드는 동안 이 화면이 나타나요.<br>오른쪽 데모 버튼으로 생성·실패·멈춤 화면을 확인할 수 있어요.</p>
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
      <div class="eyebrow" style="text-align:center;color:var(--bad)">Generation failed</div><div class="title-lg" style="text-align:center">${josa(STAGE_NAME[stage], '을', '를')} 만들지 못했어요</div>`;
    extra = notice(esc(t.error), 'bad') + (t.failStreak >= 3 ? '<div style="height:8px"></div>' + notice(`같은 단계에서 ${t.failStreak}번 연속 실패했어요. <b>잠시 후 다시 시도해 주세요.</b>`, 'warn') : '') +
      '<div style="height:8px"></div>' + notice('이전 단계까지의 결과는 그대로 남아 있어요.', 'plain');
    bottom = `<button class="btn primary block" data-act="retry">다시 시도</button>`;
  } else if (stale) {
    head = `<div class="orbit stopped"><div class="plane"><i></i></div><div class="core">15:00+</div></div>
      <div class="eyebrow" style="text-align:center;color:var(--bad)">Stalled</div><div class="title-lg" style="text-align:center">생성이 멈춘 것 같아요</div>`;
    extra = notice(`생성을 시작한 지 15분이 지났어요. 서버 작업이 중간에 멈췄을 수 있어요. 다시 시도할 수 있어요.`, 'bad');
    bottom = `<button class="btn primary block" data-act="retry">다시 시도</button>`;
  } else {
    head = `<div class="orbit"><div class="plane"><i></i></div><div class="core" data-live="elapsed">${elapsed()}</div></div>
      <div class="eyebrow" style="text-align:center">${requested ? 'Requested' : 'Generating'}</div>
      <div class="title-lg" style="text-align:center">${STAGE_OBJ[stage]} 만들고 있어요</div>
      <p class="sub" style="text-align:center">화면을 닫거나 새로고침해도 이어서 진행돼요.</p>`;
    bottom = `<button class="btn soft block" disabled>생성 중에는 다시 요청할 수 없어요</button>`;
    if (g.stuck) extra = notice('서버 응답이 오지 않고 있어요. (데모: 오른쪽 "16분 경과시키기"로 멈춤 처리를 확인하세요)', 'plain');
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
  const meta = S.reportMeta[city], sel = selCount(city);
  const base = S.places.filter(p => p.city === city && !p.isCandidate), cands = S.places.filter(p => p.city === city && p.isCandidate);
  const nonEng = !ENGLISH_COUNTRIES.includes(t.country);
  const total = S.places.filter(p => p.selected).length;
  const open = S.showCand[city] || cands.some(p => p.selected);
  const inner = `<div class="app-pad">
    <div class="city-tabs">${t.cities.map(c => `<button class="${c.name === city ? 'on' : ''}" data-act="city-tab" data-city="${esc(c.name)}">${esc(c.name)} <b>${selCount(c.name)}/${S.reportMeta[c.name].base}</b></button>`).join('')}</div>
    <div class="stack" style="margin-bottom:14px">
      ${locked ? notice('장소를 확정했어요. 이제 선택을 바꿀 수 없어요.', 'plain') : ''}
      ${notice('웹 검색으로 최신 정보를 모았지만, 영업시간과 메뉴는 바뀔 수 있어요.')}
      ${nonEng ? notice('현지에서 영어가 통하지 않을 수 있어요.', 'warn') : ''}
      ${meta.found < meta.base ? notice(`추천할 장소를 충분히 찾지 못했어요. 기본 ${meta.base}곳 중 ${meta.found}곳만 찾았어요. 후보로 채울 수 있어요.`, 'warn') : ''}
      ${sel < meta.base / 2 ? notice('장소가 적어 비어 있는 날(자유 일정)이 생길 수 있어요.', 'warn') : ''}
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
  const src = p.sources.length ? p.sources.map(s => `<a href="${s.url}" data-act="link">${esc(s.title)}</a>`).join('') : '<span>출처 없음</span>';
  return `<div class="place ${p.selected ? 'on' : 'off'} ${locked ? 'locked' : ''}" data-act="place" data-id="${p.id}">
    <div class="check">${p.selected ? I.check : ''}</div>
    <div><div class="nm"><span class="kind ${p.kind}">${p.kind === 'attraction' ? '관광지' : '맛집'}</span>${esc(p.name)}${p.isCandidate ? '<span class="badge b-only">후보</span>' : ''}</div>
      <div class="meta">${esc(p.area)}${p.cuisine ? ` · ${esc(p.cuisine)}` : ''}</div>
      <div class="desc">${esc(p.desc)} <span style="color:var(--muted)">— ${esc(p.reason)}</span></div>
      ${p.menuKo ? `<div class="menu">대표 메뉴 · ${esc(p.menuKo)}</div>` : ''}
      <div class="src">${src}</div></div></div>`;
}

/* SCR-05 */
function scrRoute() {
  const t = S.trip, p = S.plan;
  const errs = R.validateRoute(S.days, S.places);
  const groups = {}; p.per.forEach(n => (groups[n] = (groups[n] || 0) + 1));
  const perTxt = Object.entries(groups).sort((a, b) => b[0] - a[0]).map(([n, c]) => `${n}문장 ${c}곳`).join(' · ');
  const inner = `<div class="app-pad">
    <div class="card" style="background:var(--ink);color:#fff;border:0">
      <div class="eyebrow" style="color:var(--sun)">Plan summary</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;font-size:12.5px;color:#c8c3b7">
        <div>전체 문장<b style="display:block;color:#fff;font-size:20px;font-family:var(--display)">${p.T}개</b>공통 30 + 장소 ${p.T - 30}</div>
        <div>하루 학습량<b style="display:block;color:#fff;font-size:20px;font-family:var(--display)">${p.A ? p.A + '문장' : '없음'}</b>${p.A ? `새 문장 ${p.usedNew}일` : '여행 전 학습 없음'}</div>
        <div>여행 전 학습<b style="display:block;color:#fff;font-size:16px">${p.N}일</b>복습 ${p.review} · 총복습 ${p.final}</div>
        <div>여행 중 새 문장<b style="display:block;color:#fff;font-size:16px">${p.tripNew}개</b>문장 모음 전용 ${p.none}개</div>
      </div>
      <div style="margin-top:10px;font-size:12px;color:#9aa0ad">장소당 ${perTxt}</div>
    </div>
    <div class="stack" style="margin:12px 0 16px">
      ${notice('지도 기반 최적 경로가 아니라, 장소의 지역을 기준으로 정한 <b>추천 방문 순서</b>예요.')}
      ${t.routeFallback ? notice('AI가 만든 방문 순서가 규칙을 2번 어겨 <b>코드 규칙으로 배치</b>했어요. (같은 지역끼리 묶어 날짜 순서대로 채움)', 'warn') : ''}
      ${errs.length ? notice('검증 실패: ' + errs.join(', '), 'bad') : `<div class="small" style="display:flex;gap:6px;align-items:center;color:var(--ok)">${I.check} 검증 통과 · 도시 일치 · 하루 장소 수 · 누락·중복 없음</div>`}
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
  if (ph === 'ended') return frame(`<div class="app-pad">${endBody()}</div>`, { tabbar: true });
  const pr = progress();
  let hero;
  if (ph === 'trip') {
    const day = S.days.find(d => d.date === S.today);
    hero = `<div class="hero trip"><div class="route">${esc(tripTitle(t))}</div><div class="big">${Dt.diff(S.today, t.tripStart) + 1}<small>일차</small></div>
      <div class="dates">오늘 도시 · ${esc(day?.city || '')} ${day ? day.types.map(ty => DAYTYPE[ty].label).join('·') : ''}</div></div>`;
  } else if (ph === 'before') {
    hero = `<div class="hero"><div class="route">${esc(tripTitle(t))}</div><div class="big">D-${Dt.diff(t.studyStart, S.today)}<small>학습 시작까지</small></div>
      <div class="dates">학습 ${Dt.md(t.studyStart)} → 여행 ${Dt.md(t.tripStart)}~${Dt.md(t.tripEnd)}</div></div>`;
  } else {
    hero = `<div class="hero"><div class="route">${esc(tripTitle(t))}</div><div class="big">D-${Dt.diff(t.tripStart, S.today)}<small>여행까지</small></div>
      <div class="dates">여행 ${Dt.md(t.tripStart)}~${Dt.md(t.tripEnd)} · 학습 종료 ${Dt.md(t.tripEnd)}</div></div>`;
  }
  const r = S.sched.find(x => x.date === S.today);
  let today;
  if (!r) {
    const first = S.sched[0];
    today = `<div class="today-card"><div class="top"><span class="badge k-free">학습 전</span></div><h3>학습은 ${Dt.full(first.date)}부터 시작해요</h3>
      <p class="sub" style="font-size:13px">첫날 학습 · ${describe(first)}문장</p><button class="btn soft block" style="margin-top:12px" data-act="study-date" data-date="${first.date}">첫날 카드 미리 보기</button></div>`;
  } else {
    const st = rowStatus(r), n = r.ids.length;
    const title = r.kind === 'free' ? '오늘은 자유 일정이에요' : r.kind === 'new' ? `새 문장 ${n}개` : r.kind === 'trip' ? `오늘 장소 문장 ${n}개` : `${KIND[r.kind].label} · 문장 ${n}개`;
    today = `<div class="today-card"><div class="top"><span class="badge ${KIND[r.kind].cls}">${KIND[r.kind].label}</span>${st === 'done' ? '<span class="st done">완료</span>' : ''}</div>
      <h3>${title}</h3><p class="sub" style="font-size:13px">${describe(r)}</p>
      ${r.newIds.length ? `<div style="margin-top:8px"><span class="badge b-new">새 문장 ${r.newIds.length}개 포함</span></div>` : ''}
      ${r.kind === 'free' ? `<button class="btn soft block" style="margin-top:12px" data-act="tab" data-id="u-coll">문장 모음에서 복습하기</button>`
        : `<button class="btn ${st === 'done' ? 'soft' : 'accent'} block" style="margin-top:12px" data-act="study-date" data-date="${r.date}">${st === 'done' ? '완료했어요 · 다시 보기' : '오늘 학습 시작'}</button>`}</div>`;
  }
  const upcoming = S.sched.filter(x => x.date > S.today).slice(0, 3);
  const inner = `<div class="app-pad">
    <div style="display:flex;justify-content:space-between;align-items:center;margin:4px 0 12px"><div><div class="small">안녕하세요</div><b style="font-size:18px">${DEMO_USER.name}님</b></div><span class="badge t-norm">${STATUS_KO[t.status]}</span></div>
    ${hero}<div style="height:12px"></div>${today}
    ${pr.miss ? `<div style="height:10px"></div>${notice(`지난 학습 ${pr.miss}일이 미완료예요. 일정표에서 여행 종료일까지 언제든 채울 수 있어요.`, 'warn')}` : ''}
    <div class="sec-title"><h4>진도</h4><button data-act="tab" data-id="u-sched">일정표 ›</button></div>
    <div class="card progress-row">${ring(pr.rate)}
      <div class="mini-stats"><div><span>완료한 날</span><b>${pr.done}일</b></div><div><span>학습 날짜</span><b>${pr.den}일</b></div>
      <div class="${pr.miss ? 'bad' : ''}"><span>미완료</span><b>${pr.miss}일</b></div><div><span>자유 일정 (제외)</span><b>${pr.free}일</b></div></div></div>
    ${upcoming.length ? `<div class="sec-title"><h4>다가오는 일정</h4></div>${upcoming.map(srow).join('')}` : ''}
  </div>`;
  return frame(inner, { tabbar: true });
}
function ring(rate) {
  const r = 40, c = 2 * Math.PI * r;
  return `<div class="ring"><svg width="96" height="96"><circle cx="48" cy="48" r="${r}" fill="none" stroke="#efeadf" stroke-width="9"/>
    <circle cx="48" cy="48" r="${r}" fill="none" stroke="var(--accent)" stroke-width="9" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - rate)}"/></svg>
    <div class="v"><div><b>${Math.round(rate * 100)}%</b><span>완료율</span></div></div></div>`;
}
function srow(r) {
  const st = rowStatus(r);
  const stLabel = { done: '완료', miss: '미완료', today: '오늘', future: '예정', free: '—' }[st];
  const extra = r.phase === 'trip' ? `${r.day.types.map(ty => `<span class="badge ${DAYTYPE[ty].cls}">${DAYTYPE[ty].label}</span>`).join('')}<span class="small">${esc(r.day.city)}</span>` : '';
  return `<button class="srow ${r.date === S.today ? 'today' : ''}" data-act="study-date" data-date="${r.date}">
    <span class="dt">${Dt.md(r.date)}<small>${Dt.dow(r.date)}요일</small></span>
    <span class="ct"><span class="line1"><span class="badge ${KIND[r.kind].cls}">${KIND[r.kind].label}</span>${extra}${r.newIds.length ? `<span class="badge b-new">새 ${r.newIds.length}</span>` : ''}</span>
      <span class="line2">${r.kind === 'free' ? '자유 일정 · 완료율 계산 제외' : `${r.ids.length}문장 · ${esc(describe(r))}`}</span></span>
    <span class="st ${st}">${stLabel}</span></button>`;
}

/* SCR-07 */
function scrSched() {
  const pr = progress();
  let rows = S.sched;
  if (S.schedFilter === 'miss') rows = rows.filter(r => rowStatus(r) === 'miss');
  const pre = rows.filter(r => r.phase === 'pre'), trip = rows.filter(r => r.phase === 'trip');
  const inner = `<div class="app-pad">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div class="seg"><button class="${S.schedFilter === 'all' ? 'on' : ''}" data-act="sched-filter" data-v="all">전체</button><button class="${S.schedFilter === 'miss' ? 'on' : ''}" data-act="sched-filter" data-v="miss">미완료 ${pr.miss}</button></div>
      <span class="small">완료율 <b style="color:var(--ink)">${Math.round(pr.rate * 100)}%</b> (${pr.done}/${pr.den})</span></div>
    ${pre.length ? `<div class="phase-label">여행 전 · ${S.plan.N}일</div>${pre.map(srow).join('')}` : ''}
    ${trip.length ? `<div class="phase-label">여행 중</div>${trip.map(srow).join('')}` : ''}
    ${!rows.length ? `<div class="empty"><div class="ico">${I.check}</div>미완료 날짜가 없어요</div>` : ''}
  </div>`;
  return frame(inner, { appbar: appbar('일정표'), tabbar: true });
}

/* SCR-08 */
function scrStudy() {
  const r = pickRow();
  if (!r) return frame(`<div class="empty">일정이 없어요</div>`, { tabbar: true });
  if (S.card.date !== r.date) resetCard(r.date);
  const st = rowStatus(r), ended = S.today > S.trip.tripEnd;
  const head = `<div class="study-head"><div><div class="small">${r.phase === 'trip' ? `${esc(r.day.city)} · ${r.day.types.map(ty => DAYTYPE[ty].label).join('·')}` : '여행 전 학습'}</div>
    <b style="font-size:19px">${Dt.full(r.date)}</b></div><span class="badge ${KIND[r.kind].cls}">${KIND[r.kind].label}</span></div>`;
  let banner = '';
  if (ended) banner = notice('여행이 끝나 더 이상 완료 처리할 수 없어요.', 'plain');
  else if (r.completed) banner = notice('완료한 날이에요. 다시 학습해도 완료 상태는 유지돼요.', 'plain');
  else if (st === 'future') banner = notice('앞으로의 날짜예요. 카드는 미리 볼 수 있지만 완료는 그날부터 가능해요.', 'plain');
  else if (st === 'miss') banner = notice('지난 날짜예요. 지금 학습하면 완료로 기록돼요.', 'warn');

  if (r.kind === 'free') {
    return frame(`<div class="app-pad">${head}<div class="empty" style="padding-top:70px"><div class="ico">☼</div><b style="color:var(--ink);font-size:17px">오늘은 자유 일정이에요</b>
      <p>배치된 장소가 없어 카드가 없어요.<br>문장 모음에서 복습해 보세요. (완료율 계산에서 제외돼요)</p><button class="btn soft" data-act="tab" data-id="u-coll">문장 모음 열기</button></div></div>`,
      { appbar: appbar('학습', { back: 'u-sched' }), tabbar: true, tab: 'u-study' });
  }
  if (S.justCompleted === r.date) {
    const pr = progress();
    return frame(`<div class="app-pad">${head}<div class="done-banner"><div class="seal">DONE<br>${Dt.md(r.date)}</div>
      <div class="title-lg">학습 완료!</div><p class="sub">문장 ${r.ids.length}개를 모두 확인했어요. 완료율이 <b>${Math.round(pr.rate * 100)}%</b>로 갱신됐어요.</p></div>
      <button class="btn primary block" data-act="tab" data-id="u-home">홈으로</button><div style="height:8px"></div>
      <button class="btn soft block" data-act="restudy">다시 보기</button></div>`, { appbar: appbar('학습', { back: 'u-sched' }), tabbar: true, tab: 'u-study' });
  }
  const i = Math.min(S.card.i, r.ids.length - 1), s = S.smap[r.ids[i]];
  const isNew = r.kind === 'new' || r.newIds.includes(s.id);
  const pl = s.placeId ? S.places.find(p => p.id === s.placeId) : null;
  const tag = s.source === 'common' ? `<span class="badge t-norm">공통 · ${s.sitLabel}</span>` : `<span class="badge ${pl.kind === 'attraction' ? 't-dep' : 't-arr'}">${esc(pl.name)}</span>`;
  const ts = ttsState();
  const tts = ts === 'ok'
    ? `<div class="tts-row"><button class="tts-btn" data-act="speak-card">${I.speaker}듣기</button><button class="tts-rate" data-act="rate">${S.ttsRate < 0.9 ? '느리게' : '보통 속도'}</button></div>`
    : `<div class="tts-off">이 브라우저는 듣기를 지원하지 않아요. 카드 학습은 계속할 수 있어요.</div>`;
  const inner = `<div class="app-pad">${head}${banner ? banner + '<div style="height:10px"></div>' : ''}
    <div class="flip" data-act="flip">
      <div class="flip-inner">
        <div class="face front"><div class="ctx">${tag}${isNew ? '<span class="badge b-new">새 문장</span>' : ''}</div><div class="sit" style="margin-top:8px">${esc(s.situation)}</div>
          <div class="ko">${phHtml(s.ko)}</div><div class="hint">탭해서 영어 문장 보기 ↻</div></div>
        <div class="face back"><div class="ctx">${tag}</div><div class="sit" style="margin-top:8px">${esc(s.situation)}</div>
          <div class="en">${phHtml(s.en)}</div><div class="ko-s">${phHtml(s.ko)}</div>${tts}</div>
      </div>
    </div>
    <div class="card-nav"><button class="round" data-act="card-prev" ${i === 0 ? 'disabled' : ''}>${I.back}</button>
      <div style="text-align:center"><div class="dots">${r.ids.map((_, k) => `<i class="${S.card.flipped.has(k) ? 'seen' : ''} ${k === i ? 'cur' : ''}"></i>`).join('')}</div>
      <div class="small" style="margin-top:6px" data-live="flipcount">${i + 1} / ${r.ids.length} · 뒤집은 카드 ${S.card.flipped.size}</div></div>
      <button class="round" data-act="card-next" ${i === r.ids.length - 1 ? 'disabled' : ''}>${I.next}</button></div>
  </div>`;
  return frame(inner, { appbar: appbar('학습', { back: 'u-sched' }), bottom: completeBtn(r), tabbar: false });
}
function completeBtn(r) {
  const all = S.card.flipped.size >= r.ids.length;
  if (r.completed) return `<button class="btn soft block" disabled>완료한 날이에요</button>`;
  if (S.today > S.trip.tripEnd) return `<button class="btn soft block" disabled>여행 종료 후에는 완료할 수 없어요</button>`;
  if (r.date > S.today) return `<button class="btn soft block" disabled>${Dt.md(r.date)}부터 완료할 수 있어요</button>`;
  return `<button class="btn accent block" data-act="complete" ${all && canComplete(r) ? '' : 'disabled'}>학습 완료 (${S.card.flipped.size}/${r.ids.length})</button>
    ${all ? '' : '<div class="small" style="text-align:center">모든 카드를 한 번 이상 뒤집으면 완료할 수 있어요</div>'}`;
}
function updateStudyLive() {
  const r = pickRow(); if (!r) return;
  const dots = document.querySelectorAll('.dots i');
  dots.forEach((d, k) => d.classList.toggle('seen', S.card.flipped.has(k)));
  const fc = $('[data-live=flipcount]'); if (fc) fc.textContent = `${Math.min(S.card.i, r.ids.length - 1) + 1} / ${r.ids.length} · 뒤집은 카드 ${S.card.flipped.size}`;
  const bb = $('.bottombar'); if (bb) bb.innerHTML = completeBtn(r);
}

/* SCR-09 */
function scrColl() {
  const tab = S.coll.tab, f = S.coll.filter;
  const learnBadge = s => s.learnPhase === 'none' ? '<span class="badge b-only">문장 모음 전용</span>' : s.learnPhase === 'trip' ? '<span class="badge b-new">여행 중 새 문장</span>' : '';
  const item = s => `<div class="sent"><div><div class="tags">${learnBadge(s)}<span class="small">${esc(s.situation)}</span></div><div class="en">${phHtml(s.en)}</div><div class="ko">${phHtml(s.ko)}</div></div>
    <button class="play" data-act="speak" data-id="${s.id}">${I.speaker}</button></div>`;
  let body;
  if (tab === 'common') {
    const chips = [['all', '전체'], ...SIT_ORDER.map(k => [k, S.commons.find(g => g.key === k).label])];
    const list = S.sents.filter(s => s.source === 'common' && (f === 'all' || s.sit === f));
    body = `<div class="chips">${chips.map(([k, l]) => `<button class="${f === k ? 'on' : ''}" data-act="coll-filter" data-v="${k}">${l}</button>`).join('')}</div>
      ${SIT_ORDER.filter(k => f === 'all' || k === f).map(k => { const g = list.filter(s => s.sit === k); return g.length ? `<div class="phase-label">${g[0].sitLabel}</div>${g.map(item).join('')}` : ''; }).join('')}`;
  } else {
    const cities = S.trip.cities.map(c => c.name);
    const cf = cities.includes(f) ? f : 'all';
    const places = S.places.filter(p => p.selected && (cf === 'all' || p.city === cf)).sort((a, b) => a.visitDate.localeCompare(b.visitDate) || a.visitOrder - b.visitOrder);
    body = `<div class="chips">${[['all', '전체'], ...cities.map(c => [c, c])].map(([k, l]) => `<button class="${cf === k ? 'on' : ''}" data-act="coll-filter" data-v="${esc(k)}">${esc(l)}</button>`).join('')}</div>
      ${places.map(p => `<div class="phase-label">${esc(p.name)} · ${Dt.md(p.visitDate)} 방문</div>${S.sents.filter(s => s.placeId === p.id).map(item).join('')}`).join('')}`;
  }
  const ts = ttsState();
  const inner = `<div class="app-pad">
    <div class="seg" style="margin-bottom:12px"><button class="${tab === 'common' ? 'on' : ''}" data-act="coll-tab" data-v="common">공통 상황 30</button><button class="${tab === 'place' ? 'on' : ''}" data-act="coll-tab" data-v="place">장소별 ${S.sents.length - 30}</button></div>
    ${ts !== 'ok' ? notice('이 브라우저는 듣기를 지원하지 않아요.', 'warn') + '<div style="height:10px"></div>' : ''}
    ${body}</div>`;
  return frame(inner, { appbar: appbar('문장 모음'), tabbar: true });
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
  return `<div class="window"><div class="win-bar"><i></i><i></i><i></i><div class="url">admin.trip-english.web.app/${path}</div></div>
    <div class="admin"><nav class="admin-nav"><div class="brand">여행영어 <span>ADMIN</span></div>${nav}</nav><div class="admin-main">${body}</div></div>${modalHtml(true)}</div>`;
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
      <div class="panel"><h3>최근 최종 실패</h3>${failedRows.length ? failedRows.map(r => `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f1ece2;font-size:12.5px">
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
    <div class="panel" style="padding:6px 8px"><table class="tbl"><thead><tr><th>여행</th><th>사용자</th><th>상태</th><th>경과</th><th>failStreak</th><th>다시 생성</th><th></th></tr></thead><tbody>
    ${list.map(r => `<tr class="${stale(r) ? 'stale' : ''} ${r.me ? 'me' : ''}"><td><b>${esc(r.route)}</b><div class="mono" style="color:var(--muted)">${r.id}${r.me ? ' · 데모 여행' : ''}</div></td>
      <td class="mono">${r.user}</td><td>${chip(r)}</td><td class="mono">${isGen(r) && r.genMinAgo != null ? r.genMinAgo + '분' : '—'}</td>
      <td class="mono">${r.failStreak}</td><td class="mono">${r.regen}/3</td>
      <td>${stale(r) ? `<button class="btn soft sm" data-act="job-fail" data-id="${r.id}">실패로 처리</button>` : /_failed$/.test(r.status) ? '<span class="small">사용자 재시도 대기</span>' : ''}</td></tr>`).join('') || `<tr><td colspan="7"><div class="empty">해당하는 작업이 없어요</div></td></tr>`}
    </tbody></table></div>
    <p class="small" style="margin-top:10px">데모: 사이드바에서 "생성 멈춤"을 켜고 여행을 만든 뒤, SCR-03의 "16분 경과시키기"를 누르면 데모 여행이 멈춤으로 표시돼요.</p>`;
}
function admCommon() {
  S.commonsDraft ??= JSON.parse(JSON.stringify(S.commons));
  const dirty = JSON.stringify(S.commonsDraft) !== JSON.stringify(S.commons);
  return `<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px"><div><h2>공통 상황 문장 관리</h2>
    <p class="desc">6개 상황 × 5문장 = 30개. 모든 여행에 똑같이 들어가요 (FR-SENT-01). 저장하면 <b>다음 문장 생성부터</b> 반영돼요.</p></div>
    <div style="display:flex;gap:6px;flex:none"><button class="btn soft sm" data-act="cs-reset" ${dirty ? '' : 'disabled'}>되돌리기</button><button class="btn primary sm" data-act="cs-save" ${dirty ? '' : 'disabled'}>변경 사항 저장</button></div></div>
    ${notice('이름·목적지는 <b>[name]</b>, <b>[destination]</b> 빈칸으로 적어요. 듣기에서는 "your name", "your destination"으로 읽어요.')}
    <div style="height:14px"></div>
    ${S.commonsDraft.map((g, gi) => `<div class="cs-group panel"><h4>${g.label} <span class="small">${g.key}</span></h4>
      <div class="cs-row" style="font-size:11px;color:var(--muted)"><span>#</span><span>상황</span><span>영어 문장</span><span>한국어 뜻</span><span></span></div>
      ${g.items.map((it, ii) => { const o = S.commons[gi].items[ii]; return `<div class="cs-row"><span class="i">${ii + 1}</span>
        <input data-cs="${gi}.${ii}.situation" value="${esc(it.situation)}" class="${it.situation !== o.situation ? 'dirty' : ''}">
        <input data-cs="${gi}.${ii}.en" value="${esc(it.en)}" class="${it.en !== o.en ? 'dirty' : ''}">
        <input data-cs="${gi}.${ii}.ko" value="${esc(it.ko)}" class="${it.ko !== o.ko ? 'dirty' : ''}">
        <button class="play" data-act="cs-play" data-k="${gi}.${ii}">${I.speaker}</button></div>`; }).join('')}</div>`).join('')}`;
}
function admUsers() {
  const t = S.trip;
  const demoTrips = [
    ...(t ? [{ route: tripTitle(t), state: phase() === 'ended' ? '종료' : STATUS_KO[t.status], cur: true }] : []),
    ...S.archived.map(a => ({ route: a.route, state: '보관' })),
  ];
  const users = [{ email: DEMO_USER.email, name: DEMO_USER.name + ' (데모)', trips: demoTrips, me: true }, ...MOCK_USERS];
  return `<h2>사용자 · 여행</h2><p class="desc">현재 여행 = <code>archived = false</code>인 내 여행 (FR-TRIP-05). 새 여행을 만들면 이전 여행은 삭제하지 않고 보관해요 (FR-TRIP-04).</p>
    <div class="panel" style="padding:4px 10px">
      <div class="user-row" style="font-size:11.5px;color:var(--muted)"><span>이름</span><span>이메일</span><span>여행</span></div>
      ${users.map(u => `<div class="user-row" style="${u.me ? 'background:#f4fbfa' : ''}"><b>${esc(u.name)}</b><span class="mono" style="font-family:var(--mono);font-size:12px">${esc(u.email)}</span>
        <div class="trips">${u.trips.length ? u.trips.map((tr, i) => `<span class="trip-chip ${tr.state === '보관' ? 'arch' : 'cur'}">${esc(tr.route)} · ${tr.state}</span>`).join('') : '<span class="small">여행 없음</span>'}</div></div>`).join('')}
    </div>`;
}

/* ================= 이벤트 ================= */
let toastTimer;
function toast(msg) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

function go(id) { S.screen = id; S.modal = null; render(); }

function navFromMenu(id) {
  S.modal = null;
  let did = false;
  if (id.startsWith('a-')) { if (id === 'a-common') S.commonsDraft = null; go(id); return; }
  if (id === 'u-login') { go(id); return; }
  if (id === 'u-input' || id === 'u-gen') did = ensure('user');
  if (id === 'u-report') did = ensure('report');
  if (['u-route', 'u-home', 'u-sched', 'u-study', 'u-coll', 'u-end'].includes(id)) did = ensure('plan');
  if (id === 'u-end' && phase() !== 'ended') { S.today = Dt.add(S.trip.tripEnd, 1); toast(`데모: 오늘을 여행 종료 다음 날(${Dt.md(S.today)})로 바꿨어요.`); }
  else if (did) toast('데모: 이 화면에 필요한 데이터를 자동으로 준비했어요.');
  if (id === 'u-study') S.studyDate = null;
  S.justCompleted = null;
  go(id);
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
  ensure('user');
  S.flags.fail = mode === 'fail'; S.flags.stuck = mode === 'stuck';
  createTrip(defaultDraft(S.today));
  request('report');
  toast(mode === 'fail' ? '데모: "AI 생성 실패"를 켜고 새 여행으로 보고서를 요청했어요.' : mode === 'stuck' ? '데모: "생성 멈춤"을 켜고 요청했어요. 끝까지 진행 후 멈춰요.' : '새 데모 여행으로 보고서 생성을 요청했어요.');
}

function preset(kind) {
  genToken++; clearTimeout(genTimer);
  S.user = DEMO_USER;
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

const ACT = {
  nav: el => navFromMenu(el.dataset.id),
  tab: el => {
    const id = el.dataset.id;
    if (['u-home', 'u-sched', 'u-study', 'u-coll', 'u-route'].includes(id) && !S.plan) { navFromMenu(id); return; }
    if (id === 'u-study') S.studyDate = null;
    S.justCompleted = null; go(id);
  },
  noop: () => {},
  link: el => window.open(el.getAttribute('href'), '_blank', 'noopener'),
  reset: () => { const c = S.demoClosed; initState(); S.demoClosed = c; render(); toast('처음 상태로 되돌렸어요.'); },
  'demo-toggle': () => { S.demoClosed = !S.demoClosed; renderDemo(); },
  'set-today': el => { S.today = el.dataset.date; S.justCompleted = null; render(); toast(`오늘을 ${Dt.full(S.today)}로 바꿨어요.`); },
  preset: el => preset(el.dataset.kind),

  login: () => { S.user = DEMO_USER; toast('Google 계정으로 로그인했어요.'); ACT['after-login'](); },
  'after-login': () => go(S.trip && !S.trip.archived ? (S.plan ? 'u-home' : S.places.length ? 'u-report' : 'u-gen') : 'u-input'),
  logout: () => { S.user = null; toast('로그아웃했어요. 로그인 화면 외에는 들어갈 수 없어요.'); go('u-login'); },

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

  'study-date': el => { S.studyDate = el.dataset.date; S.justCompleted = null; go('u-study'); },
  flip: el => {
    el.classList.toggle('flipped');
    if (el.classList.contains('flipped')) { S.card.flipped.add(S.card.i); updateStudyLive(); }
    else if (ttsSupported()) speechSynthesis.cancel();
  },
  'card-prev': () => { S.card.i = Math.max(0, S.card.i - 1); render(); },
  'card-next': () => { const r = pickRow(); S.card.i = Math.min(r.ids.length - 1, S.card.i + 1); render(); },
  'speak-card': el => { const r = pickRow(); speak(S.smap[r.ids[S.card.i]].en, el); },
  speak: el => speak(S.smap[el.dataset.id].en, el),
  rate: el => { S.ttsRate = S.ttsRate < 0.9 ? 0.95 : 0.75; el.textContent = S.ttsRate < 0.9 ? '느리게' : '보통 속도'; },
  complete: () => {
    const r = pickRow();
    if (!canComplete(r) || S.card.flipped.size < r.ids.length) return;
    r.completed = true; r.completedAt = Date.now(); S.justCompleted = r.date; S.studyDate = r.date;
    render(); toast('학습 완료! 완료율이 갱신됐어요.');
  },
  restudy: () => { S.justCompleted = null; resetCard(); render(); },
  'sched-filter': el => { S.schedFilter = el.dataset.v; render(); },
  'demo-fill': () => {
    if (!S.plan) ensure('plan');
    let n = 0;
    S.sched.forEach((r, i) => { if (r.date < S.today && r.kind !== 'free' && !r.completed && i % 3 !== 2) { r.completed = true; n++; } });
    render(); toast(n ? `지난 날 ${n}일을 완료로 채웠어요. 나머지는 미완료로 남아요.` : '채울 지난 날이 없어요. 사이드바에서 오늘 날짜를 뒤로 옮겨 보세요.');
  },
  'coll-tab': el => { S.coll = { tab: el.dataset.v, filter: 'all' }; render(); },
  'coll-filter': el => { S.coll.filter = el.dataset.v; render(); },
  'new-trip': () => confirmBox('새 여행을 만들까요?', '이 여행은 보관되고 더 이상 보이지 않아요. (삭제되지는 않아요)', '보관하고 새로 만들기', () => {
    archiveTrip(); S.trip = null; S.places = []; S.sched = []; S.plan = null; S.sents = []; S.days = [];
    S.draft = defaultDraft(S.today); S.showErrors = false; S.modal = null; go('u-input'); toast('이전 여행을 보관했어요.');
  }, { danger: true }),

  'modal-ok': () => { const fn = modalFn; modalFn = null; fn && fn(); },
  'modal-cancel': () => { S.modal = null; render(); },
  'modal-bg': (el, e) => { if (e.target === el) { S.modal = null; render(); } },

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

initState();
renderSide();
render();
/* index.html#u-home 처럼 주소 뒤에 화면 ID를 붙이면 그 화면으로 바로 열림 */
if (SCR[location.hash.slice(1)]) navFromMenu(location.hash.slice(1));
