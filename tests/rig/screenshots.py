# SPDX-License-Identifier: Apache-2.0
# LOCALHOST TESTING ONLY (xvfb-run): regenerates the README screenshots in docs/images/ from the
# local rig, with neutral sample data (example users, groups and agentless devices) that is created
# here and deleted at the end. The app runs with a throwaway config directory, so no personal
# settings (saved server, user name) can appear.
#   GDK_BACKEND=x11 WEBKIT_DISABLE_DMABUF_RENDERER=1 xvfb-run -a -s "-screen 0 1280x800x24" \
#       python3 tests/rig/screenshots.py
import json
import os
import ssl
import subprocess
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="mcd-shots-")
os.environ["GTK_THEME"] = "Adwaita:dark"          # neutral theme, not the desktop's own
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(TMP, var.lower())
os.makedirs(os.path.join(os.environ["XDG_CONFIG_HOME"], "meshcentral-desktop"))
with open(os.path.join(os.environ["XDG_CONFIG_HOME"], "meshcentral-desktop", "config.json"), "w") as f:
    json.dump({"dark": True, "server": "https://mesh.example.com", "username": "alice", "remember": False}, f)

import rigenv  # noqa: E402  (puts the app on sys.path)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib  # noqa: E402
from mcdesktop import app as appmod, client, ui  # noqa: E402

appmod.APP_ID = rigenv.TEST_APP_ID
OUT = os.path.join(rigenv.REPO, "docs", "images")
os.makedirs(OUT, exist_ok=True)
W, H = 1280, 800
ui.confirm = lambda *a, **k: True


def shot(name, w=W, h=H):
    while Gtk.events_pending():
        Gtk.main_iteration()
    subprocess.run(["import", "-window", "root", "-crop", f"{w}x{h}+0+0", os.path.join(OUT, name)], check=True)
    print("saved", name, flush=True)


class T(appmod.App):
    def do_activate(self):
        super().do_activate()                     # the real login window, with the neutral config
        GLib.timeout_add(1500, self.login_shot)

    def login_shot(self):
        win = self.get_windows()[0]
        win.move(0, 0)

        def take():
            ext = win.get_window().get_frame_extents()        # includes the title bar
            shot("login.png", ext.x + ext.width, ext.y + ext.height)
            self.sign_in()
            return False
        GLib.timeout_add(500, take)
        return False

    def sign_in(self):
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")

        def ready():
            if not ctrl.userinfo:
                return True
            for w in list(self.get_windows()):
                if w is not getattr(self, "main_win", None):
                    w.hide()
            self.on_login(ctrl)
            self.main_win.move(0, 0)
            self.main_win.resize(W, H)
            GLib.timeout_add(1500, self.setup)
            return False
        ctrl.connect()
        GLib.timeout_add(200, ready)

    # ---- sample data ------------------------------------------------------------------------
    def setup(self):
        c = self.c = self.main_win.ctrl
        c.send({"action": "createmesh", "meshname": "Office", "meshtype": 3, "desc": "Front office computers"})
        c.send({"action": "createmesh", "meshname": "Servers", "meshtype": 3, "desc": "Data center"})
        for name, email, real in (("alice", "alice@example.com", "Alice Martin"), ("bob", "bob@example.com", "Bob Lee"),
                                  ("carol", "carol@example.com", "Carol Diaz")):
            c.send({"action": "adduser", "username": name, "email": email, "pass": "Sample-12345", "realname": real})
        c.send({"action": "createusergroup", "name": "Support", "desc": "Help desk team"})
        GLib.timeout_add(3000, self.setup2)
        return False

    def setup2(self):
        c, mw = self.c, self.main_win
        self.m = {v.get("name"): k for k, v in mw.meshes.items()}
        for mesh, devs in (("Office", ("reception-pc", "accounts-pc", "meeting-room")),
                           ("Servers", ("file-server", "web-01", "backup-nas"))):
            for i, d in enumerate(devs):
                c.send({"action": "addlocaldevice", "meshid": self.m[mesh], "devicename": d,
                        "hostname": f"10.0.{1 if mesh == 'Office' else 2}.{10 + i}", "type": 4})
        c.send({"action": "edituser", "id": "user//bob", "siteadmin": 8})
        c.send({"action": "edituser", "id": "user//carol", "siteadmin": 32})
        c.send({"action": "addmeshuser", "meshid": self.m["Office"], "meshname": "Office",
                "userids": ["user//alice", "user//bob"], "meshadmin": 8 | 16 | 64 | 128})
        c.send({"action": "setNotes", "id": "user//alice", "notes": "Team lead, front office."})
        GLib.timeout_add(2500, self.setup3)
        return False

    def setup3(self):
        c = self.c
        c.send({"action": "usergroups"})

        def got(msg):
            c.off("usergroups", got)
            self.ug = next((k for k, v in (msg.get("ugroups") or {}).items() if v.get("name") == "Support"), None)
            c.send({"action": "addusertousergroup", "ugrpid": self.ug, "usernames": ["alice", "bob"]})
            c.send({"action": "addmeshuser", "meshid": self.m["Servers"], "meshname": "Servers",
                    "userids": [self.ug], "meshadmin": 8 | 16})
            GLib.timeout_add(3000, self.shots)
        c.on("usergroups", got)
        return False

    # ---- screenshots --------------------------------------------------------------------------
    def shots(self):
        mw = self.main_win
        self.steps = [
            lambda: self.open_device("file-server"), lambda: shot("devices.png"),
            lambda: mw.show_page("users"), lambda: shot("users.png"),
            lambda: mw._pages["users"].open_user("user//alice"), lambda: shot("user-page.png"),
            lambda: (mw._pages["users"].close_user(), mw.show_page("usergroups")),
            lambda: mw._pages["usergroups"].open_group(self.ug), lambda: shot("group-page.png"),
            lambda: mw.show_page("server"), lambda: shot("my-server.png"),
            lambda: mw.show_page("account"), lambda: shot("my-account.png"),
            self.cleanup, lambda: self.quit()]
        GLib.timeout_add(500, self.step)
        return False

    def step(self):
        if self.steps:
            self.steps.pop(0)()
            GLib.timeout_add(2500, self.step)
        return False

    def open_device(self, name):
        mw = self.main_win
        mw.show_page("devices")
        node = next(n for n in mw.nodes.values() if n.get("name") == name)
        mw._open_node_id = node["_id"]
        mw.current = node
        mw._open_device(node)

    def cleanup(self):
        c = self.c
        for mesh in ("Office", "Servers"):
            c.send({"action": "deletemesh", "meshid": self.m[mesh], "meshname": mesh})
        for name in ("alice", "bob", "carol"):
            c.send({"action": "deleteuser", "userid": "user//" + name})
        if self.ug:
            c.send({"action": "deleteusergroup", "ugrpid": self.ug})


T().run([])
