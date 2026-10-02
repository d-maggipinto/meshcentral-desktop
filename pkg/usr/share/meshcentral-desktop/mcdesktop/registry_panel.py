# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Registry tab for Windows devices, like the web UI's Registry page (p9, MeshCentral 1.2.x).

Relay protocol 4. JSON requests (sent like the file relay's) and the agent's replies
(agents/meshcore.js -> modules_meshcore/win-registry-remote.js, which uses reg.exe for writes):
  listroots                               -> {roots: [hive names]}
  list {hive, path}                       -> {hive, path, subkeys: [names], values: [{name, rawname, type, value}]}
  createkey {hive, path, name}            -> {success}
  setvalue {hive, path, name, type, value} (REG_SZ / REG_EXPAND_SZ / REG_DWORD / REG_QWORD)
  delete {items: [{kind, hive, path, name}]}
  rename {item: {kind, hive, path, name}, newName}
  export {hive, path}                     -> {content: .reg text}
Every reply echoes `action` and `reqid`; a failure carries `error`. The agent only needs remote
control rights (8); the server refuses the tunnel with "No Registry" (0x400000). Consent bit 0x100
makes the agent ask the local user first (console message "Waiting for user to grant access...").
"""
import json
import os
import tempfile

from gi.repository import Gtk, GLib

from .client import Tunnel, PROTO_REGISTRY
from . import ui

STATE_TEXT = {0: "Disconnected", 1: "Connecting…", 2: "Waiting for agent…", 3: "Connected"}
HIVES = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER", "HKU": "HKEY_USERS",
         "HKCR": "HKEY_CLASSES_ROOT", "HKCC": "HKEY_CURRENT_CONFIG"}
WRITABLE_TYPES = ["REG_SZ", "REG_EXPAND_SZ", "REG_DWORD", "REG_QWORD"]
NUMERIC = ("REG_DWORD", "REG_QWORD")
# store columns
C_KIND, C_NAME, C_TYPE, C_DATA, C_RAW, C_FULL = range(6)   # C_DATA = one-line display of C_FULL


def normalize_path(text):
    """'HKLM\\Software/Foo' -> ('HKEY_LOCAL_MACHINE', 'Software\\Foo'); '' or 'Root' -> (None, '');
    None for an unknown hive (port of the web UI's p9normalizePath)."""
    text = (text or "").strip()
    if not text or text.lower() == "root":
        return None, ""
    parts = [p for p in text.replace("/", "\\").split("\\") if p != ""]
    if not parts:
        return None, ""
    hive = parts[0].upper()
    hive = HIVES.get(hive, hive)
    if hive not in HIVES.values():
        return None
    return hive, "\\".join(parts[1:])


def display_path(hive, path):
    if hive is None:
        return "Root"
    return hive + ("\\" + path if path else "")


def valid_number(text):
    t = (text or "").strip()
    if t.lower().startswith("0x"):
        return len(t) > 2 and all(c in "0123456789abcdefABCDEF" for c in t[2:])
    return t.isdigit()


class RegistryPanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.node = app, node
        self._started = False
        self.tunnel = None
        self.hive = None               # None = list of root hives
        self.path = ""
        self._seq = 0
        self._list_req = None          # reqid of the listing we wait for (older replies are ignored)
        self._export_name = None
        self._done_msg = None          # "Registry value updated." etc., shown once the refreshed list arrives

        toolbar = Gtk.Box(spacing=6, margin=6)
        nav = Gtk.Box()
        nav.get_style_context().add_class("linked")
        self.up_btn = self._btn("go-up-symbolic", "Parent key", self.go_up)
        self.root_btn = self._btn("go-home-symbolic", "Root hives", lambda *_: self.go_to(None, ""))
        self.refresh_btn = self._btn("view-refresh-symbolic", "Refresh", self.refresh)
        for b in (self.up_btn, self.root_btn, self.refresh_btn):
            nav.pack_start(b, False, False, 0)
        toolbar.pack_start(nav, False, False, 0)

        acts = Gtk.Box()
        acts.get_style_context().add_class("linked")
        self.newkey_btn = self._btn("folder-new-symbolic", "New key", self.new_key)
        self.newval_btn = self._btn("document-new-symbolic", "New value", self.new_value)
        self.edit_btn = self._btn("document-properties-symbolic", "Edit value", self.edit_value)
        self.rename_btn = self._btn("document-edit-symbolic", "Rename", self.rename_item)
        self.delete_btn = self._btn("edit-delete-symbolic", "Delete selected", self.delete_items)
        for b in (self.newkey_btn, self.newval_btn, self.edit_btn, self.rename_btn, self.delete_btn):
            acts.pack_start(b, False, False, 0)
        toolbar.pack_start(acts, False, False, 0)

        more = Gtk.Box()
        more.get_style_context().add_class("linked")
        self.export_btn = self._btn("document-save-as-symbolic", "Export the selected key as a .reg file",
                                    self.export_key)
        self.download_btn = self._btn("document-save-symbolic", "Save the selected items as text",
                                      self.download_selection)
        self.details_btn = self._btn("dialog-information-symbolic", "Details", self.show_details)
        for b in (self.export_btn, self.download_btn, self.details_btn):
            more.pack_start(b, False, False, 0)
        toolbar.pack_start(more, False, False, 0)

        # Opening the tab does NOT connect: the user presses Connect (like Desktop / Terminal / Files).
        self.connect_btn = Gtk.Button(label="Connect")
        self.connect_btn.get_style_context().add_class("suggested-action")
        self.connect_btn.connect("clicked", self._toggle)
        toolbar.pack_end(self.connect_btn, False, False, 0)
        self.status_label = Gtk.Label(label="Disconnected", xalign=1)
        self.status_label.get_style_context().add_class("dim-label")
        toolbar.pack_end(self.status_label, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

        # GoTo: type or paste a path (HKLM\Software\..., short hive names accepted), Enter opens it
        self.path_entry = Gtk.Entry(text="Root", margin_start=6, margin_end=6, sensitive=False,
                                    placeholder_text="HKEY_LOCAL_MACHINE\\SOFTWARE")
        self.path_entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "go-jump-symbolic")
        self.path_entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Go to this key")
        self.path_entry.set_tooltip_text("Registry path: type a key such as HKLM\\SOFTWARE\\Microsoft and press Enter")
        self.path_entry.connect("activate", lambda *_: self.goto_text(self.path_entry.get_text()))
        self.path_entry.connect("icon-press", lambda *_: self.goto_text(self.path_entry.get_text()))

        self.info = Gtk.InfoBar(revealed=False, show_close_button=True)
        self.info.connect("response", lambda *_: self.info.set_revealed(False))
        self.info_label = Gtk.Label(wrap=True, xalign=0, selectable=True)
        self.info.get_content_area().add(self.info_label)

        # kind (hive|key|value), display name, type, data (one line), raw name, full data
        self.store = Gtk.ListStore(str, str, str, str, str, str)
        self.tree = Gtk.TreeView(model=self.store, enable_search=True, search_column=C_NAME)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.get_selection().connect("changed", lambda *_: self._sync_buttons())
        self.tree.connect("row-activated", self._on_activate)
        icon_r, name_r = Gtk.CellRendererPixbuf(), Gtk.CellRendererText()
        c0 = Gtk.TreeViewColumn("Name")
        c0.pack_start(icon_r, False)
        c0.pack_start(name_r, True)
        c0.set_cell_data_func(icon_r, lambda _c, cell, m, it, _d: cell.set_property(
            "icon-name", "text-x-generic-symbolic" if m[it][C_KIND] == "value" else "folder-symbolic"))
        c0.add_attribute(name_r, "text", C_NAME)
        c0.set_resizable(True)
        c0.set_sort_column_id(C_NAME)
        self.tree.append_column(c0)
        self.tree.append_column(ui.text_column("Type", C_TYPE))
        self.tree.append_column(ui.text_column("Data", C_DATA, expand=True))
        ui.row_tooltip(self.tree, C_FULL)

        self.bottom = Gtk.Label(xalign=0, margin=6, ellipsize=3)
        self.bottom.get_style_context().add_class("dim-label")

        self.pack_start(self.info, False, False, 0)
        self.pack_start(self.path_entry, False, False, 2)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)
        self.pack_start(self.bottom, False, False, 0)
        self.show_all()
        self._set_bottom("Connect to browse the registry of this device.")
        self._sync_buttons()

    def _btn(self, icon, tip, cb):
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        b.set_tooltip_text(tip)
        b.connect("clicked", cb)
        return b

    def _parent_window(self):
        top = self.get_toplevel()
        return top if isinstance(top, Gtk.Window) else None

    def _connected(self):
        return bool(self.tunnel and self.tunnel.state == 3)

    def _set_bottom(self, text):
        self.bottom.set_text(text or "")

    def _show_error(self, text):
        self.info_label.set_text(text)
        self.info.set_message_type(Gtk.MessageType.ERROR)
        self.info.set_revealed(True)

    # ---- lifecycle ---------------------------------------------------------
    def on_shown(self):
        self._started = True             # no auto-connect: wait for the Connect button

    def teardown(self):
        self.disconnect_tunnel()

    def disconnect_tunnel(self):
        if self.tunnel:
            t, self.tunnel = self.tunnel, None
            t.on_state = None
            t.stop()

    def _toggle(self, *_):
        if self.tunnel and self.tunnel.state:
            self.disconnect_tunnel()
            self._on_state(0)
        else:
            self.connect_tunnel()

    def connect_tunnel(self):
        self.disconnect_tunnel()
        self.info.set_revealed(False)
        self.tunnel = Tunnel(self.app.ctrl, self.node["_id"], PROTO_REGISTRY, binary_in_thread=False)
        self.tunnel.on_state = self._on_state
        self.tunnel.on_text = self._on_text
        self.tunnel.on_binary = self._on_binary
        self.tunnel.on_console = self._on_console
        self.tunnel.start()

    def _on_state(self, s):
        self.status_label.set_text(STATE_TEXT.get(s, ""))
        self.connect_btn.set_label("Disconnect" if s else "Connect")
        ctx = self.connect_btn.get_style_context()
        (ctx.remove_class if s else ctx.add_class)("suggested-action")
        self.path_entry.set_sensitive(s == 3)
        if s == 0:
            self.store.clear()
            self.hive, self.path, self._list_req = None, "", None
            self.path_entry.set_text("Root")
            self._set_bottom("Connect to browse the registry of this device.")
        if s == 3:
            self.go_to(None, "")
        self._sync_buttons()

    def _on_console(self, msg):
        if msg:
            self.info_label.set_text(msg)
            self.info.set_message_type(Gtk.MessageType.WARNING)
            self.info.set_revealed(True)

    # ---- requests ----------------------------------------------------------
    def _send(self, obj):
        self._seq += 1
        obj["reqid"] = "%s-%d" % (obj["action"], self._seq)
        if self._connected():
            self.tunnel.send_json(obj)
        return obj["reqid"]

    def go_to(self, hive, path):
        self.hive, self.path = hive, path or ""
        self.path_entry.set_text(display_path(self.hive, self.path))
        self.store.clear()
        if not self._connected():
            return
        if hive is None:
            self._set_bottom("Loading root hives…")
            self._list_req = self._send({"action": "listroots"})
        else:
            self._set_bottom("Loading registry key…")
            self._list_req = self._send({"action": "list", "hive": hive, "path": self.path})
        self._sync_buttons()

    def goto_text(self, text):
        target = normalize_path(text)
        if target is None:
            self._set_bottom("Invalid registry path. Use a full hive path such as HKEY_LOCAL_MACHINE\\SOFTWARE.")
            return
        self.go_to(*target)

    def go_up(self, *_):
        if self.hive is None:
            return
        if not self.path:
            self.go_to(None, "")
        else:
            self.go_to(self.hive, "\\".join(self.path.split("\\")[:-1]))

    def refresh(self, *_):
        self.go_to(self.hive, self.path)

    def _child_path(self, name):
        return self.path + "\\" + name if self.path else name

    def _on_activate(self, _tv, tpath, _col):
        row = self.store[tpath]
        kind = row[C_KIND]
        if kind == "hive":
            self.go_to(row[C_RAW], "")
        elif kind == "key":
            self.go_to(self.hive, self._child_path(row[C_RAW]))
        elif row[C_TYPE] in WRITABLE_TYPES:
            self.edit_value()
        else:
            self.show_details()

    # ---- replies -----------------------------------------------------------
    # Like the file relay, the agent's JSON may arrive as a binary or a text frame.
    def _on_binary(self, data):
        self._on_text(bytes(data).decode("utf-8", "replace"))

    def _on_text(self, data):
        try:
            msg = json.loads(data)
        except Exception:
            return
        if isinstance(msg, dict):
            self._handle(msg)

    def _handle(self, msg):
        action, err = msg.get("action"), msg.get("error")
        if action in ("listroots", "list"):
            if msg.get("reqid") != self._list_req:
                return                                     # an older listing, the user moved on
            if err:
                self.store.clear()
                self._set_bottom(str(err))
                self._show_error(str(err))
                return
            self.info.set_revealed(False)
            self._fill(msg)
            return
        if err:
            self._show_error("%s failed: %s" % ({"createkey": "Create key", "setvalue": "Set value",
                                                  "delete": "Delete", "rename": "Rename",
                                                  "export": "Export"}.get(action, action or "Request"), err))
            if action != "export":
                self.refresh()
            return
        done = {"createkey": "Registry key created.", "setvalue": "Registry value updated.",
                "delete": "Registry item deleted.", "rename": "Registry item renamed."}
        if action in done:
            self.refresh()
            self._done_msg = done[action]
        elif action == "export":
            self._save_export(msg.get("content") or "")

    def _fill(self, msg):
        self.store.clear()
        if msg.get("action") == "listroots":
            for h in msg.get("roots") or []:
                self.store.append(["hive", str(h), "Hive", "", str(h), ""])
            n = len(self.store)
            self._set_bottom("%d hives" % n if n else "No registry roots were returned.")
        else:
            subkeys = [str(k) for k in msg.get("subkeys") or []]
            for k in sorted(subkeys, key=str.lower):
                self.store.append(["key", k, "Key", "", k, ""])
            values = [v for v in msg.get("values") or [] if isinstance(v, dict)]
            values.sort(key=lambda v: (v.get("rawname") != "", str(v.get("name") or "").lower()))
            for v in values:
                raw = v.get("rawname")
                raw = "" if raw is None else str(raw)
                data = "" if v.get("value") is None else str(v.get("value"))
                self.store.append(["value", str(v.get("name") or ("(Default)" if raw == "" else raw)),
                                   str(v.get("type") or ""), ui.one_line(data, 2000), raw, data])
            if subkeys or values:
                self._set_bottom("%d keys, %d values" % (len(subkeys), len(values)))
            else:
                self._set_bottom("Registry key is empty.")
        self._sync_buttons()
        if self._done_msg:
            self._set_bottom(self._done_msg)
            self._done_msg = None

    # ---- selection ---------------------------------------------------------
    def _selected(self):
        model, paths = self.tree.get_selection().get_selected_rows()
        return [{"kind": model[p][C_KIND], "name": model[p][C_NAME], "type": model[p][C_TYPE],
                 "data": model[p][C_FULL], "raw": model[p][C_RAW]} for p in paths]

    def _item_path(self, it):
        """Full path of a selected row: the hive, the key itself, or a value's key."""
        if it["kind"] == "hive":
            return it["raw"]
        if it["kind"] == "key":
            return display_path(self.hive, self._child_path(it["raw"]))
        return display_path(self.hive, self.path)

    def _sync_buttons(self):
        on = self._connected()
        sel = self._selected()
        one = sel[0] if len(sel) == 1 else None
        in_key = on and self.hive is not None
        self.up_btn.set_sensitive(in_key)
        self.root_btn.set_sensitive(on)
        self.refresh_btn.set_sensitive(on)
        self.newkey_btn.set_sensitive(in_key)
        self.newval_btn.set_sensitive(in_key)
        self.edit_btn.set_sensitive(on and one is not None and one["kind"] == "value"
                                    and one["type"] in WRITABLE_TYPES)
        self.rename_btn.set_sensitive(on and one is not None and one["kind"] != "hive"
                                      and not (one["kind"] == "value" and one["raw"] == ""))
        self.delete_btn.set_sensitive(on and bool(sel) and all(s["kind"] != "hive" for s in sel))
        self.export_btn.set_sensitive(on and one is not None and one["kind"] == "key")
        self.download_btn.set_sensitive(on and bool(sel))
        self.details_btn.set_sensitive(on and one is not None)
        if len(sel) == 1:
            self._set_bottom("Selected: " + one["name"])
        elif len(sel) > 1:
            self._set_bottom("Selected %d items" % len(sel))

    # ---- edits -------------------------------------------------------------
    def _ask_name(self, title, label, default, ok_label):
        r = ui.form_dialog(self._parent_window(), title, [("name", label, "text", default)], ok_label)
        if not r:
            return None
        name = r["name"].strip()
        if not name or "\\" in name:
            ui.message(self._parent_window(), "Invalid name", "A registry name cannot be empty or contain a backslash.")
            return None
        return name

    def new_key(self, *_):
        if self.hive is None:
            return
        name = self._ask_name("New key in " + display_path(self.hive, self.path), "Key name:", "", "Create")
        if name:
            self._send({"action": "createkey", "hive": self.hive, "path": self.path, "name": name})

    def _value_dialog(self, title, name, vtype, data, ok_label, name_editable):
        """Name / type / data form; asks again until DWORD / QWORD data is a number. -> (name, type, data)."""
        while True:
            fields = []
            if name_editable:
                fields.append(("name", "Name:", "text", name))
            fields += [("type", "Type:", "combo:" + "|".join(WRITABLE_TYPES), vtype),
                       ("data", "Data:", "multiline", data)]
            r = ui.form_dialog(self._parent_window(), title, fields, ok_label)
            if not r:
                return None
            n = r["name"].strip() if name_editable else name
            t, d = r["type"], r["data"]
            if name_editable and not n:
                ui.message(self._parent_window(), "Invalid name", "Enter a name for the value.")
            elif t in NUMERIC and not valid_number(d):
                ui.message(self._parent_window(), "Invalid number",
                           "%s data must be a decimal number or 0x followed by hex digits." % t)
            else:
                return n, t, (d.strip() if t in NUMERIC else d)
            name, vtype, data = n, t, d

    def new_value(self, *_):
        if self.hive is None:
            return
        r = self._value_dialog("New value in " + display_path(self.hive, self.path), "", "REG_SZ", "",
                               "Create", True)
        if r:
            self._send({"action": "setvalue", "hive": self.hive, "path": self.path,
                        "name": r[0], "type": r[1], "value": r[2]})

    def edit_value(self, *_):
        sel = self._selected()
        if len(sel) != 1 or sel[0]["kind"] != "value":
            return
        it = sel[0]
        if it["type"] not in WRITABLE_TYPES:
            ui.message(self._parent_window(), "Read-only value type",
                       "Only REG_SZ, REG_EXPAND_SZ, REG_DWORD and REG_QWORD values can be edited.")
            return
        r = self._value_dialog("Edit " + it["name"], it["raw"], it["type"], it["data"], "Save", False)
        if r:
            self._send({"action": "setvalue", "hive": self.hive, "path": self.path,
                        "name": it["raw"], "type": r[1], "value": r[2]})

    def rename_item(self, *_):
        sel = self._selected()
        if len(sel) != 1 or sel[0]["kind"] == "hive":
            return
        it = sel[0]
        if it["kind"] == "value" and it["raw"] == "":
            ui.message(self._parent_window(), "Cannot rename", "The default value cannot be renamed.")
            return
        name = self._ask_name("Rename " + it["name"], "New name:", it["raw"], "Rename")
        if name and name != it["raw"]:
            self._send({"action": "rename", "newName": name,
                        "item": {"kind": it["kind"], "hive": self.hive, "path": self.path, "name": it["raw"]}})

    def delete_items(self, *_):
        sel = self._selected()
        if not sel or any(s["kind"] == "hive" for s in sel):
            return
        names = ", ".join(s["name"] for s in sel[:6]) + (" …" if len(sel) > 6 else "")
        keys = sum(1 for s in sel if s["kind"] == "key")
        text = names + ("\n\nKeys are deleted with all their subkeys and values." if keys else "")
        if not ui.confirm(self._parent_window(), "Delete %d registry item%s?" % (len(sel), "s" if len(sel) > 1 else ""),
                          text, "Delete", destructive=True):
            return
        self._send({"action": "delete", "items": [{"kind": s["kind"], "hive": self.hive, "path": self.path,
                                                    "name": s["raw"]} for s in sel]})

    # ---- export / save / details ---------------------------------------------
    def export_key(self, *_):
        sel = self._selected()
        if len(sel) != 1 or sel[0]["kind"] != "key":
            return
        self._export_name = sel[0]["raw"]
        self._set_bottom("Exporting %s…" % sel[0]["name"])
        self._send({"action": "export", "hive": self.hive, "path": self._child_path(sel[0]["raw"])})

    def _save_export(self, content):
        name = ui.safe_filename(self._export_name or "registry-export", "registry-export") + ".reg"
        # reg.exe writes .reg files as UTF-16LE with a BOM; keep that so regedit imports them as-is
        if self._save_text("Save registry export", name, "﻿" + content.replace("\r\n", "\n").replace("\n", "\r\n"),
                           "utf-16-le"):
            self._set_bottom("Registry key exported.")

    def download_selection(self, *_):
        sel = self._selected()
        if not sel:
            return
        lines = []
        for it in sel:
            lines += ["Kind: " + it["kind"], "Name: " + it["name"],
                      "Type: " + {"hive": "Hive", "key": "Key"}.get(it["kind"], it["type"] or "Value"),
                      "Path: " + self._item_path(it)]
            if it["kind"] == "value":
                lines.append("Data: " + it["data"])
            lines.append("")
        self._save_text("Save registry selection", "registry-selection.txt", "\r\n".join(lines), "utf-8")

    def _save_text(self, title, name, text, encoding):
        chooser = Gtk.FileChooserNative.new(title, self._parent_window(), Gtk.FileChooserAction.SAVE,
                                            "_Save", "_Cancel")
        chooser.set_current_name(name)
        chooser.set_do_overwrite_confirmation(True)
        dl = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if dl:
            chooser.set_current_folder(dl)
        ok = chooser.run() == Gtk.ResponseType.ACCEPT
        dest = chooser.get_filename() if ok else None
        chooser.destroy()
        if not dest:
            return False
        tmp = None
        try:
            # complete file next to dest, then renamed over it: a failure never truncates an existing file
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".mcd-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(text.encode(encoding))
            os.replace(tmp, dest)
            return True
        except OSError as ex:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            ui.message(self._parent_window(), "Cannot save file", str(ex), Gtk.MessageType.ERROR)
            return False

    def show_details(self, *_):
        sel = self._selected()
        if len(sel) != 1:
            return
        it = sel[0]
        rows = [("Kind", it["kind"]), ("Name", it["name"]), ("Path", self._item_path(it)),
                ("Type", {"hive": "Hive", "key": "Key"}.get(it["kind"], it["type"]))]
        d = Gtk.Dialog(title="Registry " + {"hive": "Hive", "key": "Key"}.get(it["kind"], "Value"),
                       transient_for=self._parent_window(), modal=True)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        grid = Gtk.Grid(row_spacing=6, column_spacing=12, margin=14)
        for r, (k, v) in enumerate(rows):
            grid.attach(Gtk.Label(label=k + ":", xalign=1, yalign=0), 0, r, 1, 1)
            grid.attach(Gtk.Label(label=v, xalign=0, selectable=True, wrap=True, max_width_chars=70), 1, r, 1, 1)
        if it["kind"] == "value":
            grid.attach(Gtk.Label(label="Data:", xalign=1, yalign=0), 0, len(rows), 1, 1)
            tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            tv.get_buffer().set_text(it["data"])
            sw = Gtk.ScrolledWindow(min_content_height=120, min_content_width=460, hexpand=True, vexpand=True)
            sw.add(tv)
            grid.attach(sw, 1, len(rows), 1, 1)
        d.get_content_area().add(grid)
        d.show_all()
        d.run()
        d.destroy()
