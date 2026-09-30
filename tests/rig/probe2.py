# LOCALHOST TESTING ONLY: drives the real MainWindow + DesktopPanel against the local rig.
import sys, ssl
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
        if isinstance(p, DesktopPanel) and p._connected:
            GLib.timeout_add(2500, self.probe)
            return False
        if self.t > 45: print("never connected; status:", p.status.get_text() if isinstance(p, DesktopPanel) else p); self.quit(); return False
        return True
    PROBE = ("(function(){var m=desktop.m;return JSON.stringify({sl:m.ScalingLevel,sw:m.ScreenWidth,sh:m.ScreenHeight,"
             "cw:m.Canvas.canvas.width,ch:m.Canvas.canvas.height,ft:m.FrameRateTimer,cl:m.CompressionLevel,it:m.ImageType,"
             "bytes:(m.bytesReceived||m.BytesIn||null)});})()")
    HOOK = ("(function(){var m=desktop.m;if(!window.__mcdHook){window.__b=0;window.__t=0;var o=m.ProcessData;"
            "m.ProcessData=function(d){window.__b+=(d.byteLength||d.length||0);return o.apply(this,arguments);};"
            "var od=m.ProcessBinaryCommand;m.ProcessBinaryCommand=function(c){window.__b+=arguments[1]||0;if(c==3)window.__t++;return od.apply(this,arguments);};window.__mcdHook=1;}"
            "return typeof m.ProcessData;})()")
    def probe(self):
        p = self.panel(); self.p = p
        p._js(self.HOOK, lambda v: print("hook", v, flush=True))
        self.runs = [("1024", 1024), ("512", 512), ("256", 256)]
        GLib.timeout_add(500, self.next_run)
        return False
    def next_run(self):
        if not self.runs:
            self.quit(); return False
        name, sc = self.runs.pop(0)
        p = self.p
        p._js(f"desktop.m.SendCompressionLevel(1,50,{sc},100);'ok'")
        def start():
            p._js("window.__b=0;window.__t=0;'ok'")
            for k in range(5):
                GLib.timeout_add(1000*k, lambda: (p._js("desktop.m.SendRefresh();'ok'"), False)[1])
            GLib.timeout_add(5500, lambda: (p._js("JSON.stringify({bytes:window.__b,tiles:window.__t,sw:desktop.m.ScreenWidth})",
                lambda v: (print("SCALE", name, v, flush=True), GLib.timeout_add(300, self.next_run))), False)[1])
            return False
        GLib.timeout_add(2000, start)
        return False
    def fs(self):
        self.panel()._toggle_fullscreen()
        GLib.timeout_add(4000, self.measure)
        return False
    def measure(self):
        self.panel()._js(GEOM, lambda v: (print("FULLSCREEN", v, flush=True), GLib.timeout_add(500, self.quit)))
        return False

T().run([])
