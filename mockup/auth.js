/* Firebase Authentication.
   설정이 없으면 enabled 는 false 이고, 화면은 기존 데모 로그인을 쓴다.
   이메일·Google 만 연다. 카카오·네이버·페이스북은 Firebase 기본 제공자가 아니라 버튼을 두지 않는다.
   SDK 11.10.0 */
'use strict';

const FirebaseAuth = {
  enabled: false,
  account: null,
  ready: Promise.resolve(null),
  _started: false,
  _auth: null,
  _mod: null,
};

FirebaseAuth.koreanError = function (err) {
  const code = err && (err.code || '');
  if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') return '';
  if (code === 'auth/invalid-credential' || code === 'auth/wrong-password' || code === 'auth/user-not-found' || code === 'auth/invalid-email')
    return '이메일 또는 비밀번호가 맞지 않아요.';
  if (code === 'auth/email-already-in-use') return '이미 가입된 이메일이에요. 로그인으로 바꿔 주세요.';
  if (code === 'auth/weak-password') return '비밀번호는 6자 이상으로 해 주세요.';
  if (code === 'auth/popup-blocked') return '로그인 창이 차단됐어요. 주소창 오른쪽에서 팝업을 허용해 주세요.';
  if (code === 'auth/operation-not-allowed') return '이 로그인 방식은 Firebase 콘솔에서 아직 꺼져 있어요.';
  return '로그인에 실패했어요. 잠시 뒤 다시 시도해 주세요.';
};

function authBase() {
  if (typeof API === 'undefined' || !API || API.base === null) return null;
  return API.base;
}

async function loadFirebase(cfg) {
  const appMod = await import('https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js');
  const authMod = await import('https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js');
  const app = appMod.initializeApp({
    apiKey: cfg.apiKey,
    authDomain: cfg.authDomain,
    projectId: cfg.projectId,
    appId: cfg.appId,
  });
  FirebaseAuth._auth = authMod.getAuth(app);
  FirebaseAuth._mod = authMod;
  FirebaseAuth.enabled = true;
}

async function accountFromUser(user) {
  const token = await user.getIdToken();
  const base = authBase();
  const res = await fetch((base || '') + '/auth/me', {
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' },
  });
  if (!res.ok) {
    const err = new Error('auth/me');
    err.code = 'auth/me';
    throw err;
  }
  const body = await res.json();
  FirebaseAuth.account = {
    uid: body.uid,
    email: body.email || user.email || '',
    name: body.name || user.displayName || (user.email ? user.email.split('@')[0] : '회원'),
    provider: body.provider || '',
  };
  return FirebaseAuth.account;
}

FirebaseAuth.start = function () {
  if (FirebaseAuth._started) return FirebaseAuth.ready;
  FirebaseAuth._started = true;
  FirebaseAuth.ready = (async function () {
  const base = authBase();
  if (base === null) return null;
  let cfg;
  try {
    const res = await fetch(base + '/auth/config', { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!res.ok) return null;
    cfg = await res.json();
  } catch (e) {
    return null;
  }
  if (!cfg || !cfg.enabled) return null;
  try {
    await loadFirebase(cfg);
  } catch (e) {
    FirebaseAuth.enabled = false;
    return null;
  }
  return await new Promise(resolve => {
    FirebaseAuth._mod.onAuthStateChanged(FirebaseAuth._auth, user => {
      if (!user) { FirebaseAuth.account = null; resolve(null); return; }
      accountFromUser(user).then(resolve, () => resolve(null));
    });
  });
  }());
  return FirebaseAuth.ready;
};

FirebaseAuth.signInGoogle = async function () {
  await FirebaseAuth.ready;
  if (!FirebaseAuth.enabled) return null;
  const provider = new FirebaseAuth._mod.GoogleAuthProvider();
  const cred = await FirebaseAuth._mod.signInWithPopup(FirebaseAuth._auth, provider);
  return accountFromUser(cred.user);
};

FirebaseAuth.signInEmail = async function (email, password, name, signup) {
  await FirebaseAuth.ready;
  if (!FirebaseAuth.enabled) return null;
  const mod = FirebaseAuth._mod;
  const cred = signup
    ? await mod.createUserWithEmailAndPassword(FirebaseAuth._auth, email, password)
    : await mod.signInWithEmailAndPassword(FirebaseAuth._auth, email, password);
  if (signup && name && cred.user) {
    try { await mod.updateProfile(cred.user, { displayName: name }); } catch (e) { /* 이름은 토큰에 없어도 화면에는 쓴다 */ }
  }
  const account = await accountFromUser(cred.user);
  if (signup && name) account.name = name;
  return account;
};

FirebaseAuth.idToken = async function () {
  const user = FirebaseAuth._auth && FirebaseAuth._auth.currentUser;
  if (!user) return '';
  try { return await user.getIdToken(); } catch (e) { return ''; }
};

FirebaseAuth.signOut = async function () {
  if (FirebaseAuth._auth && FirebaseAuth._mod) {
    try { await FirebaseAuth._mod.signOut(FirebaseAuth._auth); } catch (e) { /* 화면 상태는 비운다 */ }
  }
  FirebaseAuth.account = null;
};

// 클래식 스크립트의 const 는 window 속성이 되지 않는다. app.js 는 window.FirebaseAuth 로 시작한다.
window.FirebaseAuth = FirebaseAuth;
