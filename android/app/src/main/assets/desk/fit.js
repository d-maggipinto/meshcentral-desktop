// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Keeps the whole remote screen visible in MeshCentral's viewer on a phone.
// Injected before the session starts. The app asks for the classic page (?sitestyle=1), but a server with its own
// page template, or the Modern UI on a touch screen, sizes the canvas at 1:1 remote pixels ("native zoom"), which
// shows only the top-left corner. We switch the page's mobile modes off and fit the canvas ourselves (the size goes
// into CSS variables that the app's style sheet applies with !important). Our own zoom (touch.js) is a transform
// on top of this.
(function () {
  if (window.__mcdFit) return 'already';
  window.__mcdFit = 1;
  var de = document.documentElement;
  function noMobile() {
    ['is-mobile', 'native-zoom', 'fulldesk', 'is-landscape'].forEach(function (c) {
      document.body.classList.remove(c); de.classList.remove(c);
    });
  }
  noMobile();
  window._mobileSetZoom = function () {};
  window._doOrientationUpdate = function () {};
  var last = '';
  function fit() {
    var P = document.getElementById('DeskParent'), C = document.getElementById('Desk');
    if (!P || !C) return;
    if (document.body.classList.contains('is-mobile') || document.body.classList.contains('native-zoom')) noMobile();
    var pw = P.clientWidth, ph = P.clientHeight, cw = C.width, ch = C.height;
    if (!pw || !ph || !cw || !ch) return;
    var s = Math.min(pw / cw, ph / ch), w = Math.floor(cw * s), h = Math.floor(ch * s);
    var key = [w, h, pw, ph].join(',');
    var a = document.getElementById('deskarea3x');
    if (a && (a.scrollLeft || a.scrollTop)) { a.scrollLeft = 0; a.scrollTop = 0; }
    if (key === last) return;
    last = key;
    de.style.setProperty('--mcd-w', w + 'px');
    de.style.setProperty('--mcd-h', h + 'px');
    de.style.setProperty('--mcd-l', Math.floor((pw - w) / 2) + 'px');
    de.style.setProperty('--mcd-t', Math.floor((ph - h) / 2) + 'px');
    if (window.__mcdResetZoom) window.__mcdResetZoom();
  }
  // the viewer calls deskAdjust on every remote resolution change and window resize
  window.deskAdjust = fit;
  try { if (typeof desktop !== 'undefined' && desktop && desktop.m) desktop.m.onScreenSizeChange = fit; } catch (e) {}
  window.__mcdFitNow = fit;
  window.addEventListener('resize', function () { setTimeout(fit, 50); setTimeout(fit, 400); });
  setInterval(fit, 500);
  return 'ok';
})();
