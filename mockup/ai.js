/* AI 연동 순수 함수 모음 — 화면(app.js)과 분리해서 Node 로 테스트한다 (ai.test.js).
   DOM 에 의존하지 않는다. 브라우저에서는 window.AI 로, Node 에서는 module.exports 로 노출된다. */
(function (root) {
  'use strict';

  const WEAK_KEY = 'cd_weak';
  /* 말하기 연습 동의. 문구를 바꾸면 CONSENT_VERSION 을 올려 다시 동의를 받는다. */
  const CONSENT_KEY = 'cd_consent';
  const CONSENT_VERSION = 7;   // v2 Gemini 무료 등급·민감정보 / v3 2단계 처리 / v4 서버 VAD + 전용 STT / v5 교차검증 전송 / v6 말소리 재확인은 서버 안(pyannoteAI 미전송) / v7 계정에 올리는 것에 여행 설정 포함
  /* 임시 제품 규칙: 이 점수 미만이면 "취약 상황" 후보로 저장한다. 검증된 학습 기준이 아니다. */
  const WEAK_THRESHOLD = 70;
  /* 참고 신호: 들린 문장이 목표 문장의 단어를 이 비율 미만으로 담으면 "다르게 들렸어요"로 표시한다 (저장 판정에 쓰지 않음). */
  const HEARD_MATCH_MIN = 0.8;
  const MAX_AUDIO_BYTES = 1024 * 1024; // backend/app/main.py MAX_AUDIO_BYTES 와 같다(10/23: 8MB → 1MB, 30초 녹음은 1MB 안)
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
  async function generateByCity({ fetchImpl, base, cities, weakIds, signal, timeoutMs = GEN_TIMEOUT_MS, categoryId, placeType }) {
    const allFallback = () => cities.map(c => ({ city: c.name, categoryId: c.categoryId, kind: 'fallback', pools: null }));
    if (base === null || base === undefined) return allFallback();
    const t = withTimeout(signal, timeoutMs);        // /health 와 /generate 가 하나의 제한 시간을 공유한다
    try {
      // /health 로 서버를 깨우고, 이 카테고리의 현재 유효한 상황 id 만 취약 상황으로 보낸다.
      let health;
      try { health = await httpJson(fetchImpl, base + '/health', {}, t.signal); } catch (e) { return allFallback(); }
      // 카테고리는 도시마다 장소에서 끌어낸다(없으면 인자, 그다음 restaurant).
      const jobs = cities.map(c => {
        const cat = c.categoryId || categoryId || categoryOfKind(c.placeType) || categoryOfKind(placeType) || 'restaurant';
        const valid = health && health.situations && Array.isArray(health.situations[cat]) ? health.situations[cat] : null;
        const weak = valid ? weakIds.filter(w => valid.includes(w)) : weakIds;
        return postJson(fetchImpl, base + '/generate', {
          category_id: cat, city: c.name,
          places: c.places.map(p => ({ name: p.en || p.name, place_type: p.kind || cat })),
          weak_expressions: weak,
        }, t.signal);
      });
      return collect(cities, await Promise.allSettled(jobs));
    } finally { t.done(); }
  }
  function collect(cities, settled) {
    return settled.map((r, i) => {
      const c = cities[i];
      const base = { city: c.name, categoryId: c.categoryId };
      if (r.status !== 'fulfilled') return { ...base, kind: 'fallback', pools: null };
      const n = normalizeAiResponse(r.value);
      if (n.kind === 'fallback') return { ...base, kind: 'fallback', pools: null };
      return { ...base, kind: n.kind, pools: buildPools(n.sentences, c.places) };
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
  /* uid 가 없으면 기존 키 그대로. 있으면 같은 키에 ':uid' 를 붙인다. 테마·배너는 이 함수를 쓰지 않는다. */
  function scopedStorage(storage, uid) {
    if (!storage) return null;
    if (typeof uid !== 'string' || !uid) return storage;
    const suffix = ':' + uid;
    return {
      getItem(key) { return storage.getItem(String(key) + suffix); },
      setItem(key, value) { return storage.setItem(String(key) + suffix, value); },
      removeItem(key) { return storage.removeItem(String(key) + suffix); },
    };
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

  /* ---------- 여행 입력 저장 (온보딩 1단계) ----------
     진도·복습·동의와 같은 계정 칸에 둔다. 담는 것은 입력뿐이고, 장소·문장 본문은 담지 않는다 —
     화면이 이 입력으로 규칙을 다시 돌려 같은 계획을 만든다. 서버(backend/app/user_state.py `_trip`)와 규칙이 같다. */
  const TRIP_KEY = 'cd_trip';
  const TRIP_DATE = /^\d{4}-\d{2}-\d{2}$/;
  function cleanTrip(trip) {
    if (!trip || typeof trip !== 'object') return null;
    const country = typeof trip.country === 'string' ? trip.country.trim() : '';
    if (!country || country.length > 80) return null;
    if (!Array.isArray(trip.cities) || trip.cities.length < 1 || trip.cities.length > 5) return null;
    /* 여러 나라(최대 4): countries[0] 은 country 와 같고, 도시마다 ci(속한 나라 순번)를 둔다.
       나라가 하나면 예전 모양(countries·ci 없음)으로 저장한다 — 예전 서버·예전 기록과 그대로 맞는다. */
    let countries = [country];
    if (trip.countries !== undefined) {
      if (!Array.isArray(trip.countries) || trip.countries.length < 1 || trip.countries.length > 4) return null;
      countries = trip.countries.map(n => (typeof n === 'string' ? n.trim() : ''));
      if (countries.some(n => !n || n.length > 80) || countries[0] !== country) return null;
    }
    const multi = countries.length > 1;
    const cities = [];
    for (const c of trip.cities) {
      if (!c || typeof c !== 'object') return null;
      const name = typeof c.name === 'string' ? c.name.trim() : '';
      if (!name || name.length > 80) return null;
      if (typeof c.start !== 'string' || !TRIP_DATE.test(c.start)) return null;
      if (typeof c.end !== 'string' || !TRIP_DATE.test(c.end)) return null;
      const ci = c.ci === undefined ? 0 : c.ci;
      if (!Number.isInteger(ci) || ci < 0 || ci >= countries.length) return null;
      const city = multi ? { name: name, start: c.start, end: c.end, ci: ci } : { name: name, start: c.start, end: c.end };
      // GeoNames id(목록에서 고른 도시) — 있으면 지킨다. 규칙 밖이면 여행을 버리지 않고 이 칸만 뺀다(이름으로도 찾을 수 있다)
      if (Number.isInteger(c.gid) && c.gid > 0 && c.gid < 2 ** 31) city.gid = c.gid;
      cities.push(city);
    }
    if (multi && countries.some((_, i) => !cities.some(c => c.ci === i))) return null;   // 도시 없는 나라는 없다
    const studyStart = trip.studyStart;
    if (typeof studyStart !== 'string' || !TRIP_DATE.test(studyStart)) return null;
    return multi ? { country: country, countries: countries, cities: cities, studyStart: studyStart }
      : { country: country, cities: cities, studyStart: studyStart };
  }
  function loadTrip(storage) {
    try { return cleanTrip(JSON.parse(storage.getItem(TRIP_KEY) || 'null')); } catch (e) { return null; }
  }
  function saveTrip(storage, trip) {
    const clean = cleanTrip(trip);
    try {
      if (clean) storage.setItem(TRIP_KEY, JSON.stringify(clean));
      else storage.removeItem(TRIP_KEY);
      return true;
    } catch (e) { return false; }
  }
  /* 서버 문서가 여행 입력을 갖고 있으면 서버가 이긴다.
     서버 값이 없거나 규칙 밖이면 이 브라우저 입력을 남긴다.
     예전 문서는 trip 칸이 없어 null 로 읽히므로, 그 null 이 방금 저장한 여행을 지우면 안 된다. */
  function preferTrip(remoteTrip, localTrip) {
    return cleanTrip(remoteTrip) || cleanTrip(localTrip);
  }

  /* 장소 종류 → 카테고리 계약 id. 서버 계약(agent_contract/categories/*.json)의 place_types 와 맞춘다.
     화면에 카테고리를 박아두지 않고 장소에서 끌어낸다. 계약에 없는 종류는 null(생성 대상 아님). */
  const KIND_CATEGORY = {
    restaurant: 'restaurant', cafe: 'restaurant',
    airport: 'transport', train_station: 'transport', bus_station: 'transport',
    subway_station: 'transport', taxi_stand: 'transport',
    hotel: 'lodging', hostel: 'lodging', guesthouse: 'lodging', airbnb: 'lodging',
  };
  function categoryOfKind(kind) { return KIND_CATEGORY[String(kind == null ? '' : kind).trim().toLowerCase()] || null; }

  /* 요청에는 해당 카테고리의 취약 상황 id 만 보낸다 (서버가 현재 유효한 id 로 다시 거른다). */
  function weakIdsFor(list, categoryId) {
    const cats = Array.isArray(categoryId) ? categoryId : [categoryId];
    const ids = [];
    cats.forEach(cat => cleanWeak(list).forEach(w => {
      if (w.category_id === cat && ids.indexOf(w.id) < 0) ids.push(w.id);
    }));
    return ids;
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
    // 교차검증을 못 한 결과(제한 모드)는 점수가 오더라도 자동 저장하지 않는다. 사용자가 고를 때만 저장.
    if (res.cross_validated === false) return 'ask';
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
  /* 서버가 말소리 검출(Silero VAD) → 전사(전용 STT) → 피드백(AI)을 한다. situation 은 피드백 AI 가 맥락을 알도록 보낸다. */
  async function speakCheck({ fetchImpl, base, blob, target, situation = '', signal, timeoutMs = 90 * 1000 }) {
    if (base === null || base === undefined) throw new Error('no-api');
    if (!blob || !blob.size) throw new Error('empty-audio');
    if (blob.size > MAX_AUDIO_BYTES) throw new Error('too-large');
    const mime = blob.type || 'audio/webm';
    const fd = new FormData();
    fd.append('target', target);
    fd.append('situation', String(situation || '').slice(0, 120));
    fd.append('file', blob, 'speech.' + extFor(mime));
    const t = withTimeout(signal, timeoutMs);
    try { return await httpJson(fetchImpl, base + '/speak-check', { method: 'POST', body: fd }, t.signal); }
    finally { t.done(); }
  }


  /* ---------- 인앱 브라우저 감지 ----------
     카톡·네이버·인스타 등 앱 안 웹뷰는 마이크(getUserMedia)·MediaRecorder·음성 합성이 막히거나 불안정할 수 있다.
     UA 문자열 기반의 추정이며 기기별 동작은 실기기 검증 전이다. 안내 문구 결정에만 쓰고 기능 판단은 기능 감지로 따로 한다.
     반환: null(일반 브라우저로 보임) | { name, os, scheme } — scheme 은 외부 브라우저로 여는 링크를 만들 수 있는 경우만. */
  function inAppBrowser(ua, url) {
    ua = String(ua || '');
    const ios = /iPhone|iPad|iPod/i.test(ua);
    const android = /Android/i.test(ua);
    const os = ios ? 'ios' : android ? 'android' : 'other';
    const named = [
      [/KAKAOTALK/i, '카카오톡'], [/NAVER\(inapp|NAVER\/|; naver/i, '네이버'], [/Instagram/i, '인스타그램'],
      [/FBAN|FBAV|FB_IAB/i, '페이스북'], [/\bLine\//i, '라인'], [/DaumApps/i, '다음'], [/Band\//i, '밴드'], [/everytimeApp/i, '에브리타임'],
    ].find(([re]) => re.test(ua));
    /* 이름이 없어도 웹뷰 흔적이면 일반 안내: Android 는 "; wv)", iOS 는 Safari 토큰이 없는 WebKit */
    const generic = !named && ((android && /; wv\)/.test(ua)) || (ios && /AppleWebKit/i.test(ua) && !/Safari\//i.test(ua) && !/CriOS|FxiOS|EdgiOS/i.test(ua)));
    if (!named && !generic) return null;
    const name = named ? named[1] : '앱 안';
    let scheme = null;
    if (url && /^https?:\/\//i.test(url)) {
      const u = new URL(url);
      if (named && named[1] === '카카오톡') scheme = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(url);
      else if (named && named[1] === '라인') { u.searchParams.set('openExternalBrowser', '1'); scheme = u.href; }   // 해시 앞(검색어)에 붙여야 LINE 이 읽는다
      else if (android) scheme = 'intent://' + u.host + u.pathname + u.search + u.hash + '#Intent;scheme=' + u.protocol.replace(':', '') + ';package=com.android.chrome;S.browser_fallback_url=' + encodeURIComponent(url) + ';end';
    }
    return { name, os, scheme };
  }

  /* ---------- 일정 수집 (POST /itinerary) ----------
     문장 팩과 별도다. 날짜는 로컬 달력이 아니라 화면이 가진 YYYY-MM-DD 를 UTC 자정으로 센다.
     calendarToday 만 브라우저 로컬 연·월·일을 쓴다. toISOString 은 UTC 라 자정 무렵 하루가 밀린다. */
  function isoDay(s) {
    const [y, m, d] = String(s || '').split('-').map(Number);
    if (!y || !m || !d) return NaN;
    return Date.UTC(y, m - 1, d);
  }
  function isoAdd(s, n) {
    const t = isoDay(s);
    if (!Number.isFinite(t)) return '';
    return new Date(t + n * 864e5).toISOString().slice(0, 10);
  }
  function isoDiff(a, b) {
    const x = isoDay(a), y = isoDay(b);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return NaN;
    return Math.round((x - y) / 864e5);
  }
  function calendarToday(now) {
    const n = now instanceof Date ? now : new Date();
    const m = String(n.getMonth() + 1).padStart(2, '0');
    const d = String(n.getDate()).padStart(2, '0');
    return n.getFullYear() + '-' + m + '-' + d;
  }
  const ITINERARY_KINDS = ['restaurant', 'cafe', 'attraction'];
  function itineraryRequestBody(city) {
    const days = isoDiff(city && city.end, city && city.start) + 1;
    return {
      city: String(city && city.name || '').trim(),
      days: Number.isFinite(days) ? days : 0,
      start_date: (city && city.start) || '',
      itinerary_kinds: ITINERARY_KINDS.slice(),
    };
  }
  /* primary_type 은 서버가 준 영어 값이다. 계약에 없는 종류는 관광지로 두어 문장 생성에 넣지 않는다. */
  function kindFromPrimary(primary) {
    const t = String(primary || '').trim().toLowerCase();
    if (t === 'cafe' || t.endsWith('_cafe') || t === 'coffee_shop') return 'cafe';
    if (t === 'restaurant' || t.endsWith('_restaurant') || t === 'meal_takeaway' || t === 'meal_delivery' || t === 'bakery' || t === 'bar') return 'restaurant';
    return 'attraction';
  }
  function livePlace(raw, cityName, n) {
    const data = raw && raw.data && typeof raw.data === 'object' ? raw.data : {};
    const providerId = String(raw.provider_id);
    const name = String(raw.name || '').trim();
    const primary = typeof data.primary_type === 'string' ? data.primary_type : '';
    const address = typeof data.formatted_address === 'string' ? data.formatted_address : '';
    const url = typeof raw.source_url === 'string' ? raw.source_url : '';
    return {
      id: 'g' + n,
      providerId, city: cityName, kind: kindFromPrimary(primary), live: true,
      name, en: name, area: address, desc: '', reason: '',
      cuisine: null, menuEn: null, menuKo: null,
      sources: url ? [{ url, title: 'Google Maps' }] : [],
      primaryType: primary,
      attribution: typeof raw.attribution === 'string' && raw.attribution ? raw.attribution : 'Google Maps',
      fetchedAt: typeof raw.fetched_at === 'string' ? raw.fetched_at : '',
      isCandidate: false, selected: false, visitDate: null, visitOrder: null, count: 0,
    };
  }
  function classifyItinerary(result) {
    const empty = { places: [], days: [], queries: [] };
    if (!result || result.error || !result.body || typeof result.body !== 'object') return { kind: 'down', reason: 'network', ...empty };
    const body = result.body;
    const reason = typeof body.reason === 'string' ? body.reason : '';
    const queries = Array.isArray(body.queries) ? body.queries : [];
    if (reason === 'itinerary_disabled') return { kind: 'disabled', reason, ...empty };
    const places = Array.isArray(body.places) ? body.places.filter(p => p && typeof p.provider_id === 'string' && p.provider_id && typeof p.name === 'string' && p.name.trim()) : [];
    const days = Array.isArray(body.days) ? body.days : [];
    if (!places.length) return { kind: 'empty', reason: reason || 'no_verified_places', places: [], days: [], queries };
    return { kind: 'live', reason, places, days, queries };
  }
  function dayHasBlock(days) {
    return (days || []).some(d => Array.isArray(d.blocks) && d.blocks.some(b => b && b.place_id));
  }
  /* 모든 도시가 플래그 꺼짐이거나 네트워크 실패면 example. 확인된 장소가 없으면 empty. 한 도시라도 있으면 live.
     빈 도시는 예시 장소로 채우지 않는다. 하루 블록이 하나도 없으면 blocksByCity 는 null 이다. */
  function foldItinerary(cities, results, caps) {
    const rows = (cities || []).map((city, i) => ({ city, outcome: classifyItinerary(results && results[i]) }));
    if (!rows.length || rows.every(r => r.outcome.kind === 'disabled' || r.outcome.kind === 'down')) {
      return { mode: 'example', places: [], meta: {}, blocksByCity: null };
    }
    const places = [];
    const meta = {};
    const blocksByCity = {};
    let seq = 0;
    let anyBlock = false;
    rows.forEach(r => {
      const name = r.city.name;
      const o = r.outcome;
      if (o.kind !== 'live') {
        meta[name] = { base: 0, found: 0, mode: o.kind === 'disabled' ? 'disabled' : 'empty', reason: o.reason, queries: o.queries };
        blocksByCity[name] = [];
        return;
      }
      const mapped = o.places.map(p => livePlace(p, name, ++seq));
      const hasBlocks = dayHasBlock(o.days);
      if (hasBlocks) anyBlock = true;
      const cap = caps && Number(caps[name]);
      const limit = Number.isFinite(cap) && cap > 0 ? cap : mapped.length;
      const base = hasBlocks ? mapped.length : Math.min(mapped.length, limit);
      mapped.forEach((p, i) => { p.selected = i < base; });
      places.push(...mapped);
      meta[name] = { base, found: mapped.length, mode: 'live', reason: o.reason, queries: o.queries };
      blocksByCity[name] = o.days;
    });
    return {
      mode: places.length ? 'live' : 'empty',
      places, meta,
      blocksByCity: anyBlock ? blocksByCity : null,
    };
  }
  const BLOCK_ORDER = { morning: 0, afternoon: 1, evening: 2 };
  /* 서버 day 는 1부터다. n 은 그 도시 시작일 + (n-1) 이다. 선택을 끈 장소의 블록은 뺀다. why 는 복사하지 않는다. */
  function placeBlocksOnDays(days, places, cities, blocksByCity) {
    const out = (days || []).map(d => ({ ...d, cap: { attr: d.cap.attr, rest: d.cap.rest }, placeIds: [], blocks: [] }));
    const byProvider = {};
    (places || []).forEach(p => { if (p && p.providerId) byProvider[p.providerId] = p; });
    const placed = new Set();
    (cities || []).forEach(city => {
      const rows = out.filter(d => d.city === city.name);
      const byDate = {};
      rows.forEach(d => { byDate[d.date] = d; });
      const serverDays = (blocksByCity && blocksByCity[city.name]) || [];
      serverDays.forEach(day => {
        const n = Number(day && day.day);
        if (!Number.isFinite(n)) return;
        const row = byDate[isoAdd(city.start, n - 1)];
        if (!row) return;
        const blocks = (Array.isArray(day.blocks) ? day.blocks : []).slice()
          .sort((a, b) => (BLOCK_ORDER[a.time_label] ?? 9) - (BLOCK_ORDER[b.time_label] ?? 9));
        blocks.forEach(block => {
          const p = byProvider[block && block.place_id];
          if (!p || !p.selected || placed.has(p.id) || p.city !== city.name) return;
          placed.add(p.id);
          row.placeIds.push(p.id);
          p.visitDate = row.date;
          p.visitOrder = row.placeIds.length;
          const ko = typeof block.sentence_ko === 'string' ? block.sentence_ko.trim() : '';
          row.blocks.push({ placeId: p.id, time: block.time_label, ko });
        });
      });
      (places || []).filter(p => p && p.selected && p.city === city.name && !placed.has(p.id)).forEach(p => {
        const row = rows[0];
        if (!row) return;
        placed.add(p.id);
        row.placeIds.push(p.id);
        p.visitDate = row.date;
        p.visitOrder = row.placeIds.length;
      });
      rows.forEach(row => {
        const room = row.cap.attr + row.cap.rest;
        if (row.placeIds.length > room) row.cap = { attr: row.placeIds.length, rest: 0 };
      });
    });
    return out;
  }
  async function collectItinerary({ fetchImpl, base, cities, signal, timeoutMs = GEN_TIMEOUT_MS }) {
    const list = cities || [];
    const down = city => ({ city: city.name, error: 'network', body: null });
    if (base === null || base === undefined) return list.map(down);
    const jobs = list.map(async city => {
      const t = withTimeout(signal, timeoutMs);
      try {
        const body = await postJson(fetchImpl, base + '/itinerary', itineraryRequestBody(city), t.signal);
        return { city: city.name, error: null, body };
      } catch (e) { return down(city); }
      finally { t.done(); }
    });
    return Promise.all(jobs);
  }

  /* ---------- 도시 조사 (POST /research → GET /research/{id}) ----------
     backend/app/research. 사용자가 고른 나라·도시를 여행 조건에 맞게 실제 소스(위키보이지·위키데이터·Open-Meteo·
     GOV.UK·Frankfurter)에서 조사한다. 서버 플래그가 꺼져 있거나 실패하면 mode 'example' — 화면은 예전 예시로 돌아간다.
     요청에는 나라·도시·날짜·장소 수만 담는다(사용자 정보 없음). */
  const RESEARCH_TIMEOUT_MS = 150000;
  /* caps: { 도시이름: { attr, rest } } (R.cityBase), isoOf: 나라 이름 → ISO2(없으면 '') */
  function researchRequestBody(trip, caps, isoOf) {
    const countries = (Array.isArray(trip.countries) && trip.countries.length ? trip.countries : [trip.country || ''])
      .map(n => String(n || '').trim()).filter(Boolean).slice(0, 4);
    const body = {
      countries: countries.map(name => { const iso2 = isoOf ? isoOf(name) : ''; return iso2 ? { name, iso2 } : { name }; }),
      cities: (trip.cities || []).slice(0, 5).map(c => {
        const cap = (caps && caps[c.name]) || {};
        const out = { name: String(c.name || '').trim(), ci: Math.min(Math.max(+c.ci || 0, 0), Math.max(0, countries.length - 1)),
          start: c.start, end: c.end, attr: Math.min(12, Math.max(0, +cap.attr || 0)), rest: Math.min(12, Math.max(0, +cap.rest || 0)) };
        if (Number.isInteger(c.gid) && c.gid > 0) out.gid = c.gid;
        return out;
      }),
    };
    return body;
  }
  /* 시작 → (전부 캐시면 바로 done) → 2.5초(10번 뒤 5초) 간격으로 진행을 묻는다. 끝나면 {status, report?, reason?}.
     잡이 사라지면(서버 재시작 404) 'down'. 시간이 넘으면 'timeout' — 서버 잡은 계속 돌아 캐시를 데운다. */
  async function collectResearch({ fetchImpl, base, body, signal, timeoutMs = RESEARCH_TIMEOUT_MS, onProgress, sleep }) {
    if (base === null || base === undefined) return { status: 'down', reason: 'no_server' };
    const wait = sleep || (ms => new Promise(r => setTimeout(r, ms)));
    const t = withTimeout(signal, timeoutMs);
    try {
      let res = await postJson(fetchImpl, base + '/research', body, t.signal);
      const jid = res && typeof res.job_id === 'string' ? res.job_id : '';   // 폴링 응답에는 job_id 가 없다 — 처음 것을 쓴다
      for (let n = 0; res && res.status === 'running' && jid; n++) {
        if (onProgress) { try { onProgress(res.progress || []); } catch (e) { /* 표시만 */ } }
        await wait(n < 10 ? 2500 : 5000);
        if (t.signal.aborted) return { status: 'timeout' };
        res = await httpJson(fetchImpl, base + '/research/' + encodeURIComponent(jid), { method: 'GET' }, t.signal);
      }
      return res && typeof res === 'object' ? res : { status: 'down' };
    } catch (e) {
      return { status: t.signal.aborted ? 'timeout' : 'down', reason: e && e.status ? 'http_' + e.status : 'network' };
    } finally { t.done(); }
  }
  const RESEARCH_KIND_KO = { attraction: '관광지', restaurant: '맛집', cafe: '카페' };
  // 장소 출처(대체 소스 체인): 링크 앞 이름과 라이선스 표기. 모르는 값은 위키보이지로 본다(예전 보고서 호환).
  const RESEARCH_PROVIDER = {
    wikivoyage: ['Wikivoyage', 'Wikivoyage (CC BY-SA 4.0)'], wikidata: ['Wikidata', 'Wikidata (CC0)'],
    wikipedia: ['Wikipedia', 'Wikipedia (CC BY-SA 4.0)'], osm: ['OpenStreetMap', '© OpenStreetMap contributors (ODbL)'],
  };
  function researchPlace(raw, cityName, n) {
    const name = String(raw.name || '').trim();
    const prov = s => RESEARCH_PROVIDER[s && s.provider] || RESEARCH_PROVIDER.wikivoyage;
    const okSrc = (Array.isArray(raw.sources) ? raw.sources : []).filter(s => s && /^https:\/\//.test(s.url || ''));
    const src = okSrc.map(s => ({ url: s.url, title: prov(s)[0] + ' · ' + String(s.title || '').slice(0, 60) }));
    const attribution = [...new Set((okSrc.length ? okSrc : [{}]).map(s => prov(s)[1]))].join(' · ');
    const home = typeof raw.homepage === 'string' && /^https?:\/\/[^\s"'<>]+$/.test(raw.homepage) ? raw.homepage : '';
    return {
      id: 'r' + n, providerId: String(raw.id || ''), city: cityName, kind: RESEARCH_KIND_KO[raw.kind] ? raw.kind : 'attraction',
      live: true, research: true, name, en: name,
      area: typeof raw.area === 'string' ? raw.area : '',                 // R.placeByCode 가 localeCompare 한다 — 늘 문자열
      // 한국어 요약·이유는 LLM 추출이 검증을 통과했을 때만 온다(없으면 영어 원문만)
      desc: typeof raw.summary_ko === 'string' ? raw.summary_ko : '', descEn: typeof raw.desc_en === 'string' ? raw.desc_en : '',
      reason: typeof raw.why_ko === 'string' ? raw.why_ko : '', rank: Number.isInteger(raw.rank) ? raw.rank : 0,
      cuisine: null, menuEn: null, menuKo: null, sources: src, homepage: home,
      attribution, primaryType: RESEARCH_KIND_KO[raw.kind] || '관광지',
      isCandidate: false, selected: false, visitDate: null, visitOrder: null, count: 0,
    };
  }
  /* 조사 보고서 → 화면 장소. 종류(관광지 / 맛집·카페)마다 기본 caps 개 + 후보 2개(genReport 와 같은 규칙),
     '다시 생성'(round)은 순위를 2칸씩 돌린다(추가 호출 없음). 도시 순서는 요청 순서(idx)로 맞춘다. */
  function foldResearch(cities, result, caps, round = 0) {
    const rep = result && result.status === 'done' && result.report && typeof result.report === 'object' ? result.report : null;
    if (!rep || !Array.isArray(rep.cities) || rep.quality === 'failed') {
      return { mode: 'example', places: [], meta: {}, info: null, reason: (result && (result.reason || result.status)) || 'down' };
    }
    const rot = (a, k) => { if (!a.length) return a; k = k % a.length; return a.slice(k).concat(a.slice(0, k)); };
    const places = [], meta = {}, info = { countries: rep.countries || {}, cities: {}, attributions: rep.attributions || [] };
    let seq = 0;
    (cities || []).forEach((c, i) => {
      const rc = rep.cities.find(x => x && x.idx === i) || rep.cities[i];
      const cap = (caps && caps[c.name]) || { attr: 0, rest: 0 };
      if (!rc) { meta[c.name] = { base: 0, found: 0, mode: 'empty', reason: 'no_city' }; return; }
      info.cities[c.name] = { practical: rc.practical || [], climate: rc.climate || null, days: rc.days || [], iso2: rc.iso2 || '',
        wikivoyage: rc.wikivoyage || null, resolved: !!rc.resolved, crossBorder: !!rc.cross_border_next };
      const raw = (Array.isArray(rc.places) ? rc.places : []).filter(p => p && typeof p.name === 'string' && p.name.trim());
      let found = 0;
      const take = (list, need) => rot(list, round * 2).slice(0, need + 2).forEach((p, k) => {
        const pl = researchPlace(p, c.name, ++seq);
        pl.isCandidate = k >= need; pl.selected = !pl.isCandidate;
        if (!pl.isCandidate) found++;
        places.push(pl);
      });
      take(raw.filter(p => p.kind === 'attraction'), +cap.attr || 0);
      take(raw.filter(p => p.kind === 'restaurant' || p.kind === 'cafe'), +cap.rest || 0);
      const base = (+cap.attr || 0) + (+cap.rest || 0);
      // 장소 0곳 도시: 이유(outage 소스 장애 · no_coords 위치 모름 · no_sources 자료 없음)를 서버가 알려 준다(예전 보고서는 status 로 추정).
      // base 는 일정이 정한 수 그대로 — 사용자가 직접 추가한 장소를 고를 수 있게.
      meta[c.name] = raw.length ? { base, found, mode: 'research', total: raw.length, stale: !!rc.stale, placeStatus: rc.place_status || '' }
        : { base, found: 0, mode: 'empty', stale: !!rc.stale,
            reason: rc.none_reason || (rc.status === 'partial' ? 'no_places' : 'no_article') };
    });
    return { mode: places.length ? 'research' : 'empty', places, meta, info, reason: '' };
  }

  /* ---------- 대화하기 (실시간 회화 1a — 스크립트, AI 호출 0회) ----------
     docs/research/realtime-agent/README.md 4절 1a · 3절 Must. 대사는 data.js 의 검수된 talk 만 쓴다.
     - 상대가 먼저(ask)가 있으면 상대 → 나 → 상대(replies[nextFor]) → 나(next). 없으면 나 → 상대 → 나.
     - nextFor 는 '내가 이어서(next)' 가 자연스럽게 이어지는 갈래다(6절 ⑤). 없거나 범위를 벗어나면 0.
     - 대화 중에는 점수를 보이지 않는다. 끝난 뒤 고칠 점은 한 가지만(talkSummary). */
  function talkTurns(talk, me) {
    if (!talk || !Array.isArray(talk.replies) || !talk.replies.length || !talk.next || !me || !str(me.en)) return [];
    const k = Number.isInteger(talk.nextFor) && talk.nextFor >= 0 && talk.nextFor < talk.replies.length ? talk.nextFor : 0;
    const t = [];
    if (talk.ask) t.push({ who: 'ai', key: 'ask', en: talk.ask.en, ko: talk.ask.ko });
    t.push({ who: 'me', key: 'me', en: me.en, ko: me.ko || '' });
    t.push({ who: 'ai', key: 'r' + k, en: talk.replies[k].en, ko: talk.replies[k].ko });
    t.push({ who: 'me', key: 'next', en: talk.next.en, ko: talk.next.ko });
    return t;
  }
  /* 힌트는 누를 때만 한 단계씩(조사 3절 Must): 0 없음 → 1 바로 앞 상대 질문의 한국어 뜻 → 2 내 답의 첫 단어 → 3 예시 답 전체.
     내가 먼저 말하는 턴(앞에 상대 턴이 없음)이면 1단계는 내 문장의 한국어 뜻으로 대신한다. */
  const TALK_HINT_MAX = 3;
  function talkHint(turns, idx, level) {
    const turn = (turns || [])[idx];
    if (!turn || turn.who !== 'me') return [];
    const n = Math.max(0, Math.min(TALK_HINT_MAX, Math.trunc(Number(level)) || 0));
    const prev = idx > 0 ? turns[idx - 1] : null;
    const out = [];
    if (n >= 1) {
      if (prev && prev.who === 'ai' && str(prev.ko)) out.push({ kind: 'ask-ko', text: prev.ko });
      else if (str(turn.ko)) out.push({ kind: 'me-ko', text: turn.ko });
    }
    if (n === 2) out.push({ kind: 'first', text: String(turn.en).trim().split(/\s+/)[0] + ' …' });
    if (n >= 3) out.push({ kind: 'en', text: turn.en });
    return out;
  }
  /* "Sorry?" — 처음은 같은 대사를 0.15 더 천천히(하한 0.6, 기준보다 빨라지지 않음).
     두 번째부터는 조사 3절이 '검수된 쉬운 말로 바꿔 말하기'를 요구한다. 1a 데이터에는 쉬운 말 필드가 없어서
     rephrase:true 로 알리고, 화면은 영어 자막과 한국어 뜻을 함께 펼친다(쉬운 말 데이터는 후속). */
  function talkRepeat(base, again) {
    const b = Number.isFinite(base) && base > 0 ? base : 0.8;
    const n = Math.max(0, Math.trunc(Number(again)) || 0);
    if (!n) return { rate: b, rephrase: false };
    const slow = Math.round((b - 0.15) * 100) / 100;
    return { rate: Math.min(b, Math.max(0.6, slow)), rephrase: n >= 2 };
  }
  /* 끝난 뒤 요약. results 는 턴 key('me'·'next') → /speak-check 응답(녹음 없이 넘김·서버 없음은 빈 칸).
     점수는 weakDecision 과 같은 기준으로 교차검증된 것만 센다. 고칠 점은 점수가 가장 낮은 턴의 fix_one 하나. */
  function talkScored(r) {
    return !!r && typeof r === 'object' && r.usable === true && r.limited !== true && r.mock !== true && r.score_discarded !== true &&
      r.cross_validated !== false && !('raw' in r) && typeof r.heard === 'string' && !!r.heard.trim() &&
      typeof r.score === 'number' && Number.isFinite(r.score) && r.score >= 0 && r.score <= 100;
  }
  function talkSummary(turns, results) {
    const box = results && typeof results === 'object' ? results : {};
    const mine = (turns || []).filter(t => t.who === 'me').map(t => ({ t, r: box[t.key] || null }));
    const spoken = mine.filter(x => x.r && str(x.r.heard)).length;
    const scored = mine.filter(x => talkScored(x.r));
    const withFix = scored.filter(x => str(x.r.fix_one)).sort((a, b) => a.r.score - b.r.score);
    return {
      myTurns: mine.length,
      spoken,
      lines: mine.map(x => ({ en: x.t.en, heard: x.r && str(x.r.heard) ? x.r.heard : '',
        score: talkScored(x.r) ? Math.round(x.r.score) : null, kind: talkScored(x.r) ? x.r.score_kind || null : null })),
      fix: withFix.length ? { en: withFix[0].t.en, text: withFix[0].r.fix_one } : null,
    };
  }

  const api = {
    talkTurns, talkHint, TALK_HINT_MAX, talkRepeat, talkScored, talkSummary,
    inAppBrowser, WEAK_KEY, CONSENT_KEY, CONSENT_VERSION, loadConsent, saveConsent, withdrawConsent, WEAK_THRESHOLD, HEARD_MATCH_MIN, heardCoverage, MAX_AUDIO_BYTES, GEN_TIMEOUT_MS,
    TRIP_KEY, cleanTrip, loadTrip, saveTrip, preferTrip,
    categoryOfKind,
    calendarToday, itineraryRequestBody, kindFromPrimary, foldItinerary, placeBlocksOnDays, collectItinerary,
    RESEARCH_TIMEOUT_MS, researchRequestBody, collectResearch, researchPlace, foldResearch,
    apiBase, normalizeAiResponse, buildPools, takeForPlace, generateByCity,
    cleanWeak, upsertWeak, loadWeak, saveWeak, scopedStorage, weakIdsFor, weakReviewOf, weakDecision, shouldSaveWeak, extFor, speakCheck,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AI = api;
})(typeof window !== 'undefined' ? window : globalThis);
