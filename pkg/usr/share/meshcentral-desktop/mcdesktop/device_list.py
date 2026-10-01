# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Devices list features of the web UI's "My Devices": status filter, search syntax, sort,
OS name, stars, Group Action on checked devices, Add Agent / Invite per device group,
Add Device Group and MeshCmd.

Filters, search and sort are client-side over the `nodes` list (like the web UI). Stars are kept
in the app's config: the web UI's copy lives in the browser and can only be written to the
server by replacing the user's whole web state (userWebState), which would wipe their other
browser settings.

Server behaviour worth knowing (MeshCentral 1.2.5, see docs/PROTOCOL.md): many device actions
never reply (uninstallagent, msg messagebox/alertbox); removedevices / changeDeviceMesh /
changedevice / toast / runcommands reply only with a responseid, once per device; the real
confirmation is an event (removenode, nodemeshchange, changenode). The server silently skips
devices without the needed right, so the app checks rights first and says how many it skipped.
"""
import io
import json
import os
import re
import secrets
import time
import urllib.parse

from gi.repository import Gtk, GLib, Pango

from . import ui, rights
from .client import WebSession

FULL = rights.FULL

# (label, value) like the web UI's DevFilterSelect
FILTERS = [("All", 0), ("Online", 1), ("Offline", 5), ("Sessions", 2), ("Starred", 3),
           ("Intel® AMT", 4), ("Help", 6), ("Tagged", 7), ("Untagged", 8)]
SORTS = ["Group", "Power", "Device", "Tags", "Group-Tags", "Last Seen", "Last Boot Up Time"]
POWER_HEADERS = ["", "Powered", "Sleep", "Sleep", "Sleep", "Hibernating", "Power off", "Present"]
POWER_STATES = {1: "Powered", 2: "Sleeping", 3: "Sleeping", 4: "Deep Sleep", 5: "Hibernating",
                6: "Soft-Off", 7: "Present", 8: "Off"}
SEARCH_HELP = ("Filter by name, or use a prefix: user: (u:) ip: group: (g:) tag: (t:) atag: (a:) os: amt: "
               "desc: wsc:ok/noav/noupdate/nofirewall/any connectivity: (c:). Prefix a term with ! to negate "
               "it; combine terms with \"and\" / \"or\".")
WINDOWS_AGENTS = (1, 2, 3, 4, 21, 22, 34, 42, 43)            # web UI isWindowsNode

SITE_NONEWGROUPS, SITE_NOMESHCMD, SITE_NONEWDEVICES = 64, 128, 4096
FEAT_WANONLY, FEAT_LANONLY, FEAT_EMAIL_INVITE = 0x1, 0x2, 0x40
FEAT_NOPROXY, FEAT_MQTT, FEAT_UNTRUSTED_CERT = 0x2000, 0x400000, 0x80000000


def _nat_key(s):
    """Natural, case-insensitive order (the web UI uses Intl.Collator numeric)."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", (s or "").lower())]


def node_name(node, os_name=False):
    """Display name: the device name, or the OS host name (rname) with "OS Name"."""
    return (node.get("rname") or node.get("name") or "") if os_name else (node.get("name") or "")


def is_windows(node):
    return (node.get("agent") or {}).get("id") in WINDOWS_AGENTS


def online(node, mtype=None):
    return bool((node.get("conn") or 0) & 1) or mtype == 3


def state_text(node, mtype=None):
    """Web UI NodeStateStr: "Agent, Powered" (connectivity + power state)."""
    c, out = node.get("conn") or 0, []
    if c & 1:
        out.append(("Switch" if node.get("porttype") == "PDU" else "IP-KVM") if mtype == 4 else "Agent")
    if c & 2:
        out.append("CIRA")
    elif c & 4:
        out.append("AMT")
    if c & 8:
        out.append("Relay")
    if c & 16:
        out.append("MQTT")
    if node.get("pwr"):
        out.append(POWER_STATES.get(node["pwr"], ""))
    return ", ".join(x for x in out if x)


def passes_status(node, value, stars, mtype=None):
    """The status filter (web UI onSearchInputChanged, H:6689)."""
    conn, s = node.get("conn") or 0, node.get("sessions") or {}
    if value == 1:
        return bool(conn) or mtype == 3
    if value == 5:
        return not conn
    if value == 2:
        return any(s.get(k) for k in ("kvm", "terminal", "files", "registry", "tcp", "udp"))
    if value == 3:
        return node.get("_id") in stars
    if value == 4:
        return node.get("intelamt") is not None
    if value == 6:
        return bool(s.get("help"))
    if value == 7:
        return bool(node.get("tags"))
    if value == 8:
        return not node.get("tags")
    return True


def _term_matches(node, term, meshes, stars, os_name, features2=0):
    """One search term, web UI getDevicesThatMatchFilter (H:6538-6668)."""
    def has(v, sub):
        return isinstance(v, str) and sub in v.lower()
    mesh = meshes.get(node.get("meshid")) or {}
    for pre, key in (("ip:", "ip"), ("os:", "osdesc")):
        if term.startswith(pre):
            return has(node.get(key), term[len(pre):])
    for pres, fn in ((("group:", "g:"), lambda v: has(mesh.get("name"), v)),
                     (("user:", "u:"), lambda v: any(has(x, v) for x in (node.get("users") or []) + (node.get("upnusers") or [])))):
        for pre in pres:
            if term.startswith(pre):
                return fn(term[len(pre):])
    for pre in ("tag:", "t:"):
        if term.startswith(pre):
            v = term[len(pre):]
            tags = node.get("tags") or []
            return not tags if v == "" else any(has(t, v) for t in tags)
    for pre in ("atag:", "a:"):
        if term.startswith(pre):
            v, at = term[len(pre):], (node.get("agent") or {}).get("tag")
            return not at if v == "" else has(at, v)
    if term.startswith("amt:"):
        v, amt = term[4:], node.get("intelamt")
        return amt is not None and (v == "" or str(amt.get("state")) == v)
    if term.startswith("desc:"):
        v, d = term[5:], node.get("desc") or ""
        return bool(d) and (v == "" or v in d.lower())
    if term.startswith("wsc:"):
        w = node.get("wsc") or {}
        av, up, fw = (w.get(k) == "OK" for k in ("antiVirus", "autoUpdate", "firewall"))
        return bool(w) and {"ok": av and up and fw, "noav": not av, "noupdate": not up,
                            "nofirewall": not fw, "any": not (av and up and fw)}.get(term[4:], False)
    for pre in ("connectivity:", "c:"):
        if term.startswith(pre):
            v, c, mt = term[len(pre):], node.get("conn") or 0, mesh.get("mtype")
            return {"agent": bool(c & 1) and mt != 4, "switch": bool(c & 1) and mt == 4 and node.get("porttype") == "PDU",
                    "ipkvm": bool(c & 1) and mt == 4, "cira": bool(c & 2), "amt": bool(c & 4) and not c & 2,
                    "relay": bool(c & 8) or (mt == 3 and bool(mesh.get("relayid"))), "mqtt": bool(c & 16),
                    "local": mt == 3 and not mesh.get("relayid")}.get(v, False)
    if term == "*":
        return node.get("_id") in stars
    names = [node.get("name") or "", node.get("rname") or node.get("name") or ""] if features2 & 0x8000 else \
        [node_name(node, os_name)]
    if features2 & 0x10000000:
        names.append(mesh.get("name") or "")
    return any(term in n.lower() for n in names)


def search_matches(node, query, meshes, stars, os_name, features2=0):
    """Full search: terms joined with " or " / " and ", "!" negates a term."""
    q = (query or "").lower().strip()
    if not q:
        return True
    for alt in q.split(" or "):
        ok = True
        for term in alt.split(" and "):
            term = term.strip()
            neg = term.startswith("!")
            if neg:
                term = term[1:]
            m = _term_matches(node, term, meshes, stars, os_name, features2)
            if m == neg:
                ok = False
                break
        if ok:
            return True
    return False


def buckets(nodes, sort, meshes, os_name, lastconnects=None):
    """Group the visible nodes like the web UI's sort modes.
    Returns [(key, title, [nodes])]; key None = flat list without a header."""
    name = lambda n: _nat_key(node_name(n, os_name))
    if sort == 0:                                          # Group
        groups = {}
        for n in nodes:
            groups.setdefault(n.get("meshid"), []).append(n)
        out = []
        for mid, ns in groups.items():
            mesh = meshes.get(mid)
            title = mesh.get("name") if mesh else "Individual Devices"
            out.append((mid, title, sorted(ns, key=name)))
        return sorted(out, key=lambda b: (_nat_key(b[1]), b[0] or ""))
    if sort == 1:                                          # Power (descending)
        groups = {}
        for n in nodes:
            groups.setdefault(n.get("pwr") or 0, []).append(n)
        return [(f"pwr:{p}", POWER_HEADERS[p] if 0 < p < len(POWER_HEADERS) else "Unknown", sorted(ns, key=name))
                for p, ns in sorted(groups.items(), reverse=True)]
    if sort in (3, 4):                                     # Tags / Group-Tags
        groups = {}
        for n in sorted(nodes, key=name):
            mname = (meshes.get(n.get("meshid")) or {}).get("name") or "Individual Devices"
            tags = n.get("tags") or []
            if sort == 3:
                for t in tags:
                    groups.setdefault(t, []).append(n)
            elif tags:
                for t in tags:
                    groups.setdefault(f"{mname} - {t}", []).append(n)
            else:
                groups.setdefault(mname, []).append(n)
        return [(f"tag:{k}", k.replace("|", " → "), v) for k, v in sorted(groups.items(), key=lambda kv: _nat_key(kv[0]))]
    if sort == 5:                                          # Last Seen: oldest first, online, never seen
        lc = lastconnects or {}
        key = lambda n: (99999999999998 if (n.get("conn") or 0) > 0 else lc.get(n["_id"], 99999999999999), name(n))
        return [(None, None, sorted(nodes, key=key))]
    if sort == 6:                                          # Last Boot Up Time
        key = lambda n: (0, n["lastbootuptime"], name(n)) if isinstance(n.get("lastbootuptime"), (int, float)) \
            else (1, 0, name(n))
        return [(None, None, sorted(nodes, key=key))]
    return [(None, None, sorted(nodes, key=name))]         # Device


def mesh_actions(ctrl, mesh):
    """Which per-group actions the web UI shows (getMeshActions): (add_agent, invite)."""
    if not mesh or not rights.mesh_rights(ctrl, mesh) & 4 or mesh.get("mtype") != 2:
        return False, False
    sa = rights.site_rights(ctrl)
    if sa != FULL and sa & SITE_NONEWDEVICES:
        return False, False
    feats = (ctrl.serverinfo or {}).get("features") or 0
    return True, not feats & FEAT_LANONLY


# ---- small dialog helpers -------------------------------------------------------------------
def _dialog(parent, title, ok_label="OK", width=460):
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.set_default_size(width, -1)
    area = d.get_content_area()
    area.set_spacing(8)
    area.set_border_width(12)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = None
    if ok_label:
        ok = d.add_button(ok_label, Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        d.set_default_response(Gtk.ResponseType.OK)
    return d, area, ok


def _grid_rows(area, rows):
    g = Gtk.Grid(row_spacing=8, column_spacing=12)
    for i, (label, w) in enumerate(rows):
        if label is not None:
            g.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            g.attach(w, 1, i, 1, 1)
        else:
            g.attach(w, 0, i, 2, 1)
    area.pack_start(g, False, False, 0)
    return g


def _combo(options, active=0):
    c = Gtk.ComboBoxText(hexpand=True)
    for key, label in options:
        c.append(str(key), label)
    c.set_active(active)
    return c


def _text_view(text="", height=120, editable=True, mono=False):
    tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, editable=editable, monospace=mono)
    tv.get_buffer().set_text(text)
    scr = Gtk.ScrolledWindow(min_content_height=height, hexpand=True)
    scr.add(tv)
    fr = Gtk.Frame()
    fr.add(scr)
    return tv, fr


def _buf_text(tv):
    b = tv.get_buffer()
    return b.get_text(b.get_start_iter(), b.get_end_iter(), False)


def _copy(text):
    from gi.repository import Gdk
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)


def _run(d):
    """Run a dialog; tests replace this."""
    d.show_all()
    return d.run() == Gtk.ResponseType.OK


def _choose_folder(parent, title="Save to folder"):
    ch = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SELECT_FOLDER, "_Select", "_Cancel")
    dl = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
    if dl:
        ch.set_current_folder(dl)
    ok = ch.run() == Gtk.ResponseType.ACCEPT
    folder = ch.get_filename() if ok else None
    ch.destroy()
    return folder


def download_from_server(win, path, what):
    """Download <server><path> with the app's web session into a folder the user picks, using
    the server's file name (works when the server locks agent downloads to signed-in users)."""
    folder = _choose_folder(win, f"Save {what} to folder")
    if not folder:
        return
    app = win.app
    if getattr(app, "_dl_session", None) is None:
        app._dl_session = WebSession(win.ctrl)

    def done(err, dest):
        if err:
            ui.message(win, f"Could not download {what}", err, Gtk.MessageType.ERROR)
        else:
            app.notify("Download complete", os.path.basename(dest))
    app.notify("Downloading", what)
    app._dl_session.fetch_to_dir(path, folder, done)


# ---- server addresses for agent links ------------------------------------------------------
def server_base(ctrl):
    """https://S P D like the web UI (addAgentToMesh): the server's public name when it has a
    dot (else the address we connected to), its port unless 443, and the domain path."""
    si = ctrl.serverinfo or {}
    feats = si.get("features") or 0
    name = si.get("name") or ""
    host = ctrl.server.host.split(":")[0]
    if "." not in name or feats & FEAT_LANONLY:
        name = host
    port = si.get("port") or 443
    p = "" if port == 443 else f":{port}"
    d = "/" + (si.get("domainsuffix") + "/" if si.get("domainsuffix") else "")
    return f"https://{name}{p}", d


def linux_install_command(ctrl, meshid, uninstall=False):
    feats = (ctrl.serverinfo or {}).get("features") or 0
    base, d = server_base(ctrl)
    nc = " --no-check-certificate" if feats & FEAT_UNTRUSTED_CERT else ""
    m = meshid.split("/")[2]
    arg = "uninstall " if uninstall else ""
    run = f"sudo -E ./meshinstall.sh {arg}{base}{d.rstrip('/')} '{m}' || ./meshinstall.sh {arg}{base}{d.rstrip('/')} '{m}'"
    if feats & FEAT_NOPROXY:
        return f'wget "{base}{d}meshagents?script=1" --no-proxy{nc} -O ./meshinstall.sh && chmod 755 ./meshinstall.sh && {run}'
    return (f'(wget "{base}{d}meshagents?script=1"{nc} -O ./meshinstall.sh || wget "{base}{d}meshagents?script=1" '
            f'--no-proxy{nc} -O ./meshinstall.sh) && chmod 755 ./meshinstall.sh && {run}')


BIN_SYSTEMS = [(6, "Linux x86-64"), (5, "Linux x86-32"), (10005, "Apple OSX Universal"),
               (25, "Linux ARM-HF, Rasberry Pi"), (26, "Linux ARM64-HF"), (28, "Linux MIPS24KC (OpenWRT)"),
               (30, "FreeBSD x86-64"), (32, "Linux ARM 64 bit"), (36, "OpenWRT x86-64"), (37, "OpenBSD x86-64"),
               (40, "Linux MIPSEL24KC (OpenWRT)"), (41, "ARMADA/CORTEX-A53/MUSL (OpenWRT)"), (45, "RISC-V x86-64"),
               (16, "Apple macOS x86-64"), (29, "Apple macOS ARM-64")]


class AddAgentDialog:
    """Web UI "Add Mesh Agent" (addAgentToMesh). No server message: downloads and commands only."""
    OSES = [(0, "Windows"), (1, "Linux / BSD"), (5, "Linux / BSD / macOS Binary Installer"), (2, "Apple macOS"),
            (6, "Mobile device"), (7, "MeshCentral Assistant"), (3, "Windows (Uninstall)"),
            (4, "Linux / BSD (Uninstall)"), (8, "Apple macOS (Uninstall)")]
    INSTALL = [(0, "Background & interactive"), (2, "Background only"), (1, "Interactive only")]
    ASSIST = [(2, "Application, Connect on user request"), (3, "Application, Always connected"),
              (0, "System Tray, Connect on user request"), (1, "System Tray, Always connected"),
              (4, "System Tray, Monitor only")]

    def __init__(self, win, mesh):
        self.win, self.ctrl, self.mesh = win, win.ctrl, mesh
        self.meshid = mesh["_id"]
        self.m = self.meshid.split("/")[2]
        feats = (self.ctrl.serverinfo or {}).get("features") or 0
        oses = [o for o in self.OSES if not (o[0] == 6 and feats & FEAT_LANONLY)]
        d = Gtk.Dialog(title="Add Mesh Agent", transient_for=win, modal=True)
        d.set_default_size(600, -1)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        area = d.get_content_area()
        area.set_spacing(8)
        area.set_border_width(12)
        self.os = _combo(oses)
        self.inst = _combo(self.INSTALL)
        self.assist = _combo(self.ASSIST)
        self.sys = _combo(BIN_SYSTEMS)
        self.grid = _grid_rows(area, [("Operating System", self.os)])
        self.opts = Gtk.Grid(row_spacing=8, column_spacing=12)
        area.pack_start(self.opts, False, False, 0)
        area.pack_start(Gtk.Separator(), False, False, 2)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        area.pack_start(self.body, True, True, 0)
        for w in (self.os, self.inst, self.assist, self.sys):
            w.connect("changed", lambda *_: self.render())
        self.dialog = d
        self.render()
        d.show_all()
        d.connect("response", lambda *_: d.destroy())

    def _clear(self, box):
        for c in box.get_children():
            box.remove(c)

    def _opt(self, row, label, w):
        self.opts.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
        self.opts.attach(w, 1, row, 1, 1)

    def _text(self, t):
        l = Gtk.Label(label=t, xalign=0, wrap=True, max_width_chars=70)
        self.body.pack_start(l, False, False, 0)

    def _link(self, label, path, what):
        base, d = server_base(self.ctrl)
        url = f"{base}{d}{path}"
        row = Gtk.Box(spacing=6)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        dl = Gtk.Button(label="Download…", tooltip_text=url)
        dl.connect("clicked", lambda *_: download_from_server(self.win, d + path, what))
        cp = Gtk.Button(image=Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON),
                        tooltip_text="Copy the link")
        cp.connect("clicked", lambda *_: _copy(url))
        row.pack_start(dl, False, False, 0)
        row.pack_start(cp, False, False, 0)
        self.body.pack_start(row, False, False, 0)

    def _command(self, text):
        tv, fr = _text_view(text, 110, editable=False, mono=True)
        self.body.pack_start(fr, False, False, 0)
        b = Gtk.Button(label="Copy command", halign=Gtk.Align.START,
                       image=Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON),
                       always_show_image=True)
        b.connect("clicked", lambda *_: _copy(text))
        self.body.pack_start(b, False, False, 0)

    def render(self):
        for c in self.opts.get_children():
            self.opts.remove(c)
        self._clear(self.body)
        osv = int(self.os.get_active_id() or 0)
        f = self.inst.get_active_id() or "0"
        name = self.mesh.get("name", "")
        if osv in (0, 5):
            self._opt(1 if osv == 5 else 0, "Installation Type", self.inst)
        if osv == 5:
            self._opt(0, "System Type", self.sys)
        if osv == 7:
            self._opt(0, "Installation Type", self.assist)
        if osv in (0, 3):
            self._text(f"To {'remove the agent from' if osv == 3 else 'add a new computer to'} the device group "
                       f"“{name}”, download the mesh agent and run it on that computer"
                       + (" (click “Uninstall”)." if osv == 3 else ". The agent has the server and device group "
                          "information embedded in it."))
            for aid, label in ((3, "Windows x86-32 (.exe)"), (4, "Windows x86-64 (.exe)"), (43, "Windows ARM-64 (.exe)")):
                self._link(label, f"meshagents?id={aid}&meshid={self.m}&installflags={f}", label)
        elif osv in (1, 4):
            self._text(f"To {'remove the agent from' if osv == 4 else 'add a new computer to'} the device group "
                       f"“{name}”, run the following command on it. Root credentials will be needed.")
            self._command(linux_install_command(self.ctrl, self.meshid, uninstall=osv == 4))
            self._text("For BSD, run “pkg install wget sudo bash” beforehand.")
        elif osv == 5:
            sysid = self.sys.get_active_id()
            q = f"meshagents?id={self.m}&installflags={f}&meshinstall={sysid}"
            self._text(f"Download the agent installer for the device group “{name}”, then on the computer run "
                       "“chmod +x meshagent” and start it. On macOS first run "
                       "“xattr -r -d com.apple.quarantine meshagent”.")
            self._link("Agent installer", q, "the agent installer")
            base, d = server_base(self.ctrl)
            feats = (self.ctrl.serverinfo or {}).get("features") or 0
            nc = " --no-check-certificate" if feats & FEAT_UNTRUSTED_CERT else ""
            m = self.m.replace("$", "%24").replace("@", "%40")
            self._command(f'wget -O meshagent{nc} "{base}{d}meshagents?id={m}&installflags={f}&meshinstall={sysid}"')
        elif osv in (2, 8):
            if osv == 8:
                self._text("Download the agent, extract the ZIP file, right-click “Uninstall.command” and choose Open.")
                self._link("macOS (Universal)", f"meshosxagent?id=10005&meshid={self.m}", "the macOS agent")
            else:
                self._text(f"To add a new computer to the device group “{name}”, download and install the macOS agent.")
                for aid, label in ((16, "macOS x86-64"), (29, "macOS ARM-64"), (10005, "macOS (Universal)")):
                    self._link(label, f"meshosxagent?id={aid}&meshid={self.m}", label)
        elif osv == 6:
            si = self.ctrl.serverinfo or {}
            code = f"{si.get('magenturl', '')},{si.get('agentCertHash', '')},{self.m}"
            self._text("Install the MeshCentral agent app on the phone or tablet, then scan this code with it "
                       "(or copy it into the app):")
            self._qr_or_text(code)
            self._text("Google Play: https://play.google.com/store/apps/details?id=com.meshcentral.agent2")
            self._link("Android APK", f"meshagents?id=14&meshid={self.m}", "the Android agent")
        elif osv == 7:
            ac = self.assist.get_active_id() or "2"
            self._text(f"MeshCentral Assistant for Windows, for the device group “{name}”"
                       + (". It will monitor the background agent." if ac == "4" else "."))
            self._link("Assistant for Windows (.exe)", f"meshagents?id=10006&meshid={self.m}&ac={ac}", "MeshCentral Assistant")
        self.body.show_all()
        self.opts.show_all()

    def _qr_or_text(self, code):
        try:
            import qrcode
            from gi.repository import GdkPixbuf
            img = qrcode.make(code)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(buf.getvalue())
            loader.close()
            self.body.pack_start(Gtk.Image.new_from_pixbuf(loader.get_pixbuf()), False, False, 0)
        except Exception:
            pass
        self._command(code)


class InviteDialog:
    """Web UI "Invite" (inviteAgentToMesh): a link (createInviteLink, always answered) or, when the
    server can send email, an email invitation (inviteAgent)."""
    EXPIRE = [(1, "1 hour"), (8, "8 hours"), (24, "1 day"), (168, "1 week"), (5040, "1 month"), (0, "Unlimited")]
    AGENTS = [(0, "All"), (1, "Windows"), (2, "Linux"), (4, "MacOS"), (8, "MeshCentral Assistant"), (16, "Android")]
    INSTALL = [(0, "Background and interactive"), (2, "Background only"), (1, "Interactive only")]
    EMAIL_OS = [(4, "Send installation link"), (0, "Any supported"), (1, "Windows only"), (3, "Apple macOS only"),
                (2, "Linux only"), (5, "MeshCentral Assistant")]

    def __init__(self, win, mesh):
        self.win, self.ctrl, self.mesh = win, win.ctrl, mesh
        feats = (self.ctrl.serverinfo or {}).get("features") or 0
        self.email_ok = bool(feats & FEAT_EMAIL_INVITE)
        d, area, ok = _dialog(win, f"Invite to {mesh.get('name', '')}", "Send email" if self.email_ok else None, 560)
        self.ok = ok
        area.pack_start(Gtk.Label(label="Invite someone to install the mesh agent. The link or email lets the "
                                        "computer join this device group.", xalign=0, wrap=True), False, False, 0)
        self.kind = _combo([(0, "Link invitation"), (1, "Email invitation")]) if self.email_ok else None
        if self.kind:
            _grid_rows(area, [("Invitation Type", self.kind)])
        self.link_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.expire, self.agents, self.inst = _combo(self.EXPIRE, 2), _combo(self.AGENTS), _combo(self.INSTALL)
        self.inst_label = Gtk.Label(label="Installation Type", xalign=1)
        g = Gtk.Grid(row_spacing=8, column_spacing=12)
        for i, (lab, w) in enumerate((("Link Expiration", self.expire), ("Agents", self.agents))):
            g.attach(Gtk.Label(label=lab, xalign=1), 0, i, 1, 1)
            g.attach(w, 1, i, 1, 1)
        g.attach(self.inst_label, 0, 2, 1, 1)
        g.attach(self.inst, 1, 2, 1, 1)
        self.link_box.pack_start(g, False, False, 0)
        self.url = Gtk.Entry(editable=False, hexpand=True, placeholder_text="Creating the link…")
        row = Gtk.Box(spacing=6)
        row.pack_start(self.url, True, True, 0)
        cp = Gtk.Button(image=Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON),
                        tooltip_text="Copy the link")
        cp.connect("clicked", lambda *_: _copy(self.url.get_text()))
        row.pack_start(cp, False, False, 0)
        self.link_box.pack_start(row, False, False, 0)
        area.pack_start(self.link_box, False, False, 0)
        self.email_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        if self.email_ok:
            self.name = Gtk.Entry(max_length=64, hexpand=True)
            self.email = Gtk.Entry(max_length=1024, hexpand=True)
            self.eos, self.eexp, self.einst = _combo(self.EMAIL_OS, 1), _combo(self.EXPIRE, 2), _combo(self.INSTALL)
            self.msg_tv, msg_fr = _text_view("", 70)
            _grid_rows(self.email_box, [("Name (optional)", self.name), ("Email", self.email),
                                        ("Operating System", self.eos), ("Link Expiration", self.eexp),
                                        ("Installation Type", self.einst), ("Message (optional)", msg_fr)])
            area.pack_start(self.email_box, False, False, 0)
            self.email.connect("changed", lambda *_: self._sync())
            self.eos.connect("changed", lambda *_: self._sync())
            self.kind.connect("changed", lambda *_: self._sync())
        self.result = Gtk.Label(xalign=0, wrap=True)
        area.pack_start(self.result, False, False, 0)
        for w in (self.expire, self.agents, self.inst):
            w.connect("changed", lambda *_: self.request_link())
        self.ctrl.on("createInviteLink", self._on_link)
        d.connect("destroy", lambda *_: self.ctrl.off("createInviteLink", self._on_link))
        d.connect("response", self._on_response)
        self.dialog = d
        d.show_all()
        self._sync()
        self.request_link()

    def _sync(self):
        email = self.kind is not None and self.kind.get_active_id() == "1"
        self.link_box.set_visible(not email)
        self.email_box.set_visible(email)
        self.inst_label.set_visible(self.agents.get_active_id() in ("0", "1", "2", "4"))
        self.inst.set_visible(self.inst_label.get_visible())
        if self.email_ok:
            self.ok.set_visible(email)
            v = self.email.get_text().strip()
            self.ok.set_sensitive(v.count("@") == 1 and len(v) >= 4)

    def request_link(self):
        self._sync()
        self.url.set_text("")
        self.ctrl.send({"action": "createInviteLink", "meshid": self.mesh["_id"],
                        "expire": int(self.expire.get_active_id()), "flags": int(self.inst.get_active_id()),
                        "agents": int(self.agents.get_active_id())})

    def _on_link(self, msg):
        if msg.get("meshid") not in (self.mesh["_id"], self.mesh["_id"].split("/")[-1]):
            return
        if msg.get("cookie"):
            base, d = server_base(self.ctrl)             # the web UI rebuilds the URL the same way
            self.url.set_text(f"{base}{d}agentinvite?c={msg['cookie']}")
        elif msg.get("result"):
            self.result.set_text(str(msg["result"]))

    def _on_response(self, d, resp):
        if resp != Gtk.ResponseType.OK:
            d.destroy()
            return
        self.ok.set_sensitive(False)
        self.result.set_text("Sending…")

        def done(m):
            if m.get("result") == "ok":
                self.result.set_text("Invitation sent.")
            else:
                self.result.set_markup(f"<span foreground='#e01b24'>{GLib.markup_escape_text(str(m.get('result')))}</span>")
            self.ok.set_sensitive(True)
        self.ctrl.send({"action": "inviteAgent", "meshid": self.mesh["_id"], "email": self.email.get_text().strip(),
                        "name": self.name.get_text().strip(), "os": self.eos.get_active_id(),
                        "flags": self.einst.get_active_id(), "msg": _buf_text(self.msg_tv),
                        "expire": int(self.eexp.get_active_id())}, done)


def add_device_group(win):
    """Web UI "Add Device Group" (account_createMesh): {action:'createmesh', meshname, meshtype, desc}."""
    ctrl = win.ctrl
    feats = (ctrl.serverinfo or {}).get("features") or 0
    types = [(2, "Manage using a software agent"), (1, "Intel® AMT only, no agent")]
    if not feats & FEAT_WANONLY:
        types.append((3, "Local devices, no agent"))
    d, area, ok = _dialog(win, "New Device Group", "Create")
    name = Gtk.Entry(max_length=128, hexpand=True, activates_default=True)
    tv, fr = _text_view("", 70)
    typ = _combo(types)
    _grid_rows(area, [("Name", name), ("Type", typ), ("Description", fr)])
    ok.set_sensitive(False)
    name.connect("changed", lambda *_: ok.set_sensitive(bool(name.get_text().strip())))
    if _run(d):
        def done(m):
            if m.get("result") != "ok":
                ui.message(win, "Creating the device group failed", str(m.get("result")), Gtk.MessageType.ERROR)
            win.load_devices()
        ctrl.send({"action": "createmesh", "meshname": name.get_text().strip(), "meshtype": int(typ.get_active_id()),
                   "desc": _buf_text(tv)}, done)
    d.destroy()


MESHCMD = [(4, "Windows x86-64 (.exe)"), (3, "Windows x86-32 (.exe)"), (43, "Windows ARM-64 (.exe)"),
           (6, "Linux x86-64"), (5, "Linux x86-32"), (16, "macOS x86-64"), (29, "macOS ARM-64"),
           (25, "Linux ARM 32 bit (Raspberry Pi)"), (26, "Linux ARM 64 bit (Raspberry Pi)")]


def meshcmd_dialog(win, nodeid=None):
    """Web UI "MeshCmd": download the command line tool and its action file. With a nodeid (device
    page link) the action file routes traffic through this server to that device."""
    d = Gtk.Dialog(title="MeshCmd", transient_for=win, modal=True)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    area = d.get_content_area()
    area.set_spacing(8)
    area.set_border_width(12)
    text = ("Download \"meshcmd\" with an action file to route traffic thru this server to this device. Make "
            "sure to edit meshaction.txt and add your account password or make any changes needed." if nodeid else
            "MeshCmd is MeshCentral's command line tool, for example for Intel® AMT tasks and TCP port mapping.")
    area.pack_start(Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=60), False, False, 0)
    action = ("/meshagents?meshaction=route&nodeid=" + urllib.parse.quote(nodeid, safe="")) if nodeid \
        else "/meshagents?meshaction=generic"
    osc = _combo(MESHCMD)
    b1 = Gtk.Button(label="Download MeshCmd…")
    b1.connect("clicked", lambda *_: download_from_server(win, f"/meshagents?meshcmd={osc.get_active_id()}", "MeshCmd"))
    b2 = Gtk.Button(label="Download action file…")
    b2.connect("clicked", lambda *_: download_from_server(win, action, "the MeshCmd action file"))
    _grid_rows(area, [("Operating System", osc), (None, b1), (None, b2)])
    d.show_all()
    d.connect("response", lambda *_: d.destroy())
    return d


# ---- Group Action ---------------------------------------------------------------------------
class GroupRunDialog(Gtk.Dialog):
    """Run commands on several devices and show each device's output (the web UI's group action
    sends no reply:true, so it never shows output)."""

    def __init__(self, win, nodes, request):
        super().__init__(title=f"Run commands on {len(nodes)} device(s)", transient_for=win)
        self.set_default_size(820, 520)
        self.ctrl, self.nodes = win.ctrl, {n["_id"]: n for n in nodes}
        # one request per device: the server's replies ("Agent not connected", "Access denied"…)
        # carry only the responseid, not the nodeid
        base = "mcdgrun" + secrets.token_hex(6)
        self.rids = {f"{base}-{i}": nid for i, nid in enumerate(self.nodes)}
        self.pending = set(self.nodes)
        self.buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self.buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(8)
        self.bold = self.buf.create_tag("h", weight=Pango.Weight.BOLD)
        self.get_content_area().pack_start(ui.scrolled(tv), True, True, 0)
        self.status = Gtk.Label(xalign=0, margin=6)
        self.status.get_style_context().add_class("dim-label")
        self.get_content_area().pack_start(self.status, False, False, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())
        self.connect("destroy", lambda *_: self._stop())
        self.ctrl.on("runcommands", self._on_ack)
        self.ctrl.on("msg", self._on_output)
        self._timer = GLib.timeout_add_seconds(120, self._timeout)
        self._status()
        self.show_all()
        for rid, nid in self.rids.items():
            self.ctrl.send(dict(request, nodeids=[nid], reply=True, responseid=rid))

    def _status(self):
        done = len(self.nodes) - len(self.pending)
        self.status.set_text(f"{done} of {len(self.nodes)} device(s) answered")

    def _add(self, nodeid, text):
        name = (self.nodes.get(nodeid) or {}).get("name", nodeid)
        end = self.buf.get_end_iter()
        self.buf.insert_with_tags(end, f"── {name} ──\n", self.bold)
        self.buf.insert(self.buf.get_end_iter(), (text or "").rstrip() + "\n\n")
        self.pending.discard(nodeid)
        self._status()

    def _on_ack(self, msg):
        nid = self.rids.get(msg.get("responseid"))
        if nid in self.pending and msg.get("result") not in (None, "OK", "ok"):
            self._add(nid, f"({msg['result']})")

    def _on_output(self, msg):
        nid = self.rids.get(msg.get("responseid"))
        if msg.get("type") == "runcommands" and nid:
            self._add(msg.get("nodeid") or nid, msg.get("result"))

    def _timeout(self):
        self._timer = None
        for nid in list(self.pending):
            self._add(nid, "(no answer: the agent may be offline or the command is still running)")
        return False

    def _stop(self):
        self.ctrl.off("runcommands", self._on_ack)
        self.ctrl.off("msg", self._on_output)
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None


# (op id, label, right bit(s) needed per node, extra condition)
OPS = [("export", "Export device information", 0), ("move", "Move to device group", 1),
       ("uninstall", "Uninstall Agent", 0x8000), ("wake", "Wake-up devices", 64),
       ("sleep", "Sleep devices", 0x40000), ("reset", "Reset devices", 0x40000),
       ("off", "Power off devices", 0x40000), ("run", "Run commands", 0x20000),
       ("notify", "Device notification", 0x4000), ("tags", "Edit tags", 4),
       ("upload", "Upload files", 8), ("delete", "Delete devices", 0x8000),
       ("mqtt", "Send MQTT Message", 0)]


class GroupActions:
    """single=True: used by one device's General page, so the device list's checks are left alone."""

    def __init__(self, win, single=False):
        self.win = win
        self.single = single

    def _done(self):
        if not self.single:
            self.win.clear_checked()

    @property
    def ctrl(self):
        return self.win.ctrl

    def _rights(self, node):
        return rights.node_rights(self.ctrl, self.win.meshes, node)

    def _allowed(self, op, node):
        bit = dict((o, b) for o, _l, b in OPS)[op]
        r = self._rights(node)
        if op == "uninstall":
            return bool((node.get("conn") or 0) & 1) and bool(r & 0x8000)
        if op == "mqtt":
            return bool(((self.ctrl.serverinfo or {}).get("features") or 0) & FEAT_MQTT) and bool((node.get("conn") or 0) & 16)
        return r == FULL or not bit or bool(r & bit)

    def available(self, nodes):
        return [(o, l) for o, l, _b in OPS if any(self._allowed(o, n) for n in nodes)]

    def _split(self, op, nodes):
        ok = [n for n in nodes if self._allowed(op, n)]
        return ok, len(nodes) - len(ok)

    def _skipped(self, n):
        if n:
            self.win.app.notify("Group action", f"{n} device(s) skipped: no permission for this action.")

    def run(self, nodes):
        feats = (self.ctrl.serverinfo or {}).get("features") or 0
        me = self.ctrl.userinfo or {}
        if feats & 0x40000 and not (me.get("otpsecret") or me.get("otphkeys") or me.get("otpekey") or me.get("otpduo")):
            ui.message(self.win, "Two-factor authentication required",
                       "This server requires two-factor authentication before using group actions.")
            return
        ops = self.available(nodes)
        d, area, _ok = _dialog(self.win, "Group Action")
        area.pack_start(Gtk.Label(label=f"Select an operation to perform on the {len(nodes)} selected device(s). "
                                        "Actions are performed only with proper rights.", xalign=0, wrap=True,
                                  max_width_chars=60), False, False, 0)
        combo = _combo(sorted(ops, key=lambda o: o[1]))
        combo.set_active_id("export")
        _grid_rows(area, [("Operation", combo)])
        op = combo.get_active_id() if _run(d) else None
        d.destroy()
        if op:
            getattr(self, "op_" + op)(nodes)

    # ---- operations ----------------------------------------------------------------------
    def op_wake(self, nodes):
        ok, skip = self._split("wake", nodes)
        if ok:
            self.ctrl.send({"action": "wakedevices", "nodeids": [n["_id"] for n in ok]})
            self.win.app.notify("Wake-up", f"Wake-up sent to {len(ok)} device(s).")
        self._skipped(skip)
        self._done()

    def _power(self, nodes, op, actiontype, verb):
        ok, skip = self._split(op, nodes)
        if not ok:
            self._skipped(skip)
            return
        if op != "sleep" and not ui.confirm(self.win, f"{verb} {len(ok)} device(s)?", "", verb, destructive=True):
            return
        self.ctrl.send({"action": "poweraction", "nodeids": [n["_id"] for n in ok], "actiontype": actiontype})
        self.win.app.notify(verb, f"Sent to {len(ok)} device(s).")
        self._skipped(skip)
        self._done()

    def op_sleep(self, nodes):
        self._power(nodes, "sleep", 4, "Sleep")

    def op_reset(self, nodes):
        self._power(nodes, "reset", 3, "Reset")

    def op_off(self, nodes):
        self._power(nodes, "off", 2, "Power off")

    def _confirm_box(self, title, text, ok_label):
        d, area, ok = _dialog(self.win, title, ok_label)
        area.pack_start(Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=60), False, False, 0)
        chk = Gtk.CheckButton(label="Confirm")
        area.pack_start(chk, False, False, 0)
        ok.get_style_context().add_class("destructive-action")
        ok.set_sensitive(False)
        chk.connect("toggled", lambda c: ok.set_sensitive(c.get_active()))
        res = _run(d)
        d.destroy()
        return res

    def op_delete(self, nodes):
        ok, skip = self._split("delete", nodes)
        if not ok:
            self._skipped(skip)
            return
        on = sum(1 for n in ok if (n.get("conn") or 0) > 0)
        if not self._confirm_box("Delete devices", f"Confirm removal of {len(ok)} selected device(s)? "
                                 f"{on} online, {len(ok) - on} offline. The devices and their history are removed "
                                 "from the server.", "Delete"):
            return
        self.ctrl.send({"action": "removedevices", "nodeids": [n["_id"] for n in ok]})
        self._skipped(skip)
        self._done()

    def op_uninstall(self, nodes):
        ok, skip = self._split("uninstall", nodes)
        if not ok:
            self._skipped(skip)
            return
        if not self._confirm_box("Uninstall Agent", f"Uninstall the MeshCentral agent from {len(ok)} online "
                                 "device(s)? They can only be managed again after installing a new agent. The "
                                 "device records stay on the server.", "Uninstall"):
            return
        self.ctrl.send({"action": "uninstallagent", "nodeids": [n["_id"] for n in ok]})
        self._skipped(skip)
        self._done()

    def op_move(self, nodes):
        ok, skip = self._split("move", nodes)
        meshes = self.win.meshes
        cur = {n.get("meshid") for n in ok}
        mtypes = {(meshes.get(m) or {}).get("mtype") for m in cur}
        targets = [(m, v.get("name", m)) for m, v in meshes.items()
                   if rights.mesh_rights(self.ctrl, v) & 1 and rights.mesh_rights(self.ctrl, v) & 4
                   and v.get("mtype") in mtypes and not (len(ok) == 1 and m in cur)]
        if not ok or not targets:
            ui.message(self.win, "Move to device group", "No other device group of the same type where you may "
                       "add devices." if ok else "No permission to move these devices.")
            return
        d, area, _b = _dialog(self.win, "Move to device group", "Move")
        combo = _combo(sorted(targets, key=lambda t: _nat_key(t[1])))
        _grid_rows(area, [("New Device Group", combo)])
        if _run(d):
            self.ctrl.send({"action": "changeDeviceMesh", "nodeids": [n["_id"] for n in ok],
                            "meshid": combo.get_active_id()})
            self._skipped(skip)
            self._done()
        d.destroy()

    def op_notify(self, nodes):
        ok, skip = self._split("notify", nodes)
        if not ok:
            self._skipped(skip)
            return
        d, area, okb = _dialog(self.win, "Device notification", "Send")
        typ = _combo([(2, "Toast Notification"), (1, "Message Box"), (3, "Alert Box")])
        title = Gtk.Entry(max_length=256, hexpand=True, placeholder_text="MeshCentral")
        tv, fr = _text_view("", 90)
        tmo = _combo([(2, "2 minutes"), (10, "10 minutes"), (30, "30 minutes"), (60, "60 minutes"), (0, "Until dismissed")])
        g = _grid_rows(area, [("Type", typ), ("Title", title), ("Message", fr), ("Timeout", tmo)])
        tl = g.get_child_at(0, 3)
        typ.connect("changed", lambda *_: (tmo.set_visible(typ.get_active_id() == "1"), tl.set_visible(typ.get_active_id() == "1")))
        okb.set_sensitive(False)
        tv.get_buffer().connect("changed", lambda *_: okb.set_sensitive(bool(_buf_text(tv).strip())))
        d.show_all()
        tmo.set_visible(False)
        tl.set_visible(False)
        if d.run() == Gtk.ResponseType.OK:
            t = typ.get_active_id()
            ttl, msg = title.get_text().strip() or "MeshCentral", _buf_text(tv)
            if t == "2":
                self.ctrl.send({"action": "toast", "nodeids": [n["_id"] for n in ok], "title": ttl, "msg": msg})
            for n in ok if t != "2" else []:
                m = {"action": "msg", "type": "messagebox" if t == "1" else "alertbox", "nodeid": n["_id"],
                     "title": ttl, "msg": msg}
                if t == "1":
                    m["timeout"] = int(tmo.get_active_id()) * 60000
                self.ctrl.send(m)
            self._skipped(skip)
            self._done()
        d.destroy()

    def op_tags(self, nodes):
        ok, skip = self._split("tags", nodes)
        if not ok:
            self._skipped(skip)
            return
        d, area, _b = _dialog(self.win, "Edit tags", "OK")
        opc = _combo([(1, "Add tags"), (2, "Set tags"), (3, "Remove tags")])
        e = Gtk.Entry(max_length=4096, hexpand=True, placeholder_text="Tag1, Tag2, Tag3", activates_default=True)
        _grid_rows(area, [("Operation", opc), ("Tags", e)])
        existing = sorted({t for n in self.win.nodes.values() for t in (n.get("tags") or [])}, key=_nat_key)
        if existing:
            area.pack_start(Gtk.Label(label="Tags in use: " + ", ".join(existing), xalign=0, wrap=True,
                                      max_width_chars=60, selectable=True), False, False, 0)
        if _run(d):
            op = opc.get_active_id()
            want = [t.strip() for t in e.get_text().split(",") if 0 < len(t.strip()) < 64]
            want = list(dict.fromkeys(want))
            for n in ok:
                cur = list(n.get("tags") or [])
                if op == "2":
                    new = want
                elif op == "1":
                    new = cur + [t for t in want if t not in cur]
                else:
                    new = [t for t in cur if t not in want]
                if new != cur:
                    self.ctrl.send({"action": "changedevice", "nodeid": n["_id"], "tags": ",".join(new) if new else ""})
            self._skipped(skip)
            self._done()
        d.destroy()

    def op_run(self, nodes):
        ok, skip = self._split("run", nodes)
        if not ok:
            self._skipped(skip)
            return
        types = []
        if any(is_windows(n) for n in ok):
            types += [(1, "Windows Command Prompt"), (2, "Windows PowerShell")]
        if any(n.get("agent") and not is_windows(n) for n in ok):
            types.append((3, "Linux/BSD/macOS Command Shell"))
        if any((self._rights(n) & 24) == 24 for n in ok):
            types.append((4, "Agent Console"))
        if not types:
            return
        d, area, okb = _dialog(self.win, "Run commands", "Run", 560)
        area.pack_start(Gtk.Label(label=f"Run commands on {len(ok)} selected device(s).", xalign=0), False, False, 0)
        typ = _combo(types)
        run_as = _combo([(0, "Run as agent"), (1, "Run as user, agent if no user"), (2, "Must run as user")])
        tv, fr = _text_view("", 140, mono=True)
        g = _grid_rows(area, [("Type", typ), ("Run as", run_as), ("Commands", fr)])
        ra_label = g.get_child_at(0, 1)
        typ.connect("changed", lambda *_: (run_as.set_visible(typ.get_active_id() != "4"),
                                          ra_label.set_visible(typ.get_active_id() != "4")))
        okb.set_sensitive(False)
        tv.get_buffer().connect("changed", lambda *_: okb.set_sensitive(bool(_buf_text(tv).strip())))
        if _run(d):
            GroupRunDialog(self.win, ok, {"action": "runcommands", "type": int(typ.get_active_id()),
                                          "runAsUser": int(run_as.get_active_id()), "cmds": _buf_text(tv)})
            self._skipped(skip)
        d.destroy()

    def op_upload(self, nodes):
        ok, skip = self._split("upload", nodes)
        if not ok:
            self._skipped(skip)
            return
        win_agents = lambda n: (n.get("agent") or {}).get("id") in (1, 2, 3, 4, 34)   # server-side rule
        need_win, need_lin = any(win_agents(n) for n in ok), any(not win_agents(n) for n in ok)
        d, area, okb = _dialog(self.win, "Upload files", "Upload", 560)
        area.pack_start(Gtk.Label(label=f"Upload files to {len(ok)} selected device(s). The agents download the "
                                        "files from the server.", xalign=0, wrap=True), False, False, 0)
        files = []
        flabel = Gtk.Label(label="No files chosen", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        pick = Gtk.Button(label="Choose files…")
        wp = Gtk.Entry(hexpand=True, text="C:\\Users\\Public\\Downloads" if need_win else "")
        lp = Gtk.Entry(hexpand=True, text="/tmp" if need_lin else "")
        mk = Gtk.CheckButton(label="Create the folder if it does not exist")
        ow = Gtk.CheckButton(label="Overwrite existing files")
        rows = [("Files", pick), (None, flabel)]
        if need_win:
            rows.append(("Windows folder", wp))
        if need_lin:
            rows.append(("Linux / macOS folder", lp))
        _grid_rows(area, rows + [(None, mk), (None, ow)])

        def valid(*_):
            okb.set_sensitive(bool(files) and (not need_win or bool(wp.get_text().strip()))
                              and (not need_lin or bool(lp.get_text().strip())))

        def choose(*_):
            ch = Gtk.FileChooserNative.new("Choose files", d, Gtk.FileChooserAction.OPEN, "_Open", "_Cancel")
            ch.set_select_multiple(True)
            if ch.run() == Gtk.ResponseType.ACCEPT:
                files[:] = ch.get_filenames()
                flabel.set_text(", ".join(os.path.basename(f) for f in files))
            ch.destroy()
            valid()
        pick.connect("clicked", choose)
        wp.connect("changed", valid)
        lp.connect("changed", valid)
        valid()
        if _run(d):
            fields = {"nodeIds": ",".join(n["_id"] for n in ok)}
            if need_win:
                fields["winpath"] = wp.get_text().strip()
            if need_lin:
                fields["linuxpath"] = lp.get_text().strip()
            if mk.get_active():
                fields["createFolder"] = "on"
            if ow.get_active():
                fields["overwriteFiles"] = "on"
            app = self.win.app
            if getattr(app, "_dl_session", None) is None:
                app._dl_session = WebSession(self.ctrl)

            def done(err):
                if err:
                    ui.message(self.win, "Upload failed", err, Gtk.MessageType.ERROR)
                else:
                    app.notify("Upload files", f"{len(files)} file(s) sent to the server; the agents download them now.")
            app._dl_session.post_files("/uploadfilebatch.ashx", fields, "files", list(files), None, done)
            self._skipped(skip)
            self._done()
        d.destroy()

    def op_mqtt(self, nodes):
        ok, skip = self._split("mqtt", nodes)
        d, area, okb = _dialog(self.win, "Send MQTT Message", "Send")
        topic = Gtk.Entry(max_length=64, hexpand=True)
        tv, fr = _text_view("", 90)
        _grid_rows(area, [("Topic", topic), ("Message", fr)])
        if _run(d) and topic.get_text().strip() and _buf_text(tv).strip():
            self.ctrl.send({"action": "sendmqttmsg", "nodeids": [n["_id"] for n in ok],
                            "topic": topic.get_text().strip(), "msg": _buf_text(tv)})
            self._skipped(skip)
        d.destroy()

    def op_export(self, nodes):
        d, area, _b = _dialog(self.win, "Export device information", "Export")
        fmt = _combo([("csv", "CSV (devicelist.csv)"), ("json", "JSON (devicelist.json)")])
        det = Gtk.CheckButton(label="Include device details (hardware, network, last connection)")
        _grid_rows(area, [("Format", fmt), (None, det)])
        go = _run(d)
        f, details = fmt.get_active_id(), det.get_active()
        d.destroy()
        if not go:
            return
        if details:
            def got(msg):
                if msg.get("type") != f:
                    return
                self.ctrl.off("getDeviceDetails", got)
                self._save(f"devicelist.{f}", msg.get("data") or "")
            self.ctrl.on("getDeviceDetails", got)
            # no time zone name: the server then writes the last connection time as epoch ms
            self.ctrl.send({"action": "getDeviceDetails", "nodeids": [n["_id"] for n in nodes], "tz": None,
                            "tf": time.timezone // 60, "l": "en", "type": f})
            return
        if f == "json":
            self._save("devicelist.json", json.dumps(nodes, indent=2))
        else:
            self._save("devicelist.csv", export_csv(nodes, self.win.meshes))

    def _save(self, name, text):
        ch = Gtk.FileChooserNative.new("Export devices", self.win, Gtk.FileChooserAction.SAVE, "_Save", "_Cancel")
        ch.set_current_name(name)
        ch.set_do_overwrite_confirmation(True)
        ok = ch.run() == Gtk.ResponseType.ACCEPT
        dest = ch.get_filename() if ok else None
        ch.destroy()
        if dest:
            with open(dest, "w", encoding="utf-8-sig" if name.endswith(".csv") else "utf-8", newline="") as fh:
                fh.write(text)
            self.win.app.notify("Export", os.path.basename(dest))


def export_csv(nodes, meshes):
    """devicelist.csv like the web UI (quoted values, commas removed, CRLF)."""
    clean = lambda v: "" if v is None else str(v).replace(",", "")
    out = io.StringIO()
    out.write("id,name,rname,host,icon,ip,osdesc,state,groupname,conn,pwr,av,update,firewall,avdetails,tags,lastbootuptime\r\n")
    for n in nodes:
        cells = [n.get("_id"), n.get("name"), n.get("rname"), n.get("host"), n.get("icon"), n.get("ip"),
                 n.get("osdesc"), n.get("state"), (meshes.get(n.get("meshid")) or {}).get("name"),
                 n.get("conn") or "", n.get("pwr") or ""]
        row = ",".join(f'"{clean(c)}"' for c in cells)
        w = n.get("wsc") or n.get("lsc")
        if w:
            row += "," + ",".join(f'"{clean(w.get(k))}"' if k in w else "" for k in ("antiVirus", "autoUpdate", "firewall"))
        else:
            row += ",,,"
        av = n.get("av")
        avd = "|".join(f"{clean(a.get('product'))}/{'enabled' if a.get('enabled') else 'disabled'}/"
                       f"{'updated' if a.get('updated') else 'notupdated'}" for a in av) if isinstance(av, list) else ""
        row += f',"{avd}","{"|".join(clean(t) for t in (n.get("tags") or []))}"'
        if isinstance(n.get("lastbootuptime"), (int, float)):
            row += f',"{n["lastbootuptime"]}"'
        out.write(row + "\r\n")
    return out.getvalue()
