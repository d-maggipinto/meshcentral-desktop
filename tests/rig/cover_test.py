# LOCALHOST TESTING ONLY: drives the real MainWindow + DesktopPanel against the local rig.
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib, WebKit2
from mcdesktop import app as appmod, client
from mcdesktop.desktop_panel import DesktopPanel

GEOM = ("(function(){function r(id){var e=document.getElementById(id);if(!e)return null;"
        "var b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)];}"
        "var d=document.getElementById('Desk');"
        "return JSON.stringify({vp:[innerWidth,innerHeight],area3x:r('deskarea3x'),parent:r('DeskParent'),desk:r('Desk'),"
        "focusVisible:(function(){var f=document.getElementById('DeskFocus');return f?getComputedStyle(f).display:null;})(),"
        "canvas:d?[d.width,d.height]:null,status:(document.getElementById('deskstatus')||{}).innerText});})()")

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
        if not isinstance(p, DesktopPanel):
            return True
        if not hasattr(self, "t0"):
            self.t0 = time.time(); self.log = []
            GLib.timeout_add(100, self.watch)
        return False
    def watch(self):
        p = self.panel()
        el = round(time.time() - self.t0, 2)
        state = ("cover:" + ("ON " if p._cover.get_visible() else "off") + " | " + p._cover_label.get_text()
                 + " | status=" + p.status.get_text())
        if not self.log or self.log[-1][1] != state:
            self.log.append((el, state)); print(f"{el:6.2f}s  {state}", flush=True)
        if not p._cover.get_visible() and p._connected:
            GLib.timeout_add(3000, self.after)
            return False
        if el > 40:
            print("TIMEOUT"); self.quit(); return False
        return True
    def after(self):
        p = self.panel()
        p._js("JSON.stringify({comp:window.__mcdComp,native:window.__mcdNative,sl:desktop.m.ScalingLevel,disp:desktop.m.displays,dispVisible:null})",
              lambda v: (print("AFTER", v, "| display combo visible:", p.display.get_visible(), flush=True), self.quit()))
        return False

T().run([])
