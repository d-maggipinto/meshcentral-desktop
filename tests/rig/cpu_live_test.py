# LOCALHOST TESTING ONLY (xvfb-run): CPU chart fills from live serverstats on a NeDB server.
import sys, ssl, os, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib
from mcdesktop import app as appmod, client
appmod.APP_ID = rigenv.TEST_APP_ID
SP = os.path.dirname(os.path.abspath(__file__))
class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); self.main_win.resize(1400, 800); GLib.timeout_add(1000, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win; mw.show_page("server"); p = self.p = mw._pages["server"]
        p.stack.set_visible_child_name("stats"); p.chart_kind.set_active(2)
        GLib.timeout_add(42000, self.done); return False
    def done(self):
        p = self.p
        print("live CPU readings:", [(round(t - time.time()), v) for t, v in p._cpu_live], flush=True)
        print("info:", p.chart_info.get_tooltip_text(), flush=True)
        a = self.main_win.get_allocation()
        Gdk.pixbuf_get_from_window(self.main_win.get_window(), 0, 0, a.width, a.height).savev(f"{SP}/cpu-live.png", "png", [], [])
        self.quit(); return False
T().run([])
