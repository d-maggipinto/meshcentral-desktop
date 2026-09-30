# LOCALHOST TESTING ONLY: drive connect / reconnect / disconnect / connect / cancel on the real panel.
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib, WebKit2
from mcdesktop import app as appmod, client
from mcdesktop.desktop_panel import DesktopPanel
_orig = DesktopPanel._on_script_dialog
def _logged(self, view, dialog):
    print("   >>> page raised script dialog:", dialog.get_dialog_type().value_nick, flush=True)
    return _orig(self, view, dialog)
DesktopPanel._on_script_dialog = _logged

STEPS = []   # (name, action, expected_phase, timeout_s)

class T(appmod.App):
    def do_activate(self):
        orig = self.web_context
        def wc():
            c = orig(); c.set_tls_errors_policy(WebKit2.TLSErrorsPolicy.IGNORE); return c
        self.web_context = wc
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(2000, self.pick); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready)
        self.hold()
    def panel(self):
        return next(t["panel"] for t in self.main_win._device_tabs if t["label"] == "Desktop")
    def pick(self):
        mw = self.main_win
        node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(500, lambda: (mw.goto_device_tab("Desktop"), False)[1])
        self.steps = [
            ("initial connect",           None,                                   "revealed", 25),
            ("RAW NAVIGATE while connected (old 2.9.0 behaviour)", lambda p: p.view.load_uri(p.app.ctrl.server.url + "/"), "loading", 4),
            ]
        _unused = [
            ("DISCONNECT",                lambda p: p._toggle_connect(),          "idle",      5),
            ("CONNECT (quick path)",      lambda p: p._toggle_connect(),          "revealed", 25),
            ("RECONNECT then CANCEL",     lambda p: (p.start_flow(), GLib.timeout_add(600, lambda: (p._toggle_connect(), False)[1])), "idle", 5),
            ("CONNECT after cancel",      lambda p: p._toggle_connect(),          "revealed", 25),
        ]
        self.results = []
        GLib.timeout_add(1500, self.next_step)
        return False
    def state(self, p):
        if p._phase == "connected" and not p._cover.get_visible():
            return "revealed"
        return p._phase
    def next_step(self):
        if not self.steps:
            print("\nRESULTS:"); [print(" ", r) for r in self.results]; self.quit(); return False
        self.cur = self.steps.pop(0)
        name, act, want, tmo = self.cur
        p = self.panel()
        if act:
            act(p)
        self.t0 = time.time(); self.last = None
        GLib.timeout_add(1500 if want == "idle" else 100, self.watch)
        return False
    def watch(self):
        p = self.panel()
        name, act, want, tmo = self.cur
        el = time.time() - self.t0
        st = self.state(p)
        line = f"{st} | btn={p.connect_btn.get_label()} | cover={'ON' if p._cover.get_visible() else 'off'}:{p._cover_label.get_text()!r}"
        if line != self.last:
            print(f"  [{name}] {el:5.2f}s {line}", flush=True); self.last = line
        if st == want and (want != "idle" or el > 1.4):
            self.results.append(f"PASS  {name}  ({el:.1f}s)  btn={p.connect_btn.get_label()}")
            GLib.timeout_add(1500, self.next_step); return False
        if el > tmo:
            self.results.append(f"FAIL  {name}  state={st} btn={p.connect_btn.get_label()}")
            GLib.timeout_add(500, self.next_step); return False
        return True

T().run([])
