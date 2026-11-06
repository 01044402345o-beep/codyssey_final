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
