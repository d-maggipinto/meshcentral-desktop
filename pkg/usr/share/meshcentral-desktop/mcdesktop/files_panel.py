# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Embeddable file manager panel using the agent file relay (protocol 5).

Ported from files.py (the standalone window) into a Gtk.Box panel that plugs into
the single-window Notebook. Implements the same JSON control messages the MeshCentral
web UI and meshctrl use: ls / mkdir / rename / rm and the chunked download / upload
handshake.
"""
import json
import os
import random
import re
import struct
import tempfile

from gi.repository import Gtk, GLib

from .client import Tunnel, PROTO_FILES
from . import ui

CHUNK = 65536
STATE_TEXT = {0: "Disconnected", 1: "Connecting…", 2: "Waiting for agent…", 3: "Connected"}


class FilesPanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.node = app, node
        self._started = False
        self.tunnel = None
        self.location = []          # current path components
        self.cur_path = ""
        self.download = None        # active download state
        self.upload = None          # active upload state

        # ---- toolbar (inline, not a header bar) ----
        toolbar = Gtk.Box(spacing=6, margin=6)
        nav = Gtk.Box()
        nav.get_style_context().add_class("linked")
        for icon, tip, cb in (("go-up-symbolic", "Parent folder", self.go_up),
                              ("go-home-symbolic", "Root", lambda *_: self.go_to([])),
                              ("view-refresh-symbolic", "Refresh", self.refresh)):
            nav.pack_start(self._btn(icon, tip, cb), False, False, 0)
        toolbar.pack_start(nav, False, False, 0)

        acts = Gtk.Box()
        acts.get_style_context().add_class("linked")
        for icon, tip, cb in (("folder-new-symbolic", "New folder", self.mkdir),
                              ("document-save-symbolic", "Download selected", self.download_selected),
                              ("document-send-symbolic", "Upload files", self.upload_files),
                              ("document-edit-symbolic", "Rename selected", self.rename_selected),
                              ("edit-delete-symbolic", "Delete selected", self.delete_selected)):
            acts.pack_start(self._btn(icon, tip, cb), False, False, 0)
        toolbar.pack_start(acts, False, False, 0)

        # Opening the tab does NOT connect: the user presses Connect (like Desktop / Terminal).
        self.connect_btn = Gtk.Button(label="Connect")
        self.connect_btn.get_style_context().add_class("suggested-action")
        self.connect_btn.connect("clicked", self._toggle)
        toolbar.pack_end(self.connect_btn, False, False, 0)
        self.status_label = Gtk.Label(label="Disconnected", xalign=1)
        self.status_label.get_style_context().add_class("dim-label")
        toolbar.pack_end(self.status_label, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

        self.path_label = Gtk.Label(label="/", xalign=0, ellipsize=3, margin_start=8, margin_end=8)
        self.path_label.get_style_context().add_class("dim-label")

        # name, size, type(d/f), raw_name, is_dir
        self.store = Gtk.ListStore(str, str, str, str, bool)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.connect("row-activated", self._on_activate)
        icon_r = Gtk.CellRendererPixbuf()
        name_r = Gtk.CellRendererText()
        c0 = Gtk.TreeViewColumn("Name")
        c0.pack_start(icon_r, False)
        c0.pack_start(name_r, True)
        c0.set_cell_data_func(icon_r, self._icon_cell)
        c0.add_attribute(name_r, "text", 0)
        c0.set_expand(True)
        c0.set_sort_column_id(0)
        self.tree.append_column(c0)
        for title, col in (("Size", 1), ("Type", 2)):
            c = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=col)
            c.set_resizable(True)
            self.tree.append_column(c)

        self.progress = Gtk.ProgressBar(show_text=True, text="", visible=False)
        self.info = Gtk.InfoBar(revealed=False, show_close_button=True)
        self.info.connect("response", lambda *_: self.info.set_revealed(False))
        self.info_label = Gtk.Label(wrap=True, xalign=0)
        self.info.get_content_area().add(self.info_label)

        self.pack_start(self.info, False, False, 0)
        self.pack_start(self.path_label, False, False, 4)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)
        self.pack_start(self.progress, False, False, 0)
        self.show_all()
        self.progress.hide()

    def _btn(self, icon, tip, cb):
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        b.set_tooltip_text(tip)
        b.connect("clicked", cb)
        return b

    def _icon_cell(self, _col, cell, model, it, _d):
        cell.set_property("icon-name", "folder" if model[it][4] else "text-x-generic")

    def _parent_window(self):
        top = self.get_toplevel()
        return top if isinstance(top, Gtk.Window) else None

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
        # a transfer interrupted by Disconnect or closing the device: close its file, drop the partial download
        if self.download:
            self._finish_download(ok=False)
        if self.upload and self.upload.get("fh"):
            try:
                self.upload["fh"].close()
            except Exception:
                pass
            self.upload = None

    # ---- connection --------------------------------------------------------
    def _toggle(self, *_):
        if self.tunnel and self.tunnel.state:
            self.disconnect_tunnel()
            self._on_state(0)
        else:
            self.connect_tunnel()

    def connect_tunnel(self):
        self.disconnect_tunnel()
        self.tunnel = Tunnel(self.app.ctrl, self.node["_id"], PROTO_FILES, binary_in_thread=False)
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
        if s == 0:
            self.store.clear()
        if s == 3:
            self.go_to([])

    def _on_console(self, msg):
        if msg:
            self.info_label.set_text(msg)
            self.info.set_message_type(Gtk.MessageType.WARNING)
            self.info.set_revealed(True)

    # ---- navigation --------------------------------------------------------
    def go_to(self, components):
        self.location = list(components)
        self.cur_path = "/".join(self.location)
        self.path_label.set_text("/" + self.cur_path)
        if self.tunnel and self.tunnel.state == 3:
            self.tunnel.send_json({"action": "ls", "reqid": 1, "path": self.cur_path})

    def go_up(self, *_):
        if self.location:
            self.go_to(self.location[:-1])

    def refresh(self, *_):
        self.go_to(self.location)

    def _on_activate(self, _tv, path, _col):
        row = self.store[path]
        if row[4]:
            self.go_to(self.location + [row[3]])

    def _selected(self):
        model, paths = self.tree.get_selection().get_selected_rows()
        return [(model[p][3], model[p][4], model[p][1]) for p in paths]  # (name, is_dir, size)

    # ---- incoming ----------------------------------------------------------
    # The agent file relay sends its JSON control messages (directory listing,
    # download/upload handshake) as BINARY frames that begin with '{' (0x7B).
    # Only raw download payload arrives as non-'{' binary. Some servers/agents may
    # also deliver JSON as a text frame, so both paths funnel into _handle_json.
    def _on_text(self, data):
        try:
            msg = json.loads(data)
        except Exception:
            return
        self._handle_json(msg)

    def _handle_json(self, msg):
        action = msg.get("action")
        if action == "ls" or (msg.get("path") is not None and msg.get("dir") is not None):
            self._show_listing(msg)
        elif action == "download":
            self._download_control(msg)
        elif action and action.startswith("upload"):
            self._upload_control(msg)
        elif action == "refresh":
            self.refresh()

    @staticmethod
    def _same_path(a):
        """Compare paths the agent's way: Windows agents answer "C:\\" for the requested "C:\\" folder and
        "C:\\Windows" for "C:\\/Windows", so separators and their repetition must not matter."""
        return re.sub("/+", "/", (a or "").replace("\\", "/")).strip("/")

    def _show_listing(self, msg):
        # Only apply if it matches the folder we asked for.
        if self._same_path(msg.get("path")) != self._same_path(self.cur_path):
            return
        self.store.clear()
        entries = msg.get("dir") or []
        # t: 1=drive,2=dir,3=file (t<3 => folder-like)
        entries.sort(key=lambda e: (e.get("t", 3) >= 3, (e.get("n") or "").lower()))
        for e in entries:
            is_dir = e.get("t", 3) < 3
            self.store.append([e.get("n", ""), "" if is_dir else ui.fmt_size(e.get("s")),
                               "Folder" if is_dir else "File", e.get("n", ""), is_dir])

    # ---- download ----------------------------------------------------------
    def download_selected(self, *_):
        sel = [s for s in self._selected() if not s[1]]
        if not sel:
            ui.message(self._parent_window(), "Select a file to download.")
            return
        if len(sel) > 1:
            ui.message(self._parent_window(), "Download one file at a time.", "Select a single file.")
            return
        name = sel[0][0]
        chooser = Gtk.FileChooserNative.new("Save file", self._parent_window(),
                                            Gtk.FileChooserAction.SAVE, "_Save", "_Cancel")
        chooser.set_current_name(ui.safe_filename(name, allow_dot=True))   # the name comes from the device
        chooser.set_do_overwrite_confirmation(True)
        dl = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if dl:
            chooser.set_current_folder(dl)
        if chooser.run() != Gtk.ResponseType.ACCEPT:
            chooser.destroy()
            return
        dest = chooser.get_filename()
        chooser.destroy()
        try:
            # write to a private temp file next to dest, renamed when the download completes
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".mcd-")
            fh = os.fdopen(fd, "wb")
        except OSError as ex:
            ui.message(self._parent_window(), "Cannot save file", str(ex), Gtk.MessageType.ERROR)
            return
        did = random.random()
        remote = (self.cur_path + "/" + name).strip("/")
        self.download = {"id": did, "fh": fh, "tmp": tmp, "dest": dest, "name": name, "path": remote, "got": 0}
        self._progress("Downloading %s" % name, 0)
        self.tunnel.send_json({"action": "download", "sub": "start", "id": did, "path": remote})

    def _download_control(self, msg):
        d = self.download
        if not d or msg.get("id") != d["id"]:
            return
        if msg.get("sub") == "start":
            self.tunnel.send_json({"action": "download", "sub": "startack", "id": d["id"]})
        elif msg.get("sub") == "cancel":
            self._finish_download(ok=False)

    def _on_binary(self, data):
        data = bytes(data)
        # File-relay JSON control frames (directory listing, download/upload handshake)
        # arrive as binary frames beginning with '{'. Route them to the JSON handler.
        # Real download payload frames begin with a 4-byte flags header (first byte 0x00).
        if data[:1] == b"{":
            try:
                msg = json.loads(data.decode("utf-8", "replace"))
            except Exception:
                return
            self._handle_json(msg)
            return
        d = self.download
        if not d or len(data) < 4:
            return
        flags = struct.unpack(">I", data[:4])[0]
        chunk = data[4:]
        if chunk:
            d["fh"].write(chunk)
            d["got"] += len(chunk)
            self._progress("Downloading %s" % d["name"], None, d["got"])
        if flags & 1:
            self._finish_download(ok=True)
        else:
            self.tunnel.send_json({"action": "download", "sub": "ack", "id": d["id"]})

    def _finish_download(self, ok):
        d, self.download = self.download, None
        if not d:
            return
        try:
            d["fh"].close()
        except Exception:
            pass
        self._progress_done()
        if ok:
            try:
                os.replace(d["tmp"], d["dest"])
            except OSError as ex:
                ui.message(self._parent_window(), "Cannot save file", str(ex), Gtk.MessageType.ERROR)
                ok = False
            else:
                self._notify("Download complete", d["name"])
        if not ok:
            try:
                os.remove(d["tmp"])              # only our temp file, never the existing destination
            except OSError:
                pass

    # ---- upload ------------------------------------------------------------
    def upload_files(self, *_):
        if not (self.tunnel and self.tunnel.state == 3):
            return
        chooser = Gtk.FileChooserNative.new("Upload files", self._parent_window(),
                                            Gtk.FileChooserAction.OPEN, "_Upload", "_Cancel")
        chooser.set_select_multiple(True)
        if chooser.run() != Gtk.ResponseType.ACCEPT:
            chooser.destroy()
            return
        files = chooser.get_filenames()
        chooser.destroy()
        self.upload = {"queue": list(files), "fh": None, "name": None, "size": 0, "sent": 0}
        self._upload_next()

    def _upload_next(self):
        u = self.upload
        if u["fh"]:
            try:
                u["fh"].close()
            except Exception:
                pass
            u["fh"] = None
        if not u["queue"]:
            self.upload = None
            self._progress_done()
            self.refresh()
            self._notify("Upload complete", "All files transferred.")
            return
        path = u["queue"].pop(0)
        name = os.path.basename(path)
        try:
            u["fh"] = open(path, "rb")
        except OSError as ex:
            ui.message(self._parent_window(), "Cannot read file", str(ex), Gtk.MessageType.ERROR)
            self._upload_next()
            return
        u["name"] = name
        u["size"] = os.path.getsize(path)
        u["sent"] = 0
        self._progress("Uploading %s" % name, 0)
        self.tunnel.send_json({"action": "upload", "reqid": 1, "path": self.cur_path,
                               "name": name, "size": u["size"]})

    def _upload_control(self, msg):
        u = self.upload
        if not u:
            return
        action = msg.get("action")
        if action in ("uploadstart", "uploadack"):
            self._upload_send_chunk()
        elif action == "uploaddone":
            self._upload_next()
        elif action == "uploaderror":
            ui.message(self._parent_window(), "Upload failed", msg.get("msg", ""), Gtk.MessageType.ERROR)
            self.upload = None
            self._progress_done()

    def _upload_send_chunk(self):
        u = self.upload
        if not u or not u["fh"]:
            return
        data = u["fh"].read(CHUNK)
        if not data:
            self.tunnel.send_json({"action": "uploaddone", "reqid": 1})
            return
        # Prefix a zero byte if data could be mistaken for JSON ('{' or NUL), as the web client does.
        if data[0] in (0, 123):
            self.tunnel.send(b"\x00" + data)
        else:
            self.tunnel.send(data)
        u["sent"] += len(data)
        self._progress("Uploading %s" % u["name"], None, u["sent"], u["size"])

    # ---- file operations ---------------------------------------------------
    def mkdir(self, *_):
        r = ui.form_dialog(self._parent_window(), "New folder", [("name", "Folder name:", "text", "")], "Create")
        if r and r["name"].strip():
            self.tunnel.send_json({"action": "mkdir", "reqid": 1,
                                   "path": (self.cur_path + "/" + r["name"].strip()).strip("/")})
            GLib.timeout_add(400, self.refresh)

    def delete_selected(self, *_):
        sel = self._selected()
        if not sel:
            return
        names = [s[0] for s in sel]
        if not ui.confirm(self._parent_window(), "Delete %d item(s)?" % len(names), ", ".join(names[:6]),
                          "Delete", destructive=True):
            return
        self.tunnel.send_json({"action": "rm", "reqid": 1, "path": self.cur_path,
                               "delfiles": names, "rec": True})
        GLib.timeout_add(400, self.refresh)

    def rename_selected(self, *_):
        sel = self._selected()
        if len(sel) != 1:
            ui.message(self._parent_window(), "Select a single item to rename.")
            return
        old = sel[0][0]
        r = ui.form_dialog(self._parent_window(), "Rename", [("name", "New name:", "text", old)], "Rename")
        if r and r["name"].strip() and r["name"] != old:
            self.tunnel.send_json({"action": "rename", "reqid": 1, "path": self.cur_path,
                                   "oldname": old, "newname": r["name"].strip()})
            GLib.timeout_add(400, self.refresh)

    # ---- progress + notify -------------------------------------------------
    def _progress(self, text, frac, got=None, total=None):
        self.progress.show()
        self.progress.set_text(text)
        if frac is not None:
            self.progress.set_fraction(frac)
        elif total:
            self.progress.set_fraction(min(1.0, got / total))
        else:
            self.progress.pulse()

    def _progress_done(self):
        self.progress.set_fraction(0)
        self.progress.hide()

    def _notify(self, title, body):
        self.app.notify(title, body)
