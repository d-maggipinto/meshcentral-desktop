# LOCALHOST TESTING ONLY (xvfb-run): My Server Stats charts, ranges, gaps, hover, CSV.
import sys, ssl, os, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib
from mcdesktop import app as appmod, client, server_panel
appmod.APP_ID = rigenv.TEST_APP_ID
SP = os.path.dirname(os.path.abspath(__file__))
class FakeChooser:
    def __init__(self, *a): pass
    def set_current_name(self, n): pass
    def set_do_overwrite_confirmation(self, b): pass
    def run(self): return Gtk.ResponseType.ACCEPT
    def get_filename(self): return SP + "/ServerStats-test.csv"
    def destroy(self): pass
server_panel.Gtk.FileChooserNative.new = staticmethod(lambda *a: FakeChooser())

def shot(win, name):
    a = win.get_allocation(); Gdk.pixbuf_get_from_window(win.get_window(), 0, 0, a.width, a.height).savev(f"{SP}/{name}.png", "png", [], [])

class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); self.main_win.resize(1500, 900); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win; mw.show_page("server")
        self.p = mw._pages["server"]; self.p.stack.set_visible_child_name("stats")
        self.p.chart_range.set_active(2)   # last day: more samples incl. restarts
        self.steps = [("connections", 0), ("memory", 1), ("cpu", 2), ("in", 3), ("out", 4)]
        GLib.timeout_add(2500, self.next); return False
    def next(self):
        p = self.p
        if not self.steps:
            p.chart_kind.set_active(0); p.chart_log.set_active(True)
            GLib.timeout_add(500, self.fin); return False
        kind, i = self.steps.pop(0)
        p.chart_kind.set_active(i)
        s = server_panel.build_series(p._timeline, kind)
        gaps = sum(1 for _n, _c, pts in s[:1] for _t, v in pts if v is None)
        print(f"{kind:12s} series={[n for n, _c, _p in s]} points(first)={len(s[0][2]) if s else 0} gaps={gaps}", flush=True)
        if kind == "connections":
            a = p.chart.get_allocation(); p.chart.hover = a.width * 0.7; p.chart.queue_draw()
        GLib.timeout_add(400, lambda k=kind: (shot(self.main_win, f"stats-{k}"), setattr(p.chart, "hover", None), self.next(), False)[3])
        return False
    def fin(self):
        shot(self.main_win, "stats-connections-log")
        self.p._download_csv()
        lines = open(SP + "/ServerStats-test.csv").read().splitlines()
        print("CSV rows:", len(lines) - 1, "| header:", lines[0][:80], "| last:", lines[-1][:80], flush=True)
        print("info:", self.p.chart_info.get_text(), flush=True)
        self.quit(); return False
T().run([])
