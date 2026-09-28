"""Main window: one window, device tree on the left, embedded panel tabs on the right."""
from gi.repository import Gtk, Gdk, GLib, Pango

from . import ui
from .client import PROTO_TERMINAL
from .general_actions import DeviceActions
from .info_panel import GeneralPanel, HardwarePanel, NetworkPanel, EventsPanel, NotesPanel
from .terminal_panel import TerminalPanel
from .files_panel import FilesPanel
from .desktop_panel import DesktopPanel
from .tools_panel import ProcessesPanel, ServicesPanel, ConsolePanel
from .admin_panel import UsersPanel, UserGroupsPanel, ServerEventsPanel, AccountPanel

POWER = {"wake": 100, "off": 2, "reset": 3, "sleep": 4}

# (label, class, online_only)
DEVICE_TABS = [
    ("General", GeneralPanel, False),
    ("Desktop", DesktopPanel, True),
    ("Terminal", TerminalPanel, True),
    ("Files", FilesPanel, True),
    ("Processes", ProcessesPanel, True),
    ("Services", ServicesPanel, True),
    ("Console", ConsolePanel, True),
    ("Hardware", HardwarePanel, False),
    ("Network", NetworkPanel, True),
    ("Events", EventsPanel, False),
    ("Notes", NotesPanel, False),
]
SERVER_TABS = [
    ("Users", UsersPanel),
    ("User Groups", UserGroupsPanel),
    ("Server Events", ServerEventsPanel),
    ("My Account", AccountPanel),
]


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
        self._device_tabs = []       # per-tab lazy state for the selected device
        self._server_panels = []
        self._open_node_id = None    # nodeid currently shown (guards selection re-fires)
        self._refresh_timer = None   # debounced device-refresh timer
        self._tree_sig = None        # signature of the last rendered device tree

        hb = Gtk.HeaderBar(show_close_button=True, title="Devices")
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

        self.paned = paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=340)
        self.add(paned)
        paned.pack1(self._build_sidebar(), False, False)
        paned.pack2(self._build_content(), True, False)

        self.ctrl.on("nodes", self._on_nodes)
        self.ctrl.on("meshes", self._on_meshes)
        self.ctrl.on("event", self._on_event)
        self.ctrl.on_close = self._on_disconnect
        self.connect("destroy", self._on_destroy)
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

        server_btn = Gtk.Button(label="  Server administration",
                                image=Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.BUTTON),
                                always_show_image=True)
        server_btn.set_relief(Gtk.ReliefStyle.NONE)
        server_btn.get_child().set_halign(Gtk.Align.START)
        server_btn.connect("clicked", lambda *_: self.show_server())
        box.pack_start(Gtk.Separator(), False, False, 0)
        box.pack_start(server_btn, False, False, 2)
        return box

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

        # Device view: action bar + notebook
        dev = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.action_bar = self.actions.build_bar()
        dev.pack_start(self.action_bar, False, False, 0)
        dev.pack_start(Gtk.Separator(), False, False, 0)
        self.device_notebook = Gtk.Notebook(scrollable=True)
        self.device_notebook.connect("switch-page", self._on_device_tab)
        dev.pack_start(self.device_notebook, True, True, 0)
        self.content.add_named(dev, "device")

        # Server view
        srv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        srv_hdr = Gtk.Box(spacing=8, margin=8)
        srv_hdr.pack_start(Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        srv_hdr.pack_start(Gtk.Label(label="Server administration", xalign=0), True, True, 0)
        back = Gtk.Button(label="Back to devices")
        back.connect("clicked", lambda *_: self.content.set_visible_child_name("empty"))
        srv_hdr.pack_end(back, False, False, 0)
        srv.pack_start(srv_hdr, False, False, 0)
        srv.pack_start(Gtk.Separator(), False, False, 0)
        self.server_notebook = Gtk.Notebook(scrollable=True)
        self.server_notebook.connect("switch-page", self._on_server_tab)
        srv.pack_start(self.server_notebook, True, True, 0)
        self.content.add_named(srv, "server")
        return self.content

    # ---- data --------------------------------------------------------------
    def load_devices(self):
        self.ctrl.send({"action": "meshes"})
        self.ctrl.send({"action": "nodes"})

    def _on_meshes(self, msg):
        for m in msg.get("meshes", []):
            self.meshes[m["_id"]] = m

    def _on_nodes(self, msg):
        self.nodes.clear()
        groups = {}
        for meshid, nodelist in (msg.get("nodes") or {}).items():
            for n in nodelist:
                n["meshid"] = meshid
                self.nodes[n["_id"]] = n
                groups.setdefault(meshid, []).append(n)
        self._rebuild_tree(groups)

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
        self.action_bar.hide()
        self.device_notebook.set_show_tabs(False)
        if hasattr(panel, "set_chrome_visible"):
            panel.set_chrome_visible(False)
        if not getattr(self, "_fs_key_handler", None):
            self._fs_key_handler = self.connect("key-press-event", self._fs_key_press)
        self.fullscreen()
        if hasattr(panel, "refit_soon"):
            panel.refit_soon()

    def _exit_desktop_fullscreen(self):
        self._desk_fs = False
        self.unfullscreen()
        sidebar = self.paned.get_child1()
        if sidebar is not None:
            sidebar.show()
        self.action_bar.show()
        self.device_notebook.set_show_tabs(True)
        panel = getattr(self, "_desk_fs_panel", None)
        if panel is not None and hasattr(panel, "set_chrome_visible"):
            panel.set_chrome_visible(True)
        if getattr(self, "_fs_key_handler", None):
            self.disconnect(self._fs_key_handler)
            self._fs_key_handler = None
        if panel is not None and hasattr(panel, "refit_soon"):
            panel.refit_soon()

    def _fs_key_press(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape and getattr(self, "_desk_fs", False):
            self._exit_desktop_fullscreen()
            return True
        return False

    def goto_device_tab(self, label):
        for i, tab in enumerate(self._device_tabs):
            if tab["label"] == label:
                self.device_notebook.set_current_page(i)
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
        nb = self.device_notebook
        while nb.get_n_pages():
            nb.remove_page(0)
        self._device_tabs = []
        online = ui.is_online(node)
        for label, cls, online_only in DEVICE_TABS:
            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            tab_label = Gtk.Label(label=label)
            if online_only and not online:
                tab_label.set_sensitive(False)
            nb.append_page(container, tab_label)
            self._device_tabs.append({"label": label, "cls": cls, "online_only": online_only,
                                      "container": container, "panel": None, "node": node})
        nb.show_all()
        self.actions.update(node)
        self.content.set_visible_child_name("device")
        nb.set_current_page(0)
        GLib.idle_add(self._ensure_tab, 0)

    def _ensure_tab(self, index):
        """Construct (once) and show the real panel for device tab `index`."""
        if index < 0 or index >= len(self._device_tabs):
            return False
        tab = self._device_tabs[index]
        if tab["panel"] is not None:      # already built (panel, "offline" or "error")
            return False
        node = tab["node"]
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

    def _on_device_tab(self, _nb, _page, index):
        self._ensure_tab(index)

    def _on_server_tab(self, _nb, page, _index):
        self._lazy_show(page)

    def _lazy_show(self, panel):
        if panel is None or getattr(panel, "_mcd_started", True):
            return
        panel._mcd_started = True
        if hasattr(panel, "on_shown"):
            try:
                panel.on_shown()
            except Exception as ex:
                print("panel on_shown error:", ex)

    def _teardown_device_panels(self):
        for tab in self._device_tabs:
            p = tab.get("panel")
            if p and not isinstance(p, str):
                try:
                    p.teardown()
                except Exception:
                    pass
        self._device_tabs = []

    # ---- server view -------------------------------------------------------
    def show_server(self):
        if not self._server_panels:
            for label, cls in SERVER_TABS:
                panel = cls(self.app, None)
                panel._mcd_started = False
                self._server_panels.append(panel)
                self.server_notebook.append_page(panel, Gtk.Label(label=label))
            self.server_notebook.show_all()
        self.content.set_visible_child_name("server")
        self.server_notebook.set_current_page(0)
        GLib.idle_add(lambda: self._lazy_show(self.server_notebook.get_nth_page(0)) or False)

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
    def _on_event(self, msg):
        action = msg.get("event", {}).get("action")
        if action in ("addnode", "removenode", "changenode", "nodeconnect", "meshchange"):
            # Coalesce bursts of events into a single refresh so the tree does not
            # rebuild (and jump) on every event.
            if self._refresh_timer:
                GLib.source_remove(self._refresh_timer)
            self._refresh_timer = GLib.timeout_add(1500, self._debounced_refresh)

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
        for p in self._server_panels:
            try:
                p.teardown()
            except Exception:
                pass

    def _app_menu(self):
        # Note: "Server administration" lives on the sidebar button, so it is NOT
        # repeated here (avoids the duplicate-menu look).
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
        a = Gtk.AboutDialog(transient_for=self, modal=True, program_name="MeshCentral Desktop",
                            version="2.7.5", comments="Native client for MeshCentral",
                            website=self.ctrl.server.url, logo_icon_name="meshcentral-desktop")
        a.run()
        a.destroy()
