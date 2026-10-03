# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows build check: Edge WebView2 embedded in a GTK 3 window (mcdesktop.winweb).

Run by the Windows CI job (MSYS2 UCRT64 Python). Exit code 0 = every check passed.
Writes webview2_smoke.png (a screenshot of the window) next to the working directory.
"""
import os
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pkg", "usr", "share", "meshcentral-desktop"))
sys.path.insert(0, HERE)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, GLib  # noqa: E402
from mcdesktop import winweb  # noqa: E402
from winshot import screenshot  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("  " + repr(info) if info != "" else ""), flush=True)


PAGE = """<!doctype html><html><head><title>MCD smoke</title></head>
<body style="font-family:sans-serif;margin:20px">
<h1 id=h>MeshCentral Desktop: WebView2 inside GTK</h1><p id=p>Embedded page</p>
<script>window.addEventListener('load',function(){
  window.chrome.webview.postMessage('loaded:'+document.title+':'+window.__mcd);
});</script></body></html>"""


class Smoke:
    def __init__(self):
        ver = winweb.runtime_version()
        check("WebView2 runtime installed", bool(ver), ver or "")
        self.msgs = []
        self.blocked = []
        self.win = Gtk.Window(title="MeshCentral Desktop WebView2 smoke")
        self.win.set_default_size(900, 600)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(Gtk.Label(label="GTK label above the web view"), False, False, 6)
        self.web = winweb.WebView2Widget(user_data_dir=os.path.join(os.getcwd(), "wv2-data"))
        self.web.on_ready = self.ready
        self.web.on_error = lambda e: (check("WebView2 created", False, e), self.finish())
        self.web.on_message = self.msgs.append
        self.web.allow_navigation = self.policy
        box.pack_start(self.web, True, True, 0)
        box.pack_start(Gtk.Label(label="GTK label below the web view"), False, False, 6)
        self.win.add(box)
        # queued before WebView2 exists: must run on every document
        self.web.add_user_script("window.__mcd=42;")
        self.web.add_user_css("#p{color:rgb(1, 2, 3)}")
        self.web.load_html(PAGE)
        self.win.show_all()
        self.t0 = time.time()
        GLib.timeout_add_seconds(60, lambda: (check("finished in time", False), self.finish()))

    def policy(self, uri):
        ok = uri.startswith("data:") or uri.startswith("about:")
        if not ok:
            self.blocked.append(uri)
        return ok

    def ready(self):
        check("WebView2 created inside the GTK window", True, "%.1fs" % (time.time() - self.t0))
        GLib.timeout_add(3000, self.step1)

    def step1(self):
        check("page posted a message after load (user script ran first)", "loaded:MCD smoke:42" in self.msgs, self.msgs)
        self.web.run_javascript("1+2", lambda v: (check("run_javascript returns values", v == 3, v), self.step2()))
        return False

    def step2(self):
        self.web.run_javascript("getComputedStyle(document.getElementById('p')).color",
                                lambda v: (check("user CSS applied", v == "rgb(1, 2, 3)", v), self.step3()))

    def step3(self):
        self.web.run_javascript("String(window.open('https://example.com/'))",
                                lambda v: (check("pop-up blocked", v in ("null", "None", None), v), self.step4()))

    def step4(self):
        self.web.run_javascript("location.href='https://example.com/';1")
        GLib.timeout_add(2000, self.step5)

    def step5(self):
        self.web.run_javascript("document.title", lambda v: (
            check("cross-site navigation cancelled by the policy", v == "MCD smoke" and
                  any(urllib.parse.urlsplit(u).hostname == "example.com" for u in self.blocked),
                  (v, self.blocked)), self.step6()))
        return False

    def step6(self):
        # a page loaded from a string is not a secure context: no navigator.clipboard at all (= no access);
        # where it exists, the PermissionRequested handler must deny the read
        self.web.run_javascript(
            "(function(){var p=window.chrome.webview;if(!navigator.clipboard||!navigator.clipboard.readText)"
            "{p.postMessage('clip:denied');return 1;}navigator.clipboard.readText().then("
            "function(){p.postMessage('clip:read')},function(e){p.postMessage('clip:denied')});return 1;})()")
        GLib.timeout_add(2000, self.step7)

    def step7(self):
        check("page clipboard read denied", "clip:denied" in self.msgs, [m for m in self.msgs if m.startswith("clip")])
        a = self.web.get_allocation()
        check("web view has a real size", a.width > 400 and a.height > 300, (a.width, a.height))
        try:
            white = screenshot(self.web, os.path.join(os.getcwd(), "webview2_smoke.png"))
            print("screenshot saved, white ratio in the middle row: %.2f" % white, flush=True)
        except Exception as ex:
            print("screenshot failed:", ex, flush=True)
        self.finish()
        return False

    def finish(self):
        print("%d/%d" % (sum(R), len(R)), flush=True)
        Gtk.main_quit()
        return False


Smoke()
Gtk.main()
sys.exit(0 if R and all(R) else 1)
