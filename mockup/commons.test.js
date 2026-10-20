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

// 회화 연습(팀 요청 10/17 Leechangjin 목업 #97 · 설문 7-2): 공통 30개에 상대의 예상 답변과 이어서 할 말.
// ask = 상대가 먼저 하는 말(입국심사 질문 등, 선택), replies = 내 말 뒤 상대 답 1~2개, next = 내가 이어서 할 말.
test('공통 문장: 학습량 30개 모두 회화 연습(예상 답변 1~2개 + 이어서 할 말)이 있다', () => {
  const line = (x, where) => {
    assert.ok(x && typeof x.en === 'string' && x.en.trim() && typeof x.ko === 'string' && x.ko.trim(), `${where}: 영어·한국어 필요`);
    assert.ok(!x.en.includes('/'), `${where}: 한 줄에 문장 하나 — ${x.en}`);
    assert.ok(x.en.split(/\s+/).length <= 15, `${where}: 짧게(15단어 이하) — ${x.en}`);
  };
  for (const g of groups.filter(g => g.countsTowardPlan)) for (const it of g.items) {
    const w = `${g.key}/${it.situation}`;
    assert.ok(it.talk, `${w}: talk 없음`);
    assert.ok(Array.isArray(it.talk.replies) && it.talk.replies.length >= 1 && it.talk.replies.length <= 2, `${w}: 예상 답변 1~2개`);
    it.talk.replies.forEach((r, i) => line(r, `${w} replies[${i}]`));
    line(it.talk.next, `${w} next`);
    if (it.talk.ask) line(it.talk.ask, `${w} ask`);
    // 대화하기(1a): '내가 이어서'가 이어지는 갈래. 갈래가 둘이면 어느 쪽인지 반드시 적는다(조사 6절 ⑤).
    assert.ok(Number.isInteger(it.talk.nextFor) && it.talk.nextFor >= 0 && it.talk.nextFor < it.talk.replies.length, `${w}: nextFor 범위`);
  }
});

test('공통 문장: 참고 묶음(응급 전화)에는 회화 연습을 붙이지 않는다(범위: 학습량 30개)', () => {
  for (const g of groups.filter(g => !g.countsTowardPlan)) for (const it of g.items) assert.equal(it.talk, undefined, `${g.key}/${it.situation}`);
});
