# LOCALHOST TESTING ONLY (xvfb-run): Groups, "My User Groups" list + "User Group - <name>" page.
# Throwaway: users gm1/gm2, device groups GP-Group + GP-Local (agentless) with device gp-dev,
# user groups GP-*. Everything is removed at the end.
import sys, ssl, time
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client, ui, user_panel as up, group_panel as gp
appmod.APP_ID = rigenv.TEST_APP_ID
SRV, ADMIN, PW = "https://127.0.0.1:8443", "admin", "Test-1234"
RESULTS, MSGS = [], []
def check(name, ok, info=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(info) if info else ""), flush=True)
ui.message = lambda parent, title, text="", kind=None: MSGS.append((title, text))
ui.confirm = lambda *a, **k: True
HOOK = []
def fake_run(d):
    d.show_all()
    f = HOOK.pop(0) if HOOK else None
    return bool(f(d)) if f else False
up._run = fake_run; gp._run = fake_run
_orig_run = Gtk.Dialog.run
Gtk.Dialog.run = lambda d: Gtk.ResponseType.OK if d.get_title() == "Group Action" else _orig_run(d)

def widgets(w, cls):
    out = [w] if isinstance(w, cls) else []
    if isinstance(w, Gtk.Container):
        for c in w.get_children(): out += widgets(c, cls)
    return out
def tick(d, *labels):
    for c in widgets(d, Gtk.CheckButton):
        if c.get_label() in labels: c.set_active(True)
def fill_group(name, desc):
    def h(d):
        widgets(d, Gtk.Entry)[0].set_text(name)
        widgets(d, Gtk.TextView)[0].get_buffer().set_text(desc); return True
    return h


class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection(SRV, ADMIN, PW)
        def ready():
            if not ctrl.userinfo: return True
            self.on_login(ctrl); self.main_win.resize(1400, 900); GLib.timeout_add(1500, self.setup); return False
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()

    def cleanup_all(self):
        c = self.c
        for m, v in list(self.main_win.meshes.items()):
            if (v.get("name") or "").startswith("GP-"): c.send({"action": "deletemesh", "meshid": m, "meshname": v.get("name")})
        for n in ("gm1", "gm2"): c.send({"action": "deleteuser", "userid": "user//" + n})
        g = self.main_win._pages.get("usergroups")
        for gid, v in list((g.groups if g else {}).items()):
            if (v.get("name") or "").startswith("GP-"): c.send({"action": "deleteusergroup", "ugrpid": gid})

    def setup(self):
        self.c = self.main_win.ctrl
        self.main_win.show_page("usergroups"); self.p = self.main_win._pages["usergroups"]
        GLib.timeout_add(1500, self.setup1); return False
    def setup1(self):
        self.cleanup_all(); GLib.timeout_add(2000, self.setup2); return False
    def setup2(self):
        c = self.c
        for n in ("gm1", "gm2"): c.send({"action": "adduser", "username": n, "email": n + "@example.com", "pass": "Gm-1234567"})
        c.send({"action": "createmesh", "meshname": "GP-Group", "meshtype": 2, "desc": ""})
        c.send({"action": "createmesh", "meshname": "GP-Local", "meshtype": 3, "desc": ""})
        GLib.timeout_add(3500, self.setup3); return False
    def setup3(self):
        mw = self.main_win
        self.gid = next((m for m, v in mw.meshes.items() if v.get("name") == "GP-Group"), None)
        self.lid = next((m for m, v in mw.meshes.items() if v.get("name") == "GP-Local"), None)
        self.c.send({"action": "addlocaldevice", "meshid": self.lid, "devicename": "gp-dev", "hostname": "127.0.0.3", "type": 4})
        self.c.send({"action": "users"})
        GLib.timeout_add(3500, self.go); return False

    def go(self):
        self.nid = next((n for n, v in self.main_win.nodes.items() if v.get("name") == "gp-dev"), None)
        check("setup ok", self.gid and self.lid and self.nid)
        self.steps = [self.s_new, self.s_new_chk, self.s_open, self.s_edit, self.s_edit_chk, self.s_consent,
                      self.s_consent_chk, self.s_addusers, self.s_addusers_chk, self.s_rmuser, self.s_rmuser_chk,
                      self.s_addmesh, self.s_addmesh_chk, self.s_editmesh, self.s_editmesh_chk,
                      self.s_adddev, self.s_adddev_chk, self.s_shot, self.s_dup, self.s_dup_chk,
                      self.s_rmmesh, self.s_rmdev, self.s_rm_chk, self.s_link, self.s_link_chk,
                      self.s_select, self.s_delete, self.s_delete_chk, self.s_pagedel, self.s_pagedel_chk,
                      self.s_cleanup, self.s_end]
        GLib.timeout_add(500, self.next); return False

    def next(self):
        if self.steps: self.steps.pop(0)()
        return False
    def later(self, ms=2500): GLib.timeout_add(ms, self.next)
    def g(self, name):
        return next(((k, v) for k, v in self.p.groups.items() if v.get("name") == name), (None, {}))
    def labels(self):
        return [l.get_text() for l in widgets(self.page, Gtk.Label)]
    def row(self, gid):
        return next((list(r) for r in self.p.store if r[gp.UserGroupsPanel.C_ID] == gid), None)

    def s_new(self):
        check("toolbar: New / Duplicate / Select All visible", self.p.new_btn.get_visible() and self.p.dup_btn.get_visible()
              and self.p.select_btn.get_visible())
        HOOK.append(fill_group("GP-UG1", "first")); self.p.new_group(); self.later()
    def s_new_chk(self):
        self.ug, g = self.g("GP-UG1")
        check("New Group created", self.ug and g.get("desc") == "first", g)
        r = self.row(self.ug)
        check("list row counts 0/0/0 (the creator is not a member)", r and r[2:5] == ["0", "0", "0"], r)
        self.later(100)

    def s_open(self):
        self.page = self.p.open_group(self.ug)
        t = self.labels()
        for k in ("Domain", "Group Identifier", "Description", "User Consent", "Users", "Device Groups", "Devices",
                  "Group Members", "Common Device Groups", "Common Devices"):
            if k not in t: check("page row " + k, False, t); break
        else: check("group page rows", True)
        btns = [b.get_label() for b in widgets(self.page, Gtk.Button)]
        check("page actions", {"Broadcast", "Add Users", "Add Device Group", "Add Device", "Delete User Group…"} <= set(btns), btns)
        self.later(100)

    def s_edit(self):
        HOOK.append(fill_group("GP-UG1b", "renamed group")); self.page.edit_group(); self.later()
    def s_edit_chk(self):
        _k, g = self.g("GP-UG1b")
        check("rename + description", g.get("desc") == "renamed group" and "User Group - GP-UG1b" in self.page.title.get_text(),
              (g.get("name"), g.get("desc")))
        self.later(100)

    def s_consent(self):
        def h(d):
            for c in widgets(d, Gtk.CheckButton):
                if c.get_label() == "Prompt for user consent": c.set_active(True); break    # Desktop prompt
            return True
        HOOK.append(h); self.page.edit_consent(); self.later()
    def s_consent_chk(self):
        _k, g = self.g("GP-UG1b")
        check("user consent → 8 (Desktop Prompt)", g.get("consent") == 8 and "Desktop Prompt" in self.labels(), g.get("consent"))
        self.later(100)

    def s_addusers(self):
        def h(d):
            e = widgets(d, Gtk.Entry)[0]
            lb = widgets(d, Gtk.ListBox)[0]
            e.set_text("gm")
            rows = [r for r in lb.get_children() if r.get_visible()]
            names = [widgets(r, Gtk.Label)[0].get_text() for r in rows]
            check("suggestions shown while typing", lb.get_visible() and names == ["gm1", "gm2"], (lb.get_visible(), names))
            lb.emit("row-activated", rows[1])
            check("picking a suggestion fills the name", e.get_text() == "gm2", e.get_text())
            e.set_text("gm2, gm")
            names2 = [widgets(r, Gtk.Label)[0].get_text() for r in lb.get_children() if r.get_visible()]
            lb.emit("row-activated", [r for r in lb.get_children() if r.short == "gm1"][0])
            check("suggestions work on the last name of the list", e.get_text() == "gm2, gm1" and not lb.get_visible(), (names2, e.get_text()))
            e.set_text("zzz")
            check("no match → list hidden", not lb.get_visible())
            e.set_text("gm1, gm2"); return True
        HOOK.append(h); self.page.add_users(); self.later()
    def s_addusers_chk(self):
        _k, g = self.g("GP-UG1b")
        links = g.get("links") or {}
        check("members added", "user//gm1" in links and "user//gm2" in links, list(links))
        check("member rows", "gm1" in self.labels() and "gm2" in self.labels())
        self.later(100)

    def s_rmuser(self):
        self.page.remove_member("user//gm2", "gm2"); self.later()
    def s_rmuser_chk(self):
        check("member removed", "user//gm2" not in (self.g("GP-UG1b")[1].get("links") or {})); self.later(100)

    def s_addmesh(self):
        def h(d):
            widgets(d, Gtk.ComboBoxText)[0].set_active_id(self.gid)
            tick(d, "Remote Control & Relay", "Mesh Agent Console"); return True
        HOOK.append(h); self.page.group_rights(); self.later()
    def s_addmesh_chk(self):
        r = ((self.g("GP-UG1b")[1].get("links") or {}).get(self.gid) or {}).get("rights")
        check("device group added (24)", r == 24, r)
        check("rights text", "Control, Console" in self.labels())
        check("no false 'failed' dialogs", not MSGS, MSGS)
        self.later(100)

    def s_editmesh(self):
        HOOK.append(lambda d: (tick(d, "Full Administrator"), True)[1]); self.page.group_rights(self.gid); self.later()
    def s_editmesh_chk(self):
        r = ((self.g("GP-UG1b")[1].get("links") or {}).get(self.gid) or {}).get("rights")
        check("device group → Full Rights", r == 0xFFFFFFFF and "Full Rights" in self.labels(), r); self.later(100)

    def s_adddev(self):
        def h(d):
            cbs = widgets(d, Gtk.ComboBoxText); ids = lambda cb: [r[1] for r in cb.get_model()]
            mc = next(cb for cb in cbs if self.lid in ids(cb)); mc.set_active_id(self.lid)
            next(cb for cb in cbs if cb is not mc).set_active_id(self.nid)
            tick(d, "Remote Control & Relay", "Wake Devices"); return True
        HOOK.append(h); self.page.device_rights(); self.later()
    def s_adddev_chk(self):
        r = ((self.g("GP-UG1b")[1].get("links") or {}).get(self.nid) or {}).get("rights")
        check("device added (72)", r == 72 and "gp-dev" in self.labels(), r)
        row = self.row(self.g("GP-UG1b")[0])
        check("list counts 1/1/1", row and row[2:5] == ["1", "1", "1"], row)
        self.later(100)

    def s_shot(self):
        import subprocess, os
        subprocess.run(["import", "-window", "root", os.path.join(sys.argv[1] if len(sys.argv) > 1 else "/tmp", "grouppage.png")])
        self.later(100)

    def s_dup(self):
        def h(d):
            cb = widgets(d, Gtk.ComboBoxText)[0]; cb.set_active_id(self.ug)
            widgets(d, Gtk.Entry)[0].set_text("GP-dup"); return True
        HOOK.append(h); self.p.new_group(duplicate=True); self.later(3000)
    def s_dup_chk(self):
        k, g = self.g("GP-dup")
        links = g.get("links") or {}
        check("Duplicate copies members + device group permissions (not devices, like the server)",
              k and "user//gm1" in links and links.get(self.gid, {}).get("rights") == 0xFFFFFFFF and self.nid not in links,
              list(links))
        self.later(100)

    def s_rmmesh(self):
        self.page.remove_mesh(self.gid); self.later(1500)
    def s_rmdev(self):
        self.page.remove_device(self.nid); self.later(2500)
    def s_rm_chk(self):
        links = self.g("GP-UG1b")[1].get("links") or {}
        check("device group + device permissions removed", self.gid not in links and self.nid not in links, list(links))
        self.later(100)

    def s_link(self):
        self.p.open_user("user//gm1"); self.later(3500)
    def s_link_chk(self):
        upanel = self.main_win._pages.get("users")
        check("member name opens the user page", upanel and upanel.page and upanel.page.user.get("_id") == "user//gm1")
        self.main_win.show_page("usergroups"); self.p.close_group(); self.later(800)

    def s_select(self):
        self.p.toggle_select_all()
        check("Select All", self.p._checked == set(self.p.groups) and self.p.select_btn.get_label() == "Select None"
              and self.p.group_btn.get_sensitive())
        self.p.toggle_select_all()
        check("Select None", not self.p._checked and not self.p.group_btn.get_sensitive())
        for i, r in enumerate(self.p.store):
            if r[gp.UserGroupsPanel.C_NAME] in ("GP-UG1b", "GP-dup"): self.p._on_toggled(None, str(i))
        self.later(100)

    def s_delete(self):
        self.p.group_action(); self.later(3000)
    def s_delete_chk(self):
        check("Group Action → delete", not self.g("GP-UG1b")[0] and not self.g("GP-dup")[0], [v.get("name") for v in self.p.groups.values()])
        HOOK.append(fill_group("GP-UG2", "")); self.p.new_group(); self.later(2500)

    def s_pagedel(self):
        self.page = self.p.open_group(self.g("GP-UG2")[0]); self.page.delete_group(); self.later(2500)
    def s_pagedel_chk(self):
        check("Delete User Group from the page, back to the list", not self.g("GP-UG2")[0] and self.p.page is None)
        self.later(100)

    def s_cleanup(self):
        self.cleanup_all(); self.later(2500)

    def s_end(self):
        fails = [n for n, ok in RESULTS if not ok]
        print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)), "FAILED: %s" % fails if fails else "", flush=True)
        self.quit()


T().run([])
