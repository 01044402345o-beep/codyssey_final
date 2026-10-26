/* 어휘 슬롯 문장 골든 갱신 — 백엔드 골든 코퍼스(backend/tests/fixtures/research_golden)의 장소 종류 + 기대 어휘(expected/vocab.json)로
   vocabSentences 결과를 mockup/test-fixtures/vocab_sentences.json 에 쓴다. 틀(VOCAB_TEMPLATES)을 바꿨다면 돌리고 diff 를 확인해 커밋.
     node mockup/scripts/update-vocab-sentences.js */
const fs = require('fs');
const path = require('path');
const AI = require('../ai.js');

const GOLDEN = path.join(__dirname, '..', '..', 'backend', 'tests', 'fixtures', 'research_golden');
const OUT = path.join(__dirname, '..', 'test-fixtures', 'vocab_sentences.json');

function compute() {
  const expected = JSON.parse(fs.readFileSync(path.join(GOLDEN, 'expected', 'vocab.json'), 'utf8'));
  const out = {};
  fs.readdirSync(GOLDEN).filter(f => f.endsWith('.json')).sort().forEach(f => {
    const city = f.replace(/\.json$/, '');
    const places = JSON.parse(fs.readFileSync(path.join(GOLDEN, f), 'utf8')).places;
    out[city] = {};
    places.forEach((p, i) => {
      const key = `${String(i).padStart(2, '0')} ${p.name}`;
      const vocab = (expected[city][key] || []).map(([en, kind]) => ({ en, kind }));
      out[city][key] = AI.vocabSentences({ name: p.name, kind: p.kind, vocab }, 6).map(s => [s.en, s.ko]);
    });
  });
  return out;
}
module.exports = { compute, OUT, GOLDEN };
if (require.main === module) {
  fs.writeFileSync(OUT, JSON.stringify(compute(), null, 1) + '\n');
  console.log('written', OUT);
}
