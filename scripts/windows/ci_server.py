# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows CI only: prepare the throwaway local MeshCentral server for the app test.

Signs in as the CI admin, creates the device group "CI", downloads the Windows agent and its
settings for that group into <out_dir> (meshagent.exe + meshagent.msh). LOCAL TEST SERVER ONLY:
TLS verification is off because the server uses a self-signed certificate on 127.0.0.1.
Usage: python ci_server.py <server url> <user> <password> <out_dir>
"""
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pkg", "usr", "share", "meshcentral-desktop"))
ssl.CERT_REQUIRED = ssl.CERT_NONE                  # self-signed local test server only

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import GLib  # noqa: E402
from mcdesktop import client  # noqa: E402

URL, USER, PW, OUT = sys.argv[1:5]
loop = GLib.MainLoop()
c = client.ControlConnection(URL, USER, PW)
state = {"meshid": None}


def fetch(path, dest):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(URL.rstrip("/") + path, context=ctx, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    print("downloaded", dest, os.path.getsize(dest), flush=True)


def ready():
    if not c.userinfo:
        return True
    c.on("meshes", got_meshes)
    c.send({"action": "createmesh", "meshname": "CI", "meshtype": 2, "desc": "Windows CI"})
    GLib.timeout_add(2000, lambda: (c.send({"action": "meshes"}), False)[1])
    return False


def got_meshes(msg):
    m = [x for x in msg.get("meshes") or [] if x.get("name") == "CI"]
    if not m or state["meshid"]:
        return
    state["meshid"] = m[0]["_id"]
    os.makedirs(OUT, exist_ok=True)
    fetch("/meshagents?id=4", os.path.join(OUT, "meshagent.exe"))            # Windows x64 agent
    short = state["meshid"].split("/")[-1]
    fetch("/meshsettings?id=" + urllib.parse.quote(short, safe=""), os.path.join(OUT, "meshagent.msh"))
    loop.quit()


c.on_close = lambda reason: print("control connection closed:", reason, flush=True)
c.connect()
GLib.timeout_add(200, ready)
GLib.timeout_add_seconds(180, lambda: (print("timeout", flush=True), loop.quit()))
t0 = time.time()
loop.run()
sys.exit(0 if state["meshid"] and os.path.isfile(os.path.join(OUT, "meshagent.msh")) else 1)
