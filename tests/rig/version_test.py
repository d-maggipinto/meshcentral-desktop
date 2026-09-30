# LOCALHOST TESTING ONLY (xvfb-run): My Server version check + server warnings rendering.
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client, ui, server_panel
appmod.APP_ID = rigenv.TEST_APP_ID
GOT = []
server_panel.MyServerPanel._version_dialog = lambda self, msg: GOT.append((round(time.time() - T.t0, 1), msg))
ui.message = lambda parent, title, text="", kind=None: GOT.append(("DIALOG", title, text))

class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win
        print("warnings cached at sign-in:", mw.ctrl.serverwarnings, flush=True)
        mw.show_page("server"); GLib.timeout_add(1500, self.check); return False
    def check(self):
        p = self.main_win._pages["server"]
        T.t0 = time.time(); p.check_version()
        print("progress visible while checking:", p.progress.get_visible(), "|", p.progress.get_text(), flush=True)
        GLib.timeout_add(500, self.wait); return False
    def wait(self):
        if GOT or time.time() - T.t0 > 35:
            print("VERSION CHECK ->", GOT, flush=True)
            p = self.main_win._pages["server"]
            p._render_warnings([{"msg": 'Failed to sign "MeshService.exe": AggregateError', "id": 22,
                                 "args": ["MeshService.exe", "AggregateError"]}, "Plain string warning"])
            texts = [c.get_text() for c in p.warn_box.get_children()]
            print("WARNINGS section visible:", p.warn_head.get_visible(), "|", texts, flush=True)
            self.quit(); return False
        return True
T().run([])
