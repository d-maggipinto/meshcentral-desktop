# LOCALHOST TESTING ONLY (xvfb-run): navigation rail, grouped device tabs, My Server, backup.
import sys, ssl, time, os, zipfile
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, WebKit2
from mcdesktop import app as appmod, client, ui
from mcdesktop.desktop_panel import DesktopPanel
from mcdesktop.server_panel import MyServerPanel
appmod.APP_ID = rigenv.TEST_APP_ID
SP = os.path.dirname(os.path.abspath(__file__))
USER, PW = sys.argv[1], sys.argv[2]
def _ctx():
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c.check_hostname = False; c.verify_mode = 0; return c
client.http_ssl_context = _ctx
ui.message = lambda parent, title, text="", kind=None: print("   (dialog)", title, "|", text, flush=True)

def shot(win, name):
    w = win.get_window(); a = win.get_allocation()
    pb = Gdk.pixbuf_get_from_window(w, 0, 0, a.width, a.height)
    if pb: pb.savev(f"{SP}/{name}.png", "png", [], []); print("   screenshot:", name, flush=True)

class T(appmod.App):
    def do_activate(self):
        orig = self.web_context
        def wc():
            c = orig(); c.set_tls_errors_policy(WebKit2.TLSErrorsPolicy.IGNORE); return c
        self.web_context = wc
        ctrl = client.ControlConnection("https://127.0.0.1:8443", USER, PW)
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); self.main_win.resize(1400, 860); GLib.timeout_add(2000, self.s1); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def s1(self):
        mw = self.main_win
        print(f"[{USER}] rail:", list(mw._nav_buttons), "| title:", mw.headerbar.get_title(), flush=True)
        if USER != "admin":
            self.quit(); return False
        node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        mw._reselect_silent(node["_id"]); mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(1500, self.s2); return False
    def s2(self):
        mw = self.main_win
        built = [t["label"] for t in mw._device_tabs if t["panel"] is not None]
        print("groups:", {g: mw._group_nbs[g].get_n_pages() for g in mw._group_nbs}, "| built after open:", built,
              "->", "PASS" if built == ["General"] else "FAIL", flush=True)
        shot(mw, "ui-devices-overview")
        mw.goto_device_tab("Desktop"); self.t0 = time.time()
        GLib.timeout_add(500, self.s3); return False
    def s3(self):
        mw = self.main_win
        p = mw._current_desktop_panel()
        if isinstance(p, DesktopPanel) and p._connected and not p._cover.get_visible():
            print(f"Desktop via Remote group connected in {time.time()-self.t0:.1f}s | visible group:",
                  mw.group_stack.get_visible_child_name(), flush=True)
            GLib.timeout_add(800, self.s4); return False
        if time.time() - self.t0 > 30: print("desktop never connected"); self.quit(); return False
        return True
    def s4(self):
        mw = self.main_win
        shot(mw, "ui-devices-remote-desktop")
        mw._enter_desktop_fullscreen(mw._current_desktop_panel())
        GLib.timeout_add(1500, self.s5); return False
    def s5(self):
        mw = self.main_win
        print("fullscreen hides rail:", not mw.rail.get_visible(), "| group bar hidden:", not mw.group_bar.get_visible(), flush=True)
        mw._exit_desktop_fullscreen()
        mw.show_page("server"); GLib.timeout_add(3000, self.s6); return False
    def s6(self):
        mw = self.main_win; p = mw._pages["server"]
        tiles = [" ".join(l.get_text() for l in c.get_child().get_child().get_children()) for c in p.tiles.get_children()]
        print("My Server: title", mw.headerbar.get_title(), "| cpu:", p.cpu_label.get_text(), "| mem:", p.mem_label.get_text(), flush=True)
        print("  tiles:", tiles, flush=True)
        shot(mw, "ui-my-server-general")
        p.stack.set_visible_child_name("stats"); GLib.timeout_add(2500, self.s7); return False
    def s7(self):
        p = self.main_win._pages["server"]
        print("  stats:", p.chart_info.get_text(), flush=True)
        shot(self.main_win, "ui-my-server-stats")
        p.stack.set_visible_child_name("console"); p.console_entry.set_text("info"); p._console_send()
        GLib.timeout_add(2000, self.s8); return False
    def s8(self):
        p = self.main_win._pages["server"]; b = p.console_view.get_buffer()
        txt = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        print("  console 'info' ->", "PASS" if "meshVersion" in txt else "FAIL", "|", txt.splitlines()[1:3], flush=True)
        self.dest = f"{SP}/backup-test.zip"
        if os.path.exists(self.dest): os.remove(self.dest)
        self.t0 = time.time()
        p._session().fetch("/backup.zip", self.dest, None, self.s9, timeout=300)
        return False
    def s9(self, err):
        ok = False
        try: ok = zipfile.is_zipfile(self.dest); n = len(zipfile.ZipFile(self.dest).namelist())
        except Exception as ex: n = ex
        print(f"  backup.zip: err={err} valid_zip={ok} entries={n} size={os.path.getsize(self.dest) if os.path.exists(self.dest) else 0} in {time.time()-self.t0:.1f}s", flush=True)
        self.quit()
T().run([])
