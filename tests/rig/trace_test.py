# LOCALHOST TESTING ONLY (xvfb-run): My Server -> Trace.
import sys, ssl, os, time, subprocess
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib
from mcdesktop import app as appmod, client, server_panel
appmod.APP_ID = rigenv.TEST_APP_ID
SP = os.path.dirname(os.path.abspath(__file__))
USER, PW = sys.argv[1], sys.argv[2]
SHOWN = []
server_panel.MyServerPanel._text_dialog = lambda self, title, text, **k: SHOWN.append((title, text[:80]))
class FakeChooser:
    def __init__(self, *a): pass
    def set_current_name(self, n): pass
    def set_do_overwrite_confirmation(self, b): pass
    def run(self): return Gtk.ResponseType.ACCEPT
    def get_filename(self): return SP + "/servertrace-test.csv"
    def destroy(self): pass
server_panel.Gtk.FileChooserNative.new = staticmethod(lambda *a: FakeChooser())

class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", USER, PW)
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); self.main_win.resize(1400, 820); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win
        if "server" not in mw._nav_buttons:
            print(f"[{USER}] no My Server section (expected for accounts without server rights)", flush=True); self.quit(); return False
        mw.show_page("server"); self.p = p = mw._pages["server"]
        p.stack.set_visible_child_name("trace")
        if p.trace_tree is None:
            print(f"[{USER}] Trace tab: full-admin-only message shown", flush=True); self.quit(); return False
        print("sources at sign-in:", mw.ctrl.tracesources, "| status:", p.trace_status.get_text(), flush=True)
        mw.ctrl.send({"action": "traceinfo", "traceSources": ["web", "webrequest"]})
        GLib.timeout_add(1500, self.traffic); return False
    def traffic(self):
        print("status after enabling:", self.p.trace_status.get_text(), flush=True)
        for path in ("/", "/favicon.ico", "/nonexistent-mcd-test"):
            subprocess.run(["curl", "-sk", "-o", "/dev/null", "https://127.0.0.1:8443" + path])
        GLib.timeout_add(2000, self.check); return False
    def check(self):
        p = self.p
        rows = [tuple(r)[:3] for r in p.trace_store]
        print(f"trace rows: {len(rows)} | first: {rows[:3]}", flush=True)
        a = self.main_win.get_allocation()
        Gdk.pixbuf_get_from_window(self.main_win.get_window(), 0, 0, a.width, a.height).savev(f"{SP}/ui-trace.png", "png", [], [])
        # sort by Source descending, then open the first row: must show THAT row's event
        col = p.trace_tree.get_column(1); col.clicked(); col.clicked()
        model = p.trace_tree.get_model(); first = model[Gtk.TreePath(0)]
        p._trace_show(Gtk.TreePath(0))
        print("after sort, row0 source:", first[1], "| dialog opened for:", SHOWN[-1][0] if SHOWN else None, flush=True)
        p._trace_download()
        print("CSV lines:", len(open(SP + "/servertrace-test.csv").read().splitlines()), flush=True)
        self.main_win.ctrl.send({"action": "traceinfo", "traceSources": []})
        GLib.timeout_add(1500, self.done); return False
    def done(self):
        print("status after Delete:", self.p.trace_status.get_text(), "| cached:", self.main_win.ctrl.tracesources, flush=True)
        self.quit(); return False
T().run([])
