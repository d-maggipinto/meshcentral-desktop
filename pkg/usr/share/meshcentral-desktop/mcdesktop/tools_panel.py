"""Embeddable device-tool panels: Processes, Services and Agent Console.

Each panel talks to the agent over the control channel using the "msg" envelope
(ps / pskill / services / serviceStart|Stop|Restart / console), exactly like the
MeshCentral web UI's device tools.
"""
import json

from gi.repository import Gtk, GLib, Pango

from . import ui


class _MsgPanel(Gtk.Box):
    """Common plumbing for panels that listen on the 'msg' action for one node."""

    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self.nodeid = node["_id"] if node else None
        self._started = False
        self._listening = False

    def _listen(self):
        if not self._listening:
            self.app.ctrl.on("msg", self._on_msg)
            self._listening = True

    def _on_msg(self, message):
        if message.get("nodeid") not in (None, self.nodeid):
            return
        self._handle_msg(message)

    # subclasses override
    def _handle_msg(self, message):
        pass

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self._listen()
        self._first_load()

    def _first_load(self):
        pass

    def teardown(self):
        if self._listening:
            self.app.ctrl.off("msg", self._on_msg)
            self._listening = False


class ProcessesPanel(_MsgPanel):
    def __init__(self, app, node):
        super().__init__(app, node)

        bar = Gtk.Box(spacing=6, margin=8)
        refresh = Gtk.Button(label="Refresh",
                             image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                             always_show_image=True)
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.pack_start(refresh, False, False, 0)
        self.kill_btn = Gtk.Button(label="Kill process",
                                   image=Gtk.Image.new_from_icon_name("process-stop-symbolic", Gtk.IconSize.BUTTON),
                                   always_show_image=True)
        self.kill_btn.get_style_context().add_class("destructive-action")
        self.kill_btn.connect("clicked", lambda *_: self.kill_selected())
        bar.pack_start(self.kill_btn, False, False, 0)
        self.count = Gtk.Label(xalign=1)
        self.count.get_style_context().add_class("dim-label")
        bar.pack_end(self.count, False, False, 0)
        self.pack_start(bar, False, False, 0)

        # pid (int, for sort), pid_str, user, command
        self.store = Gtk.ListStore(int, str, str, str)
        self.tree = Gtk.TreeView(model=self.store, enable_search=True, search_column=3)
        for title, col, expand in (("PID", 1, False), ("User", 2, False), ("Command", 3, True)):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, r, text=col)
            c.set_resizable(True)
            c.set_sort_column_id(0 if col == 1 else col)
            if expand:
                c.set_expand(True)
            self.tree.append_column(c)
        self.tree.connect("row-activated", lambda *_: self.kill_selected())
        self.pack_start(ui.scrolled(self.tree), True, True, 0)

    def _first_load(self):
        self.refresh()

    def refresh(self):
        self.count.set_text("Loading…")
        self.app.ctrl.send_node_msg(self.nodeid, "ps")

    def _handle_msg(self, message):
        if message.get("type") != "ps":
            return
        try:
            procs = json.loads(message.get("value") or "{}")
        except Exception:
            return
        self.store.clear()
        for pid, info in procs.items():
            try:
                ipid = int(pid)
            except (TypeError, ValueError):
                continue
            if ipid == 0:
                continue
            self.store.append([ipid, str(ipid), info.get("user") or "", info.get("cmd") or ""])
        self.count.set_text(f"{len(self.store)} processes")

    def kill_selected(self):
        model, it = self.tree.get_selection().get_selected()
        if not it:
            return
        pid, cmd = model[it][0], model[it][3]
        if not ui.confirm(self.get_toplevel(), f"Kill process {pid}?", cmd, "Kill process", destructive=True):
            return
        self.app.ctrl.send_node_msg(self.nodeid, "pskill", value=pid)
        GLib.timeout_add(400, lambda: (self.refresh(), False)[1])


class ServicesPanel(_MsgPanel):
    def __init__(self, app, node):
        super().__init__(app, node)

        bar = Gtk.Box(spacing=6, margin=8)
        refresh = Gtk.Button(label="Refresh",
                             image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                             always_show_image=True)
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.pack_start(refresh, False, False, 0)
        for label, action, icon in (("Start", "serviceStart", "media-playback-start-symbolic"),
                                     ("Stop", "serviceStop", "media-playback-stop-symbolic"),
                                     ("Restart", "serviceRestart", "view-refresh-symbolic")):
            b = Gtk.Button(label=label,
                           image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON),
                           always_show_image=True)
            b.connect("clicked", lambda _w, a=action, l=label: self.control(a, l))
            bar.pack_start(b, False, False, 0)
        self.count = Gtk.Label(xalign=1)
        self.count.get_style_context().add_class("dim-label")
        bar.pack_end(self.count, False, False, 0)
        self.pack_start(bar, False, False, 0)

        hint = Gtk.Label(
            label="Start / Stop / Restart require the agent to be running as root (Linux) or SYSTEM "
                  "(Windows); otherwise they have no effect.",
            xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_start(8)
        hint.set_margin_end(8)
        self.pack_start(hint, False, False, 0)

        # display name, type, state, service name (for control)
        self.store = Gtk.ListStore(str, str, str, str)
        self.tree = Gtk.TreeView(model=self.store, enable_search=True, search_column=0)
        for title, col, expand in (("Service", 0, True), ("Type", 1, False), ("State", 2, False)):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, r, text=col)
            c.set_resizable(True)
            c.set_sort_column_id(col)
            if expand:
                c.set_expand(True)
            self.tree.append_column(c)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)

    def _first_load(self):
        self.refresh()

    def refresh(self):
        self.count.set_text("Loading…")
        self.app.ctrl.send_node_msg(self.nodeid, "services")

    def _handle_msg(self, message):
        if message.get("type") != "services":
            return
        try:
            services = json.loads(message.get("value") or "[]")
        except Exception:
            return
        # The agent lists each unit twice (e.g. /lib and /etc copies); collapse by
        # name, preferring the copy that carries a running state.
        by_name = {}
        for svc in services:
            if not isinstance(svc, dict):
                continue
            key = svc.get("name") or svc.get("displayName") or svc.get("description")
            if key is None:
                continue
            prev = by_name.get(key)
            if prev is None or (not self._svc_state_raw(prev) and self._svc_state_raw(svc)):
                by_name[key] = svc

        self.store.clear()
        running = 0
        for svc in by_name.values():
            if svc.get("status"):                     # Windows: live SCM state
                raw = (svc["status"].get("state") or "")
                state = raw.capitalize() or "Unknown"
                svc_type = "service"
                display = svc.get("displayName") or svc.get("name") or ""
            else:                                     # Linux/systemd
                raw = self._svc_state_raw(svc)
                state = "Running" if raw else "Inactive"
                svc_type = svc.get("serviceType") or "service"
                display = svc.get("description") or svc.get("name") or ""
            if state in ("Running",):
                running += 1
            name = svc.get("name") or display
            self.store.append([display, svc_type, state, name])
        self.store.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        self.count.set_text(f"{len(self.store)} services · {running} running")

    @staticmethod
    def _svc_state_raw(svc):
        # Linux entries only carry 'state' (e.g. "RUNNING") when the unit is active.
        return svc.get("state") or (svc.get("status") or {}).get("state")

    def control(self, action, label):
        model, it = self.tree.get_selection().get_selected()
        if not it:
            return
        name, display = model[it][3], model[it][0]
        if not ui.confirm(self.get_toplevel(), f"{label} service?", display, label):
            return
        self.app.ctrl.send_node_msg(self.nodeid, action, serviceName=name)
        GLib.timeout_add(800, lambda: (self.refresh(), False)[1])


class ConsolePanel(_MsgPanel):
    def __init__(self, app, node):
        super().__init__(app, node)

        hint = Gtk.Label(
            label="Runs MeshAgent commands (type 'help'; e.g. ls, ps, services, cpuinfo). "
                  "For a real shell use the Terminal tab.",
            xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_start(8)
        hint.set_margin_end(8)
        hint.set_margin_top(6)
        self.pack_start(hint, False, False, 0)

        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log.set_left_margin(6)
        self.log.set_top_margin(6)
        self.buffer = self.log.get_buffer()
        self.pack_start(ui.scrolled(self.log), True, True, 0)

        entry_bar = Gtk.Box(spacing=6, margin=8)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Agent console command (e.g. help)")
        self.entry.connect("activate", lambda *_: self.send())
        entry_bar.pack_start(self.entry, True, True, 0)
        send = Gtk.Button(label="Send")
        send.get_style_context().add_class("suggested-action")
        send.connect("clicked", lambda *_: self.send())
        entry_bar.pack_start(send, False, False, 0)
        self.pack_start(entry_bar, False, False, 0)

    def _first_load(self):
        self._append("Agent console ready. Type 'help' for the list of MeshAgent commands.\n")

    def _append(self, text):
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, text)
        self.log.scroll_to_mark(self.buffer.get_insert(), 0.0, False, 0, 0)

    def send(self):
        cmd = self.entry.get_text().strip()
        if not cmd:
            return
        self.entry.set_text("")
        self._append(f"> {cmd}\n")
        self.app.ctrl.send_node_msg(self.nodeid, "console", value=cmd)

    def _handle_msg(self, message):
        if message.get("type") != "console":
            return
        val = message.get("value")
        if val:
            self._append(str(val) + "\n")
