# LOCALHOST TESTING ONLY (xvfb-run): Server Events readability + plain-text tooltips.
import sys, ssl, os
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
                self.on_login(ctrl); self.main_win.resize(1280, 860); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        self.main_win.show_page("events"); GLib.timeout_add(3000, self.check); return False
    def check(self):
        mw = self.main_win; p = mw._pages["events"]
        print("rows:", len(p.store), "| column widths:", [(c.get_title(), c.get_width()) for c in p.tree.get_columns()], flush=True)
        # find a row with code-like text and run the tooltip handler on it
        idx = next((i for i, r in enumerate(p.store) if "eval" in r[3] or "<" in r[3] or "&" in r[3]), 0)
        area = p.tree.get_cell_area(Gtk.TreePath(idx), p.tree.get_column(3))
        tip = Gtk.Tooltip if False else None
        ok, x, y, model, path, it = p.tree.get_tooltip_context(area.x + 5, area.y + 5 + p.tree.convert_tree_to_widget_coords(0, 0)[1] * 0, False)
        print("tooltip context ok:", ok, "| row text starts:", (model[it][3][:70] if ok else None), flush=True)
        w = mw.get_window(); a = mw.get_allocation()
        Gdk.pixbuf_get_from_window(w, 0, 0, a.width, a.height).savev(f"{SP}/ui-server-events.png", "png", [], [])
        self.quit(); return False
T().run([])
