// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Touch input for MeshCentral's desktop viewer on a phone (the viewer's own touch
// handlers are never attached). Injected by the app once the session shows its first frame.
//
// Two modes (window.__mcdSetMode('pad' | 'touch'), chosen in the app):
//  pad (default, like TeamViewer): a cursor drawn over the screen; one finger anywhere moves it like a laptop
//      touchpad (faster swipes go further), tap = left click at the cursor, double tap = double click,
//      press and hold then move = left drag. While zoomed the view follows the cursor.
//  touch: the finger is the pointer: tap = left click where you tap, hold then move = drag, one finger moves the
//      pointer (or pans while zoomed).
// Both: two-finger tap = right click, two-finger drag up / down = scroll wheel, pinch = zoom (1x to 5x).
(function () {
  if (window.__mcdTouch) return 'already';
  var P = document.getElementById('DeskParent'), C = document.getElementById('Desk');
  if (!P || !C || typeof desktop === 'undefined' || !desktop.m) return 'nodesk';
  window.__mcdTouch = 1;
  var m = desktop.m, K = m.KeyAction;
  var z = { s: 1, x: 0, y: 0 };
  var mode = window.__mcdMode === 'touch' ? 'touch' : 'pad';
  var cur = [C.width / 2, C.height / 2];         // the cursor, in remote pixels (pad mode)
  var inset = window.__mcdInset || 0;            // CSS px at the bottom covered by the soft keyboard (set by the app)

  // the cursor drawn over the screen (pointer-events off: touches go to the screen below)
  var cv = document.createElement('div');
  cv.id = 'mcdCursor';
  cv.style.cssText = 'position:fixed;left:0;top:0;width:11px;height:15px;z-index:2147483647;pointer-events:none;' +
    'display:none;will-change:transform;';
  cv.innerHTML = '<svg width="11" height="15" viewBox="2 1 16 22"><path d="M3 2 L3 19 L7.5 14.8 L10.6 21.6 L13.6 20.3 ' +
    'L10.6 13.6 L16.8 13.6 Z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  document.body.appendChild(cv);

  function rect() { return C.getBoundingClientRect(); }
  // remote pixel -> screen point and back, through our zoom (getBoundingClientRect includes the transform)
  function toScreen(p) { var r = rect(); return [r.left + p[0] * r.width / C.width, r.top + p[1] * r.height / C.height]; }
  function remote(cx, cy) {
    var r = rect();
    return [Math.max(0, Math.min(C.width - 1, (cx - r.left) * C.width / r.width)),
            Math.max(0, Math.min(C.height - 1, (cy - r.top) * C.height / r.height))];
  }
  function drawCursor() {
    if (mode !== 'pad') { cv.style.display = 'none'; return; }
    var s = toScreen(cur);
    cv.style.display = 'block';
    cv.style.transform = 'translate(' + (s[0] - 1) + 'px,' + (s[1] - 1) + 'px)';   // the arrow tip is the hot spot
  }

  function apply() {
    // h = the part of the view the keyboard leaves visible; at 1x with the keyboard open the screen can still be
    // moved up and down so any part of it can be brought above the keyboard
    var w = P.clientWidth, h = P.clientHeight - inset, ox = C.offsetLeft, oy = C.offsetTop;
    var cw = C.offsetWidth * z.s, ch = C.offsetHeight * z.s;
    if (z.s <= 1.001) {
      z.s = 1; z.x = 0;
      z.y = (inset > 0 && ch > h) ? Math.min(0, Math.max(h - ch - oy, z.y)) : 0;
    } else {
      z.x = cw >= w ? Math.min(-ox, Math.max(w - cw - ox, z.x)) : (w - cw) / 2 - ox;
      z.y = ch >= h ? Math.min(-oy, Math.max(h - ch - oy, z.y)) : (h - ch) / 2 - oy;
    }
    C.style.transformOrigin = '0 0';
    C.style.transform = (z.s === 1 && z.y === 0) ? '' : 'translate(' + z.x + 'px,' + z.y + 'px) scale(' + z.s + ')';
    drawCursor();
  }
  function shifted() { return z.s > 1 || inset > 0; }
  // pad mode while zoomed: move the view so the cursor stays inside it (with a margin)
  function follow() {
    if (!shifted()) return;
    var s = toScreen(cur), pr = P.getBoundingClientRect(), mg = 48, dx = 0, dy = 0, bottom = pr.bottom - inset;
    if (s[0] < pr.left + mg) dx = pr.left + mg - s[0]; else if (s[0] > pr.right - mg) dx = pr.right - mg - s[0];
    if (s[1] < pr.top + mg) dy = pr.top + mg - s[1]; else if (s[1] > bottom - mg) dy = bottom - mg - s[1];
    if (dx || dy) { z.x += dx; z.y += dy; apply(); }
  }
  window.__mcdResetZoom = function () { z = { s: 1, x: 0, y: 0 }; apply(); follow(); };
  // the keyboard opened / closed: keep the cursor (or what was touched last) in the visible part
  window.__mcdSetInset = function (px) { inset = Math.max(0, px | 0); window.__mcdInset = inset; apply(); follow(); };
  window.__mcdSetMode = function (v) { mode = v === 'touch' ? 'touch' : 'pad'; window.__mcdMode = mode; sync(); drawCursor(); return mode; };
  window.addEventListener('resize', function () { setTimeout(window.__mcdResetZoom, 300); });
  setInterval(drawCursor, 500);                   // the screen can move under us (fit.js, rotation)

  // SendMouseMsg adds addx/addy to (pageX - canvas offset): pass the offset itself so X = our remote pixel
  function mouse(action, p, extra) {
    var off = m.GetPositionOfControl(m.Canvas.canvas);
    var e = { pageX: off[0], pageY: off[1], addx: Math.round(p[0]), addy: Math.round(p[1]) };
    for (var k in extra) e[k] = extra[k];
    m.SendMouseMsg(action, e);
  }
  function click(p, which) {
    mouse(K.NONE, p, {});
    mouse(K.DOWN, p, { which: which });
    mouse(K.UP, p, { which: which });
  }
  // the remote's own pointer must be where our cursor is drawn (it starts wherever the remote user left it)
  function sync() { if (mode === 'pad' && m.State === 3) mouse(K.NONE, cur, {}); }
  function moveCursor(dx, dy, dt) {
    // touchpad acceleration: slow moves are precise, fast swipes travel further
    var r = rect(), per = C.width / r.width;           // remote pixels per screen pixel at this zoom
    var speed = Math.hypot(dx, dy) / Math.max(dt, 8);  // screen px per ms
    var gain = Math.min(3, 1 + Math.max(0, speed - 0.3) * 1.6);
    cur = [Math.max(0, Math.min(C.width - 1, cur[0] + dx * per * gain)),
           Math.max(0, Math.min(C.height - 1, cur[1] + dy * per * gain))];
    mouse(K.NONE, cur, {});
    drawCursor();
    follow();
  }

  // on the window in the capture phase, and stopped there: the page's own touch handlers (the Modern UI has some on
  // the canvas) never see the touches, so nothing is sent twice
  function on(type, f) {
    window.addEventListener(type, function (e) {
      if (!P.contains(e.target) && e.target !== P) return;
      e.stopImmediatePropagation();
      f(e);
    }, { passive: false, capture: true });
  }

  var t0 = null, g = '', lp = null, last = null, lastT = 0, start = 0, d0 = 0, s0 = 1, mid0 = null, z0 = null, acc = 0, last2 = null;
  function dist(a, b) { return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY); }
  function mid(a, b) { return [(a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2]; }
  function cancelLp() { if (lp) { clearTimeout(lp); lp = null; } }
  function haptic() { if (window.mcd) mcd.postMessage('{"t":"haptic"}'); }

  on('touchstart', function (e) {
    e.preventDefault();
    if (m.State !== 3) return;
    var t = e.touches;
    if (t.length === 1) {
      t0 = [t[0].clientX, t[0].clientY]; last = t0; lastT = Date.now(); start = lastT; g = 'tap';
      lp = setTimeout(function () {             // long press: start a left drag (at the cursor, or under the finger)
        lp = null; if (g !== 'tap') return;
        g = 'drag';
        var p = mode === 'pad' ? cur : remote(last[0], last[1]);
        mouse(K.NONE, p, {}); mouse(K.DOWN, p, { which: 1 });
        haptic();
      }, 450);
    } else if (t.length === 2) {
      cancelLp();
      if (g === 'drag') mouse(K.UP, mode === 'pad' ? cur : remote(last[0], last[1]), { which: 1 });
      g = 'two'; start = Date.now(); d0 = dist(t[0], t[1]); s0 = z.s; mid0 = mid(t[0], t[1]); z0 = { x: z.x, y: z.y }; acc = 0;
    }
  });

  on('touchmove', function (e) {
    e.preventDefault();
    if (m.State !== 3) return;
    var t = e.touches;
    if (t.length === 1 && g !== 'two' && g !== 'pinch' && g !== 'scroll') {
      var c = [t[0].clientX, t[0].clientY], now = Date.now();
      if (g === 'tap' && Math.hypot(c[0] - t0[0], c[1] - t0[1]) > 10) {
        cancelLp();
        g = mode === 'pad' ? 'pad' : (shifted() ? 'pan' : 'move');
      }
      if (g === 'pad' || (g === 'drag' && mode === 'pad')) moveCursor(c[0] - last[0], c[1] - last[1], now - lastT);
      else if (g === 'pan') { z.x += c[0] - last[0]; z.y += c[1] - last[1]; apply(); }
      else if (g === 'move' || g === 'drag') mouse(K.NONE, remote(c[0], c[1]), {});
      last = c; lastT = now;
    } else if (t.length === 2) {
      var d = dist(t[0], t[1]), mm = mid(t[0], t[1]);
      if (g === 'two') {
        if (Math.abs(d - d0) > 24) g = 'pinch';
        else if (Math.abs(mm[1] - mid0[1]) > 12) g = 'scroll';
      }
      if (g === 'pinch') {
        var ns = Math.max(1, Math.min(5, s0 * d / d0));
        // keep the point under the fingers' midpoint fixed while zooming, and follow the midpoint (pan)
        var r = P.getBoundingClientRect(), ox = C.offsetLeft, oy = C.offsetTop;
        var px = mid0[0] - r.left - ox, py = mid0[1] - r.top - oy;
        z.s = ns;
        z.x = px - (px - z0.x) * ns / s0 + (mm[0] - mid0[0]);
        z.y = py - (py - z0.y) * ns / s0 + (mm[1] - mid0[1]);
        apply();
      } else if (g === 'scroll') {
        acc += mm[1] - (last2 || mm)[1];
        while (Math.abs(acc) >= 30) {
          var dir = acc > 0 ? 1 : -1; acc -= dir * 30;
          mouse(K.SCROLL, mode === 'pad' ? cur : remote(mm[0], mm[1]), { wheelDelta: 40 * dir });
        }
      }
      last2 = mm;
    }
  });

  on('touchend', function (e) {
    e.preventDefault();
    if (m.State !== 3) return;
    if (e.touches.length > 0) return;
    cancelLp();
    var quick = Date.now() - start < 450;
    if (g === 'tap' && quick) {
      // pad: click where the cursor is (a second quick tap makes a double click on the remote)
      if (mode === 'pad') click(cur, 1);
      else { cur = remote(t0[0], t0[1]); click(cur, 1); }
    }
    else if (g === 'drag') mouse(K.UP, mode === 'pad' ? cur : remote(last[0], last[1]), { which: 1 });
    else if (g === 'two' && Date.now() - start < 400) click(mode === 'pad' ? cur : remote(mid0[0], mid0[1]), 3);
    g = ''; last2 = null;
  });

  on('touchcancel', function () {
    cancelLp();
    if (g === 'drag') mouse(K.UP, mode === 'pad' ? cur : remote(last[0], last[1]), { which: 1 });
    g = ''; last2 = null;
  });
  sync();
  drawCursor();
  return 'ok';
})();
