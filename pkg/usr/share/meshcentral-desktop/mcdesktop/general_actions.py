"""Device action bar, power/more menus and right-click context menu."""
import secrets

from gi.repository import Gtk, Gdk, GLib

from . import ui

POWER = {"wake": 100, "off": 2, "reset": 3, "sleep": 4}
RUN_TYPE = {"Windows Command": 0, "Windows PowerShell": 2, "Linux/macOS Shell": 3}


class RunOutputDialog(Gtk.Dialog):
    """Non-modal window that runs a command and shows its live output.

    A runcommands reply may arrive as one message or several (with reply:true the
    agent streams output). We listen on the 'runcommands' action filtered by our
    responseid, append any text we find, and stop listening when closed.
    """
    def __init__(self, parent, ctrl, node, rid, request):
        super().__init__(title=f"Run command - {node.get('name')}", transient_for=parent)
        self.set_modal(False)
        self.set_default_size(760, 460)
        self.ctrl = ctrl
        self.rid = rid
        self._got_output = False
        self._status = None

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
        self.status_label = Gtk.Label(label="Running…", xalign=0)
        self.status_label.get_style_context().add_class("dim-label")
        hb = Gtk.Box(spacing=8, margin=6)
        hb.pack_start(self.spinner, False, False, 0)
        hb.pack_start(self.status_label, True, True, 0)
        self.get_content_area().pack_start(hb, False, False, 0)

        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())
        self.connect("destroy", self._cleanup)

        self.ctrl.on("runcommands", self._on_reply)
        self.ctrl.send(request)
        # Safety: stop waiting after 60s if the agent never signals completion.
        self._timeout_id = GLib.timeout_add_seconds(60, self._on_timeout)
        self.show_all()

    def _append(self, text):
        if not text:
            return
        self.buffer.insert(self.buffer.get_end_iter(), text if text.endswith("\n") else text + "\n")
        self._got_output = True

    def _on_reply(self, msg):
        if msg.get("responseid") != self.rid:
            return
        # Output can appear under different keys depending on agent/server version.
        for key in ("value", "data", "output", "cmdData"):
            v = msg.get(key)
            if isinstance(v, str) and v:
                self._append(v)
        result = msg.get("result")
        if isinstance(result, str):
            self._status = result
            if result != "OK":
                self._append(result)
        if msg.get("complete") or msg.get("done") or result in ("OK", "Access denied",
                                                                 "Invalid nodeid", "Agent not connected"):
            self._finish(result or "Done")

    def _on_timeout(self):
        self._finish("Finished (no further output).")
        return False

    def _finish(self, status):
        self.spinner.stop()
        self.spinner.hide()
        if not self._got_output:
            note = "Command sent." if status == "OK" else status
            self.status_label.set_text(
                f"{note} ,  this command returned no text output; use the Terminal tab for live output.")
        else:
            self.status_label.set_text(f"Done ({status}).")

    def _cleanup(self, *_):
        if getattr(self, "_timeout_id", None):
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        self.ctrl.off("runcommands", self._on_reply)


class DeviceActions:
    def __init__(self, win):
        self.win = win
        self.app = win.app
        self.ctrl = win.ctrl
        self.buttons = {}

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
        box.show_all()
        pop.add(box)
        return pop

    def _more_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
        for label, cb in (("Notes…", self.notes), ("Message box…", self.msg_box),
                          ("Toast notification…", self.toast),
                          ("Rename…", self.rename_device), ("Edit tags…", self.edit_tags),
                          ("Open in web UI", self.open_web)):
            b = Gtk.ModelButton(text=label)
            b.connect("clicked", cb)
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    def update(self, node):
        online = ui.is_online(node)
        for key in ("desktop", "terminal", "files", "run"):
            if key in self.buttons:
                self.buttons[key].set_sensitive(online)
        self.name_label.set_text(node.get("name", ""))

    # ---- context menu ------------------------------------------------------
    def context_menu(self, event, node):
        online = ui.is_online(node)
        menu = Gtk.Menu()
        items = [("Remote Desktop", lambda: self.win.goto_device_tab("Desktop"), online),
                 ("Terminal", lambda: self.win.goto_device_tab("Terminal"), online),
                 ("Files", lambda: self.win.goto_device_tab("Files"), online),
                 ("Run command…", self.run_command, online),
                 (None, None, None),
                 ("Wake up", lambda: self.power_action("wake"), True),
                 ("Restart", lambda: self.power_action("reset"), online),
                 ("Power off", lambda: self.power_action("off"), online),
                 (None, None, None),
                 ("Notes…", self.notes, True),
                 ("Rename…", self.rename_device, True),
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
        NotesDialog(self.win, self.ctrl, node).present()

    def open_web(self, *_):
        node = self._node()
        if node:
            self.app.open_uri(f"{self.ctrl.server.url}/?gotonode={node['_id']}&viewmode=11")


class NotesDialog(Gtk.Dialog):
    """Quick view/edit of a single device's notes (getNotes / setNotes)."""

    def __init__(self, parent, ctrl, node):
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
        hint = Gtk.Label(label="Notes for this device (shared with other administrators):",
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
