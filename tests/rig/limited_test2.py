# LOCALHOST TESTING ONLY (xvfb-run). Restricted account: view-only rights, no site rights.
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib, WebKit2
from mcdesktop import app as appmod, client, rights
from mcdesktop.desktop_panel import DesktopPanel
appmod.APP_ID = rigenv.TEST_APP_ID
USER, PW = sys.argv[1], sys.argv[2]

class T(appmod.App):
    def do_activate(self):
        orig = self.web_context
        def wc():
            c = orig(); c.set_tls_errors_policy(WebKit2.TLSErrorsPolicy.IGNORE); return c
        self.web_context = wc
        ctrl = client.ControlConnection("https://127.0.0.1:8443", USER, PW)
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(2000, self.pick); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def tab(self, label): return next(t for t in self.main_win._device_tabs if t["label"] == label)
    def pick(self):
        mw = self.main_win
        node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        caps = rights.node_caps(mw.ctrl, mw.meshes, node)
        print(f"[{USER}] siteadmin={mw.ctrl.userinfo.get('siteadmin')} node rights={caps.rights}", flush=True)
        print("  device tabs allowed:", {t["label"]: t["allowed"] for t in mw._device_tabs}, flush=True)
        a = mw.actions
        print("  actions: run=%s power=%s" % (a.buttons["run"].get_sensitive(), a.buttons["power"].get_sensitive()),
              {k: b.get_sensitive() for k, b in a.items.items()}, flush=True)
        mw.goto_device_tab("Terminal")
        GLib.timeout_add(500, self.denied_text)
        return False
    def denied_text(self):
        c = self.tab("Terminal")["container"].get_children()
        print("  Terminal tab text:", repr(c[0].get_text() if c and isinstance(c[0], Gtk.Label) else c), flush=True)
        mw = self.main_win; mw.show_server()
        print("  server tabs:", [(mw.server_notebook.get_tab_label(p).get_text(), mw.server_notebook.get_tab_label(p).get_sensitive(), type(p).__name__) for p in mw._server_panels], flush=True)
        mf = mw._server_panels[0]
        print("  My Files allowed:", getattr(mf, "allowed", None), flush=True)
        mw.content.set_visible_child_name("device"); mw.goto_device_tab("Notes")
        GLib.timeout_add(1500, self.notes)
        return False
    def notes(self):
        n = self.tab("Notes")["panel"]
        print("  Notes editable:", n.view.get_editable(), "| status:", repr(n.status.get_text()), flush=True)
        self.main_win.goto_device_tab("Desktop"); self.t0 = time.time()
        GLib.timeout_add(500, self.desk)
        return False
    def desk(self):
        p = self.tab("Desktop")["panel"]
        if isinstance(p, DesktopPanel) and p._connected and not p._cover.get_visible():
            GLib.timeout_add(1000, lambda: (self.desk_report(p), False)[1]); return False
        if isinstance(p, DesktopPanel) and int(time.time() - self.t0) % 5 == 0:
            p._js("(function(){var d=document.getElementById('deskstatus');return JSON.stringify({status:d?d.innerText:null,state:(typeof desktop!=='undefined'&&desktop)?desktop.State:null});})()",
                  lambda v: print("   viewer:", v, "| phase:", p._phase, flush=True))
        if time.time() - self.t0 > 40:
            print("  Desktop: never connected; cover:", p._cover_label.get_text() if isinstance(p, DesktopPanel) else p, flush=True)
            self.quit(); return False
        return True
    def desk_report(self, p):
        print("  Desktop connected | input_allowed:", p.caps.desktop_input,
              "| CAD/paste/type sensitive:", [w.get_sensitive() for w in p._input_widgets],
              "| copy-from-remote sensitive:", p._ctrl_widgets[3].get_sensitive(),
              "| hotkeys switch sensitive:", p.hotkeys.get_sensitive(), "| status:", repr(p.status.get_text()), flush=True)
        self.quit()
T().run([])
