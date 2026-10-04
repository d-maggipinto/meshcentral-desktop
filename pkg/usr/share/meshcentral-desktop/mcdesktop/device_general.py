# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Device "General" page like the web UI's (p10): the device attributes with in-place editing
(hostname, description, user consent, notifications, tags), security / antivirus / active users,
and the Actions, Notes, Log Event, Run, Message, Chat and Share buttons.

Ground truth (MeshCentral 1.2.5 default.handlebars / meshuser.js):
- changedevice {nodeid, host|desc|consent|tags} needs Manage computers (4); consent 0 clears it.
  The change comes back as event changenode, the device list reloads and on_node_update() refreshes.
- changeusernotify {nodeid, notify} (own account; no reply on success, the userinfo is updated
  locally); bits 2/4/8 web page, 16/32/64 email, 128/256/512 messaging.
- setDeviceEvent {nodeid, msg: encodeURIComponent(text)}: adds a 'manual' event, no reply.
- msg messagebox {title, msg, timeout ms}; pushmessage for push-capable mobile devices (pmt 1).
- Chat: {server}/messenger?id=meshmessenger/<enc nodeid>/<enc userid>&title=..&auth=<authcookie>
  plus {action:'meshmessenger', nodeid} (asks the agent to open its chat window).
- createDeviceShareLink {nodeid, guestname, p, expire|start+end|start+expire+recurring, consent,
  viewOnly}: with a responseid the reply is the command echoed with url and result 'OK', or
  {result:<error>}.
- powertimeline {nodeid} → {timeline:[state, start s, state, delta s, state, …]} (verified on the rig:
  [0, 1790856345, 1]); the server's "no history" fallback puts Date.now() in ms in the time slot.
- getcookie {nodeid, tcpport, tag novnc|mstsc|ssh, name} → the request echoed with `cookie`
  (+ localRelay for local devices), responseid echoed. Pages: novnc/vnc.html?ws=wss://…meshrelay.ashx
  ?auth=<cookie>, mstsc.html?ws=<cookie>, ssh.html?ws=<cookie>.
- adddeviceuser {nodeid, nodename, usernames|userids, rights[, remove]} → {result:'ok'} even for an
  unknown user name (verified), so the page checks node.links afterwards.
- changeDeviceMesh {nodeids, meshid}; removedevices {nodeids}.
"""
import time
import urllib.parse
from datetime import datetime

from gi.repository import Gtk, GLib, Pango, PangoCairo

from . import ui, rights, servericons
from . import device_list as dl
from .general_actions import NotesDialog
from .info_panel import agent_description, _group_name
from .user_panel import RightsDialog, list_section, device_rights_text

GREEN, RED = "#2ec27e", "#e01b24"

# consent bits (web UI p20editmeshconsent): (bit, section, label)
CONSENT_FLAGS = [(0x0001, "Desktop", "Notify user"), (0x0008, "Desktop", "Prompt for user consent"),
                 (0x0040, "Desktop", "Show connection toolbar"),
                 (0x0002, "Terminal", "Notify user"), (0x0010, "Terminal", "Prompt for user consent"),
                 (0x0004, "Files", "Notify user"), (0x0020, "Files", "Prompt for user consent"),
                 (0x0080, "Registry", "Notify user"), (0x0100, "Registry", "Prompt for user consent")]

SHARE_EXPIRE = [(1, "1 minute"), (5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"), (30, "30 minutes"),
                (45, "45 minutes"), (60, "60 minutes"), (120, "2 hours"), (240, "4 hours"), (480, "8 hours"),
                (720, "12 hours"), (960, "16 hours"), (1440, "24 hours"), (2880, "2 days"), (5760, "4 days"),
                (0, "Unlimited")]
SHARE_TYPES = {1: "Terminal", 2: "Desktop", 3: "Desktop, View only", 4: "Files", 5: "Desktop + Files",
               6: "Terminal + Files", 7: "Desktop + Terminal + Files"}
SHARE_LINK_NAMES = ["", "Remote Terminal Link", "Remote Desktop Link", "Remote Desktop + Terminal Link",
                    "Remote Files Link", "Remote Terminal + Files Link", "Remote Desktop + Files Link",
                    "Remote Desktop + Terminal + Files Link"]
_DT_FMT = "%Y-%m-%d %H:%M"


def _esc(s):
    return GLib.markup_escape_text(str(s))


def _ok(text):
    return f"<span foreground='{GREEN}'>{text}</span>"


def _bad(text):
    return f"<span foreground='{RED}'>{text}</span>"


def _none():
    return "<i>None</i>"


def consent_text(consent):
    """Web UI wording for a consent bitmask ('Desktop Prompt+Toolbar, Terminal Notify'...)."""
    c, out = consent, []
    if c & 0x40 and c & 0x08:
        out.append("Desktop Prompt+Toolbar")
    elif c & 0x40:
        out.append("Desktop Toolbar")
    elif c & 0x08:
        out.append("Desktop Prompt")
    elif c & 0x01:
        out.append("Desktop Notify")
    if c & 0x10:
        out.append("Terminal Prompt")
    elif c & 0x02:
        out.append("Terminal Notify")
    if c & 0x20:
        out.append("Files Prompt")
    elif c & 0x04:
        out.append("Files Notify")
    if c & 0x100:
        out.append("Registry Prompt")
    elif c & 0x80:
        out.append("Registry Notify")
    if c == 0x87:
        out = ["Always Notify"]
    if (c & 0x138) == 0x138:
        out = ["Always Prompt"]
    return ", ".join(out)


def security_markup(state, keys):
    """node.wsc / node.lsc → 'AV - OK, Firewall - BAD' (web UI colours)."""
    parts = []
    for key, label in keys:
        v = (state or {}).get(key)
        if v is not None:
            parts.append(f"{label} - " + (_ok("OK") if v == "OK" else _bad("BAD")))
    return ", ".join(parts)


def _shield(states):
    """Badge for a security row: all OK, all bad, or mixed ("OK" / "BAD" / None = not reported)."""
    s = [x for x in states if x is not None]
    if not s:
        return None
    bad = sum(1 for x in s if x != "OK")
    return "shield-ok" if not bad else ("shield-error" if bad == len(s) else "shield-warning")


def antivirus_markup(av):
    rows = []
    for a in av or []:
        if not isinstance(a, dict) or not a.get("product"):
            continue
        x = _esc(a["product"])
        if a.get("enabled") is not True:
            x += " - " + _bad("Disabled")
        if a.get("updated") is not True:
            x += " - " + _bad("Out of date")
        if a.get("enabled") is True and a.get("updated") is True:
            x += " - " + _ok("OK")
        rows.append(x)
    return "\n".join(rows)


def active_users(node):
    users = node.get("users") or []
    locked = node.get("lusers") or []
    return ", ".join(f"{u} (Locked)" if u in locked else str(u) for u in users)


def notify_text(ctrl, node):
    me, f2 = ctrl.userinfo or {}, (ctrl.serverinfo or {}).get("features2") or 0
    n = ((me.get("notify") or {}).get(node["_id"])) or 0
    out = []
    if n & 2:
        out.append("Connect")
    if n & 4:
        out.append("Disconnect")
    if node.get("intelamt") is not None and n & 8:
        out.append("Intel® AMT")
    if f2 & 0x4000 and me.get("emailVerified"):
        k = sum(1 for b in (16, 32, 64) if n & b)
        if k:
            out.append(f"Email ({k})")
    if me.get("msghandle") is not None and f2 & 0x02000000:
        k = sum(1 for b in (128, 256, 512) if n & b)
        if k:
            out.append(f"Messaging ({k})")
    return ", ".join(out)


class GeneralPanel(Gtk.Box):
    """Device attributes + the web UI's General buttons. No network traffic until a button is used."""

    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._share_rid = None
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=16)
        self.grid = Gtk.Grid(row_spacing=8, column_spacing=16)
        body.pack_start(self.grid, False, False, 0)
        self.buttons = Gtk.Box(spacing=0)
        self.buttons.get_style_context().add_class("linked")
        body.pack_start(self.buttons, False, False, 0)
        self.power = PowerTimeline()
        body.pack_start(self.power, False, False, 0)
        self.links = Gtk.Box(spacing=4)
        body.pack_start(self.links, False, False, 0)
        self.users = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        body.pack_start(self.users, False, False, 0)
        self.usergroups = None
        self._power_at = 0
        self._handlers = [("powertimeline", self._on_power), ("usergroups", self._on_usergroups)]
        for action, cb in self._handlers:
            self.app.ctrl.on(action, cb)
        self.add(ui.scrolled(body))
        self.refresh(node)

    # ---- helpers ---------------------------------------------------------------------------
    @property
    def ctrl(self):
        return self.app.ctrl

    @property
    def win(self):
        return getattr(self.app, "main_win", None)

    def _meshes(self):
        return getattr(self.app, "meshes", None) or getattr(self.win, "meshes", None) or {}

    def _mesh(self):
        return self._meshes().get(self.node.get("meshid")) or {}

    def _rights(self):
        return rights.node_rights(self.ctrl, self._meshes(), self.node)

    def _parent(self):
        top = self.get_toplevel()
        return top if isinstance(top, Gtk.Window) else None

    def _row(self, row, key, markup, edit=None, tip=None):
        klabel = Gtk.Label(label=key, xalign=0, yalign=0)
        klabel.get_style_context().add_class("dim-label")
        v = Gtk.Label(xalign=0, yalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        v.set_markup(markup)
        if tip:
            v.set_tooltip_text(tip)
        box = Gtk.Box(spacing=4, hexpand=True)
        badge = (getattr(self, "_badges", None) or {}).get(key)
        if badge:
            fallback = {"shield-ok": "security-high-symbolic", "shield-warning": "security-medium-symbolic",
                        "shield-error": "security-low-symbolic"}[badge]
            img = Gtk.Image.new_from_icon_name(servericons.icon("status", badge, fallback), Gtk.IconSize.MENU)
            img.set_valign(Gtk.Align.START)
            box.pack_start(img, False, False, 0)
        box.pack_start(v, False, False, 0)
        if edit:
            b = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.MENU)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_valign(Gtk.Align.START)
            b.set_tooltip_text(f"Edit {key.lower()}")
            b.connect("clicked", lambda *_: edit())
            box.pack_start(b, False, False, 0)
        self.grid.attach(klabel, 0, row, 1, 1)
        self.grid.attach(box, 1, row, 1, 1)

    # ---- content ---------------------------------------------------------------------------
    def refresh(self, node):
        self.node = node
        for child in self.grid.get_children():
            self.grid.remove(child)
        for child in self.buttons.get_children():
            self.buttons.remove(child)
        r = self._rights()
        full = r == rights.FULL
        manage = full or bool(r & 4)
        mesh = self._mesh()
        mtype = mesh.get("mtype")
        agent = node.get("agent") or {}
        feats = (self.ctrl.serverinfo or {}).get("features") or 0
        local = mtype == 3
        rows = [("Group", _esc(_group_name(self.app, node)), None)]
        if node.get("rname") and node.get("rname") != node.get("name"):
            rows.append(("OS Name", _esc(node["rname"]), None))
        if (not feats & 1 and mtype != 4) or local:          # hostname unused in WAN-only mode
            rows.append(("Hostname", _esc(node.get("host")) if node.get("host") else _none(),
                         (lambda: self.edit_value("host", "Hostname", 64)) if manage else None))
        rows.append(("Description", _esc(node.get("desc")) if node.get("desc") else _none(),
                     (lambda: self.edit_value("desc", "Description", 1024)) if manage else None))
        desc = agent_description(node)
        if desc:
            rows.append(("Mesh Agent", _esc(desc), None))
        if node.get("osdesc"):
            rows.append(("Operating System", _esc(node["osdesc"]), None))
        self._badges = {}
        wsc = security_markup(node.get("wsc"), (("antiVirus", "AV"), ("autoUpdate", "Update"), ("firewall", "Firewall")))
        if node.get("wsc"):
            rows.append(("Windows Security", wsc, None))
            self._badges["Windows Security"] = _shield(node["wsc"].get(k) for k in ("antiVirus", "autoUpdate", "firewall"))
        dfd = node.get("defender") or {}
        if dfd:
            y = []
            for key, label in (("RealTimeProtection", "RealTimeProtection"), ("TamperProtected", "TamperProtection")):
                if dfd.get(key) is not None:
                    y.append(f"{label} - " + (_ok("On") if dfd[key] is True else _bad("Off")))
            if dfd.get("AntivirusSignatureVersion") is not None:
                y.append("SignatureVersion - " + _ok(_esc(dfd["AntivirusSignatureVersion"])))
            if y:
                rows.append(("Windows Defender", ", ".join(y), None))
                self._badges["Windows Defender"] = _shield(
                    "OK" if dfd.get(k) is True else ("BAD" if dfd.get(k) is False else None)
                    for k in ("RealTimeProtection", "TamperProtected"))
        if node.get("pr"):
            pr = node["pr"]
            pr = pr.values() if isinstance(pr, dict) else pr
            rows.append(("Pending Reboot", _esc(", ".join(str(x) for x in pr)), None))
        lsc = security_markup(node.get("lsc"), (("antiVirus", "AV"), ("firewall", "Firewall")))
        if lsc:
            rows.append(("Linux Security", lsc, None))
            self._badges["Linux Security"] = _shield(node["lsc"].get(k) for k in ("antiVirus", "firewall"))
        av = antivirus_markup(node.get("av"))
        if av:
            rows.append(("Antivirus", av, None))
            self._badges["Antivirus"] = _shield("OK" if a.get("enabled") is True and a.get("updated") is True else "BAD"
                                                for a in node.get("av") or [] if isinstance(a, dict) and a.get("product"))
        users = node.get("users") or []
        if users:
            rows.append(("Active Users" if len(users) > 1 else "Active User", _esc(active_users(node)), None))
        if node.get("idletime") and node.get("idletime") != -1:
            rows.append(("Idle Time", _esc(_duration(node["idletime"])), None))
        if node.get("agent") is not None and agent.get("id") != 14 and not local:
            consent = (node.get("consent") or 0) | ((self.ctrl.serverinfo or {}).get("consent") or 0)
            rows.append(("User Consent", _esc(consent_text(consent)) or _none(),
                         self.edit_consent if (full or rights.mesh_rights(self.ctrl, mesh) & 1) else None))
        rows.append(("Notifications", _esc(notify_text(self.ctrl, node)) or _none(), self.edit_notify))
        conn = node.get("conn") or 0
        if conn > 1:
            c = []
            if conn & 1:
                c.append("Mesh Agent")
            if conn & 2:
                c.append("Intel® AMT CIRA")
            elif conn & 4:
                c.append("Intel® AMT")
            if conn & 8:
                c.append("Mesh Relay")
            if conn & 16:
                c.append("MQTT")
            rows.append(("Connectivity", _esc(", ".join(c)), None))
        tags = node.get("tags") or []
        rows.append(("Tags", _esc(", ".join(tags)) if tags else _none(), self.edit_tags if manage else None))
        # app extras, below the web UI's attributes
        rows.append(("Status", "Local device" if local else (_ok("Online") if ui.is_online(node) else "Offline"), None))
        if node.get("ip"):
            rows.append(("IP address", _esc(node["ip"]), None))
        if agent.get("core"):
            rows.append(("Agent core", _esc(agent["core"]), None))
        rows.append(("Node ID", _esc(node.get("_id", "")), None))
        for i, (key, markup, edit) in enumerate(rows):
            self._row(i, key, markup, edit)
        self.grid.show_all()
        self._build_buttons(r, mtype, conn)
        self.power.set_visible(not local)
        self._build_links(r, mtype, conn)
        self._build_users(r)

    def _build_buttons(self, r, mtype, conn):
        full = r == rights.FULL
        node, agent = self.node, self.node.get("agent") or {}
        si = self.ctrl.serverinfo or {}
        f2 = si.get("features2") or 0
        push = node.get("pmt") == 1 and bool(f2 & 2)
        msg_ok = (bool(r & 8) and bool(conn & 1) and bool(r & 16384)) or push
        btns = []
        if r & (4 + 8 + 64 + 262144) and mtype is not None and mtype < 3 and agent.get("id") != 34:
            btns.append(("Actions", "Perform power actions on the device", self.actions))
        btns.append(("Notes", "View notes about this device", self.notes))
        btns.append(("Log Event", "Write an event for this device", self.log_event))
        if mtype == 2 and conn & 1 and r & 131072:
            btns.append(("Run", "Run commands on this device", self.run_cmds))
        if mtype != 4 and msg_ok:
            btns.append(("Message", "Display a text message on the remote device", self.message))
            btns.append(("Chat", "Open chat window to this computer", self.chat))
        if (mtype != 4 and si.get("guestdevicesharing") is not False and (agent.get("caps") or 0) & 3
                and conn & 1 and (r & 0x80008) == 0x80008 and (full or not r & 0x1000)):
            btns.append(("Share", "Create a link to share this device with a guest", self.share))
        for label, tip, cb in btns:
            b = Gtk.Button(label=label, tooltip_text=tip)
            b.connect("clicked", lambda _b, f=cb: f())
            self.buttons.pack_start(b, False, False, 0)
        self.buttons.show_all()

    # ---- panel contract --------------------------------------------------------------------
    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.refresh(self.node)
        self._request_power()
        self.ctrl.send({"action": "usergroups"})

    def on_node_update(self, node):
        was = self.node.get("conn")
        self.refresh(node)
        # like the web UI: refresh the timeline every 5 minutes, and when the connection changes
        if self._started and (time.time() - self._power_at > 300 or was != node.get("conn")):
            self._request_power()

    def teardown(self):
        for action, cb in self._handlers:
            self.ctrl.off(action, cb)

    # ---- power timeline, user groups ---------------------------------------------------------
    def _request_power(self):
        if self._mesh().get("mtype") == 3:
            return
        self._power_at = time.time()
        self.ctrl.send({"action": "powertimeline", "nodeid": self.node["_id"]})

    def _on_power(self, msg):
        if msg.get("nodeid") == self.node["_id"]:
            self.power.set_timeline(msg.get("timeline") or [])

    def _on_usergroups(self, msg):
        if isinstance(msg.get("ugroups"), dict):
            self.usergroups = msg["ugroups"]
            self._build_users(self._rights())

    # ---- links (Interfaces, MeshCmd, Web-VNC, Web-RDP, Web-SSH), Change Group, Delete Device ----
    def _build_links(self, r, mtype, conn):
        for c in self.links.get_children():
            self.links.remove(c)
        node, agent = self.node, self.node.get("agent") or {}
        full = r == rights.FULL
        si = self.ctrl.serverinfo or {}
        feats, f2 = si.get("features") or 0, si.get("features2") or 0
        sa = rights.site_rights(self.ctrl)
        left, right = [], []
        if node.get("agent") and mtype != 3 and (full or r & 1048576):
            left.append(("Interfaces", "Show device network interface information",
                         lambda: self.win.goto_device_tab("Network") if self.win else None))
        if not node.get("agent") or agent.get("id") not in (14, 34):
            if (sa == rights.FULL or not sa & 128) and (full or not r & 512) and r & 8 and node.get("agent"):
                left.append(("MeshCmd", "Traffic router used to connect to a device thru this server", self.meshcmd))
            reach = (conn & 1 or mtype == 3) and node.get("agent") and r & 8
            if reach and not feats & 0x20000000:
                left.append(("Web-VNC", "Launch web-based VNC session to this device",
                             lambda: self.web_session("novnc", node.get("rfbport") or 5900)))
            if reach and not feats & 0x40000000:
                left.append(("Web-RDP", "Launch web-based RDP session to this device",
                             lambda: self.web_session("mstsc", node.get("rdpport") or 3389)))
            if reach and f2 & 0x200:
                left.append(("Web-SSH", "Launch web-based SSH session to this device",
                             lambda: self.web_session("ssh", node.get("sshport") or 22)))
        if r & 1 and mtype != 4:
            right.append(("Change Group", "Move this device to a different device group", self.change_group))
        if r & 0x8000:
            right.append(("Delete Device", "Remove this device", self.delete_device))

        def link(label, tip, cb):
            b = Gtk.LinkButton(label=label, uri="", tooltip_text=tip)
            b.connect("activate-link", lambda *_: (cb(), True)[1])
            return b
        for label, tip, cb in left:
            self.links.pack_start(link(label, tip, cb), False, False, 0)
        for label, tip, cb in reversed(right):
            if label == "Delete Device":                 # destructive: a red button, not a link
                b = Gtk.Button(label=label, tooltip_text=tip, valign=Gtk.Align.CENTER)
                b.get_style_context().add_class("destructive-action")
                b.connect("clicked", lambda *_, f=cb: f())
            else:
                b = link(label, tip, cb)
            self.links.pack_end(b, False, False, 0)
        self.links.show_all()

    def meshcmd(self):
        dl.meshcmd_dialog(self._parent(), nodeid=self.node["_id"])

    def web_session(self, tag, port):
        """Web-VNC / Web-RDP / Web-SSH: the server's own web clients, in an embedded web view window."""
        node, mesh = self.node, self._mesh()
        msg = {"action": "getcookie", "nodeid": node["_id"], "tcpport": port, "tag": tag, "name": mesh.get("name")}
        if mesh.get("mtype") == 3 and mesh.get("relayid"):          # local device through a relay agent
            msg["nodeid"], msg["tcpaddr"] = mesh["relayid"], node.get("host")

        def got(reply):
            cookie = reply.get("cookie")
            if not cookie:
                ui.message(self._parent(), "Web session", "The server did not return a session cookie.",
                           Gtk.MessageType.ERROR)
                return
            base = self.ctrl.server.url.rstrip("/")
            si = self.ctrl.serverinfo or {}
            dom = "/" + si["domainsuffix"] + "/" if si.get("domainsuffix") else "/"
            q = urllib.parse.quote
            name = "&name=" + q(node.get("name", ""), safe="")
            local = bool(reply.get("localRelay"))
            if tag == "novnc":
                host = urllib.parse.urlsplit(base).netloc
                ws = "wss://" + host + dom + ("local" if local else "mesh") + "relay.ashx?auth=" + cookie
                url = base + dom + "novnc/vnc.html?ws=" + q(ws, safe="") + "&show_dot=1" + name
                ChatWindow(self.app, f"Web-VNC - {node.get('name', '')}", url, (1024, 768))
                return
            # mstsc.html / ssh.html answer 401 without a signed-in web session (verified on the rig):
            # sign in over HTTP and give the window those session cookies.
            page = "mstsc.html" if tag == "mstsc" else "ssh.html"
            url = base + dom + page + "?ws=" + cookie + name + ("&local=1" if local else "")
            title = "Web-RDP" if tag == "mstsc" else "Web-SSH"

            def have(cookies, err):
                if err or not cookies:
                    ui.message(self._parent(), title, f"Could not sign in to the web interface: {err or 'no session'}",
                               Gtk.MessageType.ERROR)
                    return
                ChatWindow(self.app, f"{title} - {node.get('name', '')}", url, (1024, 768), cookies)
            self._web_session().session_cookies(have)
        self.ctrl.send(msg, got)

    def _web_session(self):
        if getattr(self.app, "_dl_session", None) is None:     # shared with device_list downloads
            from .client import WebSession
            self.app._dl_session = WebSession(self.ctrl)
        return self.app._dl_session

    def change_group(self):
        node = self.node
        cur = node.get("meshid")
        mtype = self._mesh().get("mtype")
        targets = [(m, v.get("name", m)) for m, v in self._meshes().items()
                   if m != cur and rights.mesh_rights(self.ctrl, v) & 4 and v.get("mtype") == mtype]
        if not targets:
            ui.message(self._parent(), "Change Group", "No other device group of same type exists.")
            return
        d, area, _ok = dl._dialog(self._parent(), "Change Group", "OK")
        area.pack_start(Gtk.Label(label="Select a new group for this device", xalign=0), False, False, 0)
        combo = dl._combo(sorted(targets, key=lambda t: dl._nat_key(t[1])))
        dl._grid_rows(area, [("New Device Group", combo)])
        if dl._run(d):
            self.ctrl.send({"action": "changeDeviceMesh", "nodeids": [node["_id"]], "meshid": combo.get_active_id()})
        d.destroy()

    def delete_device(self):
        node = self.node
        d, area, ok = dl._dialog(self._parent(), "Delete Node", "OK")
        area.pack_start(Gtk.Label(label=f"Are you sure you want to delete node {ui.one_line(node.get('name', ''))}?",
                                  xalign=0),
                        False, False, 0)
        chk = Gtk.CheckButton(label="Confirm")
        area.pack_start(chk, False, False, 0)
        ok.get_style_context().add_class("destructive-action")
        ok.set_sensitive(False)
        chk.connect("toggled", lambda c: ok.set_sensitive(c.get_active()))
        if dl._run(d):
            self.ctrl.send({"action": "removedevices", "nodeids": [node["_id"]]})
            if self.win and hasattr(self.win, "close_device"):
                GLib.idle_add(lambda: (self.win.close_device(node["_id"]), False)[1])
        d.destroy()

    # ---- user authorizations ----------------------------------------------------------------
    def _link_name(self, uid):
        link = (self.node.get("links") or {}).get(uid) or {}
        if uid in (self.usergroups or {}):
            return self.usergroups[uid].get("name") or uid
        if uid == (self.ctrl.userinfo or {}).get("_id"):
            return self.ctrl.userinfo.get("name") or uid
        return link.get("name") or uid.split("/")[-1]

    def _build_users(self, r):
        for c in self.users.get_children():
            self.users.remove(c)
        node = self.node
        links = node.get("links") or {}
        dom = node["_id"].split("/")[1]
        if r & 7:
            add_user = self.add_user
            free = [g for g, v in (self.usergroups or {}).items()
                    if v.get("membershipType") is None and g.split("/")[1] == dom and g not in links]
            add_group = self.add_user_group if free else None
        else:
            add_user = add_group = None
        rows = []
        for uid in sorted(u for u in links if u.startswith("user/") or u.startswith("ugrp/")):
            grp = uid.startswith("ugrp/")
            edit = (lambda u=uid: self.edit_user(u)) if r & 2 else None
            rem = (lambda u=uid: self.remove_user(u)) if r & 2 else None
            rows.append((("Group: " if grp else "") + self._link_name(uid), device_rights_text(links[uid].get("rights") or 0),
                         edit, rem, "Remove user group rights to this device" if grp else "Remove user rights to this device"))
        list_section(self.users, "User Authorizations", "Add User", add_user, rows,
                     "No users with special device permissions")
        if add_group:                                     # second "Add" link, like the web UI
            first = self.users.get_children()[0]
            b = Gtk.Button(label="Add User Group", image=Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU),
                           always_show_image=True, relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.END)
            b.connect("clicked", lambda *_: add_group())
            first.pack_start(b, False, False, 0)
        self.users.show_all()

    def _rights_dialog(self, title, value, entry_label=None, combo=None):
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        d, area, ok = dl._dialog(self._parent(), title, "OK", 460)
        entry = None
        if entry_label:
            msg = "Allow users to manage this device."
            if ((self.ctrl.serverinfo or {}).get("features") or 0) & 0x80000:
                msg += " Users need to login to this server once before they can be added to a device group."
            area.pack_start(Gtk.Label(label=msg, xalign=0, wrap=True, max_width_chars=60), False, False, 0)
            entry = Gtk.Entry(max_length=256, hexpand=True, placeholder_text="user1, user2, user3")
            dl._grid_rows(area, [(entry_label, entry)])
            ok.set_sensitive(False)
            entry.connect("changed", lambda e: ok.set_sensitive(bool(e.get_text().strip())))
        if combo is not None:
            dl._grid_rows(area, [("User Group", combo)])
        rd = RightsDialog(area, False, guest, value)
        # read everything before destroy() (a destroyed combo has no model any more)
        res = (rd.value(), entry.get_text() if entry else combo.get_active_id() if combo else None) \
            if dl._run(d) else None
        d.destroy()
        return res

    def _adddeviceuser(self, extra, check_names=None, title="Device permissions"):
        msg = dict({"action": "adddeviceuser", "nodeid": self.node["_id"], "nodename": self.node.get("name")}, **extra)

        def done(reply):
            res = reply.get("result")
            if res not in (None, "ok"):
                ui.message(self._parent(), title, str(res), Gtk.MessageType.ERROR)
            elif check_names:
                # the server answers ok even for unknown names: look for them once the node refreshed
                GLib.timeout_add(3000, lambda: (self._check_added(check_names, title), False)[1])
        self.ctrl.send(msg, done)

    def _check_added(self, names, title):
        dom = self.node["_id"].split("/")[1]
        links = self.node.get("links") or {}
        missing = [n for n in names if f"user/{dom}/{n.lower()}" not in links and f"user/{dom}/{n}" not in links]
        if missing:
            ui.message(self._parent(), title, "No account found for: " + ", ".join(missing),
                       Gtk.MessageType.WARNING)

    def add_user(self):
        r = self._rights_dialog("Add User Device Permissions", 0, "User Identifiers")
        if r:
            value, text = r
            names = [n.strip() for n in text.split(",") if n.strip()]
            if names:
                self._adddeviceuser({"usernames": names, "rights": value}, names, "Add User")

    def add_user_group(self):
        links = self.node.get("links") or {}
        dom = self.node["_id"].split("/")[1]
        ug = self.usergroups or {}
        opts = sorted(((g, v.get("name") or g) for g, v in ug.items()
                       if v.get("membershipType") is None and g.split("/")[1] == dom and g not in links),
                      key=lambda t: t[1].lower())
        combo = dl._combo(opts)
        r = self._rights_dialog("Add User Group Device Permissions", 0, combo=combo)
        if r and r[1]:
            self._adddeviceuser({"userids": [r[1]], "rights": r[0]}, None, "Add User Group")

    def edit_user(self, uid):
        cur = ((self.node.get("links") or {}).get(uid) or {}).get("rights") or 0
        grp = uid.startswith("ugrp/")
        r = self._rights_dialog("Edit User Group Device Permissions" if grp else "Edit User Device Permissions", cur)
        if r:
            self._adddeviceuser({"userids": [uid], "rights": r[0]})

    def remove_user(self, uid):
        grp = uid.startswith("ugrp/")
        name = self._link_name(uid)
        if ui.confirm(self._parent(), "Remove User Group Permissions" if grp else "Remove User Permissions",
                      f"Confirm removal of access rights for {'user group' if grp else 'user'} \"{name}\"?",
                      "Remove", True):
            self._adddeviceuser({"userids": [uid], "rights": 0, "remove": True})

    # ---- editing ---------------------------------------------------------------------------
    def _changedevice(self, **kw):
        self.ctrl.send(dict({"action": "changedevice", "nodeid": self.node["_id"]}, **kw))

    def edit_value(self, field, title, maxlen):
        d, area, ok = dl._dialog(self._parent(), "Edit Device", "OK")
        e = Gtk.Entry(text=self.node.get(field) or "", max_length=maxlen, hexpand=True, activates_default=True,
                      width_chars=40)
        dl._grid_rows(area, [(title, e)])
        if field == "host":                               # web UI: hostname may not be empty
            ok.set_sensitive(bool(e.get_text()))
            e.connect("changed", lambda *_: ok.set_sensitive(bool(e.get_text())))
        if dl._run(d):
            val = e.get_text()
            if val != (self.node.get(field) or ""):
                self._changedevice(**{field: val})
                self.node[field] = val
                self.refresh(self.node)
        d.destroy()

    def edit_tags(self):
        d, area, _ok = dl._dialog(self._parent(), "Edit Device", "OK")
        e = Gtk.Entry(text=", ".join(self.node.get("tags") or []), max_length=4096, hexpand=True,
                      activates_default=True, width_chars=40, placeholder_text="Tag1, Tag2, Tag3")
        dl._grid_rows(area, [("Tags", e)])
        nodes = (getattr(self.win, "nodes", None) or {}).values()
        existing = sorted({t for n in nodes for t in (n.get("tags") or [])}, key=dl._nat_key)
        if existing:                                      # click to add, like the web UI's tag chips
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8)
            for t in existing:
                b = Gtk.Button(label=t)
                b.connect("clicked", lambda _b, tag=t: _add_tag(e, tag))
                flow.add(b)
            area.pack_start(flow, False, False, 0)
        if dl._run(d):
            new = [t.strip() for t in e.get_text().split(",") if 0 < len(t.strip()) < 64]
            new = list(dict.fromkeys(new))
            if new != list(self.node.get("tags") or []):
                self._changedevice(tags=",".join(new))
                if new:
                    self.node["tags"] = new
                else:
                    self.node.pop("tags", None)
                self.refresh(self.node)
        d.destroy()

    def edit_consent(self):
        cur = self.node.get("consent") or 0
        forced = (self.ctrl.serverinfo or {}).get("consent") or 0
        d, area, _ok = dl._dialog(self._parent(), "Edit Device User Consent", "OK")
        checks, section = {}, None
        for bit, sec, label in CONSENT_FLAGS:
            if sec != section:
                section = sec
                h = Gtk.Label(xalign=0)
                h.set_markup(f"<b>{sec}</b>")
                area.pack_start(h, False, False, 0)
            c = Gtk.CheckButton(label=label, active=bool((cur | forced) & bit), margin_start=12)
            c.set_sensitive(not forced & bit)             # forced by the server's configuration
            area.pack_start(c, False, False, 0)
            checks[bit] = c
        if dl._run(d):
            consent = sum(bit for bit, c in checks.items() if c.get_active())
            if consent != cur:
                self._changedevice(consent=consent)
                if consent:
                    self.node["consent"] = consent
                else:
                    self.node.pop("consent", None)
                self.refresh(self.node)
        d.destroy()

    def edit_notify(self):
        me = self.ctrl.userinfo or {}
        f2 = (self.ctrl.serverinfo or {}).get("features2") or 0
        cur = (me.get("notify") or {}).get(self.node["_id"]) or 0
        d, area, _ok = dl._dialog(self._parent(), "Notification Settings", "OK")
        sections = [("Web Page Notifications", [(2, "Device connections"), (4, "Device disconnections")]
                     + ([(8, "Intel® AMT desktop and serial events")] if self.node.get("intelamt") is not None else []))]
        if f2 & 0x4000 and me.get("emailVerified"):
            sections.append(("Email Notifications", [(16, "Device connections"), (32, "Device disconnections"),
                                                     (64, "Help requests")]))
        if me.get("msghandle") is not None and f2 & 0x02000000:
            sections.append(("Messaging Notifications", [(128, "Device connections"), (256, "Device disconnections"),
                                                         (512, "Help requests")]))
        checks = {}
        for title, flags in sections:
            h = Gtk.Label(xalign=0)
            h.set_markup(f"<b>{_esc(title)}</b>")
            area.pack_start(h, False, False, 0)
            for bit, label in flags:
                c = Gtk.CheckButton(label=label, active=bool(cur & bit), margin_start=12)
                area.pack_start(c, False, False, 0)
                checks[bit] = c
        if dl._run(d):
            # bits of sections not shown are dropped, like the web UI
            notify = sum(bit for bit, c in checks.items() if c.get_active())
            if notify != cur:
                self.ctrl.send({"action": "changeusernotify", "nodeid": self.node["_id"], "notify": notify})
                if isinstance(self.ctrl.userinfo, dict):
                    self.ctrl.userinfo.setdefault("notify", {})[self.node["_id"]] = notify
                self.refresh(self.node)
        d.destroy()

    # ---- buttons ---------------------------------------------------------------------------
    def _group_actions(self):
        return dl.GroupActions(self.win, single=True)

    def actions(self):
        """Web UI "Device Action": wake, run commands, sleep / reset / power off, uninstall agent."""
        r, node = self._rights(), self.node
        conn = node.get("conn") or 0
        agent = node.get("agent") or {}
        ops = []
        if agent.get("id") == 14:
            if conn & 1 and r & 8:
                ops += [(400, "Flash"), (401, "Vibrate")]
        else:
            if r & 64:
                ops.append((100, "Wake-up"))
            if conn & 1 and r & 131072:
                ops.append((106, "Run Commands"))
            if conn and r & 262144:
                ops += [(4, "Sleep"), (3, "Reset"), (2, "Power off")]
            if conn & 1 and r & 32768:
                ops.append((104, "Uninstall Agent"))
        if not ops:
            ui.message(self._parent(), "Device Action", "No actions currently available for this device.")
            return
        d, area, _ok = dl._dialog(self._parent(), "Device Action", "OK")
        area.pack_start(Gtk.Label(label="Select an operation to perform on this device.", xalign=0), False, False, 0)
        combo = dl._combo(ops)
        dur = dl._combo([(1000, "1 second"), (5000, "5 seconds"), (10000, "10 seconds")])
        g = dl._grid_rows(area, [("Operation", combo), ("Time", dur)])
        tl = g.get_child_at(0, 1)

        def vis(*_):
            on = combo.get_active_id() in ("400", "401")
            dur.set_visible(on)
            tl.set_visible(on)
        combo.connect("changed", vis)
        d.show_all()
        vis()
        op = int(combo.get_active_id()) if d.run() == Gtk.ResponseType.OK else None
        d.destroy()
        if op is None:
            return
        ga = self._group_actions()
        if op == 100:
            ga.op_wake([node])
        elif op == 106:
            ga.op_run([node])
        elif op == 104:
            ga.op_uninstall([node])
        elif op in (400, 401):
            self.ctrl.send({"action": "poweraction", "nodeids": [node["_id"]], "actiontype": op,
                            "time": int(dur.get_active_id())})
        else:
            verb = {4: "Sleep", 3: "Reset", 2: "Power off"}[op]
            if op == 4 or ui.confirm(self._parent(), f"{verb} {node.get('name')}?", "", verb, destructive=True):
                self.ctrl.send({"action": "poweraction", "nodeids": [node["_id"]], "actiontype": op})
                self.app.notify(verb, f"Sent to {node.get('name')}")

    def notes(self):
        NotesDialog(self._parent(), self.ctrl, self.node, editable=bool(self._rights() & 128)).present()

    def log_event(self):
        d, area, ok = dl._dialog(self._parent(), "Add Device Event", "OK", 480)
        tv, fr = dl._text_view("", 160)
        area.pack_start(fr, True, True, 0)
        hint = Gtk.Label(label="This will add an entry to this device's event log.", xalign=0)
        hint.get_style_context().add_class("dim-label")
        area.pack_start(hint, False, False, 0)
        ok.set_sensitive(False)
        tv.get_buffer().connect("changed", lambda *_: ok.set_sensitive(0 < len(dl._buf_text(tv)) <= 4096))
        if dl._run(d):
            self.ctrl.send({"action": "setDeviceEvent", "nodeid": self.node["_id"],
                            "msg": urllib.parse.quote(dl._buf_text(tv), safe="-_.!~*'()")})
            self.app.notify("Log Event", f"Event added to {self.node.get('name')}")
        d.destroy()

    def run_cmds(self):
        self._group_actions().op_run([self.node])

    def message(self):
        d, area, ok = dl._dialog(self._parent(), "Device Message", "OK", 480)
        area.pack_start(Gtk.Label(label="Display a message box on the remote device.", xalign=0), False, False, 0)
        tv, fr = dl._text_view("", 90)
        area.pack_start(fr, True, True, 0)
        tmo = dl._combo([(2, "Show for 2 Minutes (Default)"), (10, "Show for 10 minutes"),
                         (30, "Show for 30 minutes"), (60, "Show for 60 minutes"),
                         (0, "Show message until dismissed by user")])
        area.pack_start(tmo, False, False, 0)
        ok.set_sensitive(False)
        tv.get_buffer().connect("changed", lambda *_: ok.set_sensitive(bool(dl._buf_text(tv))))
        if dl._run(d):
            msg, title = dl._buf_text(tv), "MeshCentral"
            if self.node.get("pmt") == 1:
                self.ctrl.send({"action": "pushmessage", "nodeid": self.node["_id"], "title": title, "msg": msg})
            else:
                self.ctrl.send({"action": "msg", "type": "messagebox", "nodeid": self.node["_id"], "title": title,
                                "msg": msg, "timeout": int(tmo.get_active_id()) * 60000})
        d.destroy()

    def chat(self):
        open_chat(self.app, self.node)

    def share(self):
        ShareDialog(self)


def open_chat(app, node):
    """Web UI chat with the device's user: the server's /messenger page in a window, then the agent is
    told to open its side (meshmessenger)."""
    ctrl = app.ctrl
    me, si = ctrl.userinfo or {}, ctrl.serverinfo or {}

    def got(cookie, _rcookie):
        q = urllib.parse.quote
        path = "/messenger?id=meshmessenger/" + q(node["_id"], safe="") + "/" + q(me.get("_id", ""), safe="")
        path += "&title=" + q(node.get("name", ""), safe="")
        if si.get("domainsuffix"):
            path = "/" + si["domainsuffix"] + path
        if cookie:
            path += "&auth=" + q(cookie, safe="")
        if node.get("pmt") == 1 and (si.get("features2") or 0) & 2:
            path += "&pmt=1"
        ChatWindow(app, f"Chat - {node.get('name', '')}", ctrl.server.url.rstrip("/") + path)
        ctrl.send({"action": "meshmessenger", "nodeid": node["_id"]})
    ctrl.get_auth_cookie(got)                   # callbacks already run on the GTK loop


class DeviceContext:
    """What ShareDialog (and other device dialogs) need from the General page, for use elsewhere (the
    remote desktop toolbar): app, node, rights, a parent window."""

    def __init__(self, app, node, parent=None):
        self.app, self.node, self._parent_win = app, node, parent
        self._share_rid = None

    @property
    def ctrl(self):
        return self.app.ctrl

    def _meshes(self):
        win = getattr(self.app, "main_win", None)
        return getattr(self.app, "meshes", None) or getattr(win, "meshes", None) or {}

    def _rights(self):
        return rights.node_rights(self.ctrl, self._meshes(), self.node)

    def _parent(self):
        return self._parent_win or getattr(self.app, "main_win", None)


def _add_tag(entry, tag):
    cur = [t.strip() for t in entry.get_text().split(",") if t.strip()]
    if tag not in cur:
        entry.set_text(entry.get_text() + ("" if not entry.get_text().strip() else ", ") + tag)
        entry.set_position(-1)


def _duration(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ChatWindow(Gtk.Window):
    """A server page in an embedded web view window, like the web UI's popups: the chat (/messenger) or the
    web VNC / RDP / SSH clients."""

    def __init__(self, app, title, url, size=(400, 560), cookies=None):
        super().__init__(title=title)
        from .webview import WebView                       # stays on the server, no pop-ups
        self.set_default_size(*size)
        if getattr(app, "main_win", None):
            self.set_transient_for(app.main_win)
        self.web = WebView(app, server_url=app.ctrl.server.url)
        self.add(self.web.widget)
        self.show_all()
        if not cookies:
            self.web.load_uri(url)
            return
        self.web.add_cookies(url, cookies, lambda: self.web.load_uri(url))


class ShareDialog:
    """Web UI "Share Device": a guest link for desktop / terminal / files."""

    def __init__(self, panel):
        self.panel = panel
        self.ctrl = panel.ctrl
        node = panel.node
        r = panel._rights()
        full = r == rights.FULL
        caps = (node.get("agent") or {}).get("caps") or 0
        types = []
        if caps & 1:
            if full or not r & 0x100:
                types.append(2)
            types.append(3)
        if caps & 2 and (full or not r & 0x200):
            types.append(1)
        if caps & 4 and (full or not r & 0x400):
            types.append(4)
        if caps & 5 == 5 and (full or not r & 0x500):
            types.append(5)
        if caps & 6 == 6 and (full or not r & 0x600):
            types.append(6)
        if caps & 7 == 7 and (full or not r & 0x700):
            types.append(7)
        if not types:
            ui.message(panel._parent(), "Share Device", "This device cannot be shared with your rights.")
            return
        maxt = (self.ctrl.serverinfo or {}).get("guestdevicesharingmaxtime")
        expire = [(k, v) for k, v in SHARE_EXPIRE if maxt is None or 0 < k <= maxt]
        duration = [(k, v) for k, v in SHARE_EXPIRE if 0 < k <= 720 and (maxt is None or k <= maxt)]
        self.caps = caps
        d, area, ok = dl._dialog(panel._parent(), "Share Device", "OK", 500)
        area.pack_start(Gtk.Label(label="Creates a link that allows a guest without an account to remote control "
                                        "this device for a limited time.", xalign=0, wrap=True, max_width_chars=60),
                        False, False, 0)
        self.name = Gtk.Entry(max_length=128, hexpand=True)
        self.typ = dl._combo([(t, SHARE_TYPES[t]) for t in types])
        self.mode = dl._combo([(0, "Starting now"), (1, "Time range"), (2, "Recurring daily"), (3, "Recurring weekly")])
        self.expire = dl._combo(expire)
        now = datetime.now()
        self.start = Gtk.Entry(text=now.strftime(_DT_FMT), placeholder_text="YYYY-MM-DD HH:MM")
        self.end = Gtk.Entry(text=datetime.fromtimestamp(time.time() + 86400).strftime(_DT_FMT),
                             placeholder_text="YYYY-MM-DD HH:MM")
        self.duration = dl._combo(duration)
        self.consent = dl._combo([(0, "Notify Only"), (1, "Prompt for consent"), (2, "No Consent")])
        rows = [("Guest Name", self.name), ("Type", self.typ), ("Validity", self.mode), ("Expire Time", self.expire),
                ("Start", self.start), ("End", self.end), ("Duration", self.duration)]
        if caps & 1:
            rows.append(("User Consent", self.consent))
        self.grid = dl._grid_rows(area, rows)
        self.ok = ok
        for w in (self.name, self.start, self.end):
            w.connect("changed", self._validate)
        for w in (self.typ, self.mode):
            w.connect("changed", self._validate)
        d.show_all()
        self._validate()
        if d.run() == Gtk.ResponseType.OK:
            self._send()
        d.destroy()

    def _show(self, row, on):
        for col in (0, 1):
            w = self.grid.get_child_at(col, row)
            if w:
                w.set_visible(on)

    def _times(self):
        try:
            s = datetime.strptime(self.start.get_text().strip(), _DT_FMT).timestamp()
            e = datetime.strptime(self.end.get_text().strip(), _DT_FMT).timestamp()
            return int(s), int(e)
        except ValueError:
            return None, None

    def _validate(self, *_):
        m = int(self.mode.get_active_id())
        self._show(3, m == 0)
        self._show(4, m >= 1)
        self._show(5, m == 1)
        self._show(6, m >= 2)
        ok = bool(self.name.get_text().strip())
        s, e = self._times() if m == 1 else (self._times()[0], 0) if m >= 2 else (0, 0)
        if m >= 1 and s is None:
            ok = False
        if m == 1 and (e is None or s is None or e <= s):
            ok = False
        self.ok.set_sensitive(ok)

    def _send(self):
        node = self.panel.node
        p = int(self.typ.get_active_id())
        q = [0, 1, 2, 2, 4, 6, 5, 7][p]                   # 1 terminal, 2 desktop, 4 files
        cv = int(self.consent.get_active_id()) if self.caps & 1 else 0
        consent = 0
        if q & 1:
            consent |= 0x0002
        if q & 2:
            consent |= 0x0041
        if q & 4:
            consent |= 0x0004
        if cv == 1:
            consent |= (0x0010 if q & 1 else 0) | (0x0008 if q & 2 else 0) | (0x0020 if q & 4 else 0)
        elif cv == 2:
            consent = 0
        msg = {"action": "createDeviceShareLink", "nodeid": node["_id"], "guestname": self.name.get_text().strip(),
               "p": q, "consent": consent, "viewOnly": p == 3}
        m = int(self.mode.get_active_id())
        s, e = self._times()
        if m == 0:
            msg["expire"] = int(self.expire.get_active_id())
        elif m == 1:
            msg["start"], msg["end"] = s, e
        else:
            msg["start"], msg["expire"], msg["recurring"] = s, int(self.duration.get_active_id()), m - 1
        self.ctrl.send(msg, lambda reply: _share_result(self.panel, reply))


def _share_result(panel, reply):
    parent = panel._parent()
    if reply.get("result") not in (None, "OK") or not reply.get("url"):
        ui.message(parent, "Share Device", f"The link was not created: {reply.get('result') or 'no answer'}",
                   Gtk.MessageType.ERROR)
        return
    d, area, _ok = dl._dialog(parent, "Share Device", None, 520)
    for b in d.get_action_area().get_children():
        b.set_label("Close")
    rows = [("Device", panel.node.get("name", "")), ("Guest Name", reply.get("guestname", "")),
            ("User Input", "Not allowed, view only" if reply.get("viewOnly") else "Allowed")]
    if reply.get("start") and reply.get("expire"):
        rows.append(("Start Time", ui.fmt_time(reply["start"])))
        if reply.get("recurring"):
            rows.append(("Duration", f"{reply['expire']} minute{'s' if reply['expire'] > 1 else ''}"))
        else:
            rows.append(("Expire Time", ui.fmt_time(reply["expire"])))
    if reply.get("recurring") in (1, 2):
        rows.append(("Recurring", "Daily" if reply["recurring"] == 1 else "Weekly"))
    c = reply.get("consent") or 0
    y = [t for bit, t in ((0x07, "Notify"), (0x38, "Prompt"), (0x40, "Privacy bar")) if c & bit] or ["None"]
    rows.append(("User Consent", ", ".join(y)))
    p = reply.get("p") or 0
    rows.append(("Type", SHARE_LINK_NAMES[p] if 0 < p < len(SHARE_LINK_NAMES) else str(p)))
    dl._grid_rows(area, [(k, Gtk.Label(label=str(v), xalign=0, selectable=True)) for k, v in rows])
    url = Gtk.Entry(text=reply["url"], editable=False, hexpand=True)
    copy = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
    copy.set_tooltip_text("Copy link")
    copy.connect("clicked", lambda *_: (dl._copy(reply["url"]), panel.app.notify("Share Device", "Link copied")))
    box = Gtk.Box(spacing=6)
    box.pack_start(url, True, True, 0)
    box.pack_start(copy, False, False, 0)
    area.pack_start(box, False, False, 0)
    dl._run(d)
    d.destroy()


# web UI powerStateStrings2; colours like the web UI's powerColorTable except "powered", which is
# green here (the web UI's black bar disappears on a dark theme)
POWER_STATES = ["", "Device is powered", "Device is in sleep state (S1)", "Device is in sleep state (S2)",
                "Device is in deep sleep state (S3)", "Device is hibernating (S4)", "Device is in soft-off state (S5)",
                "Device is present, but power state cannot be determined", "The device is powered off"]
POWER_COLORS = [None, (0.18, 0.76, 0.49), (0, 0, 1), (0, 0, 1), (0.68, 0.85, 0.9), (0.54, 0.17, 0.89), (0, 0.39, 0),
                (0.13, 0.7, 0.67), (0.13, 0.7, 0.67)]


def power_blocks(timeline, now_ms):
    """Decompress [state, start s, state, delta s, state, …] into [(start ms, end ms, state)] like the
    web UI's drawDeviceTimeline (the last state lasts until now)."""
    t = list(timeline or [])
    if len(t) < 2:
        return []
    for i in range(1, len(t), 2):                         # times are seconds; tolerate the ms fallback
        if isinstance(t[i], (int, float)) and not (i == 1 and t[i] > 1e11):
            t[i] = t[i] * 1000
    blocks = [(0, t[1], t[0])]
    ct = t[1]
    for i in range(2, len(t), 2):
        end = ct + t[i + 1] if i + 1 < len(t) else now_ms
        blocks.append((ct, end, t[i]))
        ct = end
    return blocks


class PowerTimeline(Gtk.Box):
    """"7 Day Power State": one bar per day (today first), coloured by power state, hover for details."""
    ROW, LABEL = 20, 110

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head = Gtk.Box(spacing=8)
        t = Gtk.Label(xalign=0)
        t.set_markup("<b>7 Day Power State</b>")
        head.pack_start(t, False, False, 0)
        self.note = Gtk.Label(xalign=0)
        self.note.get_style_context().add_class("dim-label")
        head.pack_start(self.note, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.area = Gtk.DrawingArea(height_request=self.ROW * 7, hexpand=True, has_tooltip=True)
        self.area.connect("draw", self._draw)
        self.area.connect("query-tooltip", self._tooltip)
        self.pack_start(self.area, False, False, 0)
        self.blocks = None
        self.note.set_text("Loading…")

    def set_timeline(self, timeline):
        self.blocks = power_blocks(timeline, time.time() * 1000)
        self.note.set_text("" if self.blocks else "No power history")
        self.area.queue_draw()

    @staticmethod
    def _days():
        d = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        for _ in range(7):
            start = d.timestamp() * 1000
            out.append((d, start, start + 86400000))
            d = datetime.fromtimestamp(d.timestamp() - 43200).replace(hour=0, minute=0, second=0, microsecond=0)
        return out

    def _segments(self, width):
        now = time.time() * 1000
        bar = max(1, width - self.LABEL)
        for row, (day, start, end) in enumerate(self._days()):
            for bs, be, st in self.blocks or []:
                ts, te = max(start, bs), min(end, be, now)
                if te > ts and isinstance(st, int):
                    x0 = self.LABEL + (ts - start) * bar / 86400000
                    x1 = self.LABEL + (te - start) * bar / 86400000
                    yield row, day, x0, x1, ts, te, st

    def _draw(self, w, cr):
        width = w.get_allocated_width()
        fg = w.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        layout = w.create_pango_layout("")
        for row, (day, _s, _e) in enumerate(self._days()):
            y = row * self.ROW
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.10 if row % 2 else 0.05)
            cr.rectangle(0, y, width, self.ROW - 1)
            cr.fill()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
            layout.set_text(day.strftime("%a %d/%m/%Y"), -1)
            cr.move_to(6, y + (self.ROW - layout.get_pixel_size()[1]) / 2)
            PangoCairo.show_layout(cr, layout)
        for row, _day, x0, x1, _ts, _te, st in self._segments(width):
            col = POWER_COLORS[st] if 0 <= st < len(POWER_COLORS) else (1, 1, 0)
            if col is None:
                continue
            cr.set_source_rgb(*col)
            cr.rectangle(x0, row * self.ROW + 3, max(1, x1 - x0), self.ROW - 7)
            cr.fill()
        return False

    def _tooltip(self, w, x, y, _kb, tip):
        row = int(y // self.ROW)
        for r, _day, x0, x1, ts, te, st in self._segments(w.get_allocated_width()):
            if r == row and x0 <= x <= x1:
                what = POWER_STATES[st] if 0 < st < len(POWER_STATES) else f"State {st}"
                fmt = lambda ms: datetime.fromtimestamp(ms / 1000).strftime("%H:%M")
                tip.set_text(f"{what} from {fmt(ts)} to {fmt(te)}.")
                return True
        return False
