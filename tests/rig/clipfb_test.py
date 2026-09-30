# LOCALHOST TESTING ONLY: remote->local clipboard via the eval fallback (getclip deliberately dropped).
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, WebKit2
from mcdesktop import app as appmod, client
from mcdesktop.desktop_panel import DesktopPanel
appmod.APP_ID = rigenv.TEST_APP_ID

MARK = "mcd-fallback-%d" % int(time.time())
_orig_send = client.ControlConnection.send_node_msg
def send_node_msg(self, nodeid, mtype, **kw):
    if mtype == "getclip":
        print("   (test) dropping getclip to simulate the silent service-agent failure", flush=True); return
    return _orig_send(self, nodeid, mtype, **kw)
client.ControlConnection.send_node_msg = send_node_msg
DELIVERED = []
_orig_got = DesktopPanel._clip_got_text
def _got(self, data):
    DELIVERED.append((round(time.time() - T.t0, 2), data)); return _orig_got(self, data)
DesktopPanel._clip_got_text = _got
_orig_reply = DesktopPanel._on_clip_eval_reply
def _reply(self, value):
    print(f"   eval reply @{time.time() - T.t0:.2f}s: {str(value)[:70]}", flush=True); return _orig_reply(self, value)
DesktopPanel._on_clip_eval_reply = _reply

class T(appmod.App):
    def do_activate(self):
        orig = self.web_context
        def wc():
            c = orig(); c.set_tls_errors_policy(WebKit2.TLSErrorsPolicy.IGNORE); return c
        self.web_context = wc
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        self.console_seen = []
        def ready():
            if ctrl.userinfo:
                ctrl.on("msg", lambda m: m.get("type") == "console" and self.console_seen.append(m.get("value")))
                self.on_login(ctrl); GLib.timeout_add(2000, self.pick); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready)
        self.hold()
    def panel(self):
        return next(t["panel"] for t in self.main_win._device_tabs if t["label"] == "Desktop")
    def pick(self):
        mw = self.main_win
        self.node = node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(500, lambda: (mw.goto_device_tab("Desktop"), False)[1])
        GLib.timeout_add(500, self.wait)
        return False
    def wait(self):
        p = self.panel()
        if isinstance(p, DesktopPanel) and p._connected:
            # put a known value into the REMOTE clipboard (setclip works on the rig agent)
            self.main_win.ctrl.send_node_msg(self.node["_id"], "setclip", data=MARK)
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("local-before", -1)
            GLib.timeout_add(1500, self.copy)
            return False
        return True
    def copy(self):
        self.t0 = T.t0 = time.time()
        self.panel()._clip_from_remote()
        GLib.timeout_add(250, self.check)
        return False
    def check(self):
        p = self.panel()
        el = time.time() - self.t0
        if DELIVERED or el > 14:
            print("delivered by fallback:", DELIVERED, "->", "PASS" if DELIVERED and DELIVERED[0][1] == MARK else "FAIL")
            print("status:", p.status.get_text(), "| note shown:", p.info.get_revealed(), p.info_label.get_text()[:80])
            print("console msgs seen by session:", len(self.console_seen),
                  "| any contain clipboard text outside eval replies:",
                  any(MARK in str(v) and "MCDCLIP1" not in str(v) for v in self.console_seen))
            self.quit(); return False
        return True

T().run([])
