/* =====================================================================
   카드 좌우 스와이프 — 붙여넣기용 (mockup/app.js 의 맨 끝에 붙입니다)

   이 파일 하나가 다음을 모두 담고 있습니다.
     1) cardSwipe  — 좌우로 밀어 카드 넘기기, 넘어가는 동안의 움직임,
                     첫 카드·마지막 카드에서 밀었을 때의 빈 자리
     2) cardHint   — 처음 한 번만 카드를 흔들어 스와이프를 알려 주는 안내

   자리가 이미 있으면(기존 블록이 있으면) 그 블록을 통째로 이 내용으로 바꾸세요.
   새 블록을 덧붙이면 카드가 두 번 움직입니다.
   ===================================================================== */
/* ===== 카드 좌우로 밀어 넘기기 (cardSwipe) =====
   가로로 확정된 제스처만 앞/뒤 카드로 넘긴다 — 세로 스크롤은 브라우저가 그대로 처리한다.
   손을 떼면 곧바로 카드를 바꾸고, 바뀐 사실은 새 카드가 옆에서 들어오는 움직임으로 보여 준다.
   나가고 들어오는 2단 구성은 손을 뗀 뒤 기다리는 시간(체감 지연)을 만들어 '뚝뚝 끊기는' 느낌을 줬다.
   새 CSS 토큰을 만들지 않는다 — 이동은 카드의 inline transform 하나로 처리한다. */
(function () {
  var LOCK_X = 12;   /* 이만큼 가로로 움직이면 스와이프로 확정 */
  var ABORT_Y = 60;  /* 확정 전에 이보다 세로로 움직이면 스크롤에 양보 */
  var GO = 40;       /* 손을 뗄 때 넘어가는 최소 이동량 */
  var FREE = 40;     /* 여기까지는 손가락을 1:1 로 따라간다 */
  var CAP = 96;      /* 따라오는 최대 거리 */
  var CURVE = 0.35;  /* 끝에서 무거워지는 정도 */
  var IN = 240;      /* 새 카드가 들어오는 시간 — styles.css 의 cardInNext·cardInPrev 와 맞춘다 */
  var swallowUntil = 0, own = false, cur = null, lastIdx = null;
  var slow = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function card() { return document.querySelector('.flip'); }
  function navBtn(dir) {
    var n = document.querySelector('.card-nav');
    return n ? n.querySelector(dir > 0 ? '[data-act="card-next"]' : '[data-act="card-prev"]') : null;
  }
  function curIdx() {
    var list = document.querySelectorAll('.dots i');
    for (var i = 0; i < list.length; i++) if (list[i].classList.contains('cur')) return i;
    return null;
  }
  function amp(dx) {
    var a = Math.abs(dx);
    if (a > FREE) a = FREE + (a - FREE) * CURVE;
    return Math.min(a, CAP);
  }
  /* 끝 카드 전용 — 고무줄을 덜 조여 빈 자리를 넓게 연다(안내 문구가 들어갈 폭). */
  function edgeAmp(dx) {
    var a = Math.abs(dx);
    if (a > FREE) a = FREE + (a - FREE) * 0.6;
    return Math.min(a, 168);
  }
  function back(el) {                /* 넘기지 못했다 — 부드럽게 제자리로 */
    if (!el) return;
    el.style.transform = 'translateX(0px)';
    el.style.opacity = '';
    setTimeout(function () { el.style.removeProperty('transform'); }, 220);
  }
  /* ===== 끝 카드에서 밀면 드러나는 자리에 안내와 가장자리 그늘 =====
     .flip-wrap 은 가만히 있고 .flip 만 미끄러지므로 카드가 있던 자리가 비고 그 자리에 이 층이 보인다.
     그늘은 카드 쪽이 진하고 바깥으로 옅어진다(카드가 드리우는 그림자처럼). */
  var edgeSide = null;
  function edgeEl() { return document.querySelector('.flip-edge'); }
  function edgeHide() {
    edgeSide = null;
    var e = edgeEl();
    if (!e) return;
    e.classList.remove('shown', 'side-left', 'side-right');
    e.style.clipPath = '';
    var sp = e.querySelectorAll('span');
    for (var q = 0; q < sp.length; q++) { sp[q].style.width = ''; sp[q].style.transform = ''; }
  }
  function edgeShow(dx, amount) {
    var e = edgeEl();
    if (!e) return;
    var side = dx < 0 ? 'side-right' : 'side-left';   /* 카드가 왼쪽으로 갔으면 빈 자리는 오른쪽 */
    if (edgeSide && edgeSide !== side) return;         /* 방향이 뒤집히는 도중에는 그리지 않는다 */
    edgeSide = side;
    if (!e.classList.contains('shown')) {
      e.classList.add('shown');
      e.setAttribute('data-first', side === 'side-left' ? '1' : '0');
    }
    e.classList.toggle('side-left', side === 'side-left');
    e.classList.toggle('side-right', side === 'side-right');
    var box = e.getBoundingClientRect().width || 1;
    var w = Math.max(0, Math.min(100, amount / box * 100));   /* 드러난 폭(px)을 층 폭에 대한 % 로 */
    e.style.clipPath = side === 'side-left' ? 'inset(0 ' + (100 - w) + '% 0 0)' : 'inset(0 0 0 ' + (100 - w) + '%)';
    /* 드러난 자리 폭과 같은 폭을 주고 그 쪽으로 붙인다 — 문구가 그 자리 한가운데에 온다. */
    e.style.justifyContent = side === 'side-left' ? 'flex-start' : 'flex-end';
    var sp = e.querySelectorAll('span');
    for (var q = 0; q < sp.length; q++) sp[q].style.width = amount.toFixed(0) + 'px';
    e.style.opacity = String(Math.min(1, amount / 60));
  }
  function advance(dir) {
    var b = navBtn(dir);
    /* 넘어갈 곳이 없는 끝 카드(첫 카드에서 오른쪽, 마지막 카드에서 왼쪽)는 제자리로 되돌린다.
       여기서 그냥 돌아가면 드래그로 옮겨 놓은 위치와 투명도가 그대로 남아,
       카드가 어긋난 채 멈춘다 — 넘어가지도 않고 돌아오지도 않는 상태가 된다. */
    edgeHide();
    if (!b || b.disabled) { back(card()); return; }
    if (slow) { b.click(); return; }
    swallowUntil = Date.now() + 420;   /* 손 떼며 브라우저가 합성하는 클릭을 막는다 */
    b.click();                         /* 기다리지 않고 곧바로 — 지연이 곧 끊김이다 */
  }
  /* 손 떼며 브라우저가 만드는 클릭이 카드를 뒤집지 않게 한 번 먹는다.
     카드 밖(하단 버튼·말하기 버튼)은 그대로 누를 수 있어야 하므로 카드 위 클릭만 먹는다. */
  document.addEventListener('click', function (e) {
    if (own || Date.now() >= swallowUntil) return;
    var t = e.target;
    if (!t || !t.closest || !t.closest('.flip')) return;
    e.stopPropagation(); e.preventDefault();
  }, true);

  function begin(target, x, y) {
    if (!target || !target.closest) return;
    if (target.closest('.tts-btn, button, a, input, select, textarea')) return;
    var el = target.closest('.flip');
    if (!el) return;
    cur = { x: x, y: y, dx: 0, dy: 0, card: el, on: false };
  }
  function drag(x, y, ev) {
    if (!cur) return;
    cur.dx = x - cur.x; cur.dy = y - cur.y;
    var ax = Math.abs(cur.dx), ay = Math.abs(cur.dy);
    if (!cur.on) {
      if (ay > ABORT_Y && ay > ax) { cur = null; return; }        /* 세로 스크롤에 양보 */
      if (ax >= LOCK_X && ax >= ay) { cur.on = true; cur.card.classList.add('dragging'); }
      else return;
    }
    if (ay > ABORT_Y && ay > ax) {
      var g = cur; cur = null; g.card.classList.remove('dragging'); back(g.card); return;
    }
    if (ev && ev.cancelable) ev.preventDefault();
    var a = amp(cur.dx), dx = cur.dx < 0 ? -a : a;
    var nb = navBtn(cur.dx < 0 ? 1 : -1);
    var stop = !!(nb && nb.disabled);                  /* 넘어갈 카드가 없다 = 끝 */
    if (stop) a = edgeAmp(cur.dx);                     /* 끝에서는 더 넓게 드러나야 문구가 읽힌다 */
    var dx2 = cur.dx < 0 ? -a : a;
    cur.card.style.transform = 'translateX(' + dx2 + 'px)';
    cur.card.style.opacity = String(1 - Math.min(a, 96) / 420);
    if (stop) edgeShow(cur.dx, a);
    else edgeHide();
  }
  function finish() {
    if (!cur) return;
    var c = cur; cur = null;
    c.card.classList.remove('dragging');
    edgeHide();
    if (c.on && Math.abs(c.dx) >= GO) { advance(c.dx < 0 ? 1 : -1); return; }
    back(c.card);
  }

  document.addEventListener('touchstart', function (e) {
    if (e.touches.length !== 1) return;
    begin(e.target, e.touches[0].clientX, e.touches[0].clientY);
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (e.touches.length !== 1) return;
    drag(e.touches[0].clientX, e.touches[0].clientY, e);
  }, { passive: false });
  document.addEventListener('touchend', finish, { passive: true });
  document.addEventListener('touchcancel', function () {
    if (!cur) return;
    var c = cur; cur = null; c.card.classList.remove('dragging'); edgeHide(); back(c.card);
  }, { passive: true });

  /* 마우스(데스크톱) — 끌어서 넘기기 */
  document.addEventListener('pointerdown', function (e) {
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    begin(e.target, e.clientX, e.clientY);
  }, { passive: true });
  document.addEventListener('pointermove', function (e) {
    if (e.pointerType !== 'mouse' || !cur) return;
    drag(e.clientX, e.clientY, null);
  }, { passive: true });
  document.addEventListener('pointerup', function (e) {
    if (e.pointerType !== 'mouse') return;
    finish();
  }, { passive: true });

  /* 내용이 바뀐 뒤 새 카드를 들여보낸다.
     스와이프와 버튼 탭이 모두 이 한 곳을 지나가므로 넘어가는 움직임이 한 곳에서만 정의된다. */
  function settle() {
    var v = curIdx();
    if (lastIdx === null) { lastIdx = v; return; }
    if (v === null || v === lastIdx) return;
    var dir = v > lastIdx ? 1 : -1;
    lastIdx = v;
    var c = card();
    if (!c || slow) return;
    c.style.removeProperty('transform'); c.style.opacity = '';
    c.classList.add(dir > 0 ? 'in-next' : 'in-prev');
    setTimeout(function () { c.classList.remove('in-next', 'in-prev'); }, IN);
  }
  new MutationObserver(function () { window.requestAnimationFrame(settle); })
    .observe(document.body, { childList: true, subtree: true });
  window.requestAnimationFrame(settle);
})();
/* ===== 처음 한 번만, 카드가 좌우로 흔들려 스와이프를 알려 준다 (cardHint) =====
   다음 카드 버튼이 화면 밖일 때만 띄운다 — 그때가 스와이프가 유일한 길인 상황이다.
   사용자가 만지거나 카드가 바뀌면 곧바로 끝내고 다시는 띄우지 않는다.
   (끝내지 않으면 카드가 넘어갈 때마다 다시 흔들려 넘김 움직임과 뒤엉킨다.) */
(function () {
  var KEY = 'cd_hint_swipe';
  var TXT = '좌우로 밀어 넘겨 보세요 ↔';
  var SETTLE = 450;      /* 이만큼 다시 그리지 않으면 붙인다 */
  var MS = 3200;         /* 처음 붙인 뒤 이만큼 지나면 끝낸다 */
  var ack = false, baseIdx = null, settleT = null, endT = null, orig = null, front = null;
  try { if (localStorage.getItem(KEY)) ack = true; } catch (e) {}

  function curIdx() {
    var list = document.querySelectorAll('.dots i');
    for (var i = 0; i < list.length; i++) if (list[i].classList.contains('cur')) return i;
    return null;
  }
  function reachable() {              /* 다음 카드 버튼이 온전히 보이는가 */
    var b = document.querySelector('.card-nav [data-act="card-next"]');
    if (!b || b.disabled) return true;
    var r = b.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= window.innerHeight;
  }
  function onTop(card) {              /* 동의 모달 같은 것이 덮여 있으면 띄우지 않는다 */
    var r = card.getBoundingClientRect();
    var x = r.left + r.width / 2, y = r.top + Math.min(60, r.height / 2);
    if (y < 0 || y > window.innerHeight) return false;
    var top = document.elementFromPoint(x, y);
    return !!top && card.contains(top);
  }
  function detach() {
    var list = document.querySelectorAll('.flip.hint-swipe');
    for (var i = 0; i < list.length; i++) list[i].classList.remove('hint-swipe');
    if (front && orig !== null) {
      var h = front.querySelector('.face .hint');
      if (h) h.textContent = orig;
    }
    orig = null; front = null;
  }
  function done() {                   /* 끝: 저장하고 다시는 띄우지 않는다 */
    if (settleT) { clearTimeout(settleT); settleT = null; }
    if (endT) { clearTimeout(endT); endT = null; }
    detach();
    if (!ack) { ack = true; try { localStorage.setItem(KEY, '1'); } catch (e) {} }
  }
  function attach() {
    settleT = null;
    if (ack) return;
    var v = curIdx();
    if (baseIdx !== null && v !== baseIdx) { done(); return; }   /* 카드가 넘어갔다 — 안내 끝 */
    if (baseIdx === null) baseIdx = v;
    var card = document.querySelector('.flip');
    if (!card || card.classList.contains('flipped') || !onTop(card) || reachable()) return;
    if (card.classList.contains('hint-swipe')) return;
    front = card;
    var h = card.querySelector('.face .hint');
    if (h) { orig = h.textContent; h.textContent = TXT; }
    card.classList.add('hint-swipe');
    if (!endT) endT = setTimeout(done, MS);
  }
  function schedule() {               /* 다시 그려질 때마다 미룬다 → 잠잠해지면 붙인다 */
    if (ack) return;
    if (settleT) clearTimeout(settleT);
    settleT = setTimeout(attach, SETTLE);
  }

  document.addEventListener('touchstart', function () { if (front) done(); }, { capture: true, passive: true });
  document.addEventListener('pointerdown', function () { if (front) done(); }, { capture: true, passive: true });
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  schedule();
})();
