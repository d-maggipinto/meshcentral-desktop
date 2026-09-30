"""Users → one user's page, like the web UI's "General - <user>" / "Events" (views 30/31).

Everything goes through the documented control-channel actions the web UI uses:
  edituser {id, email|realname|phone|flags+removeRights|siteadmin(+quota)|consent|groups}
  changeuserpass {userid, pass, removeMultiFactor, resetNextLogin[, hint]}   (no reply at all)
  deleteuser {userid, username}
  addmeshuser {meshid, meshname, userids:[id], meshadmin}   removemeshuser {meshid, userid}
  adddeviceuser {nodeid, nodename, userids:[id], rights[, remove]}
  addusertousergroup {ugrpid, usernames:[short id]}   removeuserfromusergroup {ugrpid, userid}
  getNotes/setNotes {id: user id}   previousLogins {userid}   events {userid, limit[, filter]}
Successful changes arrive as {action:'event', event:{action:'accountchange', account}}, the
Users panel refreshes its list on those events and re-renders this page from the new data.
"""
import os
import re
import tempfile
import time

from gi.repository import Gtk, GLib, GdkPixbuf, Pango

from . import ui, rights
from .client import WebSession

FULL = 0xFFFFFFFF
FEAT_LDAP_SSPI = 0x80000
FEAT_PASSWORD_HINT = 0x10000
FEAT_SMS = 0x02000000

# (bit, label, indent, mesh_only), web UI p20showAddMeshUserDialog
DEVICE_RIGHTS = [
    (1, "Edit Device Group", 0, True), (2, "Manage Device Group Users", 0, True),
    (4, "Manage Device Group Computers", 0, True),
    (8, "Remote Control & Relay", 0, False), (256, "Remote View Only", 1, False),
    (4096, "Limited Input Only", 1, False), (524288, "Guest Sharing", 1, False),
    (65536, "No Desktop Access", 1, False), (512, "No Terminal Access", 1, False),
    (1024, "No File Access", 1, False), (4194304, "No Registry Access", 1, False),
    (8388608, "No Software", 1, False), (2048, "No Intel® AMT", 1, False),
    (16, "Mesh Agent Console", 0, False), (32, "Server Files", 0, False), (64, "Wake Devices", 0, False),
    (128, "Edit Device Notes", 0, False), (8192, "Show Only Own Events", 0, False),
    (16384, "Chat & Notify", 0, False), (32768, "Uninstall Agent / Delete Device", 0, False),
    (131072, "Remote Commands", 0, False), (262144, "Reset / Power Off", 0, False),
    (1048576, "Device Details", 0, False), (2097152, "Use as Relay", 0, False),
]
_UNDER_CONTROL = (256, 4096, 524288, 65536, 512, 1024, 4194304, 8388608, 2048)


def _control_detail(r, guest=True):
    parts = [n for b, n in ((256, "No Input"), (512, "No Terminal"), (1024, "No Files"),
                            (4194304, "No Registry"), (8388608, "No Software"), (2048, "No AMT"),
                            (4096, "Limited Input"), (65536, "No Desktop")) if r & b]
    if guest and r & 524288:
        parts.append("Guest Share")
    return "Control (%s)" % ", ".join(parts) if parts else "Control"


def _rights_tail(r):
    return [n for b, n in ((16, "Console"), (32, "Server Files"), (64, "Wake"), (128, "Notes"),
                           (8192, "Limit Events"), (16384, "Chat"), (32768, "Uninstall"),
                           (131072, "Commands"), (262144, "Reset/Off"), (524288, "Sharing"),
                           (1048576, "Details"), (2097152, "Relay")) if r & b]


def group_rights_text(r, guest=True):
    """web UI makeDeviceGroupRightsString"""
    if r == FULL:
        return "Full Rights"
    s = [n for b, n in ((1, "Edit Group"), (2, "Manage Users"), (4, "Manage Devices")) if r & b]
    if r & 8:
        s.append(_control_detail(r, guest))
    s += _rights_tail(r)
    return ", ".join(s) or "No Rights"


def device_rights_text(r, guest=True):
    """web UI makeUserDeviceRightsString"""
    if r == 57592:
        return "Full Device Rights"
    s = [_control_detail(r, guest)] if r & 8 else []
    s += _rights_tail(r)
    return ", ".join(s) or "No Rights"


def server_rights_text(u):
    sa = u.get("siteadmin")
    out = []
    if isinstance(sa, int) and sa & 32 and sa != FULL:
        out.append("Locked account")
    if not isinstance(sa, int) or (sa & (FULL - 1248)) == 0:
        out.append("No server rights")
    elif sa == 8:
        out.append("Access to server files")
    elif sa == FULL:
        out.append("Full administrator")
    else:
        out.append("Partial rights")
    if isinstance(sa, int) and sa != FULL and sa & (64 + 128 + 1024):
        out.append("Restrictions")
    return ", ".join(out)


def features_text(u, serverinfo):
    f = []
    if serverinfo.get("usersSessionRecording") == 1 and (u.get("flags") or 0) & 2:
        f.append("Record Sessions")
    rr = u.get("removeRights") or 0
    if rr:
        if rr & 0x8:
            f.append("No Remote Control")
        else:
            if rr & 0x10000:
                f.append("No Desktop")
            elif rr & 0x100:
                f.append("Desktop View Only")
            f += [n for b, n in ((0x200, "No Terminal"), (0x400, "No Files"), (0x400000, "No Registry"),
                                 (0x800000, "No Software")) if rr & b]
        f += [n for b, n in ((0x10, "No Console"), (0x8000, "No Uninstall"), (0x20000, "No Remote Command"),
                             (0x40, "No Wake"), (0x40000, "No Reset/Off")) if rr & b]
    return ", ".join(f) or "None"


def consent_text(u, serverinfo):
    c = (u.get("consent") or 0) | (serverinfo.get("consent") or 0)
    f = []
    if c & 0x40 and c & 0x8:
        f.append("Desktop Prompt+Toolbar")
    elif c & 0x40:
        f.append("Desktop Toolbar")
    elif c & 0x8:
        f.append("Desktop Prompt")
    elif c & 0x1:
        f.append("Desktop Notify")
    for prompt, notify, name in ((0x10, 0x2, "Terminal"), (0x20, 0x4, "Files"), (0x100, 0x80, "Registry")):
        if c & prompt:
            f.append(name + " Prompt")
        elif c & notify:
            f.append(name + " Notify")
    if c == 0x87:
        f = ["Always Notify"]
    if c & 0x138 == 0x138:
        f = ["Always Prompt"]
    return ", ".join(f) or "None"


def second_factors(u):
    f = [n for k, n in (("otpsecret", "Authentication App"), ("otphkeys", "Security Key"),
                        ("otpekey", "Email"), ("otpduo", "Duo")) if u.get(k)]
    if not f:
        return []
    if u.get("otpkeys"):
        f.append("Backup Codes")
    if u.get("otpdev"):
        f.append("Device Push")
    return f


def _check(label, active=False, indent=0):
    c = Gtk.CheckButton(label=label, active=bool(active))
    c.set_margin_start(18 * indent)
    return c


def _dialog(parent, title, ok_label="OK", width=420):
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.set_default_size(width, -1)
    area = d.get_content_area()
    area.set_spacing(6)
    area.set_border_width(12)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = d.add_button(ok_label, Gtk.ResponseType.OK)
    ok.get_style_context().add_class("suggested-action")
    d.set_default_response(Gtk.ResponseType.OK)
    return d, area, ok


def _run(d):
    d.show_all()
    r = d.run()
    return r == Gtk.ResponseType.OK


def _section_title(text):
    l = Gtk.Label(xalign=0, margin_top=8)
    l.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return l


class RightsDialog:
    """Device-group or device permission checkboxes (web UI p20showAddMeshUserDialog types 1 / 4)."""

    def __init__(self, area, mesh_level, guest_sharing=True, value=0):
        self.mesh_level = mesh_level
        self.checks = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.full = None
        if mesh_level:
            self.full = _check("Full Administrator", value == FULL)
            self.full.connect("toggled", lambda *_: self.validate())
            box.pack_start(self.full, False, False, 0)
        for bit, label, indent, mesh_only in DEVICE_RIGHTS:
            if mesh_only and not mesh_level:
                continue
            if bit == 524288 and not guest_sharing:
                continue
            c = _check(label, value != FULL and bool(value & bit), indent)
            c.connect("toggled", lambda *_: self.validate())
            self.checks[bit] = c
            box.pack_start(c, False, False, 0)
        scr = Gtk.ScrolledWindow(min_content_height=300, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scr.add(box)
        frame = Gtk.Frame()
        frame.add(scr)
        area.pack_start(frame, True, True, 0)
        self.enabled = True
        self.validate()

    def set_value(self, value):
        if self.full is not None:
            self.full.set_active(value == FULL)
        for bit, c in self.checks.items():
            c.set_active(value != FULL and bool(value & bit))
        self.validate()

    def set_enabled(self, on):
        self.enabled = on
        self.validate()

    def validate(self):
        nc = self.enabled and not (self.full is not None and self.full.get_active())
        if self.full is not None:
            self.full.set_sensitive(self.enabled)
        on = lambda b: self.checks[b].get_active() if b in self.checks else False
        rc = on(8)
        for bit, c in self.checks.items():
            if bit == 256:
                c.set_sensitive(nc and rc)
            elif bit == 4096:
                c.set_sensitive(nc and rc and not on(256))
            elif bit == 524288:
                c.set_sensitive(nc and rc and (on(256) or not on(4096)))
            elif bit in _UNDER_CONTROL:
                c.set_sensitive(nc and rc)
            else:
                c.set_sensitive(nc)

    def value(self):
        if self.full is not None and self.full.get_active():
            return FULL
        v = 0
        for bit, c in self.checks.items():
            if c.get_active():
                v |= bit
        if v & 256 and v & 4096:            # limited input only without view-only
            v &= ~4096
        if v & 524288 and not (v & 256 or not v & 4096):
            v &= ~524288
        if not v & 8:                        # no remote control → drop its sub-options
            for b in _UNDER_CONTROL:
                v &= ~b
        return v


def show_previous_logins(parent, ctrl, userid=None, title="Previous logins"):
    """previousLogins [{userid}] → {events:[{t, m, a, tn?}]} (m 107 = login from ip, browser, os).
    Shared by My Account (own logins) and the Users page (another user's)."""
    state = {"done": False}

    def show(msg):
        if state["done"] or (userid and msg.get("userid") not in (None, userid)):
            return
        state["done"] = True
        ctrl.off("previousLogins", show)
        d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
        d.set_default_size(720, 460)
        area = d.get_content_area()
        area.set_spacing(6)
        area.set_border_width(10)
        store = Gtk.ListStore(str, str, str)
        for e in sorted(msg.get("events") or [], key=lambda e: str(e.get("t")), reverse=True):
            a = [str(x) for x in (e.get("a") or [])]
            if e.get("m") == 107 and len(a) >= 3:
                what, detail = "Login", f"{a[0]} · {a[1]} · {a[2]}"
            elif e.get("m") == 107:
                what, detail = "Login", ", ".join(a)
            else:
                what, detail = f"Event {e.get('m')}", ", ".join(a)
            if e.get("tn"):
                detail += f"  (token: {e['tn']})"
            store.append([ui.fmt_time(e.get("t")), what, detail])
        tv = Gtk.TreeView(model=store)
        for i, (t, ex) in enumerate((("Time", False), ("Event", False), ("From", True))):
            tv.append_column(ui.text_column(t, i, ex))
        ui.row_tooltip(tv, 2)
        area.pack_start(ui.scrolled(tv), True, True, 0)
        note = f"{len(store)} entries" if len(store) else \
            "No logins recorded yet. The server records web sign-ins (not app sign-ins) for this list."
        area.pack_start(Gtk.Label(label=note, xalign=0, wrap=True), False, False, 0)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        d.connect("response", lambda *_: d.destroy())
        d.show_all()

    def expire():
        if not state["done"]:
            state["done"] = True
            ctrl.off("previousLogins", show)
            ui.message(parent, "No answer from the server")
        return False
    ctrl.on("previousLogins", show)
    GLib.timeout_add_seconds(15, expire)
    msg = {"action": "previousLogins"}
    if userid:
        msg["userid"] = userid
    ctrl.send(msg)


class UserPage(Gtk.Box):
    """One user's page inside the Users panel. `panel` is the UsersPanel (list data, back button,
    user groups cache); set_user() re-renders from a fresh user object."""
    EVENT_LIMITS = [("Last 60", 60), ("Last 120", 120), ("Last 250", 250), ("Last 500", 500),
                    ("Last 1000", 1000), ("No limit", None)]
    EVENT_FILTERS = [("All Logs", ""), ("Agent Logs", "agentlog"), ("Relay Logs", "relaylog"),
                     ("Manual Logs", "manual"), ("Run Command Logs", "runcommands"),
                     ("Batch Upload Logs", "batchupload"), ("Change Node Logs", "changenode"),
                     ("Remove Node Logs", "removenode")]

    def __init__(self, panel, user):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.app, self.ctrl = panel, panel.app, panel.app.ctrl
        self.user = user
        self._web = None
        self._avatar_for = None
        self._pw_wait = None
        # header: back + title + General/Events switcher
        head = Gtk.Box(spacing=8, margin=8)
        back = Gtk.Button(image=Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON),
                          tooltip_text="Back to the user list")
        back.connect("clicked", lambda *_: self.panel.close_user())
        head.pack_start(back, False, False, 0)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        head.pack_start(self.title, True, True, 0)
        self.stack = Gtk.Stack()
        sw = Gtk.StackSwitcher(stack=self.stack)
        head.pack_end(sw, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.pack_start(self.stack, True, True, 0)
        self.general = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self.stack.add_titled(ui.scrolled(self.general), "general", "General")
        self.stack.add_titled(self._build_events(), "events", "Events")
        self.stack.connect("notify::visible-child-name", lambda *_: self._maybe_load_events())
        self._events_loaded = False
        self.ctrl.on("events", self._on_events)
        self.connect("destroy", lambda *_: self.teardown())
        self.render()
        self.show_all()

    # ---- helpers ----------------------------------------------------------------------------
    def _top(self):
        return self.get_toplevel()

    def _me(self):
        return self.ctrl.userinfo or {}

    def _my_sa(self):
        return rights.site_rights(self.ctrl)

    def _features(self):
        f = (self.ctrl.serverinfo or {}).get("features")
        return f if isinstance(f, int) else 0

    def _is_self(self):
        return self.user.get("_id") == self._me().get("_id")

    def _user_admin(self):
        """web: userAdminRights, manage-users right and the target is not a full admin, or we are."""
        sa, tsa = self._my_sa(), self.user.get("siteadmin")
        return (bool(sa & 2) and tsa != FULL) or sa == FULL

    def _reply(self, what):
        def cb(msg):
            res = msg.get("result")
            if "success" in msg:        # addmeshuser: result = "Added user x, …" + success/failed counts
                ok = msg.get("success", 0) > 0 and not msg.get("failed")
            else:
                ok = res in (None, "ok")
            if not ok:
                ui.message(self._top(), f"{what} failed", str(res), Gtk.MessageType.ERROR)
            self.panel.refresh_soon()
        return cb

    def _edituser(self, what, **fields):
        self.ctrl.send(dict(action="edituser", id=self.user["_id"], **fields), self._reply(what))

    # ---- General ----------------------------------------------------------------------------
    def set_user(self, user):
        self.user = user
        self.render()

    def render(self):
        u, si = self.user, (self.ctrl.serverinfo or {})
        self.title.set_markup(f"<big><b>{GLib.markup_escape_text(u.get('name', ''))}</b></big>")
        for c in self.general.get_children():
            self.general.remove(c)
        top = Gtk.Box(spacing=12)
        grid = Gtk.Grid(row_spacing=6, column_spacing=16)
        top.pack_start(grid, True, True, 0)
        self.avatar = Gtk.Image(valign=Gtk.Align.START)
        top.pack_end(self.avatar, False, False, 0)
        self.general.pack_start(top, False, False, 0)
        self._row_n = 0

        def row(key, value, edit=None, tip=None, italic=False):
            k = Gtk.Label(label=key, xalign=0, valign=Gtk.Align.CENTER)
            k.get_style_context().add_class("dim-label")
            grid.attach(k, 0, self._row_n, 1, 1)
            box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            v = Gtk.Label(xalign=0, selectable=True, wrap=True, max_width_chars=70)
            text = GLib.markup_escape_text(value)
            v.set_markup(f"<i>{text}</i>" if italic else text)
            box.pack_start(v, False, False, 0)
            if edit is not None:
                b = Gtk.Button(image=Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.MENU),
                               relief=Gtk.ReliefStyle.NONE, tooltip_text=tip or f"Change {key.lower()}")
                b.get_style_context().add_class("flat")
                if callable(edit):
                    b.connect("clicked", lambda *_: edit())
                else:                                    # edit=False → shown but not allowed
                    b.set_sensitive(False)
                box.pack_start(b, False, False, 0)
            grid.attach(box, 1, self._row_n, 1, 1)
            self._row_n += 1

        uid = u.get("_id", "")
        dom = uid.split("/")[1] if uid.count("/") == 2 else ""
        row("Domain", dom or "Default", italic=not dom)
        row("User Identifier", uid)
        may_edit = u.get("siteadmin") != FULL or self._my_sa() == FULL
        email = u.get("email") or ""
        if si.get("emailcheck") and email:
            email += "  ✓ verified" if u.get("emailVerified") else "  ✗ not verified"
        email_is_name = bool(self._features() & 0x200000)
        if email_is_name:
            row("Email", email or "Not set", False, "This server uses the email address as the user name "
                "(the server ignores email changes)", italic=not email)
        else:
            row("Email", email or "Not set", self.edit_email if may_edit else None, italic=not email)
        row("Real Name", u.get("realname") or "Not set", self.edit_realname if may_edit else None,
            italic=not u.get("realname"))
        if self._features() & FEAT_SMS or u.get("phone") is not None:
            row("Phone Number", u.get("phone") or "None", self.edit_phone, italic=not u.get("phone"))
        ft = features_text(u, si)
        row("Features", ft, self.edit_features, italic=ft == "None")
        row("Server Rights", server_rights_text(u), self.edit_server_rights,
            "View or change server permissions")
        if u.get("quota"):
            row("Server Quota", "%d k" % (int(u["quota"]) // 1024))
        if u.get("creation"):
            row("Creation", ui.fmt_time(u["creation"] * 1000))
        if u.get("login"):
            row("Last Login", ui.fmt_time(u["login"] * 1000))
        if u.get("passchange") == -1:
            row("Password", "Will be changed on next login.")
        elif u.get("passchange"):
            row("Password", "Last changed: " + ui.fmt_time(u["passchange"] * 1000))
        links = u.get("links") or {}
        n = sum(1 for k in links if k.startswith("mesh/"))
        row("Device Groups", "None" if not n else ("1 group" if n == 1 else f"{n} groups"), italic=not n)
        sa = self._my_sa()
        if sa == FULL or sa & 2:
            realms = ", ".join(u.get("groups") or []) or "None"
            can = sa == FULL or (not self._me().get("groups") and not self._is_self() and u.get("siteadmin") != FULL)
            row("Admin Realms", realms, self.edit_realms if can else None, italic=realms == "None")
        ct = consent_text(u, si)
        row("User Consent", ct, self.edit_consent, italic=ct == "None")
        f2 = second_factors(u)
        if f2:
            row("Security", "2nd factor: " + ", ".join(f2))
        # buttons
        bb = Gtk.Box(spacing=6, margin_top=6)
        notes = Gtk.Button(label="Notes", tooltip_text="View notes about this user")
        notes.connect("clicked", lambda *_: self.notes())
        bb.pack_start(notes, False, False, 0)
        self.general.pack_start(bb, False, False, 0)
        # membership sections
        self._section_groups()
        self._section_usergroups()
        self._section_devices()
        # bottom actions
        bottom = Gtk.Box(spacing=6, margin_top=10)
        ua = self._user_admin()
        uid_short = uid.split("/")[-1]
        if ua and not (self._features() & FEAT_LDAP_SSPI) and not uid_short.startswith("~"):
            for label, cb in (("Change Password…", self.change_password), ("Previous Logins", self.previous_logins)):
                b = Gtk.Button(label=label)
                b.connect("clicked", lambda _b, f=cb: f())
                bottom.pack_start(b, False, False, 0)
        if ua and not self._is_self():
            d = Gtk.Button(label="Delete User…", tooltip_text="Remove this user")
            d.get_style_context().add_class("destructive-action")
            d.connect("clicked", lambda *_: self.delete_user())
            bottom.pack_end(d, False, False, 0)
        self.general.pack_start(bottom, False, False, 0)
        self.general.show_all()
        self._load_avatar()

    def _list_section(self, title, add_label, add_cb, rows, empty):
        """rows: list of (name, detail, edit_cb|None, remove_cb|None, tooltip)"""
        hdr = Gtk.Box(spacing=8)
        hdr.pack_start(_section_title(title), False, False, 0)
        if add_cb:
            b = Gtk.Button(label=add_label, image=Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU),
                           always_show_image=True, relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.END)
            b.connect("clicked", lambda *_: add_cb())
            hdr.pack_start(b, False, False, 0)
        self.general.pack_start(hdr, False, False, 0)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lb.get_style_context().add_class("frame")
        if not rows:
            l = Gtk.Label(xalign=0, margin=8)
            l.set_markup(f"<i>{GLib.markup_escape_text(empty)}</i>")
            lb.add(l)
        for name, detail, edit_cb, remove_cb, tip in rows:
            r = Gtk.Box(spacing=8, margin=4)
            n = Gtk.Label(label=name, xalign=0, width_chars=28, ellipsize=Pango.EllipsizeMode.END)
            r.pack_start(n, False, False, 4)
            dl = Gtk.Label(label=detail, xalign=0, ellipsize=Pango.EllipsizeMode.END, tooltip_text=detail)
            dl.get_style_context().add_class("dim-label")
            r.pack_start(dl, True, True, 0)
            if edit_cb:
                b = Gtk.Button(image=Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.MENU),
                               relief=Gtk.ReliefStyle.NONE, tooltip_text="Edit permissions")
                b.connect("clicked", lambda _b, f=edit_cb: f())
                r.pack_start(b, False, False, 0)
            if remove_cb:
                b = Gtk.Button(image=Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.MENU),
                               relief=Gtk.ReliefStyle.NONE, tooltip_text=tip)
                b.connect("clicked", lambda _b, f=remove_cb: f())
                r.pack_start(b, False, False, 0)
            lb.add(r)
        self.general.pack_start(lb, False, False, 0)

    def _meshes(self):
        return getattr(self.app, "meshes", None) or {}

    def _nodes(self):
        mw = getattr(self.app, "main_win", None)
        return getattr(mw, "nodes", None) or {}

    def _section_groups(self):
        u, meshes = self.user, self._meshes()
        links = u.get("links") or {}
        dom = u["_id"].split("/")[1]
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        rows = []
        for mid in sorted((m for m in links if m.startswith("mesh/") and m in meshes),
                          key=lambda m: (meshes[m].get("name") or "").lower()):
            r = links[mid].get("rights") or 0
            can = not self._is_self() and bool(rights.mesh_rights(self.ctrl, meshes[mid]) & 2)
            rows.append((meshes[mid].get("name") or mid, group_rights_text(r, guest),
                         (lambda m=mid: self.group_rights(m)) if can else None,
                         (lambda m=mid: self.remove_group(m)) if can else None,
                         "Remove user rights to this device group"))
        avail = [m for m in meshes if m.split("/")[1] == dom and m not in links]
        self._list_section("Common Device Groups", "Add Device Group", self.group_rights if avail else None,
                           rows, "No device groups in common")

    def _section_usergroups(self):
        ug = self.panel.usergroups
        if ug is None:
            return
        u = self.user
        links = u.get("links") or {}
        dom = u["_id"].split("/")[1]
        may = bool(self._my_sa() & 256)
        rows = []
        for gid in sorted((g for g in links if g.startswith("ugrp/") and g in ug),
                          key=lambda g: (ug[g].get("name") or "").lower()):
            g = ug[gid]
            rm = (lambda x=gid: self.remove_usergroup(x)) if may and g.get("membershipType") is None else None
            rows.append((g.get("name") or gid, g.get("desc") or "", None, rm, "Remove user group membership"))
        avail = [g for g, v in ug.items() if v.get("membershipType") is None and g.split("/")[1] == dom
                 and g not in links]
        self._list_section("User Group Memberships", "Add User Group",
                           self.add_usergroup if may and avail else None, rows, "No user group memberships")

    def _section_devices(self):
        u, nodes = self.user, self._nodes()
        links = u.get("links") or {}
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        rows = []
        for nid in sorted((n for n in links if n.startswith("node/") and n in nodes),
                          key=lambda n: (nodes[n].get("name") or "").lower()):
            r = links[nid].get("rights") or 0
            can = bool(rights.node_rights(self.ctrl, self._meshes(), nodes[nid]) & 2)
            rows.append((nodes[nid].get("name") or nid, device_rights_text(r, guest),
                         (lambda n=nid: self.device_rights(n)) if can else None,
                         (lambda n=nid: self.remove_device(n)) if can else None,
                         "Remove user rights to this device"))
        same_domain = u["_id"].split("/")[1] == (self._me().get("_id") or "//").split("/")[1]
        self._list_section("Common Devices", "Add Device", self.device_rights if same_domain else None,
                           rows, "No devices in common")

    def _load_avatar(self, size=96):
        self.avatar.set_from_icon_name("avatar-default-symbolic", Gtk.IconSize.DIALOG)
        self.avatar.set_pixel_size(size)
        u = self.user
        if not (u.get("flags") or 0) & 1:
            return
        key = (u["_id"], u.get("flags"))
        if self._avatar_for == key and getattr(self, "_avatar_pb", None) is not None:
            self.avatar.set_from_pixbuf(self._avatar_pb)
            return
        self._avatar_for = key
        fd, path = tempfile.mkstemp(suffix=".img")
        os.close(fd)

        def done(err):
            if not err:
                try:
                    self._avatar_pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
                    self.avatar.set_from_pixbuf(self._avatar_pb)
                except GLib.Error:
                    pass
            try:
                os.remove(path)
            except OSError:
                pass
        if self._web is None:
            self._web = WebSession(self.ctrl)
        short = u["_id"].split("/")[-1]
        self._web.fetch(f"/userimage.ashx?id={GLib.uri_escape_string(short, None, False)}&rnd={int(time.time())}",
                        path, None, done)

    # ---- edits --------------------------------------------------------------------------------
    def edit_email(self):
        si = self.ctrl.serverinfo or {}
        d, area, ok = _dialog(self._top(), f"Change Email for {self.user.get('name')}")
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        area.pack_start(grid, False, False, 0)
        e = Gtk.Entry(text=self.user.get("email") or "", hexpand=True, activates_default=True, max_length=256)
        grid.attach(Gtk.Label(label="Email", xalign=1), 0, 0, 1, 1)
        grid.attach(e, 1, 0, 1, 1)
        st = None
        if si.get("emailcheck"):
            st = Gtk.ComboBoxText()
            st.append_text("Not verified")
            st.append_text("Verified")
            st.set_active(1 if self.user.get("emailVerified") else 0)
            grid.attach(Gtk.Label(label="Status", xalign=1), 0, 1, 1, 1)
            grid.attach(st, 1, 1, 1, 1)

        def valid(*_):
            v = e.get_text()
            p = v.split("@")
            ok.set_sensitive(v == "" or (len(p) == 2 and p[0] and len(p[1].split(".")) > 1 and len(p[1]) > 2
                                         and len(v) < 1024))
        e.connect("changed", valid)
        valid()
        if _run(d):
            fields = {"email": e.get_text()}
            if st is not None:
                fields["emailVerified"] = st.get_active() == 1
            self._edituser("Changing the email", **fields)
        d.destroy()

    def _text_edit(self, title, label, value, field, validator=None, max_len=256):
        d, area, ok = _dialog(self._top(), title)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label=label), False, False, 0)
        e = Gtk.Entry(text=value or "", hexpand=True, activates_default=True, max_length=max_len)
        row.pack_start(e, True, True, 0)
        area.pack_start(row, False, False, 0)
        if validator:
            e.connect("changed", lambda *_: ok.set_sensitive(validator(e.get_text())))
            ok.set_sensitive(validator(e.get_text()))
        if _run(d):
            self._edituser(title, **{field: e.get_text()})
        d.destroy()

    def edit_realname(self):
        self._text_edit(f"Change Real Name for {self.user.get('name')}", "Real Name",
                        self.user.get("realname"), "realname")

    def edit_phone(self):
        self._text_edit(f"Change Phone Number for {self.user.get('name')}", "Phone Number",
                        self.user.get("phone"), "phone",
                        lambda v: v == "" or bool(re.match(r"^\+?[0-9 ()\-]{4,20}$", v)), 20)

    def edit_realms(self):
        d, area, ok = _dialog(self._top(), "Administrative Realms")
        area.pack_start(Gtk.Label(label="Enter a comma separated list of administrative realm names.",
                                  xalign=0, wrap=True), False, False, 0)
        e = Gtk.Entry(text=", ".join(self.user.get("groups") or []), placeholder_text="Name1, Name2, Name3",
                      activates_default=True, max_length=256)
        area.pack_start(e, False, False, 0)

        def valid(*_):
            v = e.get_text()
            ok.set_sensitive(v == "" or (not any(c in v for c in "\"/<>'") and
                                         all(x.strip() for x in v.split(","))))
        e.connect("changed", valid)
        valid()
        if _run(d):
            groups = [x.strip() for x in e.get_text().split(",") if x.strip()]
            self._edituser("Changing the realms", groups=groups)
        d.destroy()

    def edit_features(self):
        u, si = self.user, (self.ctrl.serverinfo or {})
        flags, rr = u.get("flags") or 0, u.get("removeRights") or 0
        d, area, _ok = _dialog(self._top(), "Edit User Features")
        rec = None
        if si.get("usersSessionRecording") == 1:
            rec = _check("Record sessions", flags & 2)
            area.pack_start(rec, False, False, 0)
        c = {}
        for bit, label, ind in ((0x8, "No Remote Control", 0), (0x10000, "No Desktop Access", 1),
                                (0x100, "Remote View Only", 2), (0x200, "No Terminal Access", 1),
                                (0x400, "No File Access", 1), (0x400000, "No Registry Access", 1),
                                (0x800000, "No Software", 1), (0x10, "No Agent Console", 0),
                                (0x8000, "No Uninstall", 0), (0x20000, "No Remote Command", 0),
                                (0x40, "No Wake", 0), (0x40000, "No Reset/Off", 0)):
            c[bit] = _check(label, rr & bit, ind)
            area.pack_start(c[bit], False, False, 0)

        def valid(*_):
            nrc = not c[0x8].get_active()
            for b in (0x10000, 0x200, 0x400, 0x400000, 0x800000):
                c[b].set_sensitive(nrc)
            c[0x100].set_sensitive(nrc and not c[0x10000].get_active())
        for w in c.values():
            w.connect("toggled", valid)
        valid()
        if _run(d):
            f = (flags & 1) | (2 if rec is not None and rec.get_active() else 0)
            r = 0
            if c[0x8].get_active():
                r |= 0x8
            else:
                if c[0x10000].get_active():
                    r |= 0x10000
                elif c[0x100].get_active():
                    r |= 0x100
                for b in (0x200, 0x400, 0x400000, 0x800000):
                    if c[b].get_active():
                        r |= b
            for b in (0x10, 0x8000, 0x20000, 0x40, 0x40000):
                if c[b].get_active():
                    r |= b
            self._edituser("Changing the features", flags=f, removeRights=r)
        d.destroy()

    def edit_consent(self):
        si_c = (self.ctrl.serverinfo or {}).get("consent") or 0
        cur = self.user.get("consent") or 0
        d, area, _ok = _dialog(self._top(), "Edit User Consent")
        c = {}
        for title, items in (("Desktop", ((0x1, "Notify user"), (0x8, "Prompt for user consent"),
                                          (0x40, "Show connection toolbar"))),
                             ("Terminal", ((0x2, "Notify user"), (0x10, "Prompt for user consent"))),
                             ("Files", ((0x4, "Notify user"), (0x20, "Prompt for user consent"))),
                             ("Registry", ((0x80, "Notify user"), (0x100, "Prompt for user consent")))):
            area.pack_start(_section_title(title), False, False, 0)
            for bit, label in items:
                w = _check(label, (cur | si_c) & bit)
                w.set_sensitive(not si_c & bit)          # forced by the server configuration
                c[bit] = w
                area.pack_start(w, False, False, 0)
        if _run(d):
            self._edituser("Changing the user consent",
                           consent=sum(b for b, w in c.items() if w.get_active()))
        d.destroy()

    def edit_server_rights(self):
        u, me = self.user, self._my_sa()
        uself, tsa = self._is_self(), u.get("siteadmin") if isinstance(u.get("siteadmin"), int) else 0
        d, area, ok = _dialog(self._top(), "Server Permissions")
        if uself:
            ok.hide()
            ok.set_no_show_all(True)
            d.get_widget_for_response(Gtk.ResponseType.CANCEL).set_label("Close")
        c = {}

        def add(bit, label, show=True):
            w = _check(label, tsa != FULL and bool(tsa & bit))
            c[bit] = w
            if show:
                area.pack_start(w, False, False, 0)
            return w
        quota = Gtk.Entry(width_chars=10, placeholder_text="default", input_purpose=Gtk.InputPurpose.DIGITS)
        if u.get("quota") is not None:
            quota.set_text(str(int(u["quota"]) // 1024))
        full = _check("Full Administrator", tsa == FULL)
        if me == FULL:
            files_row = Gtk.Box(spacing=6)
            files_row.pack_start(add(8, "Server Files", False), False, False, 0)
            files_row.pack_start(quota, False, False, 0)
            files_row.pack_start(Gtk.Label(label="k max, blank for default"), False, False, 0)
            area.pack_start(files_row, False, False, 0)
            area.pack_start(Gtk.Separator(), False, False, 4)
            area.pack_start(full, False, False, 0)
            add(1, "Server Backup")
            add(4, "Server Restore")
            add(16, "Server Updates")
        else:
            add(8, "Server Files", False)
            for b in (1, 4, 16):
                add(b, "", False)
        add(2, "Manage Users", bool(me & 2))
        add(256, "Manage User Groups", bool(me & 256))
        add(512, "Manage Recordings", bool(me & 512))
        add(2048, "View All Events")
        area.pack_start(Gtk.Separator(), False, False, 4)
        for bit, label in ((32, "Lock Account"), (64, "No New Device Groups"), (4096, "No New Devices"),
                           (128, "No Tools (MeshCmd/Router)"), (1024, "Lock Account Settings")):
            add(bit, label)
        base = {b: False for b in c}
        for b in (8, 1, 4, 16):
            base[b] = not uself and me == FULL
        for b, need in ((2, 2), (256, 256), (512, 512), (2048, 2048)):
            base[b] = not uself and bool(me & need)
        for b in (32, 64, 4096, 128, 1024):
            base[b] = not uself and bool(me & 2) and tsa != FULL
        full.set_sensitive(not uself and me == FULL)

        def valid(*_):
            fa = full.get_active()
            for b, w in c.items():
                w.set_sensitive(base[b] and (not fa or me != FULL))
            quota.set_sensitive(not uself and me == FULL and c[8].get_active() and not fa)
        full.connect("toggled", valid)
        c[8].connect("toggled", valid)
        valid()
        if _run(d) and not uself:
            if full.get_active():
                sa = FULL
            else:
                sa = sum(b for b, w in c.items() if w.get_active())
            fields = {"siteadmin": sa}
            q = quota.get_text().strip()
            if q.isdigit():
                fields["quota"] = int(q) * 1024
            self._edituser("Changing the server permissions", **fields)
        d.destroy()

    # ---- memberships --------------------------------------------------------------------------
    def group_rights(self, meshid=None):
        meshes, u = self._meshes(), self.user
        links = u.get("links") or {}
        dom = u["_id"].split("/")[1]
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        title = "Edit Device Group Permissions" if meshid else "Add Device Group Permissions"
        d, area, ok = _dialog(self._top(), title, width=460)
        combo = Gtk.ComboBoxText()
        ids = [meshid] if meshid else sorted((m for m in meshes if m.split("/")[1] == dom and m not in links),
                                             key=lambda m: (meshes[m].get("name") or "").lower())
        for m in ids:
            combo.append(m, meshes[m].get("name") or m)
        combo.set_active(0)
        combo.set_sensitive(meshid is None)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label="Device Group"), False, False, 0)
        row.pack_start(combo, True, True, 0)
        area.pack_start(row, False, False, 0)
        cur = (links.get(meshid) or {}).get("rights", 0) if meshid else 0
        rd = RightsDialog(area, True, guest, cur)
        ok.set_sensitive(bool(ids))
        if _run(d) and combo.get_active_id():
            mid = combo.get_active_id()
            self.ctrl.send({"action": "addmeshuser", "meshid": mid, "meshname": meshes[mid].get("name"),
                            "userids": [u["_id"]], "meshadmin": rd.value()}, self._reply(title))
        d.destroy()

    def remove_group(self, meshid):
        name = self._meshes().get(meshid, {}).get("name", meshid)
        if ui.confirm(self._top(), "Remove Device Group Permissions",
                      f"Confirm removal of access rights for device group “{name}”?", "Remove", True):
            self.ctrl.send({"action": "removemeshuser", "meshid": meshid, "userid": self.user["_id"]},
                           self._reply("Removing the device group permissions"))

    def device_rights(self, nodeid=None):
        meshes, nodes, u = self._meshes(), self._nodes(), self.user
        links = u.get("links") or {}
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        title = "Edit Device Permissions" if nodeid else "Add Device Permissions"
        d, area, ok = _dialog(self._top(), title, width=460)
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        area.pack_start(grid, False, False, 0)
        mcombo, ncombo = Gtk.ComboBoxText(hexpand=True), Gtk.ComboBoxText(hexpand=True)
        grid.attach(Gtk.Label(label="Device Group", xalign=1), 0, 0, 1, 1)
        grid.attach(mcombo, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Device", xalign=1), 0, 1, 1, 1)
        grid.attach(ncombo, 1, 1, 1, 1)
        sel_mesh = nodes[nodeid].get("meshid") if nodeid and nodeid in nodes else None
        for m in sorted(meshes, key=lambda m: (meshes[m].get("name") or "").lower()):
            if rights.mesh_rights(self.ctrl, meshes[m]) & 7 or m == sel_mesh:
                mcombo.append(m, meshes[m].get("name") or m)
        rd = RightsDialog(area, False, guest, 0)

        def fill_nodes(*_):
            ncombo.remove_all()
            mid = mcombo.get_active_id()
            for n in sorted((n for n, v in nodes.items() if v.get("meshid") == mid),
                            key=lambda n: (nodes[n].get("name") or "").lower()):
                ncombo.append(n, nodes[n].get("name") or n)
            if nodeid:
                ncombo.set_active_id(nodeid)
            else:
                ncombo.set_active(0)

        def node_changed(*_):
            nid = ncombo.get_active_id()
            rd.set_value((links.get(nid) or {}).get("rights", 0) if nid else 0)
            rd.set_enabled(bool(nid))
            ok.set_sensitive(bool(nid))
        mcombo.connect("changed", fill_nodes)
        ncombo.connect("changed", node_changed)
        if sel_mesh:
            mcombo.set_active_id(sel_mesh)
        else:
            mcombo.set_active(0)
        fill_nodes()
        node_changed()
        mcombo.set_sensitive(nodeid is None)
        ncombo.set_sensitive(nodeid is None)
        if _run(d) and ncombo.get_active_id():
            nid = ncombo.get_active_id()
            self.ctrl.send({"action": "adddeviceuser", "nodeid": nid, "nodename": nodes[nid].get("name"),
                            "userids": [u["_id"]], "rights": rd.value()}, self._reply(title))
        d.destroy()

    def remove_device(self, nodeid):
        node = self._nodes().get(nodeid, {})
        if ui.confirm(self._top(), "Remove Device Permissions",
                      f"Confirm removal of access rights for device “{node.get('name', nodeid)}”?", "Remove", True):
            self.ctrl.send({"action": "adddeviceuser", "nodeid": nodeid, "nodename": node.get("name"),
                            "userids": [self.user["_id"]], "rights": 0, "remove": True},
                           self._reply("Removing the device permissions"))

    def add_usergroup(self):
        ug, u = self.panel.usergroups or {}, self.user
        links, dom = u.get("links") or {}, u["_id"].split("/")[1]
        d, area, ok = _dialog(self._top(), "Add Membership")
        combo = Gtk.ComboBoxText(hexpand=True)
        for g in sorted((g for g, v in ug.items() if v.get("membershipType") is None and g.split("/")[1] == dom
                         and g not in links), key=lambda g: (ug[g].get("name") or "").lower()):
            combo.append(g, ug[g].get("name") or g)
        combo.set_active(0)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label="User Group"), False, False, 0)
        row.pack_start(combo, True, True, 0)
        area.pack_start(row, False, False, 0)
        if _run(d) and combo.get_active_id():
            self.ctrl.send({"action": "addusertousergroup", "ugrpid": combo.get_active_id(),
                            "usernames": [u["_id"].split("/")[2]]}, self._reply("Adding the membership"))
        d.destroy()

    def remove_usergroup(self, gid):
        name = (self.panel.usergroups or {}).get(gid, {}).get("name", gid)
        if ui.confirm(self._top(), "Remove User Group Membership",
                      f"Confirm membership removal of user group “{name}”?", "Remove", True):
            self.ctrl.send({"action": "removeuserfromusergroup", "ugrpid": gid, "userid": self.user["_id"]},
                           self._reply("Removing the membership"))

    # ---- actions ------------------------------------------------------------------------------
    def notes(self):
        from .general_actions import NotesDialog
        NotesDialog(self._top(), self.ctrl, {"_id": self.user["_id"], "name": self.user.get("name", "")},
                    editable=bool(self._my_sa() & 2), what="user")

    def previous_logins(self):
        show_previous_logins(self._top(), self.ctrl, self.user["_id"],
                             f"Previous logins - {self.user.get('name')}")

    def change_password(self):
        u = self.user
        mfa = bool(second_factors(u))
        d, area, ok = _dialog(self._top(), f"Change Password for {u.get('name')}")
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        area.pack_start(grid, False, False, 0)
        p1 = Gtk.Entry(visibility=False, hexpand=True, max_length=256, input_purpose=Gtk.InputPurpose.PASSWORD)
        p2 = Gtk.Entry(visibility=False, hexpand=True, max_length=256, activates_default=True,
                       input_purpose=Gtk.InputPurpose.PASSWORD)
        grid.attach(Gtk.Label(label="Password", xalign=1), 0, 0, 1, 1)
        grid.attach(p1, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Password", xalign=1), 0, 1, 1, 1)
        grid.attach(p2, 1, 1, 1, 1)
        hint = None
        if self._features() & FEAT_PASSWORD_HINT:
            hint = Gtk.Entry(hexpand=True, max_length=256)
            grid.attach(Gtk.Label(label="Password hint", xalign=1), 0, 2, 1, 1)
            grid.attach(hint, 1, 2, 1, 1)
        reset = _check("Force password reset on next login.", u.get("passchange") == -1)
        area.pack_start(reset, False, False, 0)
        rm2fa = _check("Remove all 2nd factor authentication.") if mfa else None
        if rm2fa:
            area.pack_start(rm2fa, False, False, 0)
        note = Gtk.Label(xalign=0, wrap=True, max_width_chars=50,
                         label="Leave both fields empty to only change the options below.")
        note.get_style_context().add_class("dim-label")
        area.pack_start(note, False, False, 0)
        ok.set_sensitive(True)
        p1.connect("changed", lambda *_: ok.set_sensitive(p1.get_text() == p2.get_text()))
        p2.connect("changed", lambda *_: ok.set_sensitive(p1.get_text() == p2.get_text()))
        if _run(d) and p1.get_text() == p2.get_text():
            msg = {"action": "changeuserpass", "userid": u["_id"], "pass": p1.get_text(),
                   "removeMultiFactor": bool(rm2fa and rm2fa.get_active()), "resetNextLogin": reset.get_active()}
            if hint is not None:
                msg["hint"] = hint.get_text()
            # The server never answers changeuserpass: success = an accountchange event for this user,
            # a password that fails the server's requirements is silently dropped.
            self._pw_wait = GLib.timeout_add_seconds(6, self._pw_timeout)
            self.ctrl.send(msg)
        d.destroy()

    def _pw_timeout(self):
        self._pw_wait = None
        ui.message(self._top(), "The server did not confirm the password change",
                   "The new password probably does not meet the server's password requirements.",
                   Gtk.MessageType.WARNING)
        return False

    def on_account_event(self, ev):
        """accountchange for this user (called by the Users panel)."""
        if self._pw_wait and ev.get("msgid") == 75:           # "Changed account credentials"
            GLib.source_remove(self._pw_wait)
            self._pw_wait = None
            ui.message(self._top(), "Password changed")

    def delete_user(self):
        name = self.user.get("name")
        if not ui.confirm(self._top(), f"Delete User {name}", f"Confirm deletion of user {name}?",
                          "Delete", True):
            return

        def done(msg):
            if msg.get("result") not in (None, "ok"):
                ui.message(self._top(), "Deleting the user failed", str(msg.get("result")), Gtk.MessageType.ERROR)
                return
            self.panel.close_user()
            self.panel.refresh_soon()
        self.ctrl.send({"action": "deleteuser", "userid": self.user["_id"], "username": name}, done)

    # ---- Events -------------------------------------------------------------------------------
    def _build_events(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=6, margin=8)
        self.ev_filter = Gtk.ComboBoxText()
        for label, _v in self.EVENT_FILTERS:
            self.ev_filter.append_text(label)
        self.ev_filter.set_active(0)
        self.ev_limit = Gtk.ComboBoxText()
        for label, _v in self.EVENT_LIMITS:
            self.ev_limit.append_text(label)
        self.ev_limit.set_active(0)
        refresh = Gtk.Button(label="Refresh", image=Gtk.Image.new_from_icon_name("view-refresh-symbolic",
                                                                                 Gtk.IconSize.BUTTON),
                             always_show_image=True)
        refresh.connect("clicked", lambda *_: self.load_events())
        self.ev_filter.connect("changed", lambda *_: self.load_events())
        self.ev_limit.connect("changed", lambda *_: self.load_events())
        bar.pack_start(refresh, False, False, 0)
        bar.pack_end(self.ev_limit, False, False, 0)
        bar.pack_end(self.ev_filter, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.ev_status = Gtk.Label(xalign=0, margin_start=10)
        self.ev_status.get_style_context().add_class("dim-label")
        box.pack_start(self.ev_status, False, False, 0)
        self.ev_store = Gtk.ListStore(str, str, str, str)
        tv = Gtk.TreeView(model=self.ev_store)
        for i, (t, ex) in enumerate((("Time", False), ("By", False), ("Action", False), ("Message", True))):
            tv.append_column(ui.text_column(t, i, ex))
        ui.row_tooltip(tv, 3)
        box.pack_start(ui.scrolled(tv), True, True, 0)
        return box

    def _maybe_load_events(self):
        if self.stack.get_visible_child_name() == "events" and not self._events_loaded:
            self.load_events()

    def load_events(self):
        self._events_loaded = True
        self.ev_status.set_text("Loading…")
        msg = {"action": "events", "userid": self.user["_id"]}
        lim = self.EVENT_LIMITS[self.ev_limit.get_active()][1]
        if lim:
            msg["limit"] = lim
        flt = self.EVENT_FILTERS[self.ev_filter.get_active()][1]
        if flt:
            msg["filter"] = flt
        self.ctrl.send(msg)

    def _on_events(self, msg):
        if msg.get("userid") != self.user.get("_id"):
            return                                   # server-wide or device events, not ours
        self.ev_store.clear()
        evs = msg.get("events") or []
        for e in evs:
            m = e.get("msg")
            self.ev_store.append([ui.fmt_time(e.get("time")), e.get("username", ""), e.get("action", ""),
                                  m if isinstance(m, str) else ""])
        self.ev_status.set_text("%d event(s)" % len(evs))

    def teardown(self):
        self.ctrl.off("events", self._on_events)
        if self._pw_wait:
            GLib.source_remove(self._pw_wait)
            self._pw_wait = None
