/* 탈퇴 증명 파일 암호화/복호화 — AES-256-GCM + PBKDF2-HMAC-SHA256.
 *
 * 왜 앱 계층 암호화를 두는가: 증명 파일은 기기 밖으로 나가는 유일한 사본이다(사용자가
 * 메일·USB 로 옮긴다). TLS 는 전송 중만 지켜 주고, 그 뒤 파일은 평문이다. 여기서 거는
 * 암호는 '서버 통신'이 아니라 '내려받은 파일'을 지키는 용도다 — 그래서 TLS 위의 중복이 아니다.
 *
 * 형식(SEAL-PROOF-ENC-v1): { schema, kdf:{name,iterations,salt}, cipher:{name,iv}, ciphertext }
 * 모두 base64url. salt·iv 는 매번 새로 뽑는다. 반복 횟수는 파일에 적어 두어 나중에 열 수 있게 한다.
 */
(function (root) {
  var ENC_SCHEMA = 'SEAL-PROOF-ENC-v1';
  var ITER = 600000;                      // OWASP 권고 수준. 모바일에서 0.3~0.8초.

  function subtle() {
    var c = root.crypto || (typeof globalThis !== 'undefined' ? globalThis.crypto : null);
    return c && c.subtle ? c.subtle : null;
  }
  function canSeal() { return !!subtle() && typeof TextEncoder !== 'undefined'; }

  function b64e(bytes) {
    var s = '', a = new Uint8Array(bytes);
    for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
    return root.btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function b64d(str) {
    var s = String(str).replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = root.atob(s), a = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
    return a;
  }
  function deriveKey(pw, salt, iter) {
    var enc = new TextEncoder();
    return subtle().importKey('raw', enc.encode(pw), 'PBKDF2', false, ['deriveKey'])
      .then(function (base) {
        return subtle().deriveKey(
          { name: 'PBKDF2', salt: salt, iterations: iter, hash: 'SHA-256' }, base,
          { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
      });
  }

  /* 평문 객체 → 암호 봉투. 실패는 던지지 않고 {ok:false, reason} 으로 돌려준다(화면이 안내하기 쉽게). */
  function seal(obj, password) {
    if (!canSeal()) return Promise.resolve({ ok: false, reason: 'unsupported' });
    if (!password || String(password).length < 8) return Promise.resolve({ ok: false, reason: 'short' });
    var salt = root.crypto.getRandomValues(new Uint8Array(16));
    var iv = root.crypto.getRandomValues(new Uint8Array(12));
    var plain = new TextEncoder().encode(JSON.stringify(obj));
    return deriveKey(String(password), salt, ITER).then(function (key) {
      return subtle().encrypt({ name: 'AES-GCM', iv: iv }, key, plain);
    }).then(function (ct) {
      return { ok: true, envelope: {
        schema: ENC_SCHEMA,
        kdf: { name: 'PBKDF2-HMAC-SHA256', iterations: ITER, salt: b64e(salt) },
        cipher: { name: 'AES-GCM', iv: b64e(iv) },
        ciphertext: b64e(ct),
        note: '비밀번호 없이는 열 수 없습니다. 비밀번호를 잊으면 이 파일은 복구되지 않습니다.' } };
    }).catch(function () { return { ok: false, reason: 'failed' }; });
  }

  /* 암호 봉투 → 평문 객체. 틀린 비밀번호면 AES-GCM 인증 실패로 {ok:false, reason:'bad_password'}. */
  function open(envelope, password) {
    if (!canSeal()) return Promise.resolve({ ok: false, reason: 'unsupported' });
    if (!envelope || envelope.schema !== ENC_SCHEMA) return Promise.resolve({ ok: false, reason: 'format' });
    var salt = b64d(envelope.kdf.salt), iv = b64d(envelope.cipher.iv), ct = b64d(envelope.ciphertext);
    return deriveKey(String(password), salt, envelope.kdf.iterations || ITER).then(function (key) {
      return subtle().decrypt({ name: 'AES-GCM', iv: iv }, key, ct);
    }).then(function (buf) {
      return { ok: true, data: JSON.parse(new TextDecoder().decode(buf)) };
    }).catch(function () { return { ok: false, reason: 'bad_password' }; });
  }

  var api = { canSeal: canSeal, seal: seal, open: open, ENC_SCHEMA: ENC_SCHEMA, ITER: ITER, b64e: b64e, b64d: b64d };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ProofCrypto = api;
})(typeof window !== 'undefined' ? window : globalThis);
