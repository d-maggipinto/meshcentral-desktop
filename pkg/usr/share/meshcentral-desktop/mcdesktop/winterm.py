# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows terminal widget: xterm.js (MIT) inside Edge WebView2, with the small part of the
Vte.Terminal API that terminal_panel uses (VTE does not exist on Windows).

The page is built from the bundled xterm.js files (assets/xterm, put there by the Windows build)
and loaded from a string: it never contacts a server. It talks only through postMessage:
  page -> app  {t:'ready'} | {t:'in', d:<typed text>} | {t:'size', c, r} | {t:'copy', d:<selection>} | {t:'paste'}
  app -> page  {t:'out', b:<base64 bytes>} | {t:'reset'} | {t:'font', s:<px>} | {t:'focus'} | {t:'copy'}
Copy / paste go through the app's GTK clipboard (Ctrl+Shift+C / V, like the Linux terminal); the
page itself has no clipboard access.
"""
import base64
import json
import os

from gi.repository import Gtk, Gdk, GObject

from .winweb import WebView2Widget

_BASE_FONT = 14


def _assets_dir():
    """xterm.js files: MCD_ASSETS_DIR/xterm (development, CI) or assets/xterm next to the app (installed)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(os.environ.get("MCD_ASSETS_DIR", ""), "xterm"), os.path.join(here, "assets", "xterm"),
              os.path.join(os.path.dirname(here), "assets", "xterm")):
        if os.path.isfile(os.path.join(d, "xterm.js")):
            return d
    raise FileNotFoundError("xterm.js assets not found")

_PAGE_JS = r"""
var host = window.chrome.webview;
var term = new Terminal({scrollback: %(scrollback)d, fontSize: %(font)d, cursorBlink: true,
  fontFamily: "'Cascadia Mono', Consolas, 'Courier New', monospace",
  theme: {background: '#1e1e1e', foreground: '#e6e6e6'}});
var fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(document.getElementById('t'));
function send(o) { host.postMessage(JSON.stringify(o)); }
var last = '';
function resize() {
  try { fit.fit(); } catch (e) {}
  var k = term.cols + 'x' + term.rows;
  if (k !== last) { last = k; send({t: 'size', c: term.cols, r: term.rows}); }
}
new ResizeObserver(resize).observe(document.getElementById('t'));
term.onData(function (d) { send({t: 'in', d: d}); });
term.attachCustomKeyEventHandler(function (e) {
  if (e.type === 'keydown' && e.ctrlKey && e.shiftKey && (e.code === 'KeyC' || e.code === 'KeyV')) {
    send(e.code === 'KeyC' ? {t: 'copy', d: term.getSelection()} : {t: 'paste'});
    return false;
  }
  return true;
});
host.addEventListener('message', function (ev) {
  var m = JSON.parse(ev.data);
  if (m.t === 'out') {
    var b = atob(m.b), u = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
    term.write(u);
  } else if (m.t === 'reset') { term.reset(); }
  else if (m.t === 'font') { term.options.fontSize = m.s; resize(); }
  else if (m.t === 'focus') { term.focus(); }
  else if (m.t === 'copy') { send({t: 'copy', d: term.getSelection()}); }
});
resize();
send({t: 'ready'});
term.focus();
"""


def _asset(name):
    with open(os.path.join(_assets_dir(), name), encoding="utf-8") as f:
        return f.read()


def page_html(scrollback=10000, font=_BASE_FONT):
    css = _asset("xterm.css")
    js = _asset("xterm.js") + "\n" + _asset("addon-fit.js")
    # </script> inside the bundled code would end the inline block early; the bundles contain none
    return ("<!doctype html><html><head><meta charset='utf-8'><style>%s\n"
            "html,body{margin:0;height:100%%;background:#1e1e1e;overflow:hidden}"
            "#t{position:absolute;left:4px;top:4px;right:4px;bottom:4px}</style></head>"
            "<body><div id='t'></div><script>%s</script><script>%s</script></body></html>"
            % (css, js, _PAGE_JS % {"scrollback": scrollback, "font": font}))


class XtermTerminal(Gtk.Box):
    """Drop-in for the Vte.Terminal calls in terminal_panel (signals: commit, char-size-changed)."""
    __gsignals__ = {
        "commit": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
        "char-size-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self._cols, self._rows = 80, 24
        self._scale = 1.0
        self._scrollback = 10000
        self._ready = False
        self._queue = []
        self.web = WebView2Widget()
        self.web.allow_navigation = lambda uri: uri.startswith(("about:", "data:"))
        self.web.on_message = self._on_message
        self.pack_start(self.web, True, True, 0)
        self._loaded = False
        self.web.connect("realize", lambda *_: self._load())

    def _load(self):
        if not self._loaded:
            self._loaded = True
            self.web.load_html(page_html(self._scrollback, round(_BASE_FONT * self._scale)))

    def _post(self, obj):
        if self._ready:
            self.web.post_message(json.dumps(obj))
        else:
            self._queue.append(obj)

    def _on_message(self, text):
        try:
            m = json.loads(text)
        except (TypeError, ValueError):
            return
        t = m.get("t")
        if t == "ready":
            self._ready = True
            q, self._queue = self._queue, []
            for o in q:
                self._post(o)
        elif t == "in":
            d = str(m.get("d") or "")
            if d:
                self.emit("commit", d, len(d.encode("utf-8")))
        elif t == "size":
            c, r = int(m.get("c") or 80), int(m.get("r") or 24)
            if (c, r) != (self._cols, self._rows):
                self._cols, self._rows = c, r
                self.emit("char-size-changed", c, r)
        elif t == "copy":
            sel = str(m.get("d") or "")
            if sel:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(sel, -1)
        elif t == "paste":
            self.paste_clipboard()

    # ---- the Vte.Terminal API used by terminal_panel ------------------------------
    def set_scrollback_lines(self, n):
        self._scrollback = int(n)

    def set_mouse_autohide(self, _on):
        pass

    def feed(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        if data:
            self._post({"t": "out", "b": base64.b64encode(bytes(data)).decode("ascii")})

    def reset(self, *_):
        self._post({"t": "reset"})

    def get_column_count(self):
        return self._cols

    def get_row_count(self):
        return self._rows

    def copy_clipboard_format(self, *_):
        self._post({"t": "copy"})

    def paste_clipboard(self):
        def got(_cb, text):
            if text:
                self.emit("commit", text, len(text.encode("utf-8")))
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_text(got)

    def get_font_scale(self):
        return self._scale

    def set_font_scale(self, scale):
        self._scale = scale
        self._post({"t": "font", "s": max(6, round(_BASE_FONT * scale))})

    def grab_focus(self):
        self.web.grab_focus()
        self.web.focus_page()
        self._post({"t": "focus"})
