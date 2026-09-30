# LOCALHOST TESTING ONLY, run under xvfb-run (own X display): General agent rows, Services speed,
# AltGr filter (viewer send STUBBED - nothing reaches the rig agent), hotkey grab, Ctrl+Alt+F.
import sys, ssl, time, json
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, WebKit2
from mcdesktop import app as appmod, client
from mcdesktop.desktop_panel import DesktopPanel
from mcdesktop.tools_panel import ServicesPanel
appmod.APP_ID = rigenv.TEST_APP_ID

GRABS = []
_orig_upd = DesktopPanel._kb_update
def upd(self):
    before = self._kb_seat is not None
    r = _orig_upd(self)
    after = self._kb_seat is not None
    if before != after: GRABS.append((round(time.time(), 2), "GRAB" if after else "UNGRAB"))
    return r
DesktopPanel._kb_update = upd

class Ev:  # minimal key event for MainWindow._on_key
    def __init__(self, keyval, state): self.keyval, self.state = keyval, state

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
    def tab(self, label):
        return next(t["panel"] for t in self.main_win._device_tabs if t["label"] == label)
    def pick(self):
        mw = self.main_win
        node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(800, self.general)
        return False
    def general(self):
        g = self.tab("General")
        rows = {}
        kids = g.grid.get_children()[::-1]
        for i in range(0, len(kids) - 1, 2):
            rows[kids[i].get_text()] = kids[i + 1].get_text()
        print("GENERAL: Mesh agent =", repr(rows.get("Mesh agent")), "| Agent core =", repr(rows.get("Agent core")),
              "| old 'Agent version' row present:", "Agent version" in rows, flush=True)
        self.t_svc = time.time()
        self.main_win.goto_device_tab("Services")
        GLib.timeout_add(100, self.services)
        return False
    def services(self):
        p = self.tab("Services")
        txt = p.count.get_text() if isinstance(p, ServicesPanel) else ""
        if "services" in txt or time.time() - self.t_svc > 30:
            some = [tuple(r) for r in p.store][:0]
            states = {}
            for r in p.store: states[r[2]] = states.get(r[2], 0) + 1
            ssh = [tuple(r) for r in p.store if r[3] in ("ssh", "cron")]
            print(f"SERVICES: '{txt}' after {time.time() - self.t_svc:.2f}s | states={states} | sample={ssh}", flush=True)
            self.main_win.goto_device_tab("Desktop")
            GLib.timeout_add(500, self.desk_wait)
            return False
        return True
    def desk_wait(self):
        p = self.tab("Desktop")
        if isinstance(p, DesktopPanel) and p._connected and not p._cover.get_visible():
            GLib.timeout_add(800, self.altgr)
            return False
        return True
    def altgr(self):
        p = self.tab("Desktop")
        js = ("(function(){var m=desktop.m,sent=[],os=m.send;m.send=function(x){sent.push(x.length);};"
              "function E(k,c,kc){return {key:k,code:c,keyCode:kc,ctrlKey:false,altKey:false,shiftKey:false,"
              "preventDefault:function(){},stopPropagation:function(){},getModifierState:function(){return false;}};}"
              "var a=E('AltGraph','AltRight',225);m.handleKeyDown(a);var n1=sent.length;"
              "var at=E('@','Semicolon',64);m.handleKeyDown(at);m.handleKeys(at);var n2=sent.length;"
              "m.handleKeyUp(at);m.handleKeyUp(a);var n3=sent.length;"
              "var alt=E('Alt','AltLeft',18);m.handleKeyDown(alt);var n4=sent.length;m.handleKeyUp(alt);"
              "m.send=os;return JSON.stringify({patched:!!m.__mcdKeys,afterAltGrDown:n1,afterAt:n2-n1,afterUps:n3-n2,plainAltStillSent:n4-n3});})()")
        p._js(js, lambda v: (print("ALTGR:", v, "(want afterAltGrDown=0, afterAt=1, afterUps=1, plainAltStillSent=1)", flush=True),
                             GLib.timeout_add(300, self.grab)))
        return False
    def grab(self):
        p = self.tab("Desktop"); w = self.main_win
        w.present(); w.get_window().focus(Gdk.CURRENT_TIME)
        p.view.grab_focus()
        GLib.timeout_add(1500, self.grab_check)
        return False
    def grab_check(self):
        p = self.tab("Desktop")
        print("HOTKEYS: view focused:", p.view.has_focus(), "| grabbed:", p._kb_seat is not None, flush=True)
        p.hotkeys.set_active(False)
        print("         switch off -> grabbed:", p._kb_seat is not None, flush=True)
        p.hotkeys.set_active(True)
        GLib.timeout_add(1500, self.fs)
        return False
    def fs(self):
        p = self.tab("Desktop"); mw = self.main_win
        print("         switch on  -> grabbed:", p._kb_seat is not None, "| grab/ungrab transitions so far:", len(GRABS), flush=True)
        CA = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK
        r1 = mw._on_key(None, Ev(Gdk.KEY_f, CA))
        fs1 = getattr(mw, "_desk_fs", False)
        hint = p._hint.get_text() if p._hint_rev.get_reveal_child() else None
        r_esc = mw._on_key(None, Ev(Gdk.KEY_Escape, 0))
        r2 = mw._on_key(None, Ev(Gdk.KEY_F, CA))
        print(f"CTRL+ALT+F: handled={r1} fullscreen={fs1} hint={hint!r} | Esc handled by app={r_esc} (want False) "
              f"| again handled={r2} fullscreen={getattr(mw, '_desk_fs', False)}", flush=True)
        GLib.timeout_add(1500, self.disc)
        return False
    def disc(self):
        p = self.tab("Desktop")
        p._toggle_connect()
        GLib.timeout_add(800, lambda: (print("DISCONNECT -> grabbed:", p._kb_seat is not None, "| transitions:", GRABS, flush=True), self.quit(), False)[2])
        return False

T().run([])
