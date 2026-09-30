"""Main window: one window, device tree on the left, embedded panel tabs on the right."""
import time

from gi.repository import Gtk, Gdk, GLib, Pango

from . import ui
from .client import PROTO_TERMINAL
from .general_actions import DeviceActions
from .info_panel import GeneralPanel, HardwarePanel, NetworkPanel, EventsPanel, NotesPanel
from .terminal_panel import TerminalPanel
from .files_panel import FilesPanel
from .desktop_panel import DesktopPanel
from .tools_panel import ProcessesPanel, ServicesPanel, ConsolePanel
from .admin_panel import UsersPanel, ServerEventsPanel
from .group_panel import UserGroupsPanel
from .account_panel import AccountPanel
from .server_files_panel import ServerFilesPanel
from .server_panel import MyServerPanel
from . import rights

POWER = {"wake": 100, "off": 2, "reset": 3, "sleep": 4}

# Device pages, grouped: (group id, group title, [(label, class, online_only, NodeCaps attribute)])
DEVICE_GROUPS = [
    ("overview", "Overview", [
        ("General", GeneralPanel, False, None),
        ("Hardware", HardwarePanel, False, None),
        ("Network", NetworkPanel, True, None),
        ("Events", EventsPanel, False, None),
        ("Notes", NotesPanel, False, None),
    ]),
    ("remote", "Remote", [
        ("Desktop", DesktopPanel, True, "desktop"),
        ("Terminal", TerminalPanel, True, "terminal"),
        ("Files", FilesPanel, True, "files"),
    ]),
    ("tools", "Tools", [
        ("Processes", ProcessesPanel, True, "tools"),
        ("Services", ServicesPanel, True, "tools"),
        ("Console", ConsolePanel, True, "console"),
    ]),
]
# flat list kept for callers/tests: (label, class, online_only, cap)
DEVICE_TABS = [t for _g, _t, tabs in DEVICE_GROUPS for t in tabs]


def _site_any(ctrl, *bits):
    sa = rights.site_rights(ctrl)
    return sa == rights.FULL or any(sa & b for b in bits)


# Navigation rail: (page id, icon, caption, visibility check(ctrl) or None, page class)
# Sections the account cannot use are hidden (the server enforces the rights anyway).
NAV = [
    ("devices", "computer-symbolic", "Devices", None, None),
    ("files", "folder-symbolic", "My Files",
     lambda c: rights.has_site(c, rights.SITE_FILEACCESS), ServerFilesPanel),
    ("server", "network-server-symbolic", "My Server",
     lambda c: _site_any(c, rights.SITE_BACKUP, rights.SITE_RESTORE, rights.SITE_UPDATE), MyServerPanel),
    ("users", "avatar-default-symbolic", "Users",
     lambda c: rights.has_site(c, rights.SITE_MANAGEUSERS), UsersPanel),
    ("usergroups", "system-users-symbolic", "Groups",
     lambda c: rights.has_site(c, rights.SITE_USERGROUPS), UserGroupsPanel),
    ("events", "document-open-recent-symbolic", "Events", None, ServerEventsPanel),
    ("account", "emblem-system-symbolic", "Account", None, AccountPanel),
]
_NAV_TITLES = {"devices": "Devices", "files": "My Files", "server": "My Server", "users": "Users",
               "usergroups": "User Groups", "events": "Server Events", "account": "My Account"}
_TAB_DENIED = {
    "desktop": "remote desktop", "terminal": "the terminal", "files": "file access",
    "tools": "device tools (processes and services)", "console": "the agent console",
}


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, ctrl):
        super().__init__(application=app, title="MeshCentral Desktop")
        self.app, self.ctrl = app, ctrl
        self.set_default_size(1280, 820)
        self.set_icon_name("meshcentral-desktop")
        self.meshes = {}
        self.nodes = {}
        self.current = None
        self.actions = DeviceActions(self)
        self._device_tabs = []       # per-tab lazy state for the selected device (flat list)
        self._group_nbs = {}         # device group id -> Gtk.Notebook of its pages
        self._building = False       # suppress lazy panel creation while tabs are (re)built
        self._pages = {}             # rail page id -> panel (built on first visit)
        self._nav_buttons = {}
        self._open_node_id = None    # nodeid currently shown (guards selection re-fires)
        self._refresh_timer = None   # debounced device-refresh timer
        self._tree_sig = None        # signature of the last rendered device tree

        self.headerbar = hb = Gtk.HeaderBar(show_close_button=True, title="Devices")
        from . import __version__
        hb.props.subtitle = f"{ctrl.username} @ {ctrl.server.host} · v{__version__}"
        self.set_titlebar(hb)
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_btn.set_tooltip_text("Refresh devices")
        self.refresh_btn.connect("clicked", lambda *_: self.load_devices())
        hb.pack_start(self.refresh_btn)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_btn.set_popover(self._app_menu())
        hb.pack_end(menu_btn)
        self.search = Gtk.SearchEntry(placeholder_text="Search devices")
        self.search.connect("search-changed", lambda *_: self.filter_devices())
        hb.pack_end(self.search)

        self.paned = paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=320)
        # Layout: navigation rail | page stack ("devices" = tree + device area; other pages are
        # built on first visit). Notification cards (user broadcasts, server notices) float
        # top-right above everything, including the fullscreen remote desktop.
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.pages.add_named(paned, "devices")
        body = Gtk.Box()
        self.rail = self._build_rail()
        body.pack_start(self.rail, False, False, 0)
        self.rail_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        body.pack_start(self.rail_sep, False, False, 0)
        body.pack_start(self.pages, True, True, 0)
        root = Gtk.Overlay()
        root.add(body)
        self.add(root)
        self.notify_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                  halign=Gtk.Align.END, valign=Gtk.Align.START, margin=14)
        root.add_overlay(self.notify_box)
        _install_notify_css()
        paned.pack1(self._build_sidebar(), False, False)
        paned.pack2(self._build_content(), True, False)

        self.ctrl.on("nodes", self._on_nodes)
        self.ctrl.on("meshes", self._on_meshes)
        self.ctrl.on("event", self._on_event)
        self.ctrl.on("msg", self._on_ctrl_msg)
        self.ctrl.on_close = self._on_disconnect
        self.connect("destroy", self._on_destroy)
        # Window-level shortcuts run BEFORE the focused WebView sees the key, so they work
        # even while the remote desktop has the keyboard. Ctrl+Alt+F toggles fullscreen
        # (like NoMachine); Esc is deliberately NOT used, it must reach the remote.
        self.connect("key-press-event", self._on_key)
        self.show_all()
        self.content.set_visible_child_name("empty")
        self.load_devices()

    # ---- sidebar -----------------------------------------------------------
    def _build_sidebar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # icon, name, subtitle-markup, nodeid, is_device
        self.store = Gtk.TreeStore(str, str, str, str, bool)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._filter_func)
        self.tree = Gtk.TreeView(model=self.filter, headers_visible=False)
        self.tree.get_selection().connect("changed", self._on_select)
        self.tree.connect("button-press-event", self._on_tree_click)
        col = Gtk.TreeViewColumn("Device")
        icon = Gtk.CellRendererPixbuf()
        icon.set_property("stock-size", Gtk.IconSize.LARGE_TOOLBAR)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(icon, False)
        col.pack_start(txt, True)
        col.add_attribute(icon, "icon-name", 0)
        col.set_cell_data_func(txt, self._name_cell)
        self.tree.append_column(col)
        box.pack_start(ui.scrolled(self.tree), True, True, 0)
        return box

    # ---- navigation rail ---------------------------------------------------
    def _build_rail(self):
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        rail.get_style_context().add_class("mcd-rail")
        group = None
        for pid, icon, caption, check, _cls in NAV:
            if check is not None and not check(self.ctrl):
                continue
            b = Gtk.RadioButton.new_from_widget(group)
            group = group or b
            b.set_mode(False)                              # looks like a toggle button
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("mcd-rail-btn")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
            inner.pack_start(img, False, False, 0)
            cap = Gtk.Label(label=caption)
            cap.get_style_context().add_class("mcd-rail-caption")
            inner.pack_start(cap, False, False, 0)
            b.add(inner)
            b.set_tooltip_text(_NAV_TITLES[pid])
            b.connect("toggled", lambda w, p=pid: w.get_active() and self.show_page(p))
            rail.pack_start(b, False, False, 0)
            self._nav_buttons[pid] = b
        return rail

    def show_page(self, pid):
        """Switch the main area to a rail page (building it on first visit)."""
        btn = self._nav_buttons.get(pid)
        if btn is None:
            return
        if not btn.get_active():
            btn.set_active(True)                          # re-enters via "toggled"
            return
        if pid != "devices" and pid not in self._pages:
            cls = next(c for p, _i, _t, _k, c in NAV if p == pid)
            try:
                panel = cls(self.app, None)
            except Exception as ex:
                print("page construct error:", pid, ex)
                panel = Gtk.Label(label=f"Could not open {_NAV_TITLES[pid]}:\n{ex}")
            self._pages[pid] = panel
            self.pages.add_named(panel, pid)
            panel.show_all()
            if hasattr(panel, "on_shown"):
                GLib.idle_add(lambda: (panel.on_shown(), False)[1])
        self.pages.set_visible_child_name(pid)
        self.headerbar.set_title(_NAV_TITLES[pid])
        on_devices = pid == "devices"
        self.search.set_visible(on_devices)
        self.refresh_btn.set_visible(on_devices)

    def _name_cell(self, _c, cell, model, it, _d):
        name, sub = model[it][1], model[it][2]
        if model[it][4]:
            cell.set_property("markup", f"{GLib.markup_escape_text(name)}\n<small>{sub}</small>")
        else:
            cell.set_property("markup", f"<b>{GLib.markup_escape_text(name)}</b>")

    def _filter_func(self, model, it, _d):
        q = self.search.get_text().lower().strip()
        if not q or not model[it][4]:
            return True
        return q in model[it][1].lower() or q in (model[it][2] or "").lower()

    def filter_devices(self):
        self.filter.refilter()
        self.tree.expand_all()

    # ---- content -----------------------------------------------------------
    def _build_content(self):
        self.content = Gtk.Stack()

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        img = Gtk.Image.new_from_icon_name("computer-symbolic", Gtk.IconSize.DIALOG)
        img.set_pixel_size(72)
        img.get_style_context().add_class("dim-label")
        empty.pack_start(img, False, False, 8)
        l = Gtk.Label(label="Select a device")
        l.get_style_context().add_class("dim-label")
        empty.pack_start(l, False, False, 0)
        self.content.add_named(empty, "empty")

        # Device view: action bar, group switcher (Overview / Remote / Tools), and one
        # notebook of sub-pages per group.
        dev = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.action_bar = self.actions.build_bar()
        dev.pack_start(self.action_bar, False, False, 0)
        self.group_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=100)
        for gid, title, _tabs in DEVICE_GROUPS:
            nb = Gtk.Notebook(scrollable=True, show_border=False)
            nb.connect("switch-page", lambda _nb, _pg, idx, g=gid: self._on_group_page(g, idx))
            self._group_nbs[gid] = nb
            self.group_stack.add_titled(nb, gid, title)
        self.group_stack.connect("notify::visible-child", lambda *_: self._on_group_changed())
        self.group_bar = Gtk.Box(margin_start=8, margin_end=8, margin_bottom=4)
        switcher = Gtk.StackSwitcher(stack=self.group_stack, halign=Gtk.Align.START)
        self.group_bar.pack_start(switcher, False, False, 0)
        dev.pack_start(self.group_bar, False, False, 0)
        dev.pack_start(self.group_stack, True, True, 0)
        self.content.add_named(dev, "device")
        return self.content

    # ---- data --------------------------------------------------------------
    def load_devices(self):
        self.ctrl.send({"action": "meshes"})
        self.ctrl.send({"action": "nodes"})

    def _on_meshes(self, msg):
        # the reply is the full list: replace IN PLACE (app.meshes and the panels share this dict),
        # so deleted groups disappear too
        fresh = {m["_id"]: m for m in msg.get("meshes", []) if m.get("_id")}
        self.meshes.clear()
        self.meshes.update(fresh)

    def _on_nodes(self, msg):
        self.nodes.clear()
        groups = {}
        for meshid, nodelist in (msg.get("nodes") or {}).items():
            for n in nodelist:
                n["meshid"] = meshid
                self.nodes[n["_id"]] = n
                groups.setdefault(meshid, []).append(n)
        self._rebuild_tree(groups)
        self._notify_panels()

    def _notify_panels(self):
        """Hand the fresh node dict to the open device's panels (e.g. agent went offline or
        came back after an update/restart), so they can react instead of looking frozen."""
        if not self._open_node_id:
            return
        node = self.nodes.get(self._open_node_id)
        if node is not None:
            self._last_open_node = node
        else:
            # Some servers drop a disconnected agent from the nodes list entirely (seen on
            # the rig while the agent restarts), treat "missing" as "offline".
            last = getattr(self, "_last_open_node", None)
            if not last or last.get("_id") != self._open_node_id:
                last = self.current
            if not last or last.get("_id") != self._open_node_id:
                return
            node = dict(last, conn=0)
        for tab in self._device_tabs:
            p = tab.get("panel")
            if p is not None and not isinstance(p, str) and hasattr(p, "on_node_update"):
                try:
                    p.on_node_update(node)
                except Exception as ex:
                    print("on_node_update error:", tab["label"], ex)

    def _tree_signature(self, groups):
        sig = []
        for meshid in sorted(groups):
            row = [self.meshes.get(meshid, {}).get("name", "")]
            for n in groups[meshid]:
                row.append((n["_id"], n.get("name"), ui.is_online(n), n.get("ip")))
            sig.append((meshid, tuple(sorted(row[1:])), row[0]))
        return tuple(sig)

    def _rebuild_tree(self, groups):
        # Skip the (visible) rebuild entirely when nothing that shows in the tree
        # changed, this is what stops the list jumping/scrolling on every event.
        sig = self._tree_signature(groups)
        if sig == self._tree_sig:
            if self._open_node_id and self._open_node_id in self.nodes:
                self.current = self.nodes[self._open_node_id]
            return
        self._tree_sig = sig

        # Preserve scroll position and highlighted row across the rebuild.
        vadj = self.tree.get_vadjustment()
        scroll_val = vadj.get_value() if vadj else 0
        sel = self.tree.get_selection()
        sel.handler_block_by_func(self._on_select)
        self.store.clear()
        for meshid, nodelist in sorted(groups.items(),
                                       key=lambda kv: (self.meshes.get(kv[0], {}).get("name") or "").lower()):
            mesh = self.meshes.get(meshid, {})
            online = sum(1 for n in nodelist if ui.is_online(n))
            parent = self.store.append(None, ["", mesh.get("name", "Group"),
                                              f"{online}/{len(nodelist)} online", "", False])
            for n in sorted(nodelist, key=lambda x: (not ui.is_online(x), (x.get("name") or "").lower())):
                self.store.append(parent, [self._node_icon(n), n.get("name", "?"),
                                           self._node_sub(n), n["_id"], True])
        self.tree.expand_all()
        # Re-highlight the open device silently (no scroll_to_cell -> no jump).
        if self._open_node_id:
            self._reselect_silent(self._open_node_id)
            if self._open_node_id in self.nodes:
                self.current = self.nodes[self._open_node_id]
        sel.handler_unblock_by_func(self._on_select)
        if vadj:
            GLib.idle_add(lambda: (vadj.set_value(scroll_val), False)[1])

    def _reselect_silent(self, nodeid):
        def walk(model, path, it):
            if model[it][3] == nodeid:
                self.tree.get_selection().select_path(path)
                return True
            return False
        self.filter.foreach(walk)

    def _node_icon(self, n):
        return "computer-symbolic" if ui.is_online(n) else "network-offline-symbolic"

    def _node_sub(self, n):
        parts = [p for p in (ui.node_os(n), "Online" if ui.is_online(n) else "Offline", n.get("ip")) if p]
        sub = " · ".join(GLib.markup_escape_text(p) for p in parts)
        color = "#2ecc71" if ui.is_online(n) else "#e74c3c"
        return f"<span foreground='{color}'>●</span> {sub}"

    def group_name(self, node):
        return self.meshes.get(node.get("meshid"), {}).get("name", "")

    # ---- true remote-desktop fullscreen ------------------------------------
    def toggle_desktop_fullscreen(self, panel):
        active = getattr(self, "_desk_fs", False)
        if active:
            self._exit_desktop_fullscreen()
        else:
            self._enter_desktop_fullscreen(panel)

    def _enter_desktop_fullscreen(self, panel):
        self._desk_fs = True
        self._desk_fs_panel = panel
        # Hide the app chrome so ONLY the remote screen fills the display.
        sidebar = self.paned.get_child1()
        if sidebar is not None:
            sidebar.hide()
        for w in (self.rail, self.rail_sep, self.action_bar, self.group_bar):
            w.hide()
        self._group_nbs["remote"].set_show_tabs(False)
        if hasattr(panel, "set_chrome_visible"):
            panel.set_chrome_visible(False)
        self.fullscreen()
        if hasattr(panel, "show_hint"):
            panel.show_hint("Press Ctrl+Alt+F to exit fullscreen")
        if hasattr(panel, "refit_soon"):
            panel.refit_soon()

    def _exit_desktop_fullscreen(self):
        self._desk_fs = False
        self.unfullscreen()
        sidebar = self.paned.get_child1()
        if sidebar is not None:
            sidebar.show()
        for w in (self.rail, self.rail_sep, self.action_bar, self.group_bar):
            w.show()
        self._group_nbs["remote"].set_show_tabs(True)
        panel = getattr(self, "_desk_fs_panel", None)
        if panel is not None and hasattr(panel, "set_chrome_visible"):
            panel.set_chrome_visible(True)
        if panel is not None and hasattr(panel, "refit_soon"):
            panel.refit_soon()

    def _on_key(self, _w, ev):
        mods = ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK |
                           Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.SUPER_MASK)
        if mods == (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK) and \
                Gdk.keyval_to_lower(ev.keyval) == Gdk.KEY_f:
            if getattr(self, "_desk_fs", False):
                self._exit_desktop_fullscreen()
                return True
            panel = self._current_desktop_panel()
            if panel is not None and getattr(panel, "_connected", False):
                self._enter_desktop_fullscreen(panel)
                return True
        return False

    def _current_tab(self):
        """The flat _device_tabs entry currently on screen, or None."""
        if self.pages.get_visible_child_name() != "devices" or self.content.get_visible_child_name() != "device":
            return None
        gid = self.group_stack.get_visible_child_name()
        page = self._group_nbs[gid].get_current_page()
        return next((t for t in self._device_tabs if t["group"] == gid and t["page"] == page), None)

    def _current_desktop_panel(self):
        tab = self._current_tab()
        if tab and tab["label"] == "Desktop" and not isinstance(tab["panel"], str):
            return tab["panel"]
        return None

    def goto_device_tab(self, label):
        for tab in self._device_tabs:
            if tab["label"] == label:
                self.show_page("devices")
                self.group_stack.set_visible_child_name(tab["group"])
                self._group_nbs[tab["group"]].set_current_page(tab["page"])
                self._ensure_tab(self._device_tabs.index(tab))
                return

    # ---- selection ---------------------------------------------------------
    def _on_select(self, selection):
        model, it = selection.get_selected()
        if not it or not model[it][4]:
            return
        nodeid = model[it][3]
        # Ignore re-fires for the device that is already open (e.g. on window
        # hide/show, or after a background tree rebuild).
        if nodeid == self._open_node_id:
            return
        node = self.nodes.get(nodeid)
        if not node:
            return
        self._open_node_id = nodeid
        self.current = node
        self._open_device(node)

    def _open_device(self, node):
        # Tear down the previous device's panels, then build the new tab strip
        # with EMPTY containers. Each real panel is constructed lazily the first
        # time its tab is shown (see _ensure_tab) so selecting a device is cheap.
        self._teardown_device_panels()
        self._building = True
        for nb in self._group_nbs.values():
            while nb.get_n_pages():
                nb.remove_page(0)
        self._device_tabs = []
        online = ui.is_online(node)
        caps = rights.node_caps(self.ctrl, self.meshes, node)
        for gid, _title, tabs in DEVICE_GROUPS:
            nb = self._group_nbs[gid]
            for page, (label, cls, online_only, cap) in enumerate(tabs):
                container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                tab_label = Gtk.Label(label=label)
                allowed = cap is None or getattr(caps, cap)
                if (online_only and not online) or not allowed:
                    tab_label.set_sensitive(False)
                if not allowed:
                    tab_label.set_tooltip_text("Your account does not have permission for this")
                nb.append_page(container, tab_label)
                self._device_tabs.append({"label": label, "cls": cls, "online_only": online_only,
                                          "container": container, "panel": None, "node": node,
                                          "allowed": allowed, "cap": cap, "group": gid, "page": page})
            nb.show_all()
            nb.set_current_page(0)
        self._building = False
        self.actions.update(node)
        self.content.set_visible_child_name("device")
        self.group_stack.set_visible_child_name("overview")
        GLib.idle_add(self._ensure_tab, 0)

    def _on_group_page(self, gid, page):
        # Only build panels that are actually on screen (the hidden Remote group must NOT
        # construct, and auto-connect, the Desktop just because its notebook got a page).
        if self._building or self.group_stack.get_visible_child_name() != gid:
            return
        for i, t in enumerate(self._device_tabs):
            if t["group"] == gid and t["page"] == page:
                self._ensure_tab(i)
                return

    def _on_group_changed(self):
        if self._building or not self._device_tabs:
            return
        gid = self.group_stack.get_visible_child_name()
        self._on_group_page(gid, self._group_nbs[gid].get_current_page())

    def _ensure_tab(self, index):
        """Construct (once) and show the real panel for device tab `index`."""
        if index < 0 or index >= len(self._device_tabs):
            return False
        tab = self._device_tabs[index]
        if tab["panel"] is not None:      # already built (panel, "offline" or "error")
            return False
        node = tab["node"]
        if not tab.get("allowed", True):
            what = _TAB_DENIED.get(tab.get("cap"), "this")
            msg = Gtk.Label(label=f"Your account does not have permission to use {what} on this device.\n"
                                  "An administrator can change this in the device group's permissions.",
                            justify=Gtk.Justification.CENTER)
            msg.get_style_context().add_class("dim-label")
            tab["container"].pack_start(msg, True, True, 0)
            tab["container"].show_all()
            tab["panel"] = "denied"
            return False
        if tab["online_only"] and not ui.is_online(node):
            msg = Gtk.Label(label="This device is offline.")
            msg.get_style_context().add_class("dim-label")
            tab["container"].pack_start(msg, True, True, 0)
            tab["container"].show_all()
            tab["panel"] = "offline"
            return False
        try:
            panel = tab["cls"](self.app, node)
        except Exception as ex:
            print("panel construct error:", tab["label"], ex)
            err = Gtk.Label(label=f"Could not open {tab['label']}:\n{ex}")
            err.set_line_wrap(True)
            tab["container"].pack_start(err, True, True, 0)
            tab["container"].show_all()
            tab["panel"] = "error"
            return False
        tab["panel"] = panel
        tab["container"].pack_start(panel, True, True, 0)
        tab["container"].show_all()
        if hasattr(panel, "on_shown"):
            try:
                panel.on_shown()
            except Exception as ex:
                print("panel on_shown error:", tab["label"], ex)
        return False

    def _teardown_device_panels(self):
        for tab in self._device_tabs:
            p = tab.get("panel")
            if p and not isinstance(p, str):
                try:
                    p.teardown()
                except Exception:
                    pass
        self._device_tabs = []

    # ---- context menu ------------------------------------------------------
    def _on_tree_click(self, tree, event):
        if event.button == 3:
            path = tree.get_path_at_pos(int(event.x), int(event.y))
            if path:
                tree.get_selection().select_path(path[0])
                if self.current:
                    self.actions.context_menu(event, self.current)
                return True
        return False

    # ---- events / lifecycle ------------------------------------------------
    # ---- notifications (user broadcasts / server notices) ----------------------
    # Broadcast: {action:'msg', type:'notify', value, title:<sender>, tag:'broadcast', maxtime:<s>}
    # (from the web UI's User Group "Broadcast" or from this app). Some server notices come as
    # {action:'event', event:{action:'notify', value, title, tag}} instead.
    _MAX_CARDS = 5
    _MSGIDS = {1: "Permission denied", 14: "Email sent.", 10: "Account limit reached."}

    def _on_ctrl_msg(self, msg):
        if msg.get("type") == "notify":
            self.show_notification(msg.get("title"), msg.get("value"), msg.get("maxtime"), msg.get("tag"),
                                   msg.get("msgid"))

    def show_notification(self, title, text, maxtime=None, tag=None, msgid=None):
        text = text if isinstance(text, str) and text else self._MSGIDS.get(msgid, "")
        if not text:
            return
        broadcast = tag == "broadcast"
        head = f"Broadcast from {title}" if broadcast and title else (title or "MeshCentral")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=360)
        card.get_style_context().add_class("mcd-notify")
        if broadcast:
            card.get_style_context().add_class("mcd-broadcast")
        top = Gtk.Box(spacing=8)
        icon = Gtk.Image.new_from_icon_name("mail-unread-symbolic" if broadcast else "dialog-information-symbolic",
                                            Gtk.IconSize.MENU)
        top.pack_start(icon, False, False, 0)
        t = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        t.set_markup(f"<b>{GLib.markup_escape_text(head)}</b>")
        top.pack_start(t, True, True, 0)
        when = Gtk.Label(label=time.strftime("%H:%M"))
        when.get_style_context().add_class("dim-label")
        top.pack_start(when, False, False, 0)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Dismiss")
        top.pack_start(close, False, False, 0)
        card.pack_start(top, False, False, 0)
        body = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True, max_width_chars=48,
                         wrap_mode=Pango.WrapMode.WORD_CHAR)
        card.pack_start(body, False, False, 0)

        timer = [None]

        def dismiss(*_):
            if timer[0]:
                GLib.source_remove(timer[0])
                timer[0] = None
            if card.get_parent():
                self.notify_box.remove(card)
            return False
        close.connect("clicked", dismiss)
        if isinstance(maxtime, (int, float)) and maxtime > 0:
            timer[0] = GLib.timeout_add_seconds(int(maxtime), dismiss)
        kids = self.notify_box.get_children()
        if len(kids) >= self._MAX_CARDS:
            self.notify_box.remove(kids[0])
        self.notify_box.pack_start(card, False, False, 0)
        card.show_all()
        if not self.is_active() and self.app.config.get("notify", {}).get("desktop", True):
            self.app.notify(head, text)

    def _on_event(self, msg):
        action = msg.get("event", {}).get("action")
        if action == "notify":
            ev = msg.get("event") or {}
            self.show_notification(ev.get("title"), ev.get("value"), msg.get("maxtime"), ev.get("tag"),
                                   msg.get("msgid"))
            return
        if action == "nodeconnect":
            self._notify_connection(msg.get("event") or {})
        if action in ("addnode", "removenode", "changenode", "nodeconnect", "meshchange", "createmesh",
                      "deletemesh"):
            # Coalesce bursts of events into a single refresh so the tree does not
            # rebuild (and jump) on every event.
            if self._refresh_timer:
                GLib.source_remove(self._refresh_timer)
            self._refresh_timer = GLib.timeout_add(1500, self._debounced_refresh)

    def _notify_connection(self, ev):
        """My Account -> Notification settings: cards for device connections / disconnections."""
        prefs = self.app.config.get("notify", {})
        node = self.nodes.get(ev.get("nodeid"))
        if node is None or "conn" not in ev:
            return
        was, now = ui.is_online(node), bool((ev.get("conn") or 0) & 1)
        if was == now or not prefs.get("connect" if now else "disconnect", False):
            return
        name = node.get("name") or "Device"
        group = self.group_name(node) if prefs.get("groupname", True) else ""
        if group:
            name += f" ({group})"
        self.show_notification(name, "Device connected" if now else "Device disconnected", 10)
        if prefs.get("sound"):
            Gdk.Display.get_default().beep()

    def _debounced_refresh(self):
        self._refresh_timer = None
        self.load_devices()
        return False

    def _on_disconnect(self, reason):
        ui.message(self, "Disconnected", "The connection to the server was lost.", Gtk.MessageType.WARNING)
        self.app.sign_out()

    def _on_destroy(self, *_):
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)
            self._refresh_timer = None
        self._teardown_device_panels()
        for p in self._pages.values():
            try:
                p.teardown()
            except Exception:
                pass

    def _app_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
        for label, cb in (("Sign out", lambda *_: self.app.sign_out()),
                          ("About", self._about)):
            b = Gtk.ModelButton(text=label)
            b.connect("clicked", cb)
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    def _about(self, *_):
        from . import __version__
        a = Gtk.AboutDialog(transient_for=self, modal=True, program_name="MeshCentral Desktop",
                            version=__version__, comments="Native client for MeshCentral",
                            website=self.ctrl.server.url, logo_icon_name="meshcentral-desktop")
        a.run()
        a.destroy()


_NOTIFY_CSS = b"""
.mcd-notify { background-color: rgba(34, 37, 43, 0.97); color: #eceef1; border-radius: 10px;
              padding: 10px 12px; border: 1px solid rgba(255, 255, 255, 0.08);
              box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45); }
.mcd-notify.mcd-broadcast { border-left: 4px solid #e5a50a; }
.mcd-rail { padding: 6px 4px; background-color: alpha(@theme_fg_color, 0.04); }
.mcd-rail-btn { padding: 6px 2px; min-width: 64px; border-radius: 8px; }
.mcd-rail-btn:checked { background-color: alpha(@theme_selected_bg_color, 0.35); }
.mcd-rail-caption { font-size: 8pt; }
.mcd-link { color: @theme_selected_bg_color; padding: 1px 4px; }
.mcd-link:hover { background: alpha(@theme_selected_bg_color, 0.12); }
"""
_notify_css_done = False


def _install_notify_css():
    global _notify_css_done
    if _notify_css_done:
        return
    prov = Gtk.CssProvider()
    prov.load_from_data(_NOTIFY_CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _notify_css_done = True
