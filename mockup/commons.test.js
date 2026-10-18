// 공통 문장 가드: 날짜별 학습량에 들어가는 공통 문장은 30개여야 한다.
// app.js R.counts 의 C = 30 (P = D × 5 − 30) 이 이 수를 가정한다. 묶음을 더하면 일정이 조용히 틀어진다.
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('fs'), path = require('path'), vm = require('vm');
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8');
const ctx = vm.createContext({});
vm.runInContext(read('data.js') + '\nthis.groups = JSON.stringify(COMMON_SITUATIONS);', ctx);
const groups = JSON.parse(ctx.groups);   // vm 쪽 배열은 다른 realm 이라 deepEqual 이 실패한다 — JSON 으로 옮긴다

test('공통 문장: 학습량에 포함되는 묶음의 문장은 30개 (FR-SENT-01)', () => {
  // 공통 문장 수가 30에서 벗어나면 app.js R.counts 의 계산식이 틀어진다
  assert.equal(groups.filter(g => g.countsTowardPlan).flatMap(g => g.items).length, 30);
});

test('공통 문장: 모든 묶음이 countsTowardPlan 을 명시한다', () => {
  // 빠뜨리면 undefined → 참고용으로 빠진다. 우연한 필터가 되지 않게 true/false 를 직접 적는다
  assert.deepEqual(groups.filter(g => typeof g.countsTowardPlan !== 'boolean').map(g => g.key), []);
});

test('공통 문장: 묶음 key 는 겹치지 않고, 문장은 영어·한국어가 하나씩', () => {
  assert.equal(new Set(groups.map(g => g.key)).size, groups.length);
  for (const g of groups) for (const it of g.items) {
    assert.ok(it.en.trim() && it.ko.trim(), `${g.key}: 빈 문장`);
    assert.ok(!it.en.includes('/'), `${g.key}: 카드 하나에 목표 문장 하나 (말해 보기 채점) — ${it.en}`);
  }
});
