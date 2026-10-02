# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows CI only: the whole app against a local MeshCentral server and a REAL Windows agent.

Signs in, opens the agent's device and uses the Windows-specific parts end to end: Registry
(protocol 4: list, create key / value, export, delete), Terminal (Admin PowerShell in xterm.js),
Files, the remote Desktop in WebView2, notifications. LOCAL TEST SERVER ONLY (self-signed TLS).
Usage: python app_smoke.py <server url> <user> <password>   (exit code 0 = every check passed)
"""
import os
import ssl
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pkg", "usr", "share", "meshcentral-desktop"))
ssl.CERT_REQUIRED = ssl.CERT_NONE                  # self-signed local test server only
os.environ["MCD_TEST_INSECURE_TLS"] = "1"          # same for the embedded WebView2

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib  # noqa: E402
from mcdesktop import app as appmod, client, ui, osdep  # noqa: E402

URL, USER, PW = sys.argv[1:4]
appmod.APP_ID = "uk.co.cyvelion.MeshCentralDesktop.WinCI"
R = []
OUT = os.getcwd()


def check(name, ok, info=""):
    R.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("  " + repr(info)[:300] if info != "" else ""), flush=True)


def shot(win, name):
    try:
        sys.path.insert(0, HERE)
        from winshot import screenshot
        screenshot(win, os.path.join(OUT, name))
        print("screenshot", name, flush=True)
    except Exception as ex:
        print("screenshot failed:", ex, flush=True)


class A(appmod.App):
    def do_activate(self):
        self.steps = []
        ctrl = client.ControlConnection(URL, USER, PW)

        def ready():
            if not ctrl.userinfo:
                return True
            self.on_login(ctrl)
            self.main_win.resize(1400, 900)
            self.t0 = time.time()
            GLib.timeout_add(1000, self.wait_device)
            return False
        ctrl.connect()
        GLib.timeout_add(200, ready)
        GLib.timeout_add_seconds(600, lambda: (check("finished in time", False), self.done()))
        self.hold()

    # ---- helpers -------------------------------------------------------------------
    def wait(self, cond, then, timeout=60, name=None):
        t0 = time.time()

        def tick():
            try:
                ok = cond()
            except Exception:
                ok = False
            if ok:
                then()
                return False
            if time.time() - t0 > timeout:
                if name:
                    check(name, False, "timeout")
                then()
                return False
            return True
        GLib.timeout_add(250, tick)

    def tab(self, label):
        w = self.main_win
        w.goto_device_tab(label)
        t = next((t for t in w._device_tabs if t["label"] == label), None)
        return t and t["panel"]

    # ---- device ----------------------------------------------------------------------
    def wait_device(self):
        w = self.main_win
        self.wait(lambda: any(ui.is_online(n) for n in w.nodes.values()), self.open_device, 120,
                  "Windows agent online")
        return False

    def open_device(self):
        w = self.main_win
        node = next((n for n in w.nodes.values() if ui.is_online(n)), None)
        if node is None:
            return self.done()
        self.node = node
        check("agent reports Windows", ui.is_windows(node), (node.get("agent") or {}).get("id"))
        w._open_node_id = node["_id"]
        w.current = node
        w._open_device(node)
        labels = [t["label"] for t in w._device_tabs]
        check("Registry tab offered", "Registry" in labels, labels)
        GLib.timeout_add(1500, self.registry)

    # ---- registry ----------------------------------------------------------------------
    def registry(self):
        p = self.tab("Registry")
        self.reg = p
        p.connect_tunnel()
        self.wait(lambda: len(p.store) == 5, self.reg_roots, 60, "Registry: root hives listed")
        return False

    def reg_roots(self):
        p = self.reg
        check("Registry: 5 hives", [r[1] for r in p.store][:1] == ["HKEY_LOCAL_MACHINE"], [r[1] for r in p.store])
        p.goto_text("HKCU\\Software")
        self.wait(lambda: p.path == "Software" and len(p.store) > 0, self.reg_create, 30, "Registry: HKCU\\Software")

    def reg_create(self):
        p = self.reg
        p._send({"action": "createkey", "hive": "HKEY_CURRENT_USER", "path": "Software", "name": "MCDTestCI"})
        self.wait(lambda: any(r[1] == "MCDTestCI" for r in p.store), self.reg_value, 30,
                  "Registry: key created (reg.exe on the agent)")

    def reg_value(self):
        p = self.reg
        p.go_to("HKEY_CURRENT_USER", "Software\\MCDTestCI")
        GLib.timeout_add(1500, lambda: (p._send({"action": "setvalue", "hive": "HKEY_CURRENT_USER",
                                                  "path": "Software\\MCDTestCI", "name": "Answer",
                                                  "type": "REG_DWORD", "value": "0x2A"}), False)[1])
        self.wait(lambda: any(r[1] == "Answer" for r in p.store), self.reg_check_value, 30, "Registry: value set")

    def reg_check_value(self):
        p = self.reg
        row = next((r for r in p.store if r[1] == "Answer"), None)
        check("Registry: REG_DWORD 42 read back", row is not None and row[2] == "REG_DWORD" and row[3] == "42",
              row and tuple(row)[:4])
        self.export = None
        p._save_export = lambda content: setattr(self, "export", content)       # no save dialog in CI
        p.go_to("HKEY_CURRENT_USER", "Software")
        GLib.timeout_add(1500, lambda: (p._send({"action": "export", "hive": "HKEY_CURRENT_USER",
                                                  "path": "Software\\MCDTestCI"}), False)[1])
        self.wait(lambda: self.export is not None, self.reg_delete, 30, "Registry: export")

    def reg_delete(self):
        p = self.reg
        e = self.export or ""
        check("Registry: .reg export content", "Windows Registry Editor" in e and "MCDTestCI" in e and "Answer" in e,
              e[:160])
        p._send({"action": "delete", "items": [{"kind": "key", "hive": "HKEY_CURRENT_USER", "path": "Software",
                                                "name": "MCDTestCI"}]})
        GLib.timeout_add(1500, lambda: (p.refresh(), False)[1])
        self.wait(lambda: p.bottom.get_text() not in ("Loading registry key…",) and
                  not any(r[1] == "MCDTestCI" for r in p.store) and len(p.store) > 0,
                  self.terminal, 30, "Registry: key deleted")

    # ---- terminal ------------------------------------------------------------------------
    def terminal(self):
        p = self.tab("Terminal")
        self.term = p
        labels = [p.shell.get_model()[i][0] for i in range(len(p.shell.get_model()))]
        check("Terminal: Windows shell choices", labels == ["Admin Shell", "Admin PowerShell", "User Shell",
                                                             "User PowerShell"], labels)
        p.shell.set_active(1)
        p.connect_tunnel()
        self.wait(lambda: p.tunnel and p.tunnel.state == 3, self.term_type, 60, "Terminal: PowerShell connected")
        return False

    def term_type(self):
        GLib.timeout_add(4000, self.term_send)

    def term_send(self):
        p = self.term
        p.tunnel.send("Write-Output ('MCD-' + (6*7))\r")
        GLib.timeout_add(4000, self.term_read)
        return False

    def term_read(self):
        js = ("(function(){var b=term.buffer.active,o=[];for(var i=0;i<b.length;i++){var l=b.getLine(i);"
              "if(l)o.push(l.translateToString(true));}return o.join('\\n');})()")
        self.term.term.web.run_javascript(js, self.term_check)
        return False

    def term_check(self, text):
        text = text or ""
        check("Terminal: PowerShell output in xterm.js", "MCD-42" in text, text[-200:])
        shot(self.main_win, "app_terminal.png")
        self.term.disconnect_tunnel()
        GLib.timeout_add(1000, self.files)

    # ---- files ---------------------------------------------------------------------------
    def files(self):
        p = self.tab("Files")
        self.fp = p
        p.connect_tunnel()
        self.wait(lambda: len(p.store) > 0, self.files_root, 60, "Files: drives listed")
        return False

    def files_root(self):
        names = [r[0] for r in self.fp.store]
        check("Files: C: drive", any(n.upper().startswith("C") for n in names), names[:8])
        self.fp.disconnect_tunnel()
        GLib.timeout_add(1000, self.desktop)

    # ---- desktop ---------------------------------------------------------------------------
    def desktop(self):
        p = self.tab("Desktop")
        self.desk = p
        p._toggle_connect()
        self.wait(lambda: p._connected and not p._cover.get_visible(), self.desk_up, 90,
                  "Desktop: remote screen shown in WebView2")
        return False

    def desk_up(self):
        p = self.desk
        check("Desktop: connected", p._connected, p._phase)
        GLib.timeout_add(3000, self.desk_shot)

    def desk_shot(self):
        shot(self.main_win, "app_desktop.png")
        self.desk._toggle_connect()
        GLib.timeout_add(1500, self.notify)
        return False

    # ---- notifications ---------------------------------------------------------------------------
    def notify(self):
        hwnd = osdep.window_handle(self.main_win)
        check("main window handle", bool(hwnd))
        check("notification shown", osdep.notify(hwnd, "MeshCentral Desktop", "Windows CI notification"))
        GLib.timeout_add(2000, self.done)
        return False

    def done(self):
        print("%d/%d" % (sum(R), len(R)), flush=True)
        self.quit()
        return False


A().run([])
sys.exit(0 if R and all(R) else 1)
