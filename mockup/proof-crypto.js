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

  /* ---- 복구 키와 단방향 커밋먼트 ----
   * 복구 키는 기기에만 있는 256비트 난수다. 서버와 체인에는 그 SHA-256 커밋먼트만 간다. 그래서 체인·DB·로그가
   * 새도 복구 키는 드러나지 않고, 복구 키를 내놓는 사람만 "내가 그 탈퇴를 요청했다"를 증명할 수 있다.
   * SHA-256 의 압축 함수는 Ch·Maj(AND·XOR·NOT)와 회전·모듈러 덧셈으로 된 비선형 단방향 함수다.
   * 직접 만든 S-box 조합으로 바꾸지 않는다 — 검토되지 않은 해시는 관리자가 증거로 쓸 수 없다(receipt_signing.py).
   * 입력이 256비트 난수라 사전 공격 대상이 아니므로 느린 KDF 는 필요 없다. */
  var KEY_PREFIX = 'wrk1-';
  var KEY_RE = /^wrk1-[0-9a-f]{64}$/;
  var COMMIT_DOMAIN = 'SEAL-WITHDRAW-KEY-v1\0';

  function hex(bytes) {
    var a = new Uint8Array(bytes), s = '';
    for (var i = 0; i < a.length; i++) s += (a[i] < 16 ? '0' : '') + a[i].toString(16);
    return s;
  }
  function unhex(str) {
    var a = new Uint8Array(str.length / 2);
    for (var i = 0; i < a.length; i++) a[i] = parseInt(str.substr(i * 2, 2), 16);
    return a;
  }
  function join() {
    var total = 0, i, at = 0;
    for (i = 0; i < arguments.length; i++) total += arguments[i].length;
    var out = new Uint8Array(total);
    for (i = 0; i < arguments.length; i++) { out.set(arguments[i], at); at += arguments[i].length; }
    return out;
  }
  function ascii(str) { return new TextEncoder().encode(str); }

  function commitmentOf(key) {
    if (!canSeal() || !KEY_RE.test(String(key))) return Promise.resolve('');
    var raw = unhex(String(key).slice(KEY_PREFIX.length));
    return subtle().digest('SHA-256', join(ascii(COMMIT_DOMAIN), raw)).then(hex);
  }
  /* CSPRNG·WebCrypto 가 없으면 null — 추측 가능한 값은 증거가 못 되므로 만들지 않는다. */
  function newRecoveryKey() {
    if (!canSeal() || !root.crypto.getRandomValues) return Promise.resolve(null);
    var key = KEY_PREFIX + hex(root.crypto.getRandomValues(new Uint8Array(32)));
    return commitmentOf(key).then(function (commitment) {
      return { key: key, commitment: commitment };
    }).catch(function () { return null; });
  }

  /* TLS 없는 주소로는 보내지 않는다. 개발용 루프백만 예외다. */
  function isSecureEndpoint(url, base) {
    try {
      var u = new URL(url || '', base);
      return u.protocol === 'https:' || ['localhost', '127.0.0.1', '[::1]'].indexOf(u.hostname) >= 0;
    } catch (e) { return false; }
  }

  /* ---- 관리자 공개키 봉인(MFA1) ----
   * TLS 는 Render 에서 끝나므로 서버는 평문을 볼 수 있다. 복구 키는 서버도 보면 안 되니 브라우저에서 관리자
   * 공개키로 봉인한다: gzip → AES-256-GCM → 데이터키를 X25519 로 감싼다. 형식은 backend/app/evidence.py 의
   * seal 과 같은 바이트다 — tools/opsarchive 의 container.unseal 로 연다(test_recovery.py 가 실제로 연다). */
  var MFA1 = { salt: 'mfa1', info: 'mfa1-kek', wrapSalt: 'mfa1-nonce', wrapInfo: 'mfa1-wrap' };
  /* 관리자 공개키 지문. API 서버(Render)가 침해돼 공격자의 공개키를 내줘도 여기서 걸린다. 화면은 Firebase Hosting 에서
   * 따로 배포되므로 API 서버를 장악해도 이 값은 바꾸지 못한다. 키를 회전하면 이 값을 고쳐 Hosting 을 다시 배포한다.
   * 값은 관리자가 개인키에서 역산해 올린 Actions 변수(EVIDENCE_PIN_FINGERPRINT)와 같고, verify-key-pin 이 대조한다. */
  var ADMIN_KEY_FINGERPRINT = '181b495477fbe7293e0b6de44ff831c0760929824a641ac6d62548c7ecfad778';

  function hkdf(shared, salt, info, length) {
    return subtle().importKey('raw', shared, 'HKDF', false, ['deriveBits']).then(function (base) {
      return subtle().deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: ascii(salt), info: ascii(info) }, base, length * 8);
    }).then(function (bits) { return new Uint8Array(bits); });
  }
  function aesGcm(rawKey, iv, plain, aad) {
    return subtle().importKey('raw', rawKey, 'AES-GCM', false, ['encrypt']).then(function (key) {
      var params = { name: 'AES-GCM', iv: iv };
      if (aad) params.additionalData = aad;
      return subtle().encrypt(params, key, plain);
    }).then(function (ct) { return new Uint8Array(ct); });
  }
  function gzip(bytes) {
    var stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('gzip'));
    return new Response(stream).arrayBuffer().then(function (buf) { return new Uint8Array(buf); });
  }
  /* 평문 객체 + 관리자 공개키(x25519:<base64url>) + 기대 지문 → base64url 봉투. 던지지 않고 {ok:false, reason} 으로 알린다.
   * 지문이 다르면 key_mismatch 다. 복구 키를 절대 그 공개키로 봉인하지 않는다. */
  function sealForAdmin(obj, publicKey, expectedFingerprint) {
    if (!canSeal() || typeof CompressionStream === 'undefined') return Promise.resolve({ ok: false, reason: 'unsupported' });
    var recipient;
    try { recipient = b64d(String(publicKey || '').replace(/^x25519:/, '')); } catch (e) { recipient = null; }
    if (!recipient || recipient.length !== 32) return Promise.resolve({ ok: false, reason: 'bad_key' });
    if (!expectedFingerprint) return Promise.resolve({ ok: false, reason: 'key_mismatch' });
    return subtle().digest('SHA-256', recipient).then(function (d) {
      if (hex(d) !== expectedFingerprint) return { ok: false, reason: 'key_mismatch' };
      return sealTo(obj, recipient);
    }).catch(function () { return { ok: false, reason: 'unsupported' }; });
  }
  function sealTo(obj, recipient) {
    var dataKey = root.crypto.getRandomValues(new Uint8Array(32));
    var iv = root.crypto.getRandomValues(new Uint8Array(12));
    var ephPub, shared, kek;
    return subtle().generateKey({ name: 'X25519' }, false, ['deriveBits']).then(function (eph) {
      return subtle().exportKey('raw', eph.publicKey).then(function (pub) {
        ephPub = new Uint8Array(pub);
        return subtle().importKey('raw', recipient, { name: 'X25519' }, false, []);
      }).then(function (peer) {
        return subtle().deriveBits({ name: 'X25519', public: peer }, eph.privateKey, 256);
      });
    }).then(function (bits) {
      shared = new Uint8Array(bits);
      return hkdf(shared, MFA1.salt, MFA1.info, 32);
    }).then(function (k) {
      kek = k;
      return hkdf(shared, MFA1.wrapSalt, MFA1.wrapInfo, 12);
    }).then(function (wrapNonce) {
      return aesGcm(kek, wrapNonce, dataKey);
    }).then(function (sealedKey) {
      return subtle().digest('SHA-256', recipient).then(function (d) {
        var wrapped = join(ephPub, sealedKey);
        return join(ascii('MFA1'), new Uint8Array([1, 1]), new Uint8Array(d).slice(0, 8),
          new Uint8Array([wrapped.length >> 8, wrapped.length & 255]), wrapped, iv);
      });
    }).then(function (header) {
      return gzip(new TextEncoder().encode(JSON.stringify(obj))).then(function (packed) {
        return aesGcm(dataKey, iv, packed, header);
      }).then(function (body) {
        return { ok: true, sealed: b64e(join(header, body)) };
      });
    }).catch(function () { return { ok: false, reason: 'unsupported' }; });
  }

  var api = { canSeal: canSeal, seal: seal, open: open, ENC_SCHEMA: ENC_SCHEMA, ITER: ITER, b64e: b64e, b64d: b64d,
    newRecoveryKey: newRecoveryKey, commitmentOf: commitmentOf, isSecureEndpoint: isSecureEndpoint, sealForAdmin: sealForAdmin,
    ADMIN_KEY_FINGERPRINT: ADMIN_KEY_FINGERPRINT };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ProofCrypto = api;
})(typeof window !== 'undefined' ? window : globalThis);
