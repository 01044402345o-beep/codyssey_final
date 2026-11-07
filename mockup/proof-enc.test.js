/* 증명 파일 암호화 — 왕복·오답 거부·봉투 변조 거부. */
const assert = require('assert');
const PC = require('./proof-crypto.js');

let pass = 0, fail = 0;
function t(name, fn) {
  return fn().then(() => { pass++; console.log('ok   ' + name); })
    .catch(e => { fail++; console.log('FAIL ' + name + ' — ' + e.message); });
}

(async () => {
  const doc = { schema: 'SEAL-RECEIPT-v2', receipt: { challenge: 'a'.repeat(32), outcome: 'ok', seq: 7 } };

  await t('암호를 걸고 다시 열면 같은 내용', async () => {
    const s = await PC.seal(doc, 'correct horse battery');
    assert.strictEqual(s.ok, true);
    assert.strictEqual(s.envelope.ciphertext.indexOf('challenge'), -1, '평문이 남아 있으면 안 된다');
    const o = await PC.open(s.envelope, 'correct horse battery');
    assert.strictEqual(o.ok, true);
    assert.deepStrictEqual(o.data, doc);
  });

  await t('틀린 비밀번호는 열리지 않는다', async () => {
    const s = await PC.seal(doc, 'correct horse battery');
    const o = await PC.open(s.envelope, 'wrong horse battery');
    assert.strictEqual(o.ok, false);
    assert.strictEqual(o.reason, 'bad_password');
  });

  await t('암호문 한 글자만 바꿔도 거부된다(AES-GCM 인증)', async () => {
    const s = await PC.seal(doc, 'correct horse battery');
    const ct = s.envelope.ciphertext;
    const bad = { ...s.envelope, ciphertext: (ct[0] === 'A' ? 'B' : 'A') + ct.slice(1) };
    const o = await PC.open(bad, 'correct horse battery');
    assert.strictEqual(o.ok, false);
  });

  const KEY = 'wrk1-' + '00'.repeat(32);
  // tools/opsarchive/tests/test_recovery.py 와 같은 벡터다 — 양쪽 식이 갈라지면 둘 다 실패한다.
  const VECTOR = 'cf5d8a7775351fcb9645d58784427a23c988be6a5a3e3c23a892918b8b3651b8';

  await t('복구 키의 커밋먼트는 정해진 벡터와 같고, 키 자체를 담지 않는다', async () => {
    const c = await PC.commitmentOf(KEY);
    assert.strictEqual(c, VECTOR);
    assert.strictEqual(c.indexOf('00'.repeat(32)), -1);
  });

  await t('복구 키 한 글자만 바꿔도 해시 비트의 평균 50% 가 뒤집힌다', async () => {
    // 평균만 본다. 개별 값은 128±8비트로 흩어지는 것이 정상이라 "매번 50% 이상"은 좋은 해시도 떨어진다.
    const HEX = '0123456789abcdef';
    const flipped = (a, b) => {
      let n = 0;
      for (let i = 0; i < a.length; i++) {
        let x = parseInt(a[i], 16) ^ parseInt(b[i], 16);
        while (x) { n += x & 1; x >>= 1; }
      }
      return n;
    };
    let total = 0, count = 0;
    for (let round = 0; round < 20; round++) {
      const made = await PC.newRecoveryKey();
      const text = made.key.slice(5);
      for (let i = 0; i < text.length; i++) {
        const other = HEX[(HEX.indexOf(text[i]) + 1 + (round % 15)) % 16];
        const bits = flipped(made.commitment, await PC.commitmentOf('wrk1-' + text.slice(0, i) + other + text.slice(i + 1)));
        assert.notStrictEqual(bits, 0, '같은 해시가 나오면 안 된다');
        total += bits; count++;
      }
    }
    const mean = total / count / 256 * 100;
    assert.ok(mean > 49 && mean < 51, '평균 ' + mean);
  });

  await t('복구 키 형식이 아니면 커밋먼트를 만들지 않는다', async () => {
    assert.strictEqual(await PC.commitmentOf('wrk1-abc'), '');
    assert.strictEqual(await PC.commitmentOf('00'.repeat(32)), '');
  });

  await t('복구 키는 매번 새 256비트 난수고, 커밋먼트는 서버 형식(16진수 64자)이다', async () => {
    const a = await PC.newRecoveryKey();
    const b = await PC.newRecoveryKey();
    assert.ok(/^wrk1-[0-9a-f]{64}$/.test(a.key));
    assert.ok(/^[0-9a-f]{64}$/.test(a.commitment));
    assert.notStrictEqual(a.key, b.key);
    assert.strictEqual(a.commitment, await PC.commitmentOf(a.key));
  });

  await t('TLS 없는 주소로는 보내지 않는다(루프백만 예외)', async () => {
    assert.strictEqual(PC.isSecureEndpoint('', 'https://a.test/'), true);
    assert.strictEqual(PC.isSecureEndpoint('https://b.test', 'http://a.test/'), true);
    assert.strictEqual(PC.isSecureEndpoint('', 'http://localhost:8000/'), true);
    assert.strictEqual(PC.isSecureEndpoint('', 'http://a.test/'), false);
    assert.strictEqual(PC.isSecureEndpoint('http://b.test', 'https://a.test/'), false);
  });

  await t('관리자 봉인은 공개키가 틀리면 만들지 않고, 평문을 담지 않는다', async () => {
    assert.strictEqual((await PC.sealForAdmin({ recovery_key: KEY }, 'x25519:AAAA', 'ab'.repeat(32))).reason, 'bad_key');
    const { publicKey } = await crypto.subtle.generateKey({ name: 'X25519' }, true, ['deriveBits']);
    const raw = PC.b64e(await crypto.subtle.exportKey('raw', publicKey));
    const digest = await crypto.subtle.digest('SHA-256', PC.b64d(raw));
    const pin = Buffer.from(digest).toString('hex');
    const r = await PC.sealForAdmin({ recovery_key: KEY }, 'x25519:' + raw, pin);
    assert.strictEqual(r.ok, true);
    const blob = Buffer.from(PC.b64d(r.sealed)).toString('latin1');
    assert.strictEqual(blob.slice(0, 4), 'MFA1');
    assert.strictEqual(blob.indexOf(KEY), -1);
  });

  await t('서버가 다른 공개키를 내주면 봉인하지 않는다(서버 침해 대비)', async () => {
    const { publicKey } = await crypto.subtle.generateKey({ name: 'X25519' }, true, ['deriveBits']);
    const attacker = 'x25519:' + PC.b64e(await crypto.subtle.exportKey('raw', publicKey));
    const pinned = await PC.sealForAdmin({ recovery_key: KEY }, attacker, PC.ADMIN_KEY_FINGERPRINT);
    assert.deepStrictEqual(pinned, { ok: false, reason: 'key_mismatch' });
    const noPin = await PC.sealForAdmin({ recovery_key: KEY }, attacker, '');
    assert.deepStrictEqual(noPin, { ok: false, reason: 'key_mismatch' });
    assert.ok(/^[0-9a-f]{64}$/.test(PC.ADMIN_KEY_FINGERPRINT));
  });

  await t('8자 미만은 거부', async () => {
    const s = await PC.seal(doc, 'short');
    assert.strictEqual(s.ok, false);
    assert.strictEqual(s.reason, 'short');
  });

  await t('매번 다른 salt·iv', async () => {
    const a = await PC.seal(doc, 'correct horse battery');
    const b = await PC.seal(doc, 'correct horse battery');
    assert.notStrictEqual(a.envelope.kdf.salt, b.envelope.kdf.salt);
    assert.notStrictEqual(a.envelope.cipher.iv, b.envelope.cipher.iv);
  });

  await t('형식이 다른 봉투는 거부', async () => {
    const o = await PC.open({ schema: 'nope' }, 'correct horse battery');
    assert.strictEqual(o.reason, 'format');
  });

  console.log('\n# pass ' + pass + '\n# fail ' + fail);
  process.exit(fail ? 1 : 0);
})();
