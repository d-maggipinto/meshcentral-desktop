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
PW = ["Acct-67890!"]

class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "acctest2", PW[0])
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); self.main_win.resize(1400, 820); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win; self.c = mw.ctrl
        mw.show_page("account"); self.p = mw._pages["account"]
        self.steps = [self.s_image, self.s_image_check, self.s_shot, self.s_pw, self.s_pw_check, self.s_delete, self.s_delete_check]
        GLib.timeout_add(1500, self.next); return False
    def next(self):
        if self.steps: self.steps.pop(0)()
        return False
    def later(self, ms=1500): GLib.timeout_add(ms, self.next)
    # -- 2FA
    def s_otp(self):
        p = self.p
        def setup(secret, url):
            self.secret = secret
            ap.QrCode(url)                                           # must build without error
            print("authenticator: got secret + otpauth URL, QR matrix built", flush=True)
            p._once("otpauth-setup", lambda m: print("otpauth-setup success:", m.get("success"), flush=True))
            self.c.send({"action": "otpauth-setup", "secret": secret, "token": totp(secret)})
        p._authenticator_setup = setup
        p.manage_authenticator(); self.later(2500)
    def s_otp_check(self):
        print("userinfo.otpsecret after setup:", self.c.userinfo.get("otpsecret"), "| page label rebuilt:",
              any("Enabled" in (w.get_text() if isinstance(w, Gtk.Label) else "") for w in self._all(self.p)), flush=True)
        self.later(100)
    def s_codes(self):
        got = []
        self.p._once("otpauth-getpasswords", lambda m: got.append(m.get("passwords")))
        self.c.send({"action": "otpauth-getpasswords", "subaction": 1})
        GLib.timeout_add(1500, lambda: (print("backup codes generated:", len(got[0] or []) if got else None, flush=True), self.next(), False)[2])
    def s_logins(self):
        got = []
        self.p._once("previousLogins", lambda m: got.append(m.get("events")))
        self.c.send({"action": "previousLogins"})
        GLib.timeout_add(1500, lambda: (print("previous logins:", len(got[0] or []) if got else None, "| sample:", (got[0] or [None])[0] if got else None, flush=True), self.next(), False)[2])
    def s_token(self):
        self.tok = []
        self.p._once("createLoginToken", lambda m: self.tok.append(m))
        self.c.send({"action": "createLoginToken", "name": "mcd-test", "expire": 5})
        self.later(1500)
    def s_token_use(self):
        t = self.tok[0] if self.tok else {}
        print("login token:", t.get("tokenUser"), "| sign in with it works:", login_ok(t.get("tokenUser", ""), t.get("tokenPass", "")), flush=True)
        self.c.send({"action": "loginTokens", "remove": [t.get("tokenUser")]})
        self.later(1200)
    # -- image
    def s_image(self):
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 64, 48); pb.fill(0x2266aaff)
        path = SP + "/avatar-test.png"; pb.savev(path, "png", [], [])
        class FC:
            def __init__(s, *a): pass
            def add_filter(s, f): pass
            def run(s): return Gtk.ResponseType.ACCEPT
            def get_filename(s): return path
            def destroy(s): pass
        ap.Gtk.FileChooserNative.new = staticmethod(lambda *a: FC())
        self.p.change_image(); self.later(2500)
    def s_image_check(self):
        dest = SP + "/avatar-back.png"
        def done(err):
            ok = not err and os.path.getsize(dest) > 100
            print("image flag:", self.c.userinfo.get("flags"), "| userimage.ashx readable:", ok, flush=True); self.next()
        self.p._session().fetch("/userimage.ashx", dest, None, done)
    # -- device group, language, notifications
    def s_group(self):
        ui.form_dialog = lambda *a, **k: {"name": "Acct Test Group", "desc": "made by test"}
        ap.ui.form_dialog = ui.form_dialog
        self.p.new_device_group(); self.later(2500)
    def s_group_check(self):
        names = [m.get("name") for m in self.main_win.meshes.values()]
        print("device group created:", "Acct Test Group" in names, "| cards:", len(self.p.groups_box.get_children()), flush=True)
        self.later(100)
    def s_lang(self):
        self.c.send({"action": "changelang", "lang": "it"}); self.later(1500)
    def s_lang_check(self):
        print("language now:", self.c.userinfo.get("lang"), flush=True); self.later(100)
    def s_notify(self):
        mw = self.main_win
        self.main_win.app.config["notify"] = {"connect": True, "disconnect": True, "groupname": True}
        fake = {"_id": "node//fake", "name": "Test PC", "meshid": "m", "conn": 0}
        mw.nodes["node//fake"] = fake
        n0 = len(mw.notify_box.get_children())
        mw._notify_connection({"nodeid": "node//fake", "conn": 1})
        cards = mw.notify_box.get_children()[n0:]
        print("device-connected card:", [l.get_text() for c in cards for l in self._all(c) if isinstance(l, Gtk.Label)][:3], flush=True)
        self.later(100)
    def s_shot(self):
        mw = self.main_win; a = mw.get_allocation()
        Gdk.pixbuf_get_from_window(mw.get_window(), 0, 0, a.width, a.height).savev(f"{SP}/ui-account.png", "png", [], [])
        self.later(100)
    # -- password, delete
    def s_pw(self):
        new = "Acct-11111!"
        class D:
            pass
        orig_dialog = self.p._dialog
        def fake_dialog(title, width=460):
            d, area = orig_dialog(title, width)
            def run():
                ents = [w for w in self._all(area) if isinstance(w, Gtk.Entry)]
                grid = ents[0].get_parent()
                ents.sort(key=lambda e: grid.child_get_property(e, "top-attach"))   # real row order
                for e, v in zip(ents, (PW[0], new, new)): e.set_text(v)
                return Gtk.ResponseType.OK
            d.run = run
            return d, area
        self.p._dialog = fake_dialog
        self.newpw = new
        self.p.change_password(); self.p._dialog = orig_dialog; self.later(3000)
    def s_pw_check(self):
        print("password change: app copy updated:", self.c.password == self.newpw, "| sign in with new:",
              login_ok("acctest2", self.newpw), "| with old:", login_ok("acctest2", PW[0]), flush=True)
        PW[0] = self.newpw; self.later(100)
    def s_delete(self):
        orig_dialog = self.p._dialog
        def fake_dialog(title, width=460):
            d, area = orig_dialog(title, width)
            def run():
                for e in [w for w in self._all(area) if isinstance(w, Gtk.Entry)]: e.set_text(PW[0])
                return Gtk.ResponseType.OK
            d.run = run
            return d, area
        self.p._dialog = fake_dialog
        self.p.delete_account(); self.later(5000)
    def s_delete_check(self):
        print("after delete: sign in still possible:", login_ok("acctest2", PW[0]), "| app session closed:", not self.c.connected, "| dialogs:", MSG, flush=True)
        self.quit()
    def _all(self, w):
        out = [w]
        if isinstance(w, Gtk.Container):
            for c in w.get_children(): out += self._all(c)
        return out
T().run([])
