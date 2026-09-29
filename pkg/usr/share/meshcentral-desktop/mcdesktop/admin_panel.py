"""Server-wide admin panels: users, user groups, server events, my account.

These panels take node=None. They read from the control connection with the same
documented actions the MeshCentral web UI uses (users / usergroups / events) and
from the already-cached app.ctrl.userinfo / app.ctrl.serverinfo.
"""
from gi.repository import Gtk, GLib, Pango

from . import ui, rights

BROADCAST_MAX = 512          # server limit (meshuser.js validates 1..512 chars)


class BroadcastDialog(Gtk.Dialog):
    """Same as the web UI's "Broadcast Message": {action:'userbroadcast', msg, target, maxtime}.
    target = a user group id (only its connected members) or None (all connected users).
    Needs site right 2 (manage users). Note the server only delivers to users who share a user
    group with the sender when the sender is in any user group."""
    DURATIONS = [("Show message until dismissed by user", 0), ("Show for 10 seconds", 10),
                 ("Show for 1 minute", 60), ("Show for 5 minutes", 300)]

    def __init__(self, parent, ctrl, target=None, target_name=None):
        super().__init__(title="Broadcast Message", transient_for=parent, modal=True)
        self.ctrl, self.target = ctrl, target
        self.set_default_size(460, 320)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        who = f"all connected members of “{target_name}”" if target else "all connected users"
        box.pack_start(Gtk.Label(label=f"Broadcast a message to {who}.", xalign=0), False, False, 0)
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(8)
        self.view.set_top_margin(6)
        self.view.get_buffer().connect("changed", lambda *_: self._changed())
        scr = Gtk.ScrolledWindow(hexpand=True, vexpand=True, min_content_height=150)
        scr.add(self.view)
        frame = Gtk.Frame()
        frame.add(scr)
        box.pack_start(frame, True, True, 0)
        row = Gtk.Box(spacing=8)
        self.duration = Gtk.ComboBoxText()
        for label, _v in self.DURATIONS:
            self.duration.append_text(label)
        self.duration.set_active(0)
        row.pack_start(self.duration, True, True, 0)
        self.count = Gtk.Label()
        self.count.get_style_context().add_class("dim-label")
        row.pack_start(self.count, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.result = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.result, False, False, 0)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.send_btn = self.add_button("Send", Gtk.ResponseType.OK)
        self.send_btn.get_style_context().add_class("suggested-action")
        self.connect("response", self._on_response)
        self._changed()
        self.show_all()
        self.view.grab_focus()

    def _text(self):
        b = self.view.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()

    def _changed(self):
        n = len(self._text())
        self.count.set_text(f"{n}/{BROADCAST_MAX}")
        self.send_btn.set_sensitive(0 < n <= BROADCAST_MAX)

    def _on_response(self, _d, resp):
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        self.send_btn.set_sensitive(False)
        self.result.set_text("Sending…")
        maxtime = self.DURATIONS[self.duration.get_active()][1]
        msg = {"action": "userbroadcast", "msg": self._text(), "maxtime": maxtime}
        if self.target:
            msg["target"] = self.target

        def reply(r):
            if r.get("result") == "ok":
                self.destroy()
            else:
                self.result.set_markup(f"<span foreground='#e01b24'>{GLib.markup_escape_text(str(r.get('result')))}</span>")
                self.send_btn.set_sensitive(True)
        self.ctrl.send(msg, reply)


def _has_2fa(u):
    return bool(u.get("otphkeys") or u.get("otpkeys") or u.get("otpsecret") or u.get("otpdev"))


def _rights_summary(u):
    sa = u.get("siteadmin")
    if sa is None:
        return ""
    if sa == 0xFFFFFFFF or (isinstance(sa, int) and sa & 0xFFFFFFFF == 0xFFFFFFFF):
        return "Full administrator"
    if not sa:
        return "User"
    bits = {1: "Backup", 2: "Manage users", 4: "Restore", 8: "File upload", 16: "Update",
            32: "Locked", 64: "No new groups", 128: "No MeshCmd", 256: "User groups",
            512: "Recordings", 1024: "Locked settings", 2048: "Web relay", 4096: "SMS"}
    names = [v for k, v in bits.items() if isinstance(sa, int) and sa & k]
    return ", ".join(names) if names else "Admin (%s)" % sa


def _toolbar(refresh_cb):
    bar = Gtk.Box(spacing=6, margin=8)
    b = Gtk.Button(label="Refresh",
                   image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                   always_show_image=True)
    b.connect("clicked", lambda *_: refresh_cb())
    bar.pack_start(b, False, False, 0)
    return bar


def _make_tree(columns):
    """columns: list of (title, expand). Returns (treeview, liststore) with str columns."""
    store = Gtk.ListStore(*([str] * len(columns)))
    tv = Gtk.TreeView(model=store, enable_search=True)
    for i, (title, expand) in enumerate(columns):
        tv.append_column(ui.text_column(title, i, expand))
    # hovering a row shows the (possibly ellipsized) main text in full
    wide = [i for i, (_t, expand) in enumerate(columns) if expand]
    if wide:
        ui.row_tooltip(tv, wide[-1])
    return tv, store


class _TablePanel(Gtk.Box):
    """Base for a toolbar + status + table panel.

    Uses an ACTION *listener* rather than a responseid callback, because the server
    does not echo our responseid on these broadcast-style replies (users/usergroups/
    events), which previously left the panel stuck on "Loading…".
    """
    COLUMNS = []
    ACTION = None            # reply action to listen for
    NOREPLY_MSG = "No response from server."

    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._listening = False
        self.pack_start(_toolbar(self.refresh), False, False, 0)
        self.status = Gtk.Label(xalign=0, margin_start=10)
        self.status.get_style_context().add_class("dim-label")
        self.pack_start(self.status, False, False, 0)
        self.tree, self.store = _make_tree(self.COLUMNS)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)
        self.show_all()

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.refresh()

    def refresh(self):
        self.status.set_text("Loading…")
        self._replied = False
        if not self._listening and self.ACTION:
            self.app.ctrl.on(self.ACTION, self._on_reply)
            self._listening = True
        self.request()
        GLib.timeout_add(5000, self._check_timeout)

    def _on_reply(self, msg):
        self._replied = True
        try:
            self._fill(msg)
        except Exception as ex:
            self.status.set_text("Error: %s" % ex)

    def _check_timeout(self):
        if not self._replied:
            self.status.set_text(self.NOREPLY_MSG)
        return False

    def request(self):
        raise NotImplementedError

    def _fill(self, msg):
        raise NotImplementedError

    def teardown(self):
        if self._listening and self.ACTION:
            self.app.ctrl.off(self.ACTION, self._on_reply)
            self._listening = False


class UsersPanel(_TablePanel):
    COLUMNS = [("Name", True), ("User ID", False), ("Rights", True), ("2FA", False)]
    ACTION = "users"

    def __init__(self, app, node=None):
        super().__init__(app, node)
        bar = self.get_children()[0]
        b = Gtk.Button(label="Broadcast to all users",
                       image=Gtk.Image.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.BUTTON),
                       always_show_image=True)
        b.connect("clicked", lambda *_: BroadcastDialog(self.get_toplevel(), self.app.ctrl))
        b.set_sensitive(rights.has_site(app.ctrl, rights.SITE_MANAGEUSERS))
        bar.pack_end(b, False, False, 0)
        bar.show_all()

    def request(self):
        self.app.ctrl.send({"action": "users"})

    def _check_timeout(self):
        if not self._replied:
            sa = (self.app.ctrl.userinfo or {}).get("siteadmin") or 0
            # MESHRIGHT manage-users bit is 2; full admin is 0xFFFFFFFF.
            if isinstance(sa, int) and (sa == 0xFFFFFFFF or (sa & 2)):
                self.status.set_text("No response from server.")
            else:
                self.status.set_text("Your account does not have rights to list users "
                                     "(requires site user-management permission).")
        return False

    def _fill(self, msg):
        self.store.clear()
        userslist = msg.get("users") or []
        if isinstance(userslist, dict):
            userslist = list(userslist.values())
        for u in sorted(userslist, key=lambda x: (x.get("name") or "").lower()):
            self.store.append([u.get("name", ""), u.get("_id", ""),
                               _rights_summary(u), "Yes" if _has_2fa(u) else "No"])
        self.status.set_text("%d user(s)" % len(userslist))


class UserGroupsPanel(_TablePanel):
    COLUMNS = [("Name", True), ("Members", False), ("Device groups", False)]
    ACTION = "usergroups"

    def __init__(self, app, node=None):
        super().__init__(app, node)
        self.groups = {}
        self._ids = []
        # Re-layout: list on the left, details of the selected group on the right (like the
        # web UI's "User Group - <name>" page).
        scr = self.get_children()[-1]
        self.remove(scr)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=320)
        paned.pack1(scr, True, False)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        paned.pack2(ui.scrolled(self.details), True, False)
        self.pack_start(paned, True, True, 0)
        self.tree.get_selection().connect("changed", lambda *_: self._show_selected())
        self._placeholder()
        self.show_all()

    def request(self):
        self.app.ctrl.send({"action": "usergroups"})

    def _fill(self, msg):
        sel = self._selected_id()
        self.store.clear()
        groups = msg.get("ugroups") or {}
        if isinstance(groups, list):
            groups = {g.get("_id", str(i)): g for i, g in enumerate(groups)}
        self.groups = groups
        self._ids = []
        for gid, g in sorted(groups.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
            links = g.get("links") or {}
            members = sum(1 for k in links if str(k).startswith("user/"))
            meshes = sum(1 for k in links if str(k).startswith("mesh/"))
            self.store.append([g.get("name", ""), str(members), str(meshes)])
            self._ids.append(g.get("_id", gid))
        self.status.set_text("%d group(s)" % len(groups))
        if sel in self._ids:
            self.tree.get_selection().select_path(Gtk.TreePath(self._ids.index(sel)))
        elif self._ids:
            self.tree.get_selection().select_path(Gtk.TreePath(0))

    def _selected_id(self):
        model, it = self.tree.get_selection().get_selected()
        if not it:
            return None
        i = model.get_path(it).get_indices()[0]
        return self._ids[i] if i < len(self._ids) else None

    def _clear(self):
        for c in self.details.get_children():
            self.details.remove(c)

    def _placeholder(self):
        self._clear()
        l = Gtk.Label(label="Select a user group")
        l.get_style_context().add_class("dim-label")
        self.details.pack_start(l, True, True, 0)
        self.details.show_all()

    def _section(self, text):
        l = Gtk.Label(xalign=0, margin_top=10)
        l.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        self.details.pack_start(l, False, False, 0)

    def _show_selected(self):
        gid = self._selected_id()
        g = self.groups.get(gid) if gid else None
        if not g:
            self._placeholder()
            return
        self._clear()
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<span size='large' weight='bold'>User Group - {GLib.markup_escape_text(g.get('name', ''))}</span>")
        self.details.pack_start(title, False, False, 0)
        links = g.get("links") or {}
        users = [(k, v) for k, v in links.items() if str(k).startswith("user/")]
        meshes = [(k, v) for k, v in links.items() if str(k).startswith("mesh/")]
        grid = Gtk.Grid(row_spacing=4, column_spacing=16, margin_top=6)
        for i, (k, v) in enumerate((("Description", g.get("desc") or "None"), ("Users", len(users)),
                                     ("Device groups", len(meshes)), ("Group identifier", gid))):
            kl = Gtk.Label(label=k, xalign=0)
            kl.get_style_context().add_class("dim-label")
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(Gtk.Label(label=str(v), xalign=0, selectable=True, wrap=True,
                                  wrap_mode=Pango.WrapMode.CHAR), 1, i, 1, 1)
        self.details.pack_start(grid, False, False, 0)

        can = rights.has_site(self.app.ctrl, rights.SITE_MANAGEUSERS)
        b = Gtk.Button(label="Broadcast", halign=Gtk.Align.START, margin_top=8,
                       image=Gtk.Image.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.BUTTON),
                       always_show_image=True)
        b.set_sensitive(can and bool(users))
        b.set_tooltip_text("Send a message to all connected members of this group" if can
                           else "Requires the “manage users” permission")
        b.connect("clicked", lambda *_: BroadcastDialog(self.get_toplevel(), self.app.ctrl, gid, g.get("name")))
        self.details.pack_start(b, False, False, 0)

        self._section("Group members")
        for k, v in sorted(users, key=lambda kv: (kv[1].get("name") or kv[0]).lower()):
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Image.new_from_icon_name("avatar-default-symbolic", Gtk.IconSize.MENU), False, False, 0)
            row.pack_start(Gtk.Label(label=v.get("name") or k.split("/")[-1], xalign=0), False, False, 0)
            self.details.pack_start(row, False, False, 0)
        if not users:
            self.details.pack_start(Gtk.Label(label="No members", xalign=0), False, False, 0)

        self._section("Common device groups")
        meshes_known = getattr(self.app, "meshes", {}) or {}
        for k, v in sorted(meshes, key=lambda kv: (meshes_known.get(kv[0], {}).get("name") or kv[0]).lower()):
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Image.new_from_icon_name("network-workgroup-symbolic", Gtk.IconSize.MENU), False, False, 0)
            row.pack_start(Gtk.Label(label=meshes_known.get(k, {}).get("name") or k.split("/")[-1][:12] + "…",
                                     xalign=0), True, True, 0)
            r = v.get("rights") or 0
            rl = Gtk.Label(label="Full Rights" if r == rights.FULL else f"Partial rights ({r})")
            rl.get_style_context().add_class("dim-label")
            row.pack_start(rl, False, False, 0)
            self.details.pack_start(row, False, False, 0)
        if not meshes:
            self.details.pack_start(Gtk.Label(label="No device groups in common", xalign=0), False, False, 0)
        self.details.show_all()


class ServerEventsPanel(_TablePanel):
    COLUMNS = [("Time", False), ("User", False), ("Action", False), ("Message", True)]
    ACTION = "events"

    def request(self):
        self.app.ctrl.send({"action": "events", "limit": 300})

    def _fill(self, msg):
        self.store.clear()
        events = msg.get("events") or []
        for e in events:
            m = e.get("msg")
            self.store.append([ui.fmt_time(e.get("time")), e.get("username", ""),
                               e.get("action", ""), m if isinstance(m, str) else ""])
        self.status.set_text("%d event(s)" % len(events))


class AccountPanel(Gtk.Box):
    """My account + server info, rendered from cached userinfo / serverinfo."""

    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self.pack_start(_toolbar(self.refresh), False, False, 0)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self.pack_start(ui.scrolled(self.box), True, True, 0)
        self.show_all()

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.refresh()

    def _section(self, title):
        lbl = Gtk.Label(xalign=0, margin_top=6)
        lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
        self.box.pack_start(lbl, False, False, 0)

    def _kv(self, grid, row, key, val):
        k = Gtk.Label(label=str(key), xalign=1)
        k.get_style_context().add_class("dim-label")
        grid.attach(k, 0, row, 1, 1)
        v = Gtk.Label(label="" if val is None else str(val), xalign=0, selectable=True,
                      wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        grid.attach(v, 1, row, 1, 1)

    def _grid(self, pairs):
        grid = Gtk.Grid(row_spacing=4, column_spacing=16, margin_start=8)
        for i, (k, v) in enumerate(pairs):
            self._kv(grid, i, k, v)
        self.box.pack_start(grid, False, False, 0)

    def refresh(self):
        for c in self.box.get_children():
            self.box.remove(c)
        ui_info = self.app.ctrl.userinfo or {}
        srv = self.app.ctrl.serverinfo or {}

        self._section("My account")
        acct = [("Name", ui_info.get("name")),
                ("User ID", ui_info.get("_id")),
                ("Email", ui_info.get("email")),
                ("Email verified", ui_info.get("emailVerified")),
                ("Rights", _rights_summary(ui_info)),
                ("Two-factor", "Enabled" if _has_2fa(ui_info) else "Not enabled")]
        self._grid([(k, v) for k, v in acct if v not in (None, "")])

        self._section("Server")
        s = [("Server name", srv.get("name")),
             ("Version", srv.get("ver") or srv.get("serverversion")),
             ("Host", self.app.ctrl.server.host),
             ("Domain", srv.get("domain")),
             ("Agent count", srv.get("agentCount")),
             ("Time", ui.fmt_time(srv.get("serverTime")) if srv.get("serverTime") else None)]
        self._grid([(k, v) for k, v in s if v not in (None, "")])

        # Full dumps for anything not surfaced above.
        if ui_info:
            self._section("Account details (raw)")
            self.box.pack_start(ui.json_tree(ui_info), False, False, 0)
        if srv:
            self._section("Server details (raw)")
            self.box.pack_start(ui.json_tree(srv), False, False, 0)
        self.box.show_all()

    def teardown(self):
        pass
