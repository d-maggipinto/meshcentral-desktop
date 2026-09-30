"""Device action bar, power/more menus and right-click context menu."""
import secrets

from gi.repository import Gtk, Gdk, GLib

from . import ui, rights

POWER = {"wake": 100, "off": 2, "reset": 3, "sleep": 4}
RUN_TYPE = {"Windows Command": 0, "Windows PowerShell": 2, "Linux/macOS Shell": 3}


class RunOutputDialog(Gtk.Dialog):
    """Non-modal window that runs a command and shows its output.

    Ground truth (verified live): with reply:true the server first answers
    {action:'runcommands', result:'OK', responseid}, only an ACK, and the command's
    output arrives LATER as a separate {action:'msg', type:'runcommands', result:'<output>',
    responseid, nodeid}. Listening only to the 'runcommands' action (as before) finished on
    the ACK and never saw the output.
    """
    TIMEOUT_S = 120

    def __init__(self, parent, ctrl, node, rid, request):
        super().__init__(title=f"Run command - {node.get('name')}", transient_for=parent)
        self.set_modal(False)
        self.set_default_size(760, 460)
        self.ctrl = ctrl
        self.rid = rid
        self._done = False

        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(8)
        view.set_top_margin(6)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(view)
        self.get_content_area().pack_start(sw, True, True, 0)

        self.spinner = Gtk.Spinner()
        self.spinner.start()
        self.status_label = Gtk.Label(label="Sending…", xalign=0)
        self.status_label.get_style_context().add_class("dim-label")
        hb = Gtk.Box(spacing=8, margin=6)
        hb.pack_start(self.spinner, False, False, 0)
        hb.pack_start(self.status_label, True, True, 0)
        self.get_content_area().pack_start(hb, False, False, 0)

        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())
        self.connect("destroy", self._cleanup)

        self.ctrl.on("runcommands", self._on_ack)
        self.ctrl.on("msg", self._on_output)
        self.ctrl.send(request)
        self._timeout_id = GLib.timeout_add_seconds(self.TIMEOUT_S, self._on_timeout)
        self.show_all()

    def _on_ack(self, msg):
        if msg.get("responseid") != self.rid or self._done:
            return
        result = msg.get("result")
        if result == "OK":
            self.status_label.set_text("Running… waiting for the output")
        elif isinstance(result, str) and result:
            self._finish(f"Not run: {result}")            # e.g. "Access denied", "Agent not connected"

    def _on_output(self, msg):
        if msg.get("type") != "runcommands" or msg.get("responseid") != self.rid or self._done:
            return
        out = msg.get("result")
        if isinstance(out, str) and out:
            self.buffer.insert(self.buffer.get_end_iter(), out if out.endswith("\n") else out + "\n")
            self._finish("Done.")
        else:
            self._finish("Done, the command produced no output.")

    def _on_timeout(self):
        self._timeout_id = None
        self._finish(f"No output after {self.TIMEOUT_S} s, the agent may be offline or the "
                     "command is still running. Use the Terminal tab for long-running commands.")
        return False

    def _finish(self, status):
        self._done = True
        self.spinner.stop()
        self.spinner.hide()
        self.status_label.set_text(status)

    def _cleanup(self, *_):
        if getattr(self, "_timeout_id", None):
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        self.ctrl.off("runcommands", self._on_ack)
        self.ctrl.off("msg", self._on_output)


class DeviceActions:
    def __init__(self, win):
        self.win = win
        self.app = win.app
        self.ctrl = win.ctrl
        self.buttons = {}
        self.items = {}              # menu key -> ModelButton (sensitivity follows rights)

    # ---- bar ---------------------------------------------------------------
    def build_bar(self):
        bar = Gtk.Box(spacing=6, margin=8)

        def add(key, label, icon, cb, style=None):
            b = Gtk.Button(label=label, image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON),
                           always_show_image=True)
            b.connect("clicked", cb)
            if style:
                b.get_style_context().add_class(style)
            bar.pack_start(b, False, False, 0)
            self.buttons[key] = b
            return b

        # Desktop / Terminal / Files are tabs (right below this bar), so they are NOT
        # repeated here, this bar carries only device-level actions.
        add("run", "Run command", "system-run-symbolic", lambda *_: self.run_command())

        power_btn = Gtk.MenuButton(label="Power",
                                   image=Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.BUTTON),
                                   always_show_image=True)
        power_btn.set_popover(self._power_menu())
        bar.pack_start(power_btn, False, False, 0)
        self.buttons["power"] = power_btn

        more_btn = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        more_btn.set_popover(self._more_menu())
        bar.pack_end(more_btn, False, False, 0)
        self.name_label = Gtk.Label(xalign=0)
        self.name_label.get_style_context().add_class("dim-label")
        bar.pack_end(self.name_label, True, True, 6)
        return bar

    def _power_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
        for label, key in (("Wake up", "wake"), ("Sleep", "sleep"), ("Restart", "reset"), ("Power off", "off")):
            b = Gtk.ModelButton(text=label)
            b.connect("clicked", lambda _w, k=key: self.power_action(k))
            box.pack_start(b, False, False, 0)
            self.items["power_" + key] = b
        box.show_all()
        pop.add(box)
        return pop

    def _more_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
        for key, label, cb in (("notes", "Notes…", self.notes), ("msgbox", "Message box…", self.msg_box),
                               ("toast", "Toast notification…", self.toast),
                               ("rename", "Rename…", self.rename_device), ("tags", "Edit tags…", self.edit_tags),
                               ("web", "Open in web UI", self.open_web)):
            b = Gtk.ModelButton(text=label)
            b.connect("clicked", cb)
            box.pack_start(b, False, False, 0)
            self.items[key] = b
        box.show_all()
        pop.add(box)
        return pop

    def caps(self, node):
        return rights.node_caps(self.ctrl, self.win.meshes, node)

    def update(self, node):
        online = ui.is_online(node)
        c = self.caps(node)
        self.buttons["run"].set_sensitive(online and c.run_commands)
        self.buttons["run"].set_tooltip_text(None if c.run_commands else "Your account may not run commands on this device")
        sens = {"power_wake": c.wake, "power_sleep": online and c.power, "power_reset": online and c.power,
                "power_off": online and c.power, "msgbox": online and c.messages, "toast": online and c.messages,
                "rename": c.manage, "tags": c.manage}
        for key, on in sens.items():
            self.items[key].set_sensitive(bool(on))
        self.buttons["power"].set_sensitive(bool(c.wake or c.power))
        self.name_label.set_text(node.get("name", ""))

    # ---- context menu ------------------------------------------------------
    def context_menu(self, event, node):
        online = ui.is_online(node)
        c = self.caps(node)
        menu = Gtk.Menu()
        items = [("Remote Desktop", lambda: self.win.goto_device_tab("Desktop"), online and c.desktop),
                 ("Terminal", lambda: self.win.goto_device_tab("Terminal"), online and c.terminal),
                 ("Files", lambda: self.win.goto_device_tab("Files"), online and c.files),
                 ("Run command…", self.run_command, online and c.run_commands),
                 (None, None, None),
                 ("Wake up", lambda: self.power_action("wake"), c.wake),
                 ("Restart", lambda: self.power_action("reset"), online and c.power),
                 ("Power off", lambda: self.power_action("off"), online and c.power),
                 (None, None, None),
                 ("Notes…", self.notes, True),
                 ("Rename…", self.rename_device, c.manage),
                 ("Open in web UI", self.open_web, True)]
        for label, cb, enabled in items:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=label)
            mi.set_sensitive(bool(enabled))
            mi.connect("activate", lambda _w, c=cb: c())
            menu.append(mi)
        menu.show_all()
        menu.popup_at_pointer(event)

    # ---- operations --------------------------------------------------------
    def _node(self):
        return self.win.current

    def power_action(self, key):
        node = self._node()
        if not node:
            return
        if key in ("off", "reset"):
            verb = "Power off" if key == "off" else "Restart"
            if not ui.confirm(self.win, f"{verb} {node.get('name')}?", "", verb, destructive=True):
                return
        self.ctrl.send({"action": "poweraction", "nodeids": [node["_id"]], "actiontype": POWER[key]})
        self.app.notify("Power", f"{key.title()} sent to {node.get('name')}")

    def run_command(self):
        node = self._node()
        if not node:
            return
        win = ui.is_windows(node)
        shells = "Windows Command|Windows PowerShell" if win else "Linux/macOS Shell"
        default = "Windows Command" if win else "Linux/macOS Shell"
        r = ui.form_dialog(self.win, f"Run command on {node.get('name')}",
                           [("shell", "Shell:", f"combo:{shells}", default),
                            ("cmd", "Commands:", "multiline", "")], "Run")
        if not r or not r["cmd"].strip():
            return
        rid = "mcdrun" + secrets.token_hex(6)
        RunOutputDialog(self.win, self.ctrl, node, rid,
                        {"action": "runcommands", "nodeids": [node["_id"]],
                         "type": RUN_TYPE.get(r["shell"], 3), "cmds": r["cmd"],
                         "runAsUser": 0, "reply": True, "responseid": rid})

    def msg_box(self, *_):
        node = self._node()
        if not node:
            return
        r = ui.form_dialog(self.win, "Message box", [("title", "Title:", "text", "Message"),
                                                     ("msg", "Message:", "multiline", "")], "Send")
        if r and r["msg"].strip():
            self.ctrl.send({"action": "msg", "type": "messagebox", "nodeid": node["_id"],
                            "title": r["title"], "msg": r["msg"]})

    def toast(self, *_):
        node = self._node()
        if not node:
            return
        r = ui.form_dialog(self.win, "Toast notification", [("title", "Title:", "text", "Notice"),
                                                            ("msg", "Message:", "text", "")], "Send")
        if r and r["msg"].strip():
            self.ctrl.send({"action": "toast", "nodeids": [node["_id"]], "title": r["title"], "msg": r["msg"]})

    def rename_device(self, *_):
        node = self._node()
        if not node:
            return
        r = ui.form_dialog(self.win, "Rename device", [("name", "New name:", "text", node.get("name", ""))], "Rename")
        if r and r["name"].strip():
            self.ctrl.send({"action": "changedevice", "nodeid": node["_id"], "name": r["name"].strip()})
            node["name"] = r["name"].strip()

    def edit_tags(self, *_):
        node = self._node()
        if not node:
            return
        cur = node.get("tags")
        cur = ", ".join(cur) if isinstance(cur, list) else (cur or "")
        r = ui.form_dialog(self.win, "Edit tags", [("tags", "Tags (comma separated):", "text", cur)], "Save")
        if r is not None:
            tags = [t.strip() for t in r["tags"].split(",") if t.strip()]
            self.ctrl.send({"action": "changedevice", "nodeid": node["_id"], "tags": tags})

    def notes(self, *_):
        node = self._node()
        if not node:
            return
        NotesDialog(self.win, self.ctrl, node, editable=self.caps(node).notes).present()

    def open_web(self, *_):
        node = self._node()
        if node:
            # gotonode needs the SHORT id (last part of _id), like the desktop viewer URL.
            self.app.open_uri(f"{self.ctrl.server.url}/?gotonode={node['_id'].split('/')[-1]}&viewmode=11")


class NotesDialog(Gtk.Dialog):
    """Quick view/edit of the notes of a device, or of a user (Users page), getNotes / setNotes
    with the object's id; `node` only needs "_id" and "name"."""

    def __init__(self, parent, ctrl, node, editable=True, what="device"):
        super().__init__(title=f"Notes - {node.get('name', '')}", transient_for=parent, modal=True)
        self.ctrl = ctrl
        self.node = node
        self.set_default_size(520, 360)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.save_btn = self.add_button("Save", Gtk.ResponseType.APPLY)
        self.save_btn.get_style_context().add_class("suggested-action")

        box = self.get_content_area()
        box.set_spacing(6)
        box.set_border_width(10)
        hint = Gtk.Label(label=f"Notes for this {what} (shared with other administrators):",
                         xalign=0)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, editable=True)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        self.view.set_top_margin(8)
        scr = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scr.add(self.view)
        frame = Gtk.Frame()
        frame.add(scr)
        box.pack_start(frame, True, True, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        box.pack_start(self.status, False, False, 0)

        if not editable:
            self.view.set_editable(False)
            self.save_btn.set_sensitive(False)
            hint.set_text(f"Notes for this {what} (read-only, your account may not edit notes here):")
        self.connect("response", self._on_response)
        self.connect("destroy", lambda *_: self._unlisten())
        self._handler = self._on_reply
        self.ctrl.on("getNotes", self._handler)
        self.status.set_text("Loading…")
        self.ctrl.send({"action": "getNotes", "id": node["_id"]})
        GLib.timeout_add(4000, self._load_timeout)
        self._loaded = False
        self.show_all()

    def _on_reply(self, message):
        if message.get("id") not in (None, self.node["_id"]):
            return
        notes = message.get("notes")
        self.view.get_buffer().set_text(notes if isinstance(notes, str) else "")
        self._loaded = True
        self.status.set_text("Saved ✓" if getattr(self, "_saving", False) else "")
        self._saving = False

    def _load_timeout(self):
        if not self._loaded:
            self.status.set_text("")   # no notes yet, start typing
        return False

    def _on_response(self, _dlg, resp):
        if resp == Gtk.ResponseType.APPLY:
            buf = self.view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            self.ctrl.send({"action": "setNotes", "id": self.node["_id"], "notes": text})
            self._saving = True
            self.status.set_text("Saving…")
            GLib.timeout_add(300, lambda: (self.ctrl.send({"action": "getNotes", "id": self.node["_id"]}), False)[1])
            # keep the dialog open after saving (present() does not auto-close)
        else:
            self.destroy()

    def _unlisten(self):
        if self._handler is not None:
            self.ctrl.off("getNotes", self._handler)
            self._handler = None
