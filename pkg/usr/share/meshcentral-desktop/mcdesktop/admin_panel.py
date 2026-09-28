"""Server-wide admin panels: users, user groups, server events, my account.

These panels take node=None. They read from the control connection with the same
documented actions the MeshCentral web UI uses (users / usergroups / events) and
from the already-cached app.ctrl.userinfo / app.ctrl.serverinfo.
"""
from gi.repository import Gtk, GLib, Pango

from . import ui


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
        r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        c = Gtk.TreeViewColumn(title, r, text=i)
        c.set_resizable(True)
        c.set_sort_column_id(i)
        if expand:
            c.set_expand(True)
        tv.append_column(c)
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
    COLUMNS = [("Name", True), ("Group ID", False), ("Members", False)]
    ACTION = "usergroups"

    def request(self):
        self.app.ctrl.send({"action": "usergroups"})

    def _fill(self, msg):
        self.store.clear()
        groups = msg.get("ugroups") or {}
        if isinstance(groups, list):
            groups = {g.get("_id", str(i)): g for i, g in enumerate(groups)}
        for gid, g in sorted(groups.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
            links = g.get("links") or {}
            members = sum(1 for k in links if str(k).startswith("user/"))
            self.store.append([g.get("name", ""), g.get("_id", gid), str(members)])
        self.status.set_text("%d group(s)" % len(groups))


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
