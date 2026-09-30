# LOCALHOST TESTING ONLY (xvfb-run): Users → New Account… (adduser).
#   newaccount_test.py name    default server (username + email fields)
#   newaccount_test.py email   server with domains."".userNameIsEmail=true and
#                              passwordRequirements {min:8, upper:1, numeric:1}
# Creates throwaway accounts (newacc*/newacc*@example.com) and deletes them at the end.
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client, ui, admin_panel as ap
appmod.APP_ID = rigenv.TEST_APP_ID
SRV, ADMIN, PW = "https://127.0.0.1:8443", "admin", "Test-1234"
MODE = sys.argv[1] if len(sys.argv) > 1 else "name"
RESULTS = []
def check(name, ok, info=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(info) if info else ""), flush=True)
ui.message = lambda *a, **k: None


class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection(SRV, ADMIN, PW)
        def ready():
            if not ctrl.userinfo:
                return True
            self.on_login(ctrl); self.main_win.resize(1400, 820)
            GLib.timeout_add(1500, self.go)
            return False
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()

    def go(self):
        mw = self.main_win; self.ctrl = mw.ctrl
        mw.show_page("users"); self.p = mw._pages["users"]
        self.steps = [self.s_open, self.s_create, self.s_created, self.s_dup, self.s_dup_check,
                      self.s_random, self.s_random_check, self.s_weak, self.s_weak_check, self.s_cleanup, self.s_end]
        GLib.timeout_add(2000, self.next)
        return False

    def next(self):
        if self.steps:
            self.steps.pop(0)()
        return False

    def later(self, ms=1500):
        GLib.timeout_add(ms, self.next)

    def users(self):
        return {(u.get("name") or "").lower(): u for u in self.p._users}   # email mode keeps the typed case in name

    def fill(self, d, name, email, p1, p2=None):
        if d.name is not None:
            d.name.set_text(name)
        d.email.set_text(email)
        d.pass1.set_text(p1); d.pass2.set_text(p1 if p2 is None else p2)

    def s_open(self):
        feats = ap._features(self.ctrl)
        check("serverinfo.features usernameisemail bit matches mode", bool(feats & ap.FEAT_USERNAME_IS_EMAIL) == (MODE == "email"), hex(feats))
        check("New Account button visible + enabled", self.p.new_btn.get_visible() and self.p.new_btn.get_sensitive())
        d = self.p.new_account()
        check("username field only in name mode", (d.name is None) == (MODE == "email"))
        check("OK disabled when empty", not d.ok_btn.get_sensitive())
        self.fill(d, "newacc1", "newacc1@example.com", "Newacc-123", "Newacc-124")
        check("OK disabled on password mismatch", not d.ok_btn.get_sensitive() and "do not match" in d.hint.get_text())
        self.fill(d, "newacc1", "newacc1@x", "Newacc-123")
        check("OK disabled on email without TLD", not d.ok_btn.get_sensitive())
        if d.name is not None:
            self.fill(d, "new acc", "newacc1@example.com", "Newacc-123")
            check("OK disabled on username with space", not d.ok_btn.get_sensitive())
        self.fill(d, "newacc1", "NewAcc1@Example.com", "Newacc-123")
        d.reset.set_active(True)
        check("OK enabled when valid", d.ok_btn.get_sensitive())
        self.d = d
        self.later(300)

    def s_create(self):
        self.d.response(Gtk.ResponseType.OK)
        self.later(2500)

    def s_created(self):
        us = self.users()
        name = "newacc1@example.com" if MODE == "email" else "newacc1"
        u = us.get(name, {})
        check("account created, list refreshed", u, sorted(us))
        check("email stored lowercase", u.get("email") == "newacc1@example.com", u.get("email"))
        check("force reset → passchange -1", u.get("passchange") == -1)
        row = [r for sec in self.p.store for r in sec.iterchildren() if r[ap.UsersPanel.C_NAME].lower() == name]
        check("Permissions column shows User (no siteadmin field)", "siteadmin" not in u and row and row[0][ap.UsersPanel.C_PERMS] == "User",
              (u.get("siteadmin"), row and row[0][ap.UsersPanel.C_PERMS]))
        check("dialog closed on success", not self.d.get_visible() if self.d.get_realized() else True)
        self.later(100)

    def s_dup(self):
        d = self.p.new_account()
        self.fill(d, "newacc1", "newacc1@example.com", "Newacc-123")
        d.response(Gtk.ResponseType.OK)
        self.d = d
        self.later(2000)

    def s_dup_check(self):
        check("duplicate → inline error, dialog stays", "User already exists" in self.d.result.get_text(), self.d.result.get_text())
        self.d.destroy()
        self.later(100)

    def s_random(self):
        d = self.p.new_account()
        self.fill(d, "newacc2", "newacc2@example.com", "")
        check("OK disabled without password", not d.ok_btn.get_sensitive())
        d.random.set_active(True)
        d.remove_events.set_active(True)
        check("random: password fields disabled, OK enabled, hint shown",
              not d.pass1.get_sensitive() and d.ok_btn.get_sensitive() and "not shown" in d.hint.get_text())
        req = d.request()
        check("request shape", req["randomPassword"] is True and req["removeEvents"] is True and req["pass"] == ""
              and req["username"] == ("newacc2@example.com" if MODE == "email" else "newacc2"), req)
        d.response(Gtk.ResponseType.OK)
        self.later(2500)

    def s_random_check(self):
        name = "newacc2@example.com" if MODE == "email" else "newacc2"
        check("random-password account created", name in self.users())
        self.later(100)

    def s_weak(self):
        # only meaningful with the server password policy (email mode run)
        d = self.p.new_account()
        self.fill(d, "newacc3", "newacc3@example.com", "weak")
        d.response(Gtk.ResponseType.OK)
        self.d = d
        self.later(2000)

    def s_weak_check(self):
        txt = self.d.result.get_text()
        if MODE == "email":
            check("weak password → policy message", "password requirements" in txt, txt)
        else:
            check("no policy: short password accepted", "newacc3" in self.users() or txt == "", txt)
        self.d.destroy()
        self.later(100)

    def s_cleanup(self):
        for n in ("newacc1", "newacc2", "newacc3", "newacc1@example.com", "newacc2@example.com", "newacc3@example.com"):
            self.ctrl.send({"action": "deleteuser", "userid": "user//" + n})
        GLib.timeout_add(1500, lambda: (self.p.refresh(), False)[1])
        self.later(3500)

    def s_end(self):
        left = [n for n in self.users() if n.startswith("newacc")]
        check("cleanup: throwaway accounts deleted", not left, left)
        fails = [n for n, ok in RESULTS if not ok]
        print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)), "FAILED: %s" % fails if fails else "", flush=True)
        self.quit()


T().run([])
