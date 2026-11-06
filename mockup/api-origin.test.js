/* ?api= 는 개발 출처에서만 인정된다 — 배포된 화면이 링크 하나로 서버를 바꾸지 못하게. */
const fs = require('fs');
const src = fs.readFileSync(__dirname + '/ai.js', 'utf8');
const body = src.slice(src.indexOf('function devOrigin'), src.indexOf('function apiBase'));
const devOrigin = new Function(body + '; return devOrigin;')();
let pass = 0, fail = 0;
const t = (name, got, want) => {
  const ok = got === want;
  ok ? pass++ : fail++;
  console.log((ok ? 'ok   ' : 'FAIL ') + name + (ok ? '' : ` — got ${got}, want ${want}`));
};
const L = (protocol, hostname) => ({ protocol, hostname });
t('localhost 는 개발 출처', devOrigin(L('http:', 'localhost')), true);
t('127.0.0.1 은 개발 출처', devOrigin(L('http:', '127.0.0.1')), true);
t('사설망 192.168', devOrigin(L('http:', '192.168.0.12')), true);
t('사설망 10.x', devOrigin(L('http:', '10.0.0.5')), true);
t('사설망 172.16', devOrigin(L('http:', '172.16.3.9')), true);
t('172.32 는 사설망이 아니다', devOrigin(L('https:', '172.32.0.1')), false);
t('file:// 은 개발 출처', devOrigin(L('file:', '')), true);
t('web.app 은 아니다', devOrigin(L('https:', 'codyssey.web.app')), false);
t('firebaseapp.com 은 아니다', devOrigin(L('https:', 'codyssey.firebaseapp.com')), false);
t('onrender 는 아니다', devOrigin(L('https:', 'codyssey-final.onrender.com')), false);
t('공격자 도메인은 아니다', devOrigin(L('https:', 'attacker.example')), false);
t('.local 은 개발 출처', devOrigin(L('http:', 'macbook.local')), true);
console.log('\n# pass ' + pass + '\n# fail ' + fail);
process.exit(fail ? 1 : 0);
