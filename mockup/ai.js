/* AI 연동 순수 함수 모음 — 화면(app.js)과 분리해서 Node 로 테스트한다 (ai.test.js).
   DOM 에 의존하지 않는다. 브라우저에서는 window.AI 로, Node 에서는 module.exports 로 노출된다. */
(function (root) {
  'use strict';

  const WEAK_KEY = 'cd_weak';
  /* 말하기 연습 동의. 문구를 바꾸면 CONSENT_VERSION 을 올려 다시 동의를 받는다. */
  const CONSENT_KEY = 'cd_consent';
  const CONSENT_VERSION = 2;   // v2: Gemini 무료 등급 데이터 사용·민감정보 금지 고지 추가
  /* 임시 제품 규칙: 이 점수 미만이면 "취약 상황" 후보로 저장한다. 검증된 학습 기준이 아니다. */
  const WEAK_THRESHOLD = 70;
  /* 참고 신호: 들린 문장이 목표 문장의 단어를 이 비율 미만으로 담으면 "다르게 들렸어요"로 표시한다 (저장 판정에 쓰지 않음). */
  const HEARD_MATCH_MIN = 0.8;
  const MAX_AUDIO_BYTES = 8 * 1024 * 1024; // backend/app/main.py MAX_AUDIO_BYTES 와 같다
  const GEN_TIMEOUT_MS = 90 * 1000;
  const ID_RE = /^[a-z][a-z0-9_]*$/;

  const str = v => typeof v === 'string' && v.trim().length > 0;
  const norm = v => String(v ?? '').trim().toLowerCase();

  /* ---------- 서버 주소 ----------
     ?api=https://host 는 이번 방문에서만 쓰고 저장하지 않는다. 녹음이 전송될 서버를 바꾸므로 external 로 알린다.
     http(s) 로 열렸으면 같은 출처(''), file:// 이면 null(폴백 전용). */
  function apiBase(loc) {
    const protocol = loc.protocol || '';
    const own = protocol === 'http:' || protocol === 'https:';
    let raw = null;
    try { raw = new URLSearchParams(loc.search || '').get('api'); } catch (e) { raw = null; }
    if (raw) {
      try {
        const u = new URL(raw);
        if (u.protocol === 'http:' || u.protocol === 'https:') {
          const origin = u.origin;
          return { base: origin, external: !own || origin !== loc.origin, host: u.host };
        }
      } catch (e) { /* 잘못된 주소는 무시 */ }
    }
    if (own) return { base: '', external: false, host: loc.host || '' };
    return { base: null, external: false, host: '' };
  }

  /* ---------- 응답 해석 ----------
     검사 순서 고정: degraded → usable:'rejected' → (usable:'sample' ∧ mock:true) → (usable:'ok' ∧ mock:false) → 그 외 폴백.
     서버의 usable 판정과 mock 플래그가 서로 맞지 않으면 믿지 않고 폴백한다. */
  function validSentence(s) {
    return !!s && typeof s === 'object' && str(s.en) && str(s.ko) && str(s.situation) && typeof s.situation_id === 'string' && ID_RE.test(s.situation_id) &&
      (s.place === undefined || typeof s.place === 'string') &&
      (s.targets_weak === undefined || (Array.isArray(s.targets_weak) && s.targets_weak.every(x => typeof x === 'string')));
  }
  function normalizeAiResponse(res) {
    const fallback = { kind: 'fallback', sentences: [] };
    if (!res || typeof res !== 'object') return fallback;
    if (res.degraded || res.usable === 'rejected') return fallback;
    const pack = res.pack;
    if (!pack || typeof pack !== 'object' || typeof pack.category_id !== 'string' || !Array.isArray(pack.sentences) || !pack.sentences.length) return fallback;
    if (!pack.sentences.every(validSentence)) return fallback;
    let kind;
    if (res.mock === true && res.usable === 'sample') kind = 'sample';
    else if (res.mock === false && res.usable === 'ok') kind = 'ai';
    else return fallback;
    const sentences = pack.sentences.map(s => ({
      place: s.place || '', placeType: s.place_type || '', categoryId: pack.category_id, situationId: s.situation_id,
      situation: s.situation, en: s.en, ko: s.ko, targetsWeak: s.targets_weak || [],
    }));
    return { kind, sentences };
  }

  /* ---------- 장소 배정 ----------
     place 가 장소명/영문명과 일치하는 문장만 그 장소에. place 가 비었으면 공통 풀. 일치하지 않는 장소 문장은 버린다.
     같은 영문 문장은 한 번만 쓴다(도시·카테고리 안). */
  function buildPools(sentences, places) {
    const byPlace = {}, common = [], seen = new Set();
    places.forEach(p => (byPlace[p.id] = []));
    sentences.forEach(s => {
      const key = norm(s.en);
      if (!key || seen.has(key)) return;
      if (!s.place) { seen.add(key); common.push(s); return; }
      const hit = places.find(p => norm(p.name) === norm(s.place) || norm(p.en) === norm(s.place));
      if (!hit) return;
      seen.add(key); byPlace[hit.id].push(s);
    });
    const weakFirst = (a, b) => (b.targetsWeak.length > 0) - (a.targetsWeak.length > 0);
    Object.values(byPlace).forEach(arr => arr.sort(weakFirst));
    common.sort(weakFirst);
    return { byPlace, common };
  }
  /* 장소 전용 문장을 먼저, 부족하면 공통 풀에서(한 번 쓴 문장은 빠진다). 최대 n개. */
  function takeForPlace(pools, placeId, n) {
    const out = (pools.byPlace[placeId] || []).slice(0, n);
    while (out.length < n && pools.common.length) out.push(pools.common.shift());
    return out;
  }

  /* ---------- 생성 호출 ----------
     도시별 병렬 호출. 실패한 도시만 폴백하고 성공한 도시는 살린다. 자동 재시도 없음. */
  function withTimeout(parent, ms) {
    const ctl = new AbortController();
    const onAbort = () => ctl.abort();
    if (parent) { if (parent.aborted) ctl.abort(); else parent.addEventListener('abort', onAbort, { once: true }); }
    const timer = ms ? setTimeout(() => ctl.abort(), ms) : null;
    return { signal: ctl.signal, done() { if (timer) clearTimeout(timer); if (parent) parent.removeEventListener('abort', onAbort); } };
  }
  async function httpJson(fetchImpl, url, opt, signal) {
    const r = await fetchImpl(url, { ...opt, signal });
    if (!r.ok) { const e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
    return await r.json();
  }
  const postJson = (fetchImpl, url, body, signal) =>
    httpJson(fetchImpl, url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, signal);
  /* cities: [{ name, places:[{id,name,en}] }] → [{ city, kind, pools }] */
  async function generateByCity({ fetchImpl, base, cities, weakIds, signal, timeoutMs = GEN_TIMEOUT_MS, categoryId = 'restaurant', placeType = 'restaurant' }) {
    const allFallback = () => cities.map(c => ({ city: c.name, kind: 'fallback', pools: null }));
    if (base === null || base === undefined) return allFallback();
    const t = withTimeout(signal, timeoutMs);        // /health 와 /generate 가 하나의 제한 시간을 공유한다
    try {
      // /health 로 서버를 깨우고, 이 카테고리의 현재 유효한 상황 id 만 취약 상황으로 보낸다.
      let health;
      try { health = await httpJson(fetchImpl, base + '/health', {}, t.signal); } catch (e) { return allFallback(); }
      const valid = health && health.situations && Array.isArray(health.situations[categoryId]) ? health.situations[categoryId] : null;
      const weak = valid ? weakIds.filter(w => valid.includes(w)) : weakIds;
      const jobs = cities.map(c => postJson(fetchImpl, base + '/generate', {
        category_id: categoryId, city: c.name,
        places: c.places.map(p => ({ name: p.en || p.name, place_type: placeType })),
        weak_expressions: weak,
      }, t.signal));
      return collect(cities, await Promise.allSettled(jobs));
    } finally { t.done(); }
  }
  function collect(cities, settled) {
    return settled.map((r, i) => {
      const c = cities[i];
      if (r.status !== 'fulfilled') return { city: c.name, kind: 'fallback', pools: null };
      const n = normalizeAiResponse(r.value);
      if (n.kind === 'fallback') return { city: c.name, kind: 'fallback', pools: null };
      return { city: c.name, kind: n.kind, pools: buildPools(n.sentences, c.places) };
    });
  }

  /* ---------- 취약 상황 저장 (키: category_id + id) ---------- */
  function cleanWeak(list) {
    if (!Array.isArray(list)) return [];
    const seen = new Set(), out = [];
    list.forEach(w => {
      if (!w || typeof w !== 'object') return;
      if (!str(w.category_id) || !ID_RE.test(w.category_id) || !str(w.id) || !ID_RE.test(w.id) || w.id.startsWith('w_')) return;
      if (!str(w.situation)) return;
      const k = w.category_id + '/' + w.id;
      if (seen.has(k)) return;
      seen.add(k);
      out.push({ category_id: w.category_id, id: w.id, situation: w.situation, en: String(w.en || ''), ko: String(w.ko || ''), demo: w.demo === true });
    });
    return out;
  }
  function upsertWeak(list, item) {
    const next = cleanWeak(list).filter(w => !(w.category_id === item.category_id && w.id === item.id));
    next.push(...cleanWeak([item]));
    return next;
  }
  function loadWeak(storage) {
    try { return cleanWeak(JSON.parse(storage.getItem(WEAK_KEY) || '[]')); } catch (e) { return []; }
  }
  function saveWeak(storage, list) {
    try { storage.setItem(WEAK_KEY, JSON.stringify(cleanWeak(list))); return true; } catch (e) { return false; }
  }
  /* 동의는 '현재 버전 + voice === true + 시각' 이 모두 맞을 때만 유효하다. 손상·구버전·차단은 미동의로 본다. */
  function loadConsent(storage) {
    try {
      const c = JSON.parse(storage.getItem(CONSENT_KEY) || 'null');
      if (c && c.version === CONSENT_VERSION && c.voice === true && typeof c.at === 'string' && !Number.isNaN(Date.parse(c.at))) return { voice: true, at: c.at };
    } catch (e) { /* 손상·차단 */ }
    return { voice: false, at: null };
  }
  function saveConsent(storage, voice, now = new Date()) {
    try {
      if (voice) storage.setItem(CONSENT_KEY, JSON.stringify({ version: CONSENT_VERSION, voice: true, at: now.toISOString() }));
      else storage.removeItem(CONSENT_KEY);
      return true;
    } catch (e) { return false; }
  }
  /* 동의 철회: 동의 기록과, 동의 아래에서 쌓인 복습 목록을 함께 지운다. 둘 다 지워졌을 때만 true. */
  function withdrawConsent(storage) {
    let ok = saveConsent(storage, false);
    try { storage.removeItem(WEAK_KEY); } catch (e) { ok = false; }
    return ok;
  }

  /* 요청에는 해당 카테고리의 취약 상황 id 만 보낸다 (서버가 현재 유효한 id 로 다시 거른다). */
  function weakIdsFor(list, categoryId) {
    return cleanWeak(list).filter(w => w.category_id === categoryId).map(w => w.id);
  }
  /* 복습 표시는 AI 가 만든 문장이 저장된 (카테고리, 상황)과 모두 일치하고 그 상황을 겨냥했다고 표시했을 때만. */
  function weakReviewOf(sentence, list) {
    if (!sentence || sentence.ai !== true || !Array.isArray(sentence.targetsWeak)) return null;
    if (!sentence.targetsWeak.includes(sentence.situationId)) return null;
    return cleanWeak(list).find(w => w.category_id === sentence.categoryId && w.id === sentence.situationId) || null;
  }

  /* 목표 문장 단어 중 들린 문장에 나온 비율 (0~1). 대소문자·구두점 무시. */
  const words = t => norm(t).replace(/[^a-z0-9'\s]/g, ' ').split(/\s+/).filter(Boolean);
  function heardCoverage(target, heard) {
    const t = words(target), h = new Set(words(heard));
    if (!t.length) return 1;
    return t.filter(w => h.has(w)).length / t.length;
  }

  /* ---------- 말하기 결과 → 약점 저장 여부 ----------
     이 규칙은 "따라 말하기에서 목표 단어가 빠졌는가"를 보는 임시 저장 규칙이다. 과업 성공·발음·영어 능력 판정이 아니다.
     (heardCoverage 는 단어 포함 비율일 뿐이라 부정문 "I don't have…"을 같은 문장으로, 자연스러운 대체 표현을 누락으로 볼 수 있다.)
     공통: 서버가 쓸 수 있다고 판정(usable:true) ∧ 목업 아님 ∧ 파싱 실패·점수 폐기 아님 ∧ 들린 내용(heard) 있음 ∧ 실제 AI 문장(유효한 카테고리·상황).
     점수가 있으면: 0~100 ∧ 임계값 미만.
     점수가 없으면(모델이 생략): 자동 저장하지 않고 'ask'(사용자 선택). heardCoverage 는 그때 보여주는 참고 신호일 뿐이다.
     무음·인식 실패(heard 없음)·폐기된 점수는 'none'. 결과: 'auto' | 'ask' | 'none'. */
  function weakDecision(sentence, res) {
    if (!sentence || sentence.ai !== true || !str(sentence.categoryId) || !str(sentence.situationId)) return 'none';
    if (!ID_RE.test(sentence.categoryId) || !ID_RE.test(sentence.situationId)) return 'none';
    if (!res || typeof res !== 'object' || res.usable !== true || res.mock === true || res.score_discarded === true || 'raw' in res) return 'none';
    // 무음·인식 실패(heard 없음)는 점수가 낮게 와도 실력 부족이 아니다.
    if (typeof res.heard !== 'string' || !res.heard.trim()) return 'none';
    const s = res.score;
    // 점수가 없으면 단어 일치율만으로 자동 저장하지 않는다. 사용자에게 저장할지 묻는다 (일치율은 참고 신호).
    if (s === null || s === undefined) return 'ask';
    return typeof s === 'number' && Number.isFinite(s) && s >= 0 && s <= 100 && s < WEAK_THRESHOLD ? 'auto' : 'none';
  }
  /* 자동 저장(점수 기반 임시 규칙)만 true. 점수가 없는 경우는 weakDecision()이 'ask' 를 돌려주고 사용자가 선택한다. */
  function shouldSaveWeak(sentence, res) { return weakDecision(sentence, res) === 'auto'; }

  /* ---------- 말하기 업로드 ---------- */
  function extFor(mime) {
    const m = norm(mime).split(';')[0];
    if (m.includes('webm')) return 'webm';
    if (m.includes('ogg')) return 'ogg';
    if (m.includes('mp4') || m.includes('m4a') || m.includes('aac')) return 'm4a';
    if (m.includes('wav')) return 'wav';
    return 'webm';
  }
  async function speakCheck({ fetchImpl, base, blob, target, signal, timeoutMs = 60 * 1000 }) {
    if (base === null || base === undefined) throw new Error('no-api');
    if (!blob || !blob.size) throw new Error('empty-audio');
    if (blob.size > MAX_AUDIO_BYTES) throw new Error('too-large');
    const mime = blob.type || 'audio/webm';
    const fd = new FormData();
    fd.append('target', target);
    fd.append('file', blob, 'speech.' + extFor(mime));
    const t = withTimeout(signal, timeoutMs);
    try { return await httpJson(fetchImpl, base + '/speak-check', { method: 'POST', body: fd }, t.signal); }
    finally { t.done(); }
  }

  const api = {
    WEAK_KEY, CONSENT_KEY, CONSENT_VERSION, loadConsent, saveConsent, withdrawConsent, WEAK_THRESHOLD, HEARD_MATCH_MIN, heardCoverage, MAX_AUDIO_BYTES, GEN_TIMEOUT_MS,
    apiBase, normalizeAiResponse, buildPools, takeForPlace, generateByCity,
    cleanWeak, upsertWeak, loadWeak, saveWeak, weakIdsFor, weakReviewOf, weakDecision, shouldSaveWeak, extFor, speakCheck,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AI = api;
})(typeof window !== 'undefined' ? window : globalThis);
