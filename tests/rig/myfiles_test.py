# LOCALHOST TESTING ONLY (xvfb-run). Admin: exercise My Files end to end.
import sys, ssl, time, os, hashlib
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib, WebKit2
from mcdesktop import app as appmod, client, ui, rights
from mcdesktop.server_files_panel import ServerFilesPanel
appmod.APP_ID = rigenv.TEST_APP_ID
SP = os.path.dirname(os.path.abspath(__file__))
def _ctx():
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c.check_hostname = False; c.verify_mode = 0; return c
client.http_ssl_context = _ctx
ui.confirm = lambda *a, **k: True
ui.message = lambda parent, title, text="", kind=None: print("   (dialog)", title, "|", text, flush=True)
EDITED = "hello from mcd\nline 2\nEDITED BY TEST\n"
ui.form_dialog = lambda parent, title, fields, ok="OK": {"text": EDITED} if title.startswith("Edit") else None
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]

class T(appmod.App):
    def do_activate(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win; mw.show_page("files")
        self.p = p = mw._pages["files"]
        print("tab 0 is", type(p).__name__, "| allowed:", p.allowed, flush=True)
        self.steps = [self.s_enter, self.s_mkdir, self.s_enter_dir, self.s_upload, self.s_check_upload,
                      self.s_download, self.s_check_download, self.s_rename, self.s_copy, self.s_paste,
                      self.s_edit_upload, self.s_edit, self.s_check_edit, self.s_cleanup, self.s_done]
        GLib.timeout_add(1500, self.next)
        return False
    def next(self):
        if self.steps: self.steps.pop(0)()
        return False
    def later(self, ms=1500): GLib.timeout_add(ms, self.next)
    def names(self): return [r[4] for r in self.p.store]
    def sel(self, name):
        s = self.p.tree.get_selection(); s.unselect_all()
        for i, r in enumerate(self.p.store):
            if r[4] == name: s.select_path(Gtk.TreePath(i))
    def s_enter(self):
        p = self.p
        print("ROOT entries:", [(r[1], r[0]) for r in p.store], "| status:", p.status.get_text(), flush=True)
        uid = p.app.ctrl.userinfo["_id"]; p.path = [uid]; p._render()
        print("in My Files:", self.names(), "| crumb:", p.crumb.get_text(), flush=True); self.later(300)
    def s_mkdir(self):
        self.p._op(fileop="createfolder", newfolder="mcdtest"); self.later()
    def s_enter_dir(self):
        print("MKDIR ->", "PASS" if "mcdtest" in self.names() else "FAIL", flush=True)
        self.p.path = self.p.path + ["mcdtest"]; self.p._render(); self.later(300)
    def s_upload(self):
        self.t0 = time.time(); self.p._upload_next([SP + "/upload-300k.bin"], self.p._link()); self.later(3000)
    def s_check_upload(self):
        size = next((r[6] for r in self.p.store if r[4] == "upload-300k.bin"), None)
        print(f"UPLOAD 300 KB -> {'PASS' if size == 307200 else 'FAIL'} (size on server {size}) status={self.p.status.get_text()!r}", flush=True)
        self.later(100)
    def s_download(self):
        self.dest = SP + "/downloaded.bin"
        if os.path.exists(self.dest): os.remove(self.dest)
        self.p._download_next([("upload-300k.bin", 307200, self.dest)], list(self.p.path)); self.later(3000)
    def s_check_download(self):
        ok = os.path.exists(self.dest) and sha(self.dest) == sha(SP + "/upload-300k.bin")
        print(f"DOWNLOAD via HTTP session -> {'PASS' if ok else 'FAIL'} (sha match {ok})", flush=True); self.later(100)
    def s_rename(self):
        self.p._op(fileop="rename", oldname="upload-300k.bin", newname="renamed.bin"); self.later()
    def s_copy(self):
        print("RENAME ->", "PASS" if "renamed.bin" in self.names() else "FAIL", flush=True)
        self.sel("renamed.bin"); self.p.clip("copy")
        self.p.path = self.p.path[:-1] + ["Public"]; self.p._render(); self.later(300)
    def s_paste(self):
        self.p.paste(); self.later(2000)
    def s_edit_upload(self):
        print("COPY to Public ->", "PASS" if "renamed.bin" in self.names() else "FAIL", flush=True)
        self.p._upload_next([SP + "/notes.txt"], self.p._link()); self.later(2500)
    def s_edit(self):
        self.sel("notes.txt"); self.p.edit(); self.later(2500)
    def s_check_edit(self):
        # read it back through the websocket get
        got = {}
        def r(m):
            if m.get("fileop") == "get" and m.get("file") == "notes.txt" and "data" in m:
                import base64; got["t"] = base64.b64decode(m["data"]).decode()
        self.p.app.ctrl.on("fileoperation", r)
        self.p.app.ctrl.send({"action": "fileoperation", "fileop": "get", "path": list(self.p.path), "file": "notes.txt"})
        def chk():
            print("EDIT text file ->", "PASS" if got.get("t") == EDITED else f"FAIL {got!r}", flush=True); self.next(); return False
        GLib.timeout_add(1500, chk)
    def s_cleanup(self):
        p = self.p
        p._op(fileop="delete", delfiles=["renamed.bin", "notes.txt"], rec=True)
        p.path = p.path[:-1]; p._op(fileop="delete", delfiles=["mcdtest"], rec=True); p._render(); self.later(2000)
    def s_done(self):
        print("CLEANUP ->", "PASS" if "mcdtest" not in self.names() else "FAIL", "| My Files now:", self.names(), flush=True)
        self.quit()
T().run([])
