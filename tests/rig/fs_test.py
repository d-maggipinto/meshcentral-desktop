# LOCALHOST TESTING ONLY: drives the real MainWindow + DesktopPanel against the local rig.
import sys, ssl
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib, WebKit2
from mcdesktop import app as appmod, client
from mcdesktop.desktop_panel import DesktopPanel
appmod.APP_ID = rigenv.TEST_APP_ID

GEOM = ("(function(){function r(id){var e=document.getElementById(id);if(!e)return null;"
        "var b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)];}"
        "var d=document.getElementById('Desk');"
        "return JSON.stringify({vp:[innerWidth,innerHeight],area3x:r('deskarea3x'),parent:r('DeskParent'),desk:r('Desk'),"
        "focusVisible:(function(){var f=document.getElementById('DeskFocus');return f?getComputedStyle(f).display:null;})(),"
        "canvas:d?[d.width,d.height]:null,comp:window.__mcdComp,status:(document.getElementById('deskstatus')||{}).innerText});})()")

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
    def pick(self):
        mw = self.main_win
        node = next(iter(mw.nodes.values()))
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(500, lambda: (mw.goto_device_tab("Desktop"), False)[1])
        self.t = 0; GLib.timeout_add(1000, self.wait)
        return False
    def panel(self):
        return next(t["panel"] for t in self.main_win._device_tabs if t["label"] == "Desktop")
    def wait(self):
        self.t += 1
        p = self.panel()
        if isinstance(p, DesktopPanel) and p._connected:
            p._js(GEOM, lambda v: print("WINDOWED  ", v, flush=True))
            GLib.timeout_add(1000, self.fs)
            return False
        if self.t > 45: print("never connected; status:", p.status.get_text() if isinstance(p, DesktopPanel) else p); self.quit(); return False
        return True
    def fs(self):
        self.panel()._toggle_fullscreen()
        GLib.timeout_add(4000, self.measure)
        return False
    def measure(self):
        self.panel()._js(GEOM, lambda v: (print("FULLSCREEN", v, flush=True), GLib.timeout_add(500, self.quit)))
        return False

T().run([])
