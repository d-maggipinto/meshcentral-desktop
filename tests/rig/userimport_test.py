# LOCALHOST TESTING ONLY (xvfb-run): Users page export (CSV/JSON) + batch import (adduserbatch).
# Creates throwaway accounts imp1..imp4 and deletes them at the end.
import sys, ssl, os, time, json, csv, io, base64
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client, ui, admin_panel as ap
appmod.APP_ID = rigenv.TEST_APP_ID
SRV, ADMIN, PW = "https://127.0.0.1:8443", "admin", "Test-1234"
TMP = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
RESULTS = []
def check(name, ok, info=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(info) if info else ""), flush=True)
ui.message = lambda *a, **k: None
SAVED = {}
def fake_save(parent, title, filename, text):
    SAVED[filename] = text
ap._save_text = fake_save

# ---- pure helpers -------------------------------------------------------------------------
e = ap.parse_user_import("user,pass,email,resetNextLogin\r\nx1,Aa-123456!,x1@example.com,\r\n,,,\r\nx2,Aa-123456!,,TRUE\r\n", "a.csv")
check("csv parse", e == [{"user": "x1", "pass": "Aa-123456!", "email": "x1@example.com"},
                         {"user": "x2", "pass": "Aa-123456!", "resetNextLogin": True}], e)
check("json parse", ap.parse_user_import('[{"user":"a","pass":"b"}]', "x.json") == [{"user": "a", "pass": "b"}])
for bad, why in (({"user": "a b", "pass": "x"}, "space"), ({"user": "~a", "pass": "x"}, "~"),
                 ({"user": "a", "pass": ""}, "empty pass"), ({"user": "a", "pass": "x", "email": "x1@x"}, "web example email"),
                 ({"pass": "x"}, "no user")):
    check("validate rejects " + why, ap.validate_import_entry(bad))
check("validate accepts", ap.validate_import_entry({"user": "a", "pass": "x", "email": "a@b.co", "resetNextLogin": True}) is None)
try:
    ap.parse_user_import("name,password\nx,y\n", "a.csv"); check("csv header check", False)
except ValueError:
    check("csv header check", True)


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
        mw = self.main_win; self.ctrl = mw.ctrl; self.win = mw
        mw.show_page("users"); self.panel = mw._pages["users"]
        GLib.timeout_add(2000, self.after_list)
        return False

    def after_list(self):
        p = self.panel
        names = [u.get("name") for u in p._users]
        check("list loaded", ADMIN in names, names)
        check("export/import enabled", p.export_btn.get_sensitive() and p.import_btn.get_sensitive())
        p.export_users("csv"); p.export_users("json")
        rows = list(csv.reader(io.StringIO(SAVED.get("userlist.csv", ""))))
        check("csv header = web columns", rows and rows[0] == ap.EXPORT_CSV_COLUMNS, rows[:1])
        adm = [r for r in rows[1:] if r[1] == ADMIN]
        check("csv admin row flags", adm and adm[0][7:] == ["1", "1", "0"] and adm[0][0] == "user//admin", adm)
        js = json.loads(SAVED.get("userlist.json", "[]"))
        check("json export objects", any(u.get("name") == ADMIN for u in js) and not any("hash" in u or "salt" in u for u in js))
        # ---- import: invalid file blocks the import ----
        bad = os.path.join(TMP, "bad.csv")
        open(bad, "w").write("user,pass,email\nimp1,Imp-12345!,imp1@x\n")
        d = ap.UserImportDialog(self.win, self.ctrl, names)
        d.load_file(bad)
        check("invalid row blocks import", not d.ok_btn.get_sensitive() and d.store[0][3].startswith("Invalid"), d.store[0][3])
        d.destroy()
        # ---- import: good file (one existing name, one reset flag) ----
        email_mode = bool(ap._features(self.ctrl) & ap.FEAT_USERNAME_IS_EMAIL)
        self.n2 = "imp2@example.com" if email_mode else "imp2"      # no email column value → user must be an email
        if email_mode:
            chk = ap.UserImportDialog(self.win, self.ctrl, names)
            open(os.path.join(TMP, "noemail.csv"), "w").write("user,pass\nimp9,Imp-12345!\n")
            chk.load_file(os.path.join(TMP, "noemail.csv"))
            check("email mode: plain user without email flagged", chk.store[0][3].startswith("Invalid"), chk.store[0][3])
            chk.destroy()
        good = os.path.join(TMP, "good.csv")
        open(good, "w").write("user,pass,email,resetNextLogin\nimp1,Imp-12345!,imp1@example.com,\n"
                              "%s,Imp-12345!,,true\n%s" % (self.n2, "" if email_mode else "admin,Whatever-1!,,\n"))
        self.dlg = p.import_users()
        self.dlg.load_file(good)
        st = [r[3] for r in self.dlg.store]
        check("preview statuses", st == ["New", "New"] + ([] if email_mode else ["Already exists, will be skipped"]), st)
        check("import enabled", self.dlg.ok_btn.get_sensitive())
        # email-as-username server: the server renames a row with an email to that email
        self.n1 = "imp1@example.com" if ap._features(self.ctrl) & ap.FEAT_USERNAME_IS_EMAIL else "imp1"
        self.dlg.response(Gtk.ResponseType.OK)
        self.t0 = time.time()
        GLib.timeout_add(300, self.wait_created)
        return False

    def wait_created(self):
        if self.dlg.created != {self.n1, self.n2} and time.time() - self.t0 < 10:
            return True
        check("accounts created (events counted)", self.dlg.created == {self.n1, self.n2}, self.dlg.result.get_text())
        check("rows marked Created", [r[3] for r in self.dlg.store][:2] == ["Created", "Created"])
        GLib.timeout_add(1500, self.after_refresh)
        return False

    def after_refresh(self):
        us = {u.get("name"): u for u in self.panel._users}
        us["imp1"] = us.get(self.n1, {}); us["imp2"] = us.get(self.n2, {})
        check("panel refreshed with new users", self.n1 in us and self.n2 in us, sorted(us))
        check("resetNextLogin → passchange -1", us.get("imp2", {}).get("passchange") == -1 and us.get("imp1", {}).get("passchange", -1) != -1,
              (us.get("imp1", {}).get("passchange"), us.get("imp2", {}).get("passchange")))
        check("email stored", us.get("imp1", {}).get("email") == "imp1@example.com")
        self.dlg.destroy()
        # ---- server-side error path: bypass local validation to get the server's error reply ----
        self.dlg2 = ap.UserImportDialog(self.win, self.ctrl, list(us))
        self.dlg2.to_send = [{"user": "imp3", "pass": "x"}, {"user": "imp4", "pass": "Imp-12345!", "email": "bad@x"}]
        self.dlg2.response(Gtk.ResponseType.OK)
        GLib.timeout_add(2500, self.after_error)
        return False

    def after_error(self):
        txt = self.dlg2.result.get_text()
        check("server error reply shown, nothing created", txt.startswith("Import failed:") and not self.dlg2.created, txt)
        self.dlg2.destroy()
        for n in ("imp1", "imp2", "imp3", "imp4", "imp1@example.com", "imp2@example.com"):
            self.ctrl.send({"action": "deleteuser", "userid": "user//" + n})
        GLib.timeout_add(1500, self.done)
        return False

    def done(self):
        self.ctrl.send({"action": "users"})
        def got(m):
            left = [u["name"] for u in m.get("users", []) if u["name"].startswith("imp")]
            check("cleanup: throwaway accounts deleted", not left, left)
            fails = [n for n, ok in RESULTS if not ok]
            print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)), "FAILED: %s" % fails if fails else "", flush=True)
            self.quit()
        self.ctrl.on("users", got)
        return False


T().run([])
