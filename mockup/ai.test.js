/* 실행: cd mockup && node --test
   fixture 기반 테스트다. 응답 분기·배정·저장 조건 같은 "코드의 규칙"만 확인하며,
   실제 Gemini 호출·마이크·배포 환경의 동작을 보증하지 않는다. */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const AI = require('./ai.js');

const sent = (o = {}) => ({ situation_id: 'order_menu', situation: '주문', en: 'A table for two, please.', ko: '두 명이요.', ...o });
const res = (o = {}) => ({ pack: { category_id: 'restaurant', city: 'New York', sentences: [sent()] }, issues: [], attempts: 1, mock: false, usable: 'ok', ...o });

test('apiBase: ?api= 는 저장하지 않고 external 로 표시, file:// 은 폴백 전용', () => {
  assert.deepEqual(AI.apiBase({ protocol: 'https:', host: 'a.onrender.com', origin: 'https://a.onrender.com', search: '' }), { base: '', external: false, host: 'a.onrender.com' });
  const ext = AI.apiBase({ protocol: 'https:', host: 'a.onrender.com', origin: 'https://a.onrender.com', search: '?api=https://evil.example' });
  assert.equal(ext.base, 'https://evil.example'); assert.equal(ext.external, true);
  assert.equal(AI.apiBase({ protocol: 'file:', host: '', origin: 'null', search: '' }).base, null);
  assert.equal(AI.apiBase({ protocol: 'file:', host: '', origin: 'null', search: '?api=javascript:alert(1)' }).base, null);
  assert.equal(AI.apiBase({ protocol: 'https:', host: 'a', origin: 'https://a', search: '?api=ftp://x' }).base, '');
});

test('응답 분기: degraded 우선 폐기 → mock:true 샘플 → mock:false AI → 그 외 폴백', () => {
  assert.equal(AI.normalizeAiResponse(res()).kind, 'ai');
  assert.equal(AI.normalizeAiResponse(res({ mock: true, usable: 'sample' })).kind, 'sample');
  assert.equal(AI.normalizeAiResponse(res({ degraded: true })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(res({ degraded: true, mock: true, usable: 'sample' })).kind, 'fallback'); // 동시에 있어도 degraded 먼저
  assert.equal(AI.normalizeAiResponse(res({ usable: 'rejected' })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(res({ mock: true, usable: 'rejected' })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(res({ mock: true, usable: 'ok' })).kind, 'fallback');      // 판정과 mock 이 안 맞으면 믿지 않음
  assert.equal(AI.normalizeAiResponse(res({ mock: false, usable: 'sample' })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(res({ usable: undefined })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(res({ mock: undefined })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(null).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse({ mock: false }).kind, 'fallback');
  const bad = res(); bad.pack.sentences = [sent({ ko: '' })];
  assert.equal(AI.normalizeAiResponse(bad).kind, 'fallback');
  const bad2 = res(); bad2.pack.sentences = 'x';
  assert.equal(AI.normalizeAiResponse(bad2).kind, 'fallback');
});

test('장소 배정: 일치하는 장소 문장만, 불일치는 버림, 일반 문장만 공통 풀, 중복 en 제외', () => {
  const places = [{ id: 'p1', name: '카츠', en: "Katz's Delicatessen" }, { id: 'p2', name: '쉐이크쉑', en: 'Shake Shack' }];
  const r = res(); r.pack.sentences = [
    sent({ place: "Katz's Delicatessen", en: 'One pastrami, please.' }),
    sent({ place: 'Unknown Place', en: 'Dropped.' }),
    sent({ en: 'Common one.' }),
    sent({ en: 'common one.' }), // 중복
    sent({ place: 'shake shack', en: 'A burger, please.' }),
  ];
  const n = AI.normalizeAiResponse(r);
  const pools = AI.buildPools(n.sentences, places);
  assert.deepEqual(pools.byPlace.p1.map(s => s.en), ['One pastrami, please.']);
  assert.deepEqual(pools.byPlace.p2.map(s => s.en), ['A burger, please.']);
  assert.deepEqual(pools.common.map(s => s.en), ['Common one.']);
  assert.equal(AI.takeForPlace(pools, 'p1', 2).length, 2); // 전용 1 + 공통 1
  assert.equal(AI.takeForPlace(pools, 'p2', 3).length, 1); // 공통 풀은 이미 소진 → 부족분은 호출부가 템플릿으로 채움
});

test('도시별 부분 실패: 성공 도시는 살리고 실패 도시만 폴백', async () => {
  const cities = [
    { name: 'New York', places: [{ id: 'a', name: 'A', en: 'A' }] },
    { name: 'Boston', places: [{ id: 'b', name: 'B', en: 'B' }] },
    { name: 'Chicago', places: [{ id: 'c', name: 'C', en: 'C' }] },
  ];
  const fetchImpl = async (url, opt) => {
    if (url.endsWith('/health')) return { ok: true, json: async () => ({ situations: { restaurant: ['allergy_notice'] } }) };
    const city = JSON.parse(opt.body).city;
    if (city === 'Boston') throw new Error('network');
    if (city === 'Chicago') return { ok: true, json: async () => res({ degraded: true }) };
    return { ok: true, json: async () => res({ mock: false }) };
  };
  const out = await AI.generateByCity({ fetchImpl, base: '', cities, weakIds: [] });
  assert.deepEqual(out.map(o => o.kind), ['ai', 'fallback', 'fallback']);
});

test('generateByCity: 서버가 유효하다고 알린 상황 id 만 취약 상황으로 보낸다', async () => {
  const bodies = [];
  const fetchImpl = async (url, opt) => {
    if (url.endsWith('/health')) return { ok: true, json: async () => ({ situations: { restaurant: ['allergy_notice', 'order_menu'] } }) };
    bodies.push(JSON.parse(opt.body)); return { ok: true, json: async () => res() };
  };
  await AI.generateByCity({ fetchImpl, base: '', cities: [{ name: 'X', places: [] }], weakIds: ['allergy_notice', 'check_in', 'w_old'] });
  assert.deepEqual(bodies[0].weak_expressions, ['allergy_notice']);
});

test('generateByCity: 카테고리는 묶음마다 따로, 장소 종류가 place_type 으로 간다', async () => {
  const bodies = [];
  const fetchImpl = async (url, opt) => {
    if (url.endsWith('/health')) return { ok: true, json: async () => ({ situations: { restaurant: ['allergy_notice'], lodging: ['check_in'] } }) };
    bodies.push(JSON.parse(opt.body)); return { ok: true, json: async () => res() };
  };
  const cities = [
    { name: 'X', categoryId: 'restaurant', places: [{ id: 'a', name: 'A', en: 'A', kind: 'cafe' }] },
    { name: 'X', categoryId: 'lodging', places: [{ id: 'h', name: 'H', en: 'H', kind: 'hotel' }] },
  ];
  const out = await AI.generateByCity({ fetchImpl, base: '', cities, weakIds: ['allergy_notice', 'check_in'] });
  assert.deepEqual(bodies.map(b => [b.category_id, b.places[0].place_type, b.weak_expressions]),
    [['restaurant', 'cafe', ['allergy_notice']], ['lodging', 'hotel', ['check_in']]]);
  assert.deepEqual(out.map(o => o.categoryId), ['restaurant', 'lodging']);
});

test('categoryOfKind·weakIdsFor: 계약의 place_types 로 카테고리를 찾고 여러 카테고리를 합친다', () => {
  assert.equal(AI.categoryOfKind('Hotel '), 'lodging');
  assert.equal(AI.categoryOfKind('airport'), 'transport');
  assert.equal(AI.categoryOfKind('attraction'), null);
  const list = [{ category_id: 'restaurant', id: 'allergy_notice', situation: 's' }, { category_id: 'lodging', id: 'check_in', situation: 's' }];
  assert.deepEqual(AI.weakIdsFor(list, ['restaurant', 'lodging', 'restaurant']), ['allergy_notice', 'check_in']);
});

test('generateByCity: API 없음(file://)이면 전부 폴백, 호출 안 함', async () => {
  let called = 0;
  const out = await AI.generateByCity({ fetchImpl: async () => { called++; }, base: null, cities: [{ name: 'X', places: [] }], weakIds: [] });
  assert.equal(called, 0); assert.equal(out[0].kind, 'fallback');
});

test('generateByCity: 타임아웃·취소는 폴백이 되고 재시도하지 않는다', async () => {
  let calls = 0;
  const fetchImpl = (url, opt) => { calls++; return new Promise((_, rej) => opt.signal.addEventListener('abort', () => rej(new Error('aborted')))); };
  const out = await AI.generateByCity({ fetchImpl, base: '', cities: [{ name: 'X', places: [] }], weakIds: [], timeoutMs: 20 });
  assert.equal(out[0].kind, 'fallback'); assert.equal(calls, 1); // /health 에서 이미 막혀 /generate 는 부르지 않는다
  const ctl = new AbortController(); calls = 0;
  const p = AI.generateByCity({ fetchImpl, base: '', cities: [{ name: 'X', places: [] }], weakIds: [], signal: ctl.signal, timeoutMs: 5000 });
  ctl.abort();
  assert.equal((await p)[0].kind, 'fallback');
});

test('취약 상황 저장: 키는 category_id + id, 구형·불량 기록은 읽을 때 제외', () => {
  let list = AI.upsertWeak([], { category_id: 'restaurant', id: 'allergy_notice', situation: '알레르기', en: 'x', ko: 'y' });
  list = AI.upsertWeak(list, { category_id: 'transport', id: 'allergy_notice', situation: '다른 카테고리', en: '', ko: '' });
  list = AI.upsertWeak(list, { category_id: 'restaurant', id: 'allergy_notice', situation: '갱신', en: 'x2', ko: 'y2' });
  assert.equal(list.length, 2);
  assert.equal(list.find(w => w.category_id === 'restaurant').situation, '갱신');
  const dirty = [{ category_id: 'restaurant', id: 'w_allergy_peanut', situation: 's' }, { id: 'order_menu', situation: 's' }, null, 7, ...list];
  assert.equal(AI.cleanWeak(dirty).length, 2);
  assert.deepEqual(AI.weakIdsFor(list, 'restaurant'), ['allergy_notice']);
  assert.deepEqual(AI.weakIdsFor(list, 'lodging'), []);
});

test('scopedStorage: uid 가 없으면 기존 키, 있으면 계정마다 갈라지고 다른 계정은 안 보인다', () => {
  const mem = new Map();
  const storage = {
    getItem: k => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: k => mem.delete(k),
  };
  const item = { category_id: 'restaurant', id: 'order_menu', situation: '주문', en: 'Water', ko: '물' };
  AI.saveWeak(AI.scopedStorage(storage, ''), [item]);
  AI.saveWeak(AI.scopedStorage(storage, 'uidA'), [{ ...item, situation: 'A만' }]);
  AI.saveWeak(AI.scopedStorage(storage, 'uidB'), [{ ...item, situation: 'B만' }]);
  assert.equal(AI.loadWeak(AI.scopedStorage(storage, ''))[0].situation, '주문');
  assert.equal(AI.loadWeak(AI.scopedStorage(storage, 'uidA'))[0].situation, 'A만');
  assert.equal(AI.loadWeak(AI.scopedStorage(storage, 'uidB'))[0].situation, 'B만');
  assert.equal(AI.loadWeak(storage)[0].situation, '주문');
  AI.saveConsent(AI.scopedStorage(storage, 'uidA'), true, new Date('2026-10-15T00:00:00.000Z'));
  AI.withdrawConsent(AI.scopedStorage(storage, 'uidA'));
  assert.equal(AI.loadWeak(AI.scopedStorage(storage, 'uidA')).length, 0);
  assert.equal(AI.loadConsent(AI.scopedStorage(storage, 'uidA')).voice, false);
  assert.equal(AI.loadWeak(AI.scopedStorage(storage, 'uidB')).length, 1);
  assert.equal(AI.loadWeak(storage).length, 1);
  assert.equal(AI.scopedStorage(null, 'uidA'), null);
});

test('여행 입력: 규칙 밖이면 null, 저장·읽기 왕복, 계정 칸마다 갈린다, null 이면 삭제', () => {
  const good = { country: ' 미국 ', cities: [{ name: ' 뉴욕 ', start: '2026-11-10', end: '2026-11-13' }], studyStart: '2026-10-01' };
  assert.deepEqual(AI.cleanTrip(good), { country: '미국', cities: [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-13' }], studyStart: '2026-10-01' });
  assert.equal(AI.cleanTrip(null), null);
  assert.equal(AI.cleanTrip({ ...good, country: '   ' }), null);
  assert.equal(AI.cleanTrip({ ...good, cities: [] }), null);                                   // 도시 0곳
  assert.equal(AI.cleanTrip({ ...good, cities: [1, 2, 3, 4, 5, 6].map(() => good.cities[0]) }), null);   // 6곳
  assert.equal(AI.cleanTrip({ ...good, cities: [{ name: '뉴욕', start: '2026/11/10', end: '2026-11-13' }] }), null);  // 날짜 형식
  assert.equal(AI.cleanTrip({ ...good, studyStart: '' }), null);
  assert.equal(AI.cleanTrip({ country: '미국', cities: good.cities }), null);                   // 학습 시작일 없음
  // 여러 나라: countries·ci 를 지킨다. 나라가 하나면 예전 모양(서버·예전 기록과 같은 모양)
  const multi = { country: '미국', countries: ['미국', ' 캐나다 '], studyStart: '2026-10-01',
    cities: [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-13', ci: 0 }, { name: '토론토', start: '2026-11-13', end: '2026-11-16', ci: 1 }] };
  assert.deepEqual(AI.cleanTrip(multi), { ...multi, countries: ['미국', '캐나다'] });
  assert.deepEqual(AI.cleanTrip({ ...good, countries: ['미국'], cities: [{ ...good.cities[0], ci: 0 }] }), AI.cleanTrip(good));
  assert.equal(AI.cleanTrip({ ...multi, countries: ['캐나다', '미국'] }), null);                  // countries[0] != country
  assert.equal(AI.cleanTrip({ ...multi, countries: ['미국', '캐나다', '일본', '영국', '독일'] }), null);   // 5개국
  assert.equal(AI.cleanTrip({ ...multi, cities: [{ ...multi.cities[0], ci: 2 }, multi.cities[1]] }), null);   // 없는 나라
  assert.equal(AI.cleanTrip({ ...multi, cities: [multi.cities[0], { ...multi.cities[1], ci: 0 }] }), null);   // 도시 없는 나라
  // 목록에서 고른 도시의 GeoNames id(gid) 는 지키고, 규칙 밖이면 여행을 버리지 않고 그 칸만 뺀다
  assert.equal(AI.cleanTrip({ ...good, cities: [{ ...good.cities[0], gid: 5128581 }] }).cities[0].gid, 5128581);
  for (const bad of [0, -3, 2 ** 31, '5128581', 1.5, null]) {
    const t = AI.cleanTrip({ ...good, cities: [{ ...good.cities[0], gid: bad }] });
    assert.ok(t && !('gid' in t.cities[0]), String(bad));
  }

  const mem = new Map();
  const storage = { getItem: k => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) };
  assert.equal(AI.loadTrip(storage), null);                                                     // 아무것도 없을 때
  assert.equal(AI.saveTrip(AI.scopedStorage(storage, ''), good), true);
  assert.equal(AI.saveTrip(AI.scopedStorage(storage, 'uidA'), { ...good, country: '영국' }), true);
  assert.equal(AI.loadTrip(AI.scopedStorage(storage, '')).country, '미국');
  assert.equal(AI.loadTrip(AI.scopedStorage(storage, 'uidA')).country, '영국');
  assert.equal(AI.saveTrip(AI.scopedStorage(storage, ''), null), true);
  assert.equal(AI.loadTrip(AI.scopedStorage(storage, '')), null);                               // 저장 해제
  assert.equal(AI.loadTrip(AI.scopedStorage(storage, 'uidA')).country, '영국');                  // 다른 칸은 그대로
  const bad = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
  assert.equal(AI.loadTrip(bad), null); assert.equal(AI.saveTrip(bad, good), false);
  assert.equal(AI.loadTrip({ getItem: () => '{oops' }), null);

  const remote = { country: '영국', cities: [{ name: '런던', start: '2026-12-01', end: '2026-12-03' }], studyStart: '2026-11-01' };
  const local = { country: '미국', cities: [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-13' }], studyStart: '2026-10-01' };
  assert.equal(AI.preferTrip(remote, local).country, '영국');          // 서버에 여행이 있으면 서버
  assert.equal(AI.preferTrip(null, local).country, '미국');             // 서버 칸이 비면 이 브라우저
  assert.equal(AI.preferTrip({ country: '  ' }, local).country, '미국'); // 규칙 밖 서버 값은 버린다
  assert.equal(AI.preferTrip(null, null), null);
});

test('loadWeak/saveWeak: 저장소 예외·깨진 JSON에도 죽지 않는다', () => {
  const bad = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.deepEqual(AI.loadWeak(bad), []); assert.equal(AI.saveWeak(bad, []), false);
  assert.deepEqual(AI.loadWeak({ getItem: () => '{oops' }), []);
});

test('복습 표시: AI 문장이 (카테고리, 상황) 모두 일치하고 그 상황을 겨냥했을 때만', () => {
  const list = [{ category_id: 'restaurant', id: 'allergy_notice', situation: 's', demo: true }];
  const s = { ai: true, categoryId: 'restaurant', situationId: 'allergy_notice', targetsWeak: ['allergy_notice'] };
  assert.ok(AI.weakReviewOf(s, list));
  assert.equal(AI.weakReviewOf({ ...s, ai: false }, list), null);                       // 샘플
  assert.equal(AI.weakReviewOf({ ...s, categoryId: 'transport' }, list), null);         // 카테고리 불일치
  assert.equal(AI.weakReviewOf({ ...s, targetsWeak: [] }, list), null);                 // 겨냥 표시 없음
  assert.equal(AI.weakReviewOf({ ...s, situationId: 'order_menu', targetsWeak: ['allergy_notice'] }, list), null);
});

test('shouldSaveWeak: null/NaN/범위 밖/목업/샘플·폴백 문장/파싱 실패는 저장 안 함', () => {
  const ai = { ai: true, categoryId: 'restaurant', situationId: 'order_menu' };
  const ok = score => AI.shouldSaveWeak(ai, { usable: true, score, heard: 'x', issues: [], tip: 't' });
  assert.equal(ok(40), true);
  assert.equal(ok(69), true);
  assert.equal(ok(70), false);          // 임계값은 미만만
  assert.equal(ok(90), false);
  assert.equal(ok(NaN), false);
  assert.equal(ok(Infinity), false);
  assert.equal(ok(-5), false);
  assert.equal(ok(120), false);
  assert.equal(ok('40'), false);
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: 40, mock: true }), false);
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: 40, raw: '...' }), false);
  assert.equal(AI.shouldSaveWeak(ai, { usable: false, score: 40 }), false);                        // 서버가 못 쓴다고 판정
  assert.equal(AI.shouldSaveWeak(ai, { score: 40 }), false);                                       // usable 없음
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: null, score_discarded: true }), false);
  assert.equal(AI.shouldSaveWeak({ ...ai, ai: false }, { usable: true, score: 40 }), false);
  assert.equal(AI.shouldSaveWeak({ ai: true, categoryId: 'restaurant' }, { usable: true, score: 40 }), false);
  assert.equal(AI.shouldSaveWeak(ai, null), false);
});

test('weakDecision: 교차검증 못 한 결과(제한 모드)는 자동 저장하지 않고 사용자 선택만', () => {
  const ai = { ai: true, categoryId: 'restaurant', situationId: 'allergy_notice', en: 'I have a peanut allergy.' };
  const limited = { usable: true, limited: true, cross_validated: false, score: null, heard: 'I have a nut' };
  assert.equal(AI.weakDecision(ai, limited), 'ask');
  assert.equal(AI.weakDecision(ai, { ...limited, score: 10 }), 'ask');       // 서버가 실수로 점수를 보내도 자동 저장 안 함
  assert.equal(AI.shouldSaveWeak(ai, { ...limited, score: 10 }), false);
  assert.equal(AI.weakDecision(ai, { ...limited, heard: '' }), 'none');      // 들린 문장이 없으면 저장 제안도 없음
  assert.equal(AI.weakDecision({ ...ai, ai: false }, limited), 'none');      // 샘플·폴백 문장은 그대로 제외
  assert.equal(AI.weakDecision(ai, { usable: true, cross_validated: true, score: 40, heard: 'x' }), 'auto');
});

test('weakDecision: 점수가 없으면 자동 저장하지 않고 사용자에게 묻는다(ask)', () => {
  const ai = { ai: true, categoryId: 'restaurant', situationId: 'allergy_notice', en: 'I have a peanut allergy.' };
  const d = o => AI.weakDecision(ai, { usable: true, score: null, ...o });
  assert.equal(d({ heard: 'I have a nut' }), 'ask');
  assert.equal(d({ heard: "I don't have a peanut allergy." }), 'ask');       // 일치율과 무관하게 ask
  assert.equal(d({ heard: 'I have an allergy to peanuts' }), 'ask');          // 자연스러운 대체 표현도 자동 저장되지 않음
  assert.equal(d({ heard: '' }), 'none');                                     // 무음·인식 실패
  assert.equal(d({ heard: '   ' }), 'none');
  assert.equal(d({}), 'none');
  assert.equal(d({ heard: 'x', score_discarded: true }), 'none');            // 범위 밖 점수를 서버가 폐기
  assert.equal(AI.weakDecision(ai, { usable: true, heard: 'x' }), 'ask');   // score 키 자체가 없음
  assert.equal(AI.weakDecision(ai, { usable: false, heard: 'x' }), 'none');
  assert.equal(AI.weakDecision(ai, { usable: true, mock: true, heard: 'x' }), 'none');
  assert.equal(AI.weakDecision(ai, { usable: true, score: 40, heard: 'x' }), 'auto');
  assert.equal(AI.weakDecision(ai, { usable: true, score: 90, heard: 'x' }), 'none');
  assert.equal(AI.weakDecision({ ...ai, ai: false }, { usable: true, score: null, heard: 'x' }), 'none'); // 샘플·폴백 문장
  // 자동 저장은 점수 경로만
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: null, heard: 'I have a nut' }), false);
  assert.equal(AI.heardCoverage('a b c d', 'a b'), 0.5);
});

test('shouldSaveWeak: 점수가 있어도 heard 가 없으면(무음) 저장하지 않는다', () => {
  const ai = { ai: true, categoryId: 'restaurant', situationId: 'order_menu', en: 'A table for two, please.' };
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: 10, heard: '' }), false);
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: 10 }), false);
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: 10, heard: '  ' }), false);
  assert.equal(AI.shouldSaveWeak(ai, { usable: true, score: 10, heard: 'a table' }), true);
});

test('heardCoverage 한계(문서화): 부정문은 같은 문장으로, 자연스러운 대체 표현은 누락으로 본다', () => {
  assert.equal(AI.heardCoverage('I have a peanut allergy.', "I don't have a peanut allergy."), 1);
  assert.ok(AI.heardCoverage("I'd like a coffee, please.", 'Could I have a coffee, please?') < AI.HEARD_MATCH_MIN);
});

test('speakCheck: 빈 오디오·용량 초과·API 없음은 업로드 전에 거절, MIME→확장자', async () => {
  const f = async () => { throw new Error('should not call'); };
  await assert.rejects(AI.speakCheck({ fetchImpl: f, base: '', blob: { size: 0 }, target: 't' }), /empty-audio/);
  await assert.rejects(AI.speakCheck({ fetchImpl: f, base: '', blob: { size: AI.MAX_AUDIO_BYTES + 1, type: 'audio/webm' }, target: 't' }), /too-large/);
  await assert.rejects(AI.speakCheck({ fetchImpl: f, base: null, blob: new Blob(['x']), target: 't' }), /no-api/);
  assert.equal(AI.extFor('audio/webm;codecs=opus'), 'webm');
  assert.equal(AI.extFor('audio/mp4'), 'm4a');
  assert.equal(AI.extFor('audio/ogg; codecs=opus'), 'ogg');
  assert.equal(AI.extFor(''), 'webm');
});

const memStorage = (init = {}) => {
  const m = new Map(Object.entries(init));
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), m };
};
const brokenStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };

test('동의: 기본은 미동의, 저장하면 시각과 함께 유효', () => {
  const st = memStorage();
  assert.deepEqual(AI.loadConsent(st), { voice: false, at: null });
  assert.equal(AI.saveConsent(st, true, new Date('2026-10-07T01:02:03Z')), true);
  assert.deepEqual(AI.loadConsent(st), { voice: true, at: '2026-10-07T01:02:03.000Z' });
  AI.saveConsent(st, false);
  assert.equal(AI.loadConsent(st).voice, false);
});

test('동의: 구버전·손상·형식 불일치·저장소 차단은 미동의', () => {
  const v = AI.CONSENT_VERSION;
  for (const raw of [JSON.stringify({ version: v - 1, voice: true, at: 'x' }), JSON.stringify({ version: v, voice: 'yes', at: 'x' }),
                     JSON.stringify({ version: v, voice: true }), JSON.stringify({ version: v, voice: true, at: 'x' }),
                     JSON.stringify({ version: v, at: '2026-10-07T00:00:00Z' }),   // 로그인 동의 방식(voice 없음) 기록 → 다시 동의
                     '{broken', 'null', '[]']) {
    assert.equal(AI.loadConsent(memStorage({ [AI.CONSENT_KEY]: raw })).voice, false, raw);
  }
  assert.equal(AI.loadConsent(brokenStorage).voice, false);
  assert.equal(AI.saveConsent(brokenStorage, true), false);
});

test('동의 철회: 동의와 복습 목록을 함께 지운다', () => {
  const st = memStorage();
  AI.saveConsent(st, true);
  AI.saveWeak(st, [{ category_id: 'restaurant', id: 'allergy_notice', situation: '알레르기', en: 'I am allergic.', ko: '알레르기' }]);
  assert.equal(AI.loadWeak(st).length, 1);
  assert.equal(AI.withdrawConsent(st), true);
  assert.equal(AI.loadConsent(st).voice, false);
  assert.equal(AI.loadWeak(st).length, 0);
  assert.equal(st.m.size, 0);
  assert.equal(AI.withdrawConsent(brokenStorage), false);
});

test('speakCheck: 목표 문장과 상황 이름을 보낸다 (상황은 120자 제한)', async () => {
  let sent = null;
  const f = async (url, opt) => { sent = opt.body; return { ok: true, status: 200, json: async () => ({ usable: true }) }; };
  await AI.speakCheck({ fetchImpl: f, base: '', blob: new Blob(['x'], { type: 'audio/webm' }), target: 'I have a peanut allergy.', situation: '알레르기·재료 고지' + 'x'.repeat(200) });
  assert.equal(sent.get('target'), 'I have a peanut allergy.');
  assert.equal(sent.get('situation').length, 120);
  assert.ok(sent.get('situation').startsWith('알레르기·재료 고지'));
  await AI.speakCheck({ fetchImpl: f, base: '', blob: new Blob(['x'], { type: 'audio/webm' }), target: 't' });
  assert.equal(sent.get('situation'), '');
});

test('무음 판정은 서버(Silero VAD) 몫 — 브라우저 음량(데시벨) 판정 함수가 없다', () => {
  for (const k of ['isSilent', 'SILENCE_RMS', 'MIN_VOICED_MS']) assert.equal(k in AI, false, k);
});

test('저장소가 없거나(null) 차단돼도 학습 흐름이 죽지 않는다', () => {
  assert.deepEqual(AI.loadWeak(null), []);
  assert.equal(AI.saveWeak(null, []), false);
  assert.deepEqual(AI.loadConsent(null), { voice: false, at: null });
  assert.equal(AI.saveConsent(null, true), false);
  assert.equal(AI.withdrawConsent(null), false);
});

test('inAppBrowser: 인앱 브라우저 UA 추정 (실기기 동작은 미검증)', () => {
  const U = 'https://x.onrender.com/?a=1';
  const kakaoIos = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KAKAOTALK 10.4.0';
  const kakaoAnd = 'Mozilla/5.0 (Linux; Android 13; SM-S911N Build/TP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0 Mobile Safari/537.36 KAKAOTALK/10.4.0';
  const k1 = AI.inAppBrowser(kakaoIos, U); assert.equal(k1.name, '카카오톡'); assert.equal(k1.os, 'ios');
  assert.equal(k1.scheme, 'kakaotalk://web/openExternal?url=' + encodeURIComponent(U));
  assert.equal(AI.inAppBrowser(kakaoAnd, U).name, '카카오톡');
  const insta = AI.inAppBrowser('Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 Instagram 300.0', U);
  assert.equal(insta.name, '인스타그램'); assert.match(insta.scheme, /^intent:\/\/x\.onrender\.com\/\?a=1#Intent;scheme=https;package=com\.android\.chrome;S\.browser_fallback_url=.+;end$/);
  assert.equal(AI.inAppBrowser('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 300', U).scheme, null);
  const gen = AI.inAppBrowser('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148', U);
  assert.equal(gen.name, '앱 안');
  /* 일반 브라우저는 null */
  assert.equal(AI.inAppBrowser('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1', U), null);
  assert.equal(AI.inAppBrowser('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120 Mobile/15E148 Safari/604.1', U), null);
  assert.equal(AI.inAppBrowser('Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36', U), null);
  assert.equal(AI.inAppBrowser('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36', U), null);
  assert.equal(AI.inAppBrowser('', U), null);
});

test('inAppBrowser: LINE 은 openExternalBrowser 를 해시 앞에 붙이고, Android intent 는 해시·폴백을 유지한다', () => {
  const line = AI.inAppBrowser('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari Line/13.0.0', 'https://x.onrender.com/?a=1#u-home');
  assert.equal(line.name, '라인'); assert.equal(line.scheme, 'https://x.onrender.com/?a=1&openExternalBrowser=1#u-home');
  const ua = 'Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 NAVER(inapp; search; 1; 12.0)';
  const nv = AI.inAppBrowser(ua, 'https://x.onrender.com/p?a=1#u-home');
  assert.ok(nv.scheme.startsWith('intent://x.onrender.com/p?a=1#u-home#Intent;'));
  assert.ok(nv.scheme.includes('S.browser_fallback_url=' + encodeURIComponent('https://x.onrender.com/p?a=1#u-home')));
});

test('calendarToday: 로컬 연월일이고 UTC 문자열로 바꾸지 않는다', () => {
  const morning = new Date(2026, 9, 16, 0, 30);
  const evening = new Date(2026, 9, 16, 23, 30);
  const pad = n => String(n).padStart(2, '0');
  const local = n => n.getFullYear() + '-' + pad(n.getMonth() + 1) + '-' + pad(n.getDate());
  assert.equal(AI.calendarToday(morning), local(morning));
  assert.equal(AI.calendarToday(evening), local(evening));
  assert.equal(AI.calendarToday(morning), AI.calendarToday(evening));
  assert.match(String(AI.calendarToday), /getFullYear/);
  assert.doesNotMatch(String(AI.calendarToday), /toISOString/);
});

test('itineraryRequestBody: 세 종류를 보내고 14일을 넘는 구간도 자르지 않는다', () => {
  const body = AI.itineraryRequestBody({ name: '뉴욕', start: '2026-10-16', end: '2026-11-04' });
  assert.equal(body.city, '뉴욕');
  assert.equal(body.days, 20);
  assert.equal(body.start_date, '2026-10-16');
  assert.deepEqual(body.itinerary_kinds, ['restaurant', 'cafe', 'attraction']);
  assert.equal('category_id' in body, false);
  assert.equal(AI.itineraryRequestBody({ name: '뉴욕', start: '2026-11-10', end: '2026-11-12' }).days, 3);
});

const rawPlace = (id, name, primary) => ({
  provider_id: id, name, attribution: 'Google Maps', fetched_at: '2026-10-16T01:02:03Z',
  source_url: 'https://maps.google.com/?cid=' + id,
  data: { formatted_address: '7 Carmine St', primary_type: primary, business_status: 'OPERATIONAL' },
});

test('foldItinerary: 플래그 꺼짐·네트워크 실패는 예시, 빈 결과는 예시 장소가 아니다', () => {
  const cities = [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-12' }, { name: '보스턴', start: '2026-11-12', end: '2026-11-14' }];
  const off = { error: null, body: { status: 'unavailable', reason: 'itinerary_disabled' } };
  assert.equal(AI.foldItinerary(cities, [off, off], {}).mode, 'example');
  assert.equal(AI.foldItinerary(cities, [{ error: 'network' }, { error: 'network' }], {}).mode, 'example');
  const empty = { error: null, body: { status: 'unavailable', reason: 'no_verified_places', places: [], days: [], queries: [] } };
  const none = AI.foldItinerary(cities, [empty, empty], { '뉴욕': 4, '보스턴': 4 });
  assert.equal(none.mode, 'empty');
  assert.equal(none.places.length, 0);
  assert.equal(none.blocksByCity, null);
  assert.equal(none.meta['뉴욕'].reason, 'no_verified_places');
  const mixed = AI.foldItinerary(cities, [empty, off], {});
  assert.equal(mixed.mode, 'empty');
  assert.equal(mixed.places.length, 0);
});

test('foldItinerary: 성공한 도시만 남기고, 블록이 없으면 코드 상한까지만 고른다', () => {
  const cities = [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-12' }, { name: '보스턴', start: '2026-11-12', end: '2026-11-14' }];
  const places = ['a', 'b', 'c', 'd', 'e'].map((id, i) => rawPlace(id, 'Place ' + i, i === 0 ? 'cafe' : i === 1 ? 'museum' : 'pizza_restaurant'));
  const live = { error: null, body: { status: 'unavailable', reason: 'no_gemini_key', places, days: [], queries: [{ included_type: 'tourist_attraction', status: 'unavailable', reason: 'http_429' }] } };
  const empty = { error: null, body: { status: 'unavailable', reason: 'no_verified_places', places: [], days: [] } };
  const folded = AI.foldItinerary(cities, [live, empty], { '뉴욕': 2, '보스턴': 4 });
  assert.equal(folded.mode, 'live');
  assert.equal(folded.blocksByCity, null);
  assert.deepEqual(folded.places.map(p => p.city), ['뉴욕', '뉴욕', '뉴욕', '뉴욕', '뉴욕']);
  assert.deepEqual(folded.places.map(p => p.selected), [true, true, false, false, false]);
  assert.deepEqual(folded.places.map(p => p.kind), ['cafe', 'attraction', 'restaurant', 'restaurant', 'restaurant']);
  assert.equal(AI.categoryOfKind('attraction'), null);
  assert.equal(AI.categoryOfKind('cafe'), 'restaurant');
  assert.equal(folded.meta['뉴욕'].base, 2);
  assert.equal(folded.meta['보스턴'].mode, 'empty');
  assert.equal(folded.meta['보스턴'].found, 0);
  assert.equal(folded.places[0].area, '7 Carmine St');
  assert.equal(folded.places[0].desc, '');
  assert.equal(folded.places[0].menuKo, null);
  assert.equal(folded.places.some(p => p.reason), false);
});

test('placeBlocksOnDays: 2일은 시작 다음 날이고, 뺀 장소와 why 는 없다', () => {
  const cities = [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-12' }];
  const places = [rawPlace('p1', 'Joe', 'pizza_restaurant'), rawPlace('p2', 'Cafe', 'cafe'), rawPlace('p3', 'Museum', 'museum')];
  const days = [{
    day: 2, blocks: [
      { time_label: 'evening', place_id: 'p2', sentence_ko: '', why: 'cafe · 7 Carmine St' },
      { time_label: 'morning', place_id: 'p1', sentence_ko: '창가 자리 부탁해요.', why: 'pizza_restaurant · 7 Carmine St' },
      { time_label: 'afternoon', place_id: 'p3', sentence_ko: '입장권 두 장 주세요.', why: 'museum · 7 Carmine St' },
    ],
  }];
  const folded = AI.foldItinerary(cities, [{ error: null, body: { status: 'verified', reason: '', places, days, queries: [] } }], { '뉴욕': 1 });
  assert.equal(folded.mode, 'live');
  assert.equal(folded.meta['뉴욕'].base, 3);
  folded.places.find(p => p.providerId === 'p3').selected = false;
  const shells = [
    { date: '2026-11-10', city: '뉴욕', types: ['arrival'], cap: { attr: 1, rest: 1 }, placeIds: ['old'] },
    { date: '2026-11-11', city: '뉴욕', types: ['normal'], cap: { attr: 2, rest: 2 }, placeIds: [] },
    { date: '2026-11-12', city: '뉴욕', types: ['departure'], cap: { attr: 1, rest: 1 }, placeIds: [] },
  ];
  const out = AI.placeBlocksOnDays(shells, folded.places, cities, folded.blocksByCity);
  const day2 = out.find(d => d.date === '2026-11-11');
  assert.deepEqual(day2.blocks.map(b => b.time), ['morning', 'evening']);
  assert.equal(day2.blocks[0].ko, '창가 자리 부탁해요.');
  assert.equal(day2.blocks[1].ko, '');
  assert.equal(day2.blocks.some(b => 'why' in b), false);
  assert.equal(out.some(d => d.placeIds.includes(folded.places.find(p => p.providerId === 'p3').id)), false);
  assert.equal(shells[0].placeIds[0], 'old');
  const joe = folded.places.find(p => p.providerId === 'p1');
  assert.equal(joe.visitDate, '2026-11-11');
});

test('collectItinerary: /itinerary 만 부르고 실패한 도시는 나머지를 지우지 않는다', async () => {
  const bodies = [];
  const fetchImpl = async (url, opt) => {
    const body = JSON.parse(opt.body);
    bodies.push({ url, body });
    if (body.city === '보스턴') throw new Error('network');
    return { ok: true, json: async () => ({ status: 'unavailable', reason: 'itinerary_disabled' }) };
  };
  const cities = [
    { name: '뉴욕', start: '2026-11-10', end: '2026-11-12' },
    { name: '보스턴', start: '2026-11-12', end: '2026-11-14' },
  ];
  const out = await AI.collectItinerary({ fetchImpl, base: '', cities });
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0].url, '/itinerary');
  assert.equal('category_id' in bodies[0].body, false);
  assert.deepEqual(bodies[0].body.itinerary_kinds, ['restaurant', 'cafe', 'attraction']);
  assert.equal(out[0].body.reason, 'itinerary_disabled');
  assert.equal(out[1].error, 'network');
  assert.equal(AI.foldItinerary(cities, out, {}).mode, 'example');
  const offline = await AI.collectItinerary({ fetchImpl, base: null, cities });
  assert.equal(offline.every(r => r.error === 'network'), true);
});

/* ---------- 대화하기 1a (스크립트 회화) ---------- */
const TALK_ASK = { ask: { en: 'Would you like chicken or beef?', ko: '치킨과 소고기 중?' }, nextFor: 1,
  replies: [{ en: 'Here you are.', ko: '여기요.' }, { en: "Sorry, we're out of chicken. Is beef okay?", ko: '떨어졌어요.' }], next: { en: 'Beef is fine, thank you.', ko: '소고기 좋아요.' } };
const ME = { en: 'Chicken, please.', ko: '치킨으로 주세요.' };

test('talkTurns: 상대가 먼저면 상대→나→상대(nextFor 갈래)→나', () => {
  const t = AI.talkTurns(TALK_ASK, ME);
  assert.deepEqual(t.map(x => x.who), ['ai', 'me', 'ai', 'me']);
  assert.deepEqual(t.map(x => x.key), ['ask', 'me', 'r1', 'next']);
  assert.equal(t[2].en, "Sorry, we're out of chicken. Is beef okay?");
});
test('talkTurns: ask 없으면 나→상대→나, nextFor 없거나 범위 밖이면 0번 갈래', () => {
  const noAsk = { replies: TALK_ASK.replies, next: TALK_ASK.next };
  assert.deepEqual(AI.talkTurns(noAsk, ME).map(x => x.key), ['me', 'r0', 'next']);
  assert.equal(AI.talkTurns({ ...noAsk, nextFor: 5 }, ME)[1].key, 'r0');
  assert.equal(AI.talkTurns({ ...noAsk, nextFor: -1 }, ME)[1].key, 'r0');
  assert.equal(AI.talkTurns({ ...noAsk, nextFor: '1' }, ME)[1].key, 'r0');
});
test('talkTurns: 데이터가 모자라면 빈 배열(대화하기 버튼을 숨긴다)', () => {
  assert.deepEqual(AI.talkTurns(null, ME), []);
  assert.deepEqual(AI.talkTurns({ replies: [], next: TALK_ASK.next }, ME), []);
  assert.deepEqual(AI.talkTurns({ replies: TALK_ASK.replies }, ME), []);
  assert.deepEqual(AI.talkTurns(TALK_ASK, { en: ' ' }), []);
});
test('talkHint: 누를 때만 한 단계씩 — 앞 상대 질문의 한국어 뜻 → 내 답 첫 단어 → 예시 답 전체', () => {
  const T = AI.talkTurns(TALK_ASK, ME);
  assert.deepEqual(AI.talkHint(T, 1, 0), []);
  assert.deepEqual(AI.talkHint(T, 1, 1), [{ kind: 'ask-ko', text: '치킨과 소고기 중?' }]);
  assert.deepEqual(AI.talkHint(T, 1, 2), [{ kind: 'ask-ko', text: '치킨과 소고기 중?' }, { kind: 'first', text: 'Chicken, …' }]);
  assert.deepEqual(AI.talkHint(T, 1, 3), [{ kind: 'ask-ko', text: '치킨과 소고기 중?' }, { kind: 'en', text: 'Chicken, please.' }]);
  assert.deepEqual(AI.talkHint(T, 1, 99), AI.talkHint(T, 1, 3));
  assert.deepEqual(AI.talkHint(T, 3, 1), [{ kind: 'ask-ko', text: '떨어졌어요.' }]);
  assert.deepEqual(AI.talkHint(T, 0, 3), [], '상대 턴에는 힌트 없음');
});
test('talkHint: 내가 먼저 말하는 턴은 1단계가 내 문장의 한국어 뜻', () => {
  const T = AI.talkTurns({ replies: TALK_ASK.replies, next: TALK_ASK.next }, ME);
  assert.deepEqual(AI.talkHint(T, 0, 1), [{ kind: 'me-ko', text: '치킨으로 주세요.' }]);
});
test('talkRepeat: 첫 Sorry? 는 더 천천히(하한 0.6, 기준보다 빨라지지 않음), 두 번째는 바꿔 말하기 신호', () => {
  assert.deepEqual(AI.talkRepeat(0.95, 0), { rate: 0.95, rephrase: false });
  assert.deepEqual(AI.talkRepeat(0.95, 1), { rate: 0.8, rephrase: false });
  assert.deepEqual(AI.talkRepeat(0.95, 2), { rate: 0.8, rephrase: true });
  assert.deepEqual(AI.talkRepeat(0.7, 1), { rate: 0.6, rephrase: false });
  assert.deepEqual(AI.talkRepeat(0.5, 1), { rate: 0.5, rephrase: false }, '이미 느리면 빨라지지 않는다');
  assert.deepEqual(AI.talkRepeat(0.8, -1), { rate: 0.8, rephrase: false });
  assert.deepEqual(AI.talkRepeat(undefined, 0), { rate: 0.8, rephrase: false });
});
test('talkSummary: 결과는 턴 key 로 찾고, 교차검증된 점수만 세며, 고칠 점은 가장 낮은 턴 하나', () => {
  const turns = AI.talkTurns(TALK_ASK, ME);
  const s = AI.talkSummary(turns, { me: { usable: true, score: 90, heard: 'chicken please', fix_one: 'A', score_kind: 'word_match' }, next: { usable: true, score: 55, heard: 'beef fine thank', fix_one: 'B', score_kind: 'word_match' } });
  assert.equal(s.myTurns, 2); assert.equal(s.spoken, 2);
  assert.deepEqual(s.lines.map(l => [l.score, l.kind]), [[90, 'word_match'], [55, 'word_match']]);
  assert.deepEqual(s.fix, { en: 'Beef is fine, thank you.', text: 'B' });
});
test('talkSummary: 제한·샘플·폐기·교차검증 실패·heard 없음·범위 밖은 점수 없음', () => {
  const turns = AI.talkTurns(TALK_ASK, ME);
  const bad = [{ limited: true }, { mock: true }, { score_discarded: true }, { cross_validated: false }, { raw: 'x' }, { heard: '' }, { score: 140 }];
  for (const b of bad) {
    const r = { usable: true, score: 40, heard: 'x', fix_one: 'Z', ...b };
    const s = AI.talkSummary(turns, { me: r });
    assert.equal(s.lines[0].score, null, JSON.stringify(b)); assert.equal(s.fix, null, JSON.stringify(b));
  }
  const none = AI.talkSummary(turns, {});
  assert.equal(none.spoken, 0); assert.equal(none.fix, null);
  assert.equal(AI.talkSummary(turns, [{ usable: true, score: 10, heard: 'x', fix_one: 'Q' }]).fix, null, '배열 위치로는 붙지 않는다');
});

test('도시 조사: 요청 본문은 나라·도시·날짜·장소 수만(사용자 정보 없음), gid·ISO2 는 있을 때만', () => {
  const trip = { countries: ['일본', '아틀란티스'], country: '일본', cities: [
    { name: '도쿄', start: '2027-03-20', end: '2027-03-23', ci: 0, gid: 1850147 },
    { name: '어딘가', start: '2027-03-23', end: '2027-03-25', ci: 1, gid: 'x' }] };
  const body = AI.researchRequestBody(trip, { '도쿄': { attr: 2, rest: 3 } }, n => (n === '일본' ? 'JP' : ''));
  assert.deepEqual(body.countries, [{ name: '일본', iso2: 'JP' }, { name: '아틀란티스' }]);
  assert.deepEqual(body.cities[0], { name: '도쿄', ci: 0, start: '2027-03-20', end: '2027-03-23', attr: 2, rest: 3, gid: 1850147 });
  assert.deepEqual(body.cities[1], { name: '어딘가', ci: 1, start: '2027-03-23', end: '2027-03-25', attr: 0, rest: 0 });
  assert.ok(!JSON.stringify(body).includes('uid'));
});

test('도시 조사: 시작 → 폴링 → 완료, 서버 재시작(404)·시간 초과·서버 없음', async () => {
  const calls = [];
  const replies = [{ status: 'running', job_id: 'abcdefghijklmnop', progress: [] },
                   { status: 'running', progress: [{ who: '도쿄', step: 'guide', state: 'done' }] },   // 서버 폴링 응답처럼 job_id 없음
                   { status: 'done', report: { quality: 'full' } }];
  const fetchImpl = async (url, opt) => { calls.push([opt.method, url]); const b = replies.shift(); return { ok: true, status: 200, json: async () => b }; };
  const seen = [];
  const res = await AI.collectResearch({ fetchImpl, base: '', body: {}, sleep: async () => {}, onProgress: p => seen.push(p.length) });
  assert.equal(res.status, 'done');
  assert.deepEqual(calls.map(c => c[0]), ['POST', 'GET', 'GET']);
  assert.equal(calls[1][1], '/research/abcdefghijklmnop');
  assert.deepEqual(seen, [0, 1]);
  const gone = await AI.collectResearch({ fetchImpl: async (u, o) => (o.method === 'POST'
    ? { ok: true, status: 202, json: async () => ({ status: 'running', job_id: 'abcdefghijklmnop' }) }
    : { ok: false, status: 404, json: async () => ({}) }), base: '', body: {}, sleep: async () => {} });
  assert.deepEqual(gone, { status: 'down', reason: 'http_404' });
  const slow = await AI.collectResearch({ fetchImpl: async () => ({ ok: true, status: 202, json: async () => ({ status: 'running', job_id: 'abcdefghijklmnop' }) }),
    base: '', body: {}, timeoutMs: 5, sleep: () => new Promise(r => setTimeout(r, 20)) });
  assert.equal(slow.status, 'timeout');
  assert.equal((await AI.collectResearch({ fetchImpl, base: null, body: {} })).status, 'down');
});

test('도시 조사 접기: 종류별 기본 caps + 후보 2, 다시 생성은 2칸 회전, area 는 늘 문자열, 실패면 example', () => {
  const pl = (i, kind) => ({ id: 'wv:JP_1:' + i, name: 'P' + i, kind, area: i % 2 ? 'Chiyoda' : undefined, desc_en: 'd',
    sources: [{ url: 'https://en.wikivoyage.org/wiki/Tokyo', title: 'Tokyo' }, { url: 'javascript:x', title: 'bad' }], homepage: 'javascript:alert(1)' });
  const report = { quality: 'full', countries: { JP: { currency: { code: 'JPY' } } }, attributions: [{ text: 'Wikivoyage' }],
    cities: [{ idx: 0, iso2: 'JP', status: 'ok', places: [0, 1, 2, 3, 4, 5].map(i => pl(i, 'attraction')).concat([pl(6, 'restaurant'), pl(7, 'cafe')]),
               practical: [{ topic: 'tipping', text_en: 'No tipping.' }], climate: { kind: 'normals' }, days: [] }] };
  const cities = [{ name: '도쿄' }];
  const f = AI.foldResearch(cities, { status: 'done', report }, { '도쿄': { attr: 2, rest: 1 } });
  assert.equal(f.mode, 'research');
  const at = f.places.filter(p => p.kind === 'attraction');
  assert.deepEqual(at.map(p => [p.name, p.selected, p.isCandidate]), [['P0', true, false], ['P1', true, false], ['P2', false, true], ['P3', false, true]]);
  assert.deepEqual(f.places.filter(p => p.kind !== 'attraction').map(p => [p.name, p.selected]), [['P6', true], ['P7', false]]);
  assert.ok(f.places.every(p => typeof p.area === 'string' && p.research && p.live));
  assert.deepEqual(f.places[0].sources, [{ url: 'https://en.wikivoyage.org/wiki/Tokyo', title: 'Wikivoyage · Tokyo' }]);
  assert.equal(f.places[0].homepage, '');                                         // 위험한 링크는 버린다
  assert.deepEqual(f.meta['도쿄'], { base: 3, found: 3, mode: 'research', total: 8 });
  assert.equal(f.info.cities['도쿄'].practical[0].topic, 'tipping');
  const again = AI.foldResearch(cities, { status: 'done', report }, { '도쿄': { attr: 2, rest: 1 } }, 1);
  assert.equal(again.places[0].name, 'P2');                                       // 다시 생성: 2칸 회전
  assert.equal(AI.foldResearch(cities, { status: 'unavailable', reason: 'research_disabled' }, {}).mode, 'example');
  assert.equal(AI.foldResearch(cities, { status: 'done', report: { ...report, quality: 'failed' } }, {}).mode, 'example');
  const none = AI.foldResearch(cities, { status: 'done', report: { ...report, cities: [{ idx: 0, status: 'empty', places: [] }] } }, {});
  assert.equal(none.mode, 'empty');
});

test('도시 조사 장소: LLM 추출 한국어 요약·이유·순위가 있으면 싣고, 없거나 이상한 값이면 비운다', () => {
  const p = AI.researchPlace({ id: 'wv:JP_1:2', name: 'Kitanomaru Park', kind: 'attraction', desc_en: 'Cherry blossoms in spring.',
    summary_ko: '봄에 벚꽃이 피는 공원이에요.', why_ko: '3월 여행에 맞아요', rank: 1 }, '도쿄', 1);
  assert.deepEqual([p.desc, p.reason, p.rank, p.descEn], ['봄에 벚꽃이 피는 공원이에요.', '3월 여행에 맞아요', 1, 'Cherry blossoms in spring.']);
  const q = AI.researchPlace({ id: 'x', name: 'Q', kind: 'attraction', summary_ko: { bad: 1 }, why_ko: 5, rank: '1' }, '도쿄', 2);
  assert.deepEqual([q.desc, q.reason, q.rank], ['', '', 0]);
});

test('도시 조사 장소: 대체 소스(Wikidata·Wikipedia·OSM) 출처 이름과 라이선스를 provider 별로', () => {
  const p = AI.researchPlace({ id: 'wd:JP_1:Q1', name: 'Todai-ji', kind: 'attraction', sources: [
    { provider: 'wikidata', url: 'https://www.wikidata.org/wiki/Q1', title: 'Todai-ji' },
    { provider: 'wikipedia', url: 'https://en.wikipedia.org/wiki/Todai-ji', title: 'Todai-ji' }] }, '나라', 1);
  assert.deepEqual(p.sources.map(s => s.title), ['Wikidata · Todai-ji', 'Wikipedia · Todai-ji']);
  assert.equal(p.attribution, 'Wikidata (CC0) · Wikipedia (CC BY-SA 4.0)');
  const o = AI.researchPlace({ id: 'osm:x', name: 'Cafe', kind: 'cafe', sources: [{ provider: 'osm', url: 'https://www.openstreetmap.org/node/1', title: 'Cafe' }] }, '나라', 2);
  assert.equal(o.attribution, '© OpenStreetMap contributors (ODbL)');
  const old = AI.researchPlace({ id: 'wv:1', name: 'X', kind: 'attraction', sources: [{ url: 'https://en.wikivoyage.org/wiki/X', title: 'X' }] }, '나라', 3);
  assert.equal(old.attribution, 'Wikivoyage (CC BY-SA 4.0)');                    // provider 없는 예전 보고서
});
