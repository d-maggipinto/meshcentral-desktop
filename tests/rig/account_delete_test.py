# LOCALHOST TESTING ONLY (xvfb-run): My Account end to end on the throwaway account "acctest".
import sys, ssl, os, time, base64, hmac, hashlib, struct, json, subprocess
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
from mcdesktop import app as appmod, client, ui, account_panel as ap
appmod.APP_ID = rigenv.TEST_APP_ID
SP = os.path.dirname(os.path.abspath(__file__))
def _ctx():
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c.check_hostname = False; c.verify_mode = 0; return c
client.http_ssl_context = _ctx; ap.http_ssl_context = _ctx
MSG = []
ui.message = lambda parent, title, text="", kind=None: MSG.append(title)
ui.confirm = lambda *a, **k: True
def totp(secret):
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7fffffff) % 1000000)
def login_ok(user, pw):
    import websocket
    b = lambda s: base64.b64encode(s.encode()).decode()
    try:
        w = websocket.create_connection("wss://127.0.0.1:8443/control.ashx", header=[f"x-meshauth: {b(user)},{b(pw)}"], sslopt={"cert_reqs": 0}, timeout=5)
        end = time.time() + 4
        while time.time() < end:
            m = json.loads(w.recv())
            if m.get("action") == "userinfo": return True
            if m.get("action") == "close": return False
    except Exception: return False
    return False
PW = ["Acct-33333!"]

import websocket
def admin(msgs):
    b = lambda s: base64.b64encode(s.encode()).decode()
    w = websocket.create_connection("wss://127.0.0.1:8443/control.ashx", header=[f"x-meshauth: {b('admin')},{b('Test-1234')}"], sslopt={"cert_reqs": 0}, timeout=5)
    for m in msgs: w.send(json.dumps(m))
    time.sleep(1.5); w.close()
admin([{"action": "adduser", "username": "acctest3", "pass": PW[0], "email": "a3@example.com", "emailVerified": True}])
print("acctest3 created, sign in:", login_ok("acctest3", PW[0]), flush=True)
SIGNOUT = []
class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "acctest3", PW[0])
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def sign_out(self):
        SIGNOUT.append(1)
    def go(self):
        mw = self.main_win; self.c = mw.ctrl
        mw.show_page("account"); self.p = mw._pages["account"]
        self.steps = [lambda: self.s_delete("wrong-pass"), self.s_check, lambda: self.s_delete(PW[0]), self.s_check]
        GLib.timeout_add(1500, self.next); return False
    def next(self):
        if self.steps: self.steps.pop(0)()
        return False
    def later(self, ms=1500): GLib.timeout_add(ms, self.next)
    def s_delete(self, pw):
        orig_dialog = self.p._dialog
        def fake_dialog(title, width=460):
            d, area = orig_dialog(title, width)
            def run():
                for e in [w for w in self._all(area) if isinstance(w, Gtk.Entry)]: e.set_text(pw)
                return Gtk.ResponseType.OK
            d.run = run
            return d, area
        self.p._dialog = fake_dialog
        self.p.delete_account(); self.p._dialog = orig_dialog; self.later(6000)
    def s_check(self):
        print("dialogs:", MSG, "| signed out:", bool(SIGNOUT), "| account exists:", login_ok("acctest3", PW[0]), flush=True)
        MSG.clear()
        if not self.steps: self.quit()
        else: self.later(100)
    def _all(self, w):
        out = [w]
        if isinstance(w, Gtk.Container):
            for c in w.get_children(): out += self._all(c)
        return out
T().run([])
