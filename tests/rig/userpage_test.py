# LOCALHOST TESTING ONLY (xvfb-run): Users → user page (General + Events), every edit/action.
# Setup (as admin): device group "UP-Group", agentless group "UP-Local" + local device "up-dev",
# user group "UP-UG", throwaway user "upuser1". Everything is removed at the end.
import sys, ssl, time, json, base64
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client, ui, admin_panel as ap, user_panel as up
appmod.APP_ID = rigenv.TEST_APP_ID
def _ctx():
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c.check_hostname = False; c.verify_mode = 0; return c
client.http_ssl_context = _ctx
SRV, ADMIN, PW = "https://127.0.0.1:8443", "admin", "Test-1234"
UNAME, UPW, UPW2 = "upuser1", "Upuser-12345", "Upuser-67890"
UID = "user//" + UNAME
RESULTS, MSGS = [], []
def check(name, ok, info=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(info) if info else ""), flush=True)
ui.message = lambda parent, title, text="", kind=None: MSGS.append(title)
ui.confirm = lambda *a, **k: True
HOOK = []
def fake_run(d):
    d.show_all()
    f = HOOK.pop(0) if HOOK else None
    return bool(f(d)) if f else False
up._run = fake_run

def widgets(w, cls):
    out = []
    if isinstance(w, cls):
        out.append(w)
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += widgets(c, cls)
    return out
def tick(d, *labels, on=True):
    for c in widgets(d, Gtk.CheckButton):
        if c.get_label() in labels:
            c.set_active(on)
def entries(d):
    return widgets(d, Gtk.Entry)
def login_ok(user, pw):
    import websocket
    b = lambda s: base64.b64encode(s.encode()).decode()
    try:
        w = websocket.create_connection("wss://127.0.0.1:8443/control.ashx", header=[f"x-meshauth: {b(user)},{b(pw)}"],
                                        sslopt={"cert_reqs": 0}, timeout=5)
        end = time.time() + 4
        while time.time() < end:
            m = json.loads(w.recv())
            if m.get("action") == "userinfo": return True
            if m.get("action") == "close": return False
    except Exception: return False
    return False


class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection(SRV, ADMIN, PW)
        def ready():
            if not ctrl.userinfo: return True
            self.on_login(ctrl); self.main_win.resize(1400, 900); GLib.timeout_add(1500, self.setup); return False
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()

    def setup(self):
        c = self.c = self.main_win.ctrl
        for m, v in list(self.main_win.meshes.items()):          # leftovers of an aborted run
            if (v.get("name") or "").startswith("UP-"):
                c.send({"action": "deletemesh", "meshid": m, "meshname": v.get("name")})
        c.send({"action": "deleteuser", "userid": UID})
        GLib.timeout_add(2000, self.setup1); return False

    def setup1(self):
        c = self.c
        c.send({"action": "createmesh", "meshname": "UP-Group", "meshtype": 2, "desc": ""})
        c.send({"action": "createmesh", "meshname": "UP-Local", "meshtype": 3, "desc": ""})
        c.send({"action": "createusergroup", "name": "UP-UG", "desc": "test group"})
        c.send({"action": "adduser", "username": UNAME, "email": "upuser1@example.com", "pass": UPW})
        GLib.timeout_add(3500, self.setup2); return False

    def setup2(self):
        mw = self.main_win
        self.gid = next((m for m, v in mw.meshes.items() if v.get("name") == "UP-Group"), None)
        self.lid = next((m for m, v in mw.meshes.items() if v.get("name") == "UP-Local"), None)
        check("setup: device groups visible", self.gid and self.lid, list(v.get("name") for v in mw.meshes.values()))
        self.c.send({"action": "addlocaldevice", "meshid": self.lid, "devicename": "up-dev", "hostname": "127.0.0.2", "type": 4})
        GLib.timeout_add(3500, self.go); return False

    def go(self):
        mw = self.main_win
        self.nid = next((n for n, v in mw.nodes.items() if v.get("name") == "up-dev"), None)
        check("setup: local device visible", self.nid)
        mw.show_page("users"); self.p = mw._pages["users"]
        self.steps = [self.s_open, self.s_realname, self.s_realname_chk, self.s_email, self.s_email_chk,
                      self.s_features, self.s_features_chk, self.s_rights, self.s_rights_chk, self.s_consent,
                      self.s_consent_chk, self.s_realms, self.s_realms_chk, self.s_addgroup, self.s_addgroup_chk,
                      self.s_editgroup, self.s_editgroup_chk, self.s_rmgroup, self.s_rmgroup_chk,
                      self.s_addug, self.s_addug_chk, self.s_rmug, self.s_rmug_chk,
                      self.s_adddev, self.s_adddev_chk, self.s_rmdev, self.s_rmdev_chk,
                      self.s_notes, self.s_notes_chk, self.s_pw, self.s_pw_chk, self.s_pwbad, self.s_pwbad_chk,
                      self.s_prev, self.s_prev_chk, self.s_img, self.s_img_chk, self.s_img_del, self.s_img_del_chk, self.s_events, self.s_events_chk, self.s_shot,
                      self.s_delete, self.s_delete_chk, self.s_cleanup, self.s_end]
        GLib.timeout_add(2000, self.next); return False

    def next(self):
        if self.steps: self.steps.pop(0)()
        return False
    def later(self, ms=2200): GLib.timeout_add(ms, self.next)
    def u(self):
        return self.page.user
    def labels(self):
        return [l.get_text() for l in widgets(self.page.general, Gtk.Label)]

    def s_open(self):
        self.page = self.p.open_user(UID)
        check("page opens", self.page is not None and self.page.get_visible())
        t = self.labels()
        for k in ("Domain", "User Identifier", "Email", "Real Name", "Features", "Server Rights", "Creation",
                  "Password", "Device Groups", "Admin Realms", "User Consent", "Common Device Groups",
                  "Common Devices"):
            if k not in t: check("row " + k, False, t); break
        else:
            check("all General rows present", True)
        check("new user: No server rights", "No server rights" in t)
        btns = [b.get_label() for b in widgets(self.page.general, Gtk.Button)]
        check("actions present", {"Notes", "Change Password…", "Previous Logins", "Delete User…"} <= set(btns), btns)
        self.later(1500)

    def s_realname(self):
        check("User Group Memberships section after usergroups reply", "User Group Memberships" in self.labels())
        HOOK.append(lambda d: (entries(d)[0].set_text("Test Person"), True)[1])
        self.page.edit_realname(); self.later()
    def s_realname_chk(self):
        check("real name changed + page updated", self.u().get("realname") == "Test Person" and "Test Person" in self.labels())
        self.later(100)

    def s_email(self):
        HOOK.append(lambda d: (entries(d)[0].set_text("changed@example.com"), True)[1])
        self.page.edit_email(); self.later()
    def s_email_chk(self):
        check("email changed", self.u().get("email") == "changed@example.com", self.u().get("email")); self.later(100)

    def s_features(self):
        HOOK.append(lambda d: (tick(d, "No Terminal Access", "No Wake"), True)[1])
        self.page.edit_features(); self.later()
    def s_features_chk(self):
        check("features → removeRights 0x240", self.u().get("removeRights") == 0x240, self.u().get("removeRights"))
        check("features text", "No Terminal, No Wake" in self.labels()); self.later(100)

    def s_rights(self):
        HOOK.append(lambda d: (tick(d, "Server Backup", "Lock Account"), True)[1])
        self.page.edit_server_rights(); self.later()
    def s_rights_chk(self):
        check("server rights → siteadmin 33", self.u().get("siteadmin") == 33, self.u().get("siteadmin"))
        check("server rights text", "Locked account, Partial rights" in self.labels()); self.later(100)

    def s_consent(self):
        def h(d):
            for c in widgets(d, Gtk.CheckButton):
                if c.get_label() == "Notify user": c.set_active(True); break      # first = Desktop
            return True
        HOOK.append(h); self.page.edit_consent(); self.later()
    def s_consent_chk(self):
        check("consent → 1 (Desktop Notify)", self.u().get("consent") == 1 and "Desktop Notify" in self.labels(),
              self.u().get("consent")); self.later(100)

    def s_realms(self):
        HOOK.append(lambda d: (entries(d)[0].set_text("Sales, IT"), True)[1])
        self.page.edit_realms(); self.later()
    def s_realms_chk(self):
        check("realms → groups [it, sales]", self.u().get("groups") == ["it", "sales"], self.u().get("groups"))
        # clear realms again (realms restrict what the user sees)
        self.c.send({"action": "edituser", "id": UID, "groups": []}); self.later(1500)

    def s_addgroup(self):
        def h(d):
            cb = widgets(d, Gtk.ComboBoxText)[0]; cb.set_active_id(self.gid)
            tick(d, "Remote Control & Relay", "Mesh Agent Console"); return True
        HOOK.append(h); self.page.group_rights(); self.later(2500)
    def s_addgroup_chk(self):
        r = ((self.u().get("links") or {}).get(self.gid) or {}).get("rights")
        check("device group added with rights 24", r == 24, r)
        check("group row text", "Control, Console" in self.labels()); self.later(100)

    def s_editgroup(self):
        HOOK.append(lambda d: (tick(d, "Full Administrator"), True)[1])
        self.page.group_rights(self.gid); self.later(2500)
    def s_editgroup_chk(self):
        r = ((self.u().get("links") or {}).get(self.gid) or {}).get("rights")
        check("device group rights → full", r == 0xFFFFFFFF, r); self.later(100)

    def s_rmgroup(self):
        self.page.remove_group(self.gid); self.later(2500)
    def s_rmgroup_chk(self):
        check("device group removed", self.gid not in (self.u().get("links") or {})); self.later(100)

    def s_addug(self):
        self.ugid = next((g for g, v in (self.p.usergroups or {}).items() if v.get("name") == "UP-UG"), None)
        check("user groups loaded", self.ugid, list((self.p.usergroups or {}).keys()))
        HOOK.append(lambda d: (widgets(d, Gtk.ComboBoxText)[0].set_active_id(self.ugid), True)[1])
        self.page.add_usergroup(); self.later(2500)
    def s_addug_chk(self):
        check("user group membership added", self.ugid in (self.u().get("links") or {}))
        check("membership row shown", "UP-UG" in self.labels()); self.later(100)

    def s_rmug(self):
        self.page.remove_usergroup(self.ugid); self.later(2500)
    def s_rmug_chk(self):
        check("membership removed", self.ugid not in (self.u().get("links") or {})); self.later(100)

    def s_adddev(self):
        def h(d):
            cbs = widgets(d, Gtk.ComboBoxText)
            ids = lambda cb: [r[1] for r in cb.get_model()]
            mc = next(cb for cb in cbs if self.lid in ids(cb)); mc.set_active_id(self.lid)
            nc = next(cb for cb in cbs if cb is not mc); nc.set_active_id(self.nid)
            tick(d, "Remote Control & Relay", "Wake Devices"); return True
        HOOK.append(h); self.page.device_rights(); self.later(2500)
    def s_adddev_chk(self):
        check("no false 'failed' dialogs", not any("failed" in m for m in MSGS), MSGS)
        r = ((self.u().get("links") or {}).get(self.nid) or {}).get("rights")
        check("device added with rights 72", r == 72, r)
        check("device row shown", "up-dev" in self.labels()); self.later(100)

    def s_rmdev(self):
        self.page.remove_device(self.nid); self.later(2500)
    def s_rmdev_chk(self):
        check("device removed", self.nid not in (self.u().get("links") or {})); self.later(100)

    def s_notes(self):
        from mcdesktop.general_actions import NotesDialog
        orig = NotesDialog.__init__
        dlg = {}
        def spy(s, *a, **k):
            orig(s, *a, **k); dlg["d"] = s
        NotesDialog.__init__ = spy
        self.page.notes(); NotesDialog.__init__ = orig
        self.nd = dlg["d"]
        GLib.timeout_add(1200, lambda: (self.nd.view.get_buffer().set_text("user note 1"), False)[1])
        GLib.timeout_add(1600, lambda: (self.nd.response(Gtk.ResponseType.APPLY), False)[1])
        self.later(2500)
    def s_notes_chk(self):
        got = {}
        def h(m):
            if m.get("id") == UID: got["n"] = m.get("notes")
        self.c.on("getNotes", h); self.c.send({"action": "getNotes", "id": UID})
        def chk():
            self.c.off("getNotes", h); check("user notes saved", got.get("n") == "user note 1", got)
            self.nd.destroy(); self.next(); return False
        GLib.timeout_add(1500, chk)

    def s_pw(self):
        self.c.send({"action": "edituser", "id": UID, "siteadmin": 0})     # s_rights locked the account
        def h(d):
            e = entries(d); e[0].set_text(UPW2); e[1].set_text(UPW2); return True
        MSGS.clear(); HOOK.append(h); self.page.change_password(); self.later(3000)
    def s_pw_chk(self):
        check("password change confirmed by event", "Password changed" in MSGS, MSGS)
        check("new password signs in, old refused", login_ok(UNAME, UPW2) and not login_ok(UNAME, UPW)); self.later(100)

    def s_pwbad(self):
        # rig has no password policy → simulate a silently dropped change: removeMultiFactor must be bool,
        # so send a request the server ignores and check the timeout warning path
        MSGS.clear()
        self.page._pw_wait = GLib.timeout_add_seconds(1, self.page._pw_timeout)
        self.later(2000)
    def s_pwbad_chk(self):
        check("no confirmation → warning", "The server did not confirm the password change" in MSGS, MSGS); self.later(100)

    def s_prev(self):
        self.prev = {}
        def h(m):
            if m.get("userid") == UID: self.prev["m"] = m
        self.c.on("previousLogins", h); self.h_prev = h
        self.page.previous_logins(); self.later(2000)
    def s_prev_chk(self):
        self.c.off("previousLogins", self.h_prev)
        check("previous logins for the user", "m" in self.prev and isinstance(self.prev["m"].get("events"), list),
              len((self.prev.get("m") or {}).get("events") or []))
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, Gtk.Dialog) and w.get_title().startswith("Previous logins"): w.destroy()
        self.later(100)

    def s_img(self):
        import os
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 300)
        pb.fill(0x2a7fffff)
        self.imgpath = os.path.join(sys.argv[1] if len(sys.argv) > 1 else "/tmp", "avatar_src.png")
        pb.savev(self.imgpath, "png", [], [])
        self.page._choose_image = lambda parent: up.account_image_from_file(parent, self.imgpath)
        def run_dialog(d):
            for b in widgets(d, Gtk.Button):
                if b.get_label() == "Choose file…": b.clicked()
            return Gtk.ResponseType.OK
        self._orig_run = Gtk.Dialog.run
        Gtk.Dialog.run = lambda d: run_dialog(d) if d.get_title() == "Manage Account Image" else self._orig_run(d)
        self.page.manage_image(); Gtk.Dialog.run = self._orig_run
        self.later(3000)
    def s_img_chk(self):
        check("image set → flags & 1", (self.u().get("flags") or 0) & 1, self.u().get("flags"))
        # read it back like the page does (web session, userimage.ashx?id=)
        import os, tempfile
        fd, path = tempfile.mkstemp(); os.close(fd)
        def done(err):
            from gi.repository import GdkPixbuf
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path); ok = (pb.get_width(), pb.get_height()) == (256, 256)
                px = pb.get_pixels()[:3]
            except Exception as ex:
                ok, px = False, ex
            check("stored image is the 256x256 centre square", ok and tuple(px) == (0x2a, 0x7f, 0xff), px)
            self.next()
        self.page._web.fetch("/userimage.ashx?id=" + UNAME + "&rnd=1", path, None, done) if self.page._web else \
            (setattr(self.page, "_web", client.WebSession(self.c)), self.page._web.fetch("/userimage.ashx?id=" + UNAME, path, None, done))
    def s_img_del(self):
        self._orig_run = Gtk.Dialog.run
        Gtk.Dialog.run = lambda d: Gtk.ResponseType.REJECT if d.get_title() == "Manage Account Image" else self._orig_run(d)
        self.page.manage_image(); Gtk.Dialog.run = self._orig_run
        self.later(3000)
    def s_img_del_chk(self):
        check("image deleted → flags cleared", not (self.u().get("flags") or 0) & 1, self.u().get("flags"))
        self.later(100)

    def s_events(self):
        self.page.stack.set_visible_child_name("events"); self.later(2000)
    def s_events_chk(self):
        n = len(self.page.ev_store)
        msgs = [r[3] for r in self.page.ev_store]
        check("user events loaded", n > 0 and any("upuser1" in m or "Account" in m for m in msgs), (n, msgs[:3]))
        # server-wide events panel must ignore per-user replies
        sep = ap.ServerEventsPanel(self, None); sep._replied = False
        sep._on_reply({"action": "events", "events": [{"msg": "x"}], "userid": UID})
        check("Server Events ignores per-user replies", not sep._replied and len(sep.store) == 0)
        self.page.stack.set_visible_child_name("general"); self.later(800)

    def s_shot(self):
        import subprocess, os
        subprocess.run(["import", "-window", "root", os.path.join(sys.argv[1] if len(sys.argv) > 1 else "/tmp", "userpage.png")])
        self.later(100)

    def s_delete(self):
        self.page.delete_user(); self.later(2500)
    def s_delete_chk(self):
        check("user deleted, back to list", self.p.page is None and UID not in [u.get("_id") for u in self.p._users])
        self.later(100)

    def s_cleanup(self):
        for m, v in list(self.main_win.meshes.items()):
            if (v.get("name") or "").startswith("UP-"):
                self.c.send({"action": "deletemesh", "meshid": m, "meshname": v.get("name")})
        if self.ugid: self.c.send({"action": "deleteusergroup", "ugrpid": self.ugid})
        self.later(2500)

    def s_end(self):
        left = [v.get("name") for v in self.main_win.meshes.values() if v.get("name", "").startswith("UP-") and not v.get("deleted")]
        check("cleanup: test groups deleted", not left, left)
        fails = [n for n, ok in RESULTS if not ok]
        print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)), "FAILED: %s" % fails if fails else "", flush=True)
        self.quit()


T().run([])
