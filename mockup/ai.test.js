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
