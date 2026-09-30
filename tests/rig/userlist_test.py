# LOCALHOST TESTING ONLY (xvfb-run): Users list like the web UI, online/offline sections with live
# session counts (wssessioncount), Device Groups, Last Access, Permissions, filter, Select All/None
# (never yourself), Group Action lock / unlock / delete. Throwaway users ul1, ul2 + group "UL-Group".
import sys, ssl, time, json, base64, threading
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client, ui, admin_panel as ap
appmod.APP_ID = rigenv.TEST_APP_ID
SRV, ADMIN, PW = "https://127.0.0.1:8443", "admin", "Test-1234"
RESULTS = []
def check(name, ok, info=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(info) if info else ""), flush=True)
ui.message = lambda *a, **k: None
ui.confirm = lambda *a, **k: True
OP = ["lock"]
_orig_run = Gtk.Dialog.run
def fake_run(d):
    if d.get_title() == "Group Action":
        for c in d.get_content_area().get_children():
            for w in (c.get_children() if isinstance(c, Gtk.Box) else []):
                if isinstance(w, Gtk.ComboBoxText):
                    w.set_active_id(OP[0])
        return Gtk.ResponseType.OK
    return _orig_run(d)
Gtk.Dialog.run = fake_run

def open_session(user, pw):
    """hold a real control session open (counts as a session for wssessioncount)"""
    import websocket
    b = lambda s: base64.b64encode(s.encode()).decode()
    w = websocket.create_connection("wss://127.0.0.1:8443/control.ashx", header=[f"x-meshauth: {b(user)},{b(pw)}"],
                                    sslopt={"cert_reqs": 0}, timeout=5)
    end = time.time() + 4
    while time.time() < end:
        if json.loads(w.recv()).get("action") == "userinfo":
            break
    return w


class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection(SRV, ADMIN, PW)
        def ready():
            if not ctrl.userinfo: return True
            self.on_login(ctrl); self.main_win.resize(1400, 900); GLib.timeout_add(1500, self.setup); return False
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()

    def setup(self):
        c = self.c = self.main_win.ctrl
        for n in ("ul1", "ul2"):
            c.send({"action": "deleteuser", "userid": "user//" + n})
        for m, v in list(self.main_win.meshes.items()):
            if v.get("name") == "UL-Group":
                c.send({"action": "deletemesh", "meshid": m, "meshname": "UL-Group"})
        GLib.timeout_add(1500, self.setup2); return False

    def setup2(self):
        c = self.c
        c.send({"action": "adduser", "username": "ul1", "email": "ul1@example.com", "pass": "Ul1-123456"})
        c.send({"action": "adduser", "username": "ul2", "email": "ul2@corp.example", "pass": "Ul2-123456"})
        c.send({"action": "createmesh", "meshname": "UL-Group", "meshtype": 2, "desc": ""})
        GLib.timeout_add(3000, self.setup3); return False

    def setup3(self):
        gid = next((m for m, v in self.main_win.meshes.items() if v.get("name") == "UL-Group"), None)
        self.c.send({"action": "addmeshuser", "meshid": gid, "meshname": "UL-Group", "userids": ["user//ul2"], "meshadmin": 8})
        self.c.send({"action": "edituser", "id": "user//ul2", "siteadmin": 8})
        self.gid = gid
        GLib.timeout_add(1500, self.go); return False

    def go(self):
        mw = self.main_win; mw.show_page("users"); self.p = mw._pages["users"]
        self.steps = [self.s_list, self.s_login, self.s_login_chk, self.s_logout, self.s_logout_chk, self.s_filter,
                      self.s_select, self.s_lock, self.s_lock_chk, self.s_unlock, self.s_unlock_chk,
                      self.s_delete, self.s_delete_chk, self.s_end]
        GLib.timeout_add(2500, self.next); return False

    def next(self):
        if self.steps: self.steps.pop(0)()
        return False
    def later(self, ms=2500): GLib.timeout_add(ms, self.next)

    def rows(self):
        out = {}
        for sec in self.p.store:
            for r in sec.iterchildren():
                out[r[ap.UsersPanel.C_NAME]] = dict(section=sec[ap.UsersPanel.C_NAME], check=r[0], groups=r[2],
                                                    access=r[3], perms=r[4], checkable=r[9])
        return out

    def s_list(self):
        r = self.rows()
        check("admin online with session count", r.get("admin", {}).get("section", "").startswith("Online")
              and "session" in r["admin"]["access"], r.get("admin"))
        check("new users offline", all(r.get(n, {}).get("section", "").startswith("Offline") for n in ("ul1", "ul2")))
        check("Device Groups count", r.get("ul2", {}).get("groups") == "1" and r.get("ul1", {}).get("groups") == "0",
              (r.get("ul1", {}).get("groups"), r.get("ul2", {}).get("groups")))
        check("Permissions labels", r.get("admin", {}).get("perms") == "Administrator" and
              r.get("ul1", {}).get("perms") == "User" and r.get("ul2", {}).get("perms") == "User + Files",
              {k: v.get("perms") for k, v in r.items()})
        check("yourself not selectable", r.get("admin", {}).get("checkable") is False)
        self.later(100)

    def s_login(self):
        self.ws = open_session("ul1", "Ul1-123456"); self.later(2500)
    def s_login_chk(self):
        r = self.rows().get("ul1", {})
        check("live: ul1 moves to Online with 1 session", r.get("section", "").startswith("Online") and r.get("access") == "1 session", r)
        pg = self.p.open_user("user//ul1")
        found = []
        def walk(w):
            if isinstance(w, Gtk.Label): found.append(w.get_text())
            if isinstance(w, Gtk.Container):
                for ch in w.get_children(): walk(ch)
        walk(pg)
        check("user page shows '1 active session'", "1 active session" in found)
        self.p.close_user()
        self.later(100)

    def s_logout(self):
        self.ws.close(); self.later(3000)
    def s_logout_chk(self):
        r = self.rows().get("ul1", {})
        u = next(x for x in self.p._users if x.get("name") == "ul1")
        # the server only stores 'access' on session close if the user already had one (never-web users: none)
        check("live: ul1 back Offline, Last Access = date of access/login (blank if none)",
              r.get("section", "").startswith("Offline") and r.get("access") == ui.fmt_date(u.get("access") or u.get("login")),
              (r.get("access"), u.get("access"), u.get("login")))
        self.later(100)

    def s_filter(self):
        self.p.filter.set_text("ul1"); self.p._render()
        a = sorted(self.rows())
        self.p.filter.set_text("email:corp"); self.p._render()
        b = sorted(self.rows())
        self.p.filter.set_text("name:corp"); self.p._render()
        c = sorted(self.rows())
        self.p.filter.set_text(""); self.p._render()
        check("filter name / email: / name:", a == ["ul1"] and b == ["ul2"] and c == [], (a, b, c))
        self.later(100)

    def s_select(self):
        check("Group Action disabled with nothing selected", not self.p.group_btn.get_sensitive())
        self.p.toggle_select_all()
        r = self.rows()
        check("Select All checks everyone except yourself", r["ul1"]["check"] and r["ul2"]["check"] and not r["admin"]["check"]
              and self.p.select_btn.get_label() == "Select None" and self.p.group_btn.get_sensitive())
        self.p.toggle_select_all()
        check("Select None clears", not any(v["check"] for v in self.rows().values()) and self.p.select_btn.get_label() == "Select All")
        # select only ul1 + ul2 via the checkbox handler (like clicks)
        for i, sec in enumerate(self.p.store):
            for j, r in enumerate(sec.iterchildren()):
                if r[ap.UsersPanel.C_NAME] in ("ul1", "ul2"):
                    self.p._on_toggled(None, f"{i}:{j}")
        check("checkbox clicks select", self.p._checked == {"user//ul1", "user//ul2"}, self.p._checked)
        self.later(100)

    def users(self):
        return {u.get("name"): u for u in self.p._users}

    def s_lock(self):
        OP[0] = "lock"; self.p.group_action(); self.later(3000)
    def s_lock_chk(self):
        u = self.users()
        check("group lock → siteadmin & 32", (u["ul1"].get("siteadmin") or 0) & 32 and u["ul2"].get("siteadmin") == 40,
              (u["ul1"].get("siteadmin"), u["ul2"].get("siteadmin")))
        check("locked label", self.rows()["ul1"]["perms"] == "Locked, User", self.rows()["ul1"]["perms"])
        check("selection kept after refresh", self.p._checked == {"user//ul1", "user//ul2"})
        self.later(100)

    def s_unlock(self):
        OP[0] = "unlock"; self.p.group_action(); self.later(3000)
    def s_unlock_chk(self):
        u = self.users()
        check("group unlock", not (u["ul1"].get("siteadmin") or 0) & 32 and u["ul2"].get("siteadmin") == 8,
              (u["ul1"].get("siteadmin"), u["ul2"].get("siteadmin")))
        self.later(100)

    def s_delete(self):
        OP[0] = "delete"; self.p.group_action(); self.later(3000)
    def s_delete_chk(self):
        u = self.users()
        check("group delete", "ul1" not in u and "ul2" not in u and "admin" in u, sorted(u))
        check("selection cleared", not self.p._checked and self.p.select_btn.get_label() == "Select All")
        self.c.send({"action": "deletemesh", "meshid": self.gid, "meshname": "UL-Group"})
        self.later(1500)

    def s_end(self):
        fails = [n for n, ok in RESULTS if not ok]
        print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)), "FAILED: %s" % fails if fails else "", flush=True)
        self.quit()


T().run([])
