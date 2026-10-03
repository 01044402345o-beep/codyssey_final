/* 실행: cd mockup && node --test
   fixture 기반 테스트다. 응답 분기·배정·저장 조건 같은 "코드의 규칙"만 확인하며,
   실제 Gemini 호출·마이크·배포 환경의 동작을 보증하지 않는다. */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const AI = require('./ai.js');

const sent = (o = {}) => ({ situation_id: 'order_menu', situation: '주문', en: 'A table for two, please.', ko: '두 명이요.', ...o });
const res = (o = {}) => ({ pack: { category_id: 'restaurant', city: 'New York', sentences: [sent()] }, issues: [], attempts: 1, mock: false, ...o });

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
  assert.equal(AI.normalizeAiResponse(res({ mock: true })).kind, 'sample');
  assert.equal(AI.normalizeAiResponse(res({ degraded: true })).kind, 'fallback');
  assert.equal(AI.normalizeAiResponse(res({ degraded: true, mock: true })).kind, 'fallback'); // 동시에 있어도 degraded 먼저
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
    const city = JSON.parse(opt.body).city;
    if (city === 'Boston') throw new Error('network');
    if (city === 'Chicago') return { ok: true, json: async () => res({ degraded: true }) };
    return { ok: true, json: async () => res({ mock: false }) };
  };
  const out = await AI.generateByCity({ fetchImpl, base: '', cities, weakIds: [] });
  assert.deepEqual(out.map(o => o.kind), ['ai', 'fallback', 'fallback']);
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
  assert.equal(out[0].kind, 'fallback'); assert.equal(calls, 1);
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
  const ok = score => AI.shouldSaveWeak(ai, { score, heard: 'x', issues: [], tip: 't' });
  assert.equal(ok(40), true);
  assert.equal(ok(69), true);
  assert.equal(ok(70), false);          // 임계값은 미만만
  assert.equal(ok(90), false);
  assert.equal(ok(null), false);
  assert.equal(ok(undefined), false);
  assert.equal(ok(NaN), false);
  assert.equal(ok(Infinity), false);
  assert.equal(ok(-5), false);
  assert.equal(ok(120), false);
  assert.equal(ok('40'), false);
  assert.equal(AI.shouldSaveWeak(ai, { score: 40, mock: true }), false);
  assert.equal(AI.shouldSaveWeak(ai, { score: 40, raw: '...' }), false);
  assert.equal(AI.shouldSaveWeak({ ...ai, ai: false }, { score: 40 }), false);
  assert.equal(AI.shouldSaveWeak({ ai: true, categoryId: 'restaurant' }, { score: 40 }), false);
  assert.equal(AI.shouldSaveWeak(ai, null), false);
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
