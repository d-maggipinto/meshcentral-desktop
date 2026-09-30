# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Server-side file storage ("My Files" in the web UI, viewmode=5).

The server stores a personal folder per user ("My Files") plus one folder per device group
the user has the "server files" right on. Protocol (meshuser.js / webserver.js):
  * {action:'files'}                      -> {action:'files', filetree:{n:'Root', f:{<id>:{t,n,f,maxbytes}}}}
                                            (also pushed after every change)
    entries: t 1 = user root, 4 = device-group root, 2 = folder, 3 = file (s size, d mtime ms)
  * {action:'fileoperation', fileop, path:[rootid, sub...], ...}
        createfolder(newfolder) / delete(delfiles, rec) / rename(oldname,newname) /
        copy|move(scpath, names) / get(file) -> reply with base64 'data' (< 200 KB) / set(file, data)
  * uploadfile.ashx / downloadfile.ashx  (client.WebSession)
Requires site right 8 (file access); group folders need the group's "server files" right.
"""
import base64
import os
import time

from gi.repository import Gtk, GLib, Pango

from . import ui, rights
from .client import WebSession

EDIT_MAX = 200 * 1024            # server's limit for the websocket 'get' (fileop get)


def _fmt_date(ms):
    if not ms or ms == 111:       # 111 = placeholder the server uses for folders
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


def _tree_size(f):
    total = 0
    for e in (f or {}).values():
        total += e.get("s") or 0
        if e.get("f"):
            total += _tree_size(e["f"])
    return total


class ServerFilesPanel(Gtk.Box):
    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._handlers = []
        self.filetree = None
        self.path = []                 # [rootid, sub, sub...]; [] = Root
        self._clip = None              # {"op": "copy"|"move", "path": [...], "names": [...]}
        self._web = None
        self._edit_waiters = {}

        self.allowed = rights.has_site(app.ctrl, rights.SITE_FILEACCESS)
        if not self.allowed:
            msg = Gtk.Label(label="Your account does not have access to server files (called “My Files” in the web interface).\n"
                                  "An administrator can grant the “Server Files” permission.",
                            justify=Gtk.Justification.CENTER)
            msg.get_style_context().add_class("dim-label")
            self.pack_start(msg, True, True, 0)
            self.show_all()
            return

        bar = Gtk.Box(spacing=6, margin=8)
        nav = Gtk.Box()
        nav.get_style_context().add_class("linked")
        self.btn_up = self._btn(nav, "go-up-symbolic", "Up one folder", self.go_up)
        self._btn(nav, "view-refresh-symbolic", "Refresh", self.refresh)
        bar.pack_start(nav, False, False, 0)

        acts = Gtk.Box()
        acts.get_style_context().add_class("linked")
        self.btn_new = self._btn(acts, "folder-new-symbolic", "New folder", self.new_folder)
        self.btn_upload = self._btn(acts, "document-send-symbolic", "Upload files", self.upload)
        self.btn_download = self._btn(acts, "document-save-symbolic", "Download selected", self.download)
        self.btn_edit = self._btn(acts, "document-edit-symbolic", "Edit text file", self.edit)
        self.btn_rename = self._btn(acts, "insert-text-symbolic", "Rename", self.rename)
        self.btn_delete = self._btn(acts, "edit-delete-symbolic", "Delete selected", self.delete)
        bar.pack_start(acts, False, False, 0)

        clip = Gtk.Box()
        clip.get_style_context().add_class("linked")
        self.btn_cut = self._btn(clip, "edit-cut-symbolic", "Cut", lambda *_: self.clip("move"))
        self.btn_copy = self._btn(clip, "edit-copy-symbolic", "Copy", lambda *_: self.clip("copy"))
        self.btn_paste = self._btn(clip, "edit-paste-symbolic", "Paste here", self.paste)
        bar.pack_start(clip, False, False, 0)

        self.status = Gtk.Label(xalign=1)
        self.status.get_style_context().add_class("dim-label")
        bar.pack_end(self.status, True, True, 0)
        self.pack_start(bar, False, False, 0)

        self.crumb = Gtk.Label(xalign=0, margin_start=10, margin_end=10,
                               ellipsize=Pango.EllipsizeMode.START)
        self.pack_start(self.crumb, False, False, 2)

        # icon, name, size, modified, key, is_dir, size_bytes
        self.store = Gtk.ListStore(str, str, str, str, str, bool, float)
        self.tree = Gtk.TreeView(model=self.store, enable_search=True, search_column=1)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.get_selection().connect("changed", lambda *_: self._update_buttons())
        self.tree.connect("row-activated", self._on_activate)
        col = Gtk.TreeViewColumn("Name")
        ic = Gtk.CellRendererPixbuf()
        tx = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(ic, False)
        col.pack_start(tx, True)
        col.add_attribute(ic, "icon-name", 0)
        col.add_attribute(tx, "text", 1)
        col.set_expand(True)
        col.set_sort_column_id(1)
        self.tree.append_column(col)
        for title, i, sort in (("Size", 2, 6), ("Modified", 3, 3)):
            c = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            c.set_resizable(True)
            c.set_sort_column_id(sort)
            self.tree.append_column(c)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)

        self.progress = Gtk.ProgressBar(show_text=True, margin=6)
        self.progress.set_no_show_all(True)
        self.pack_start(self.progress, False, False, 0)
        self.show_all()
        self._update_buttons()

    def _btn(self, box, icon, tip, cb):
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        b.set_tooltip_text(tip)
        b.connect("clicked", lambda *_: cb())
        box.add(b)
        return b

    # ---- lifecycle ---------------------------------------------------------
    def on_shown(self):
        if self._started or not self.allowed:
            return
        self._started = True
        for action, cb in (("files", self._on_files), ("fileoperation", self._on_fileop)):
            self.app.ctrl.on(action, cb)
            self._handlers.append((action, cb))
        self.refresh()

    def teardown(self):
        for action, cb in self._handlers:
            self.app.ctrl.off(action, cb)
        self._handlers = []

    # ---- data --------------------------------------------------------------
    def refresh(self):
        self.status.set_text("Loading…")
        self.app.ctrl.send({"action": "files"})

    def _on_files(self, msg):
        self.filetree = msg.get("filetree") or {}
        # stay in the current folder if it still exists
        while self.path and self._folder(self.path) is None:
            self.path = self.path[:-1]
        self._render()

    def _folder(self, path):
        """Dict of entries for a path ([] = the roots)."""
        f = (self.filetree or {}).get("f") or {}
        for key in path:
            e = f.get(key)
            if e is None:
                return None
            f = e.get("f") or {}
        return f

    def _root_entry(self):
        return ((self.filetree or {}).get("f") or {}).get(self.path[0]) if self.path else None

    def _link(self, *extra):
        """Server path for HTTP transfers: 'user//name/sub/file'."""
        return "/".join(list(self.path) + list(extra))

    def _render(self):
        entries = self._folder(self.path) or {}
        self.tree.set_model(None)
        self.store.clear()
        for key, e in entries.items():
            t = e.get("t", 3)
            is_dir = t != 3
            icon = {1: "user-home-symbolic", 4: "network-workgroup-symbolic"}.get(t, "folder" if is_dir else "text-x-generic")
            name = e.get("n") or key
            size = e.get("s") or 0
            self.store.append([icon, name, "" if is_dir else ui.fmt_size(size), _fmt_date(e.get("d")),
                               key, is_dir, float(-1 if is_dir else size)])
        self.store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.tree.set_model(self.store)
        names = ["Root"]
        f = (self.filetree or {}).get("f") or {}
        for i, key in enumerate(self.path):
            e = f.get(key) or {}
            names.append(e.get("n") or key)
            f = e.get("f") or {}
        self.crumb.set_markup("<b>" + GLib.markup_escape_text("  ›  ".join(names)) + "</b>")
        root = self._root_entry()
        if root is not None:
            used = _tree_size(root.get("f"))
            quota = root.get("maxbytes")
            self.status.set_text(f"{len(entries)} items · {ui.fmt_size(used)}"
                                 + (f" of {ui.fmt_size(quota)}" if quota else ""))
        else:
            self.status.set_text(f"{len(entries)} storage areas")
        self._update_buttons()

    def _selected(self):
        model, paths = self.tree.get_selection().get_selected_rows()
        return [(model[p][4], model[p][5], model[p][6]) for p in paths]      # key, is_dir, size

    def _update_buttons(self):
        in_folder = bool(self.path)
        sel = self._selected()
        files = [s for s in sel if not s[1]]
        self.btn_up.set_sensitive(in_folder)
        for b in (self.btn_new, self.btn_upload):
            b.set_sensitive(in_folder)
        self.btn_download.set_sensitive(in_folder and bool(files))
        self.btn_edit.set_sensitive(in_folder and len(sel) == 1 and len(files) == 1 and files[0][2] < EDIT_MAX)
        self.btn_rename.set_sensitive(in_folder and len(sel) == 1)
        for b in (self.btn_delete, self.btn_cut, self.btn_copy):
            b.set_sensitive(in_folder and bool(sel))
        self.btn_paste.set_sensitive(in_folder and self._clip is not None)

    # ---- navigation --------------------------------------------------------
    def _on_activate(self, _tv, tpath, _col):
        row = self.store[tpath]
        if row[5]:
            self.path = self.path + [row[4]]
            self._render()
        else:
            self.download()

    def go_up(self):
        if self.path:
            self.path = self.path[:-1]
            self._render()

    # ---- operations (control channel) ---------------------------------------
    def _op(self, **kw):
        m = {"action": "fileoperation", "path": list(self.path)}
        m.update(kw)
        self.app.ctrl.send(m)
        self.status.set_text("Working…")

    def _names(self):
        return [k for k, _d, _s in self._selected()]

    def new_folder(self):
        r = ui.form_dialog(self.get_toplevel(), "New folder", [("name", "Folder name:", "text", "")], "Create")
        if r and r["name"].strip():
            self._op(fileop="createfolder", newfolder=r["name"].strip())

    def rename(self):
        names = self._names()
        if len(names) != 1:
            return
        r = ui.form_dialog(self.get_toplevel(), "Rename", [("name", "New name:", "text", names[0])], "Rename")
        if r and r["name"].strip() and r["name"].strip() != names[0]:
            self._op(fileop="rename", oldname=names[0], newname=r["name"].strip())

    def delete(self):
        names = self._names()
        if not names:
            return
        if ui.confirm(self.get_toplevel(), f"Delete {len(names)} item(s)?",
                      ", ".join(names[:6]) + (" …" if len(names) > 6 else ""), "Delete", destructive=True):
            self._op(fileop="delete", delfiles=names, rec=True)

    def clip(self, op):
        names = self._names()
        if names:
            self._clip = {"op": op, "path": list(self.path), "names": names}
            self.status.set_text(f"{'Cut' if op == 'move' else 'Copied'} {len(names)} item(s), open a folder and Paste")
            self._update_buttons()

    def paste(self):
        c = self._clip
        if not c or not self.path:
            return
        if c["path"] == self.path:
            self.status.set_text("Already in this folder")
            return
        self._op(fileop=c["op"], scpath=c["path"], names=c["names"])
        if c["op"] == "move":
            self._clip = None
        self._update_buttons()

    # ---- edit small text files (fileop get/set) ------------------------------
    def edit(self):
        sel = self._selected()
        if len(sel) != 1 or sel[0][1]:
            return
        name = sel[0][0]
        self._edit_waiters[(tuple(self.path), name)] = True
        self._op(fileop="get", file=name)

    def _on_fileop(self, msg):
        if msg.get("fileop") != "get" or "data" not in msg:
            return
        key = (tuple(msg.get("path") or []), msg.get("file"))
        if not self._edit_waiters.pop(key, None):
            return
        try:
            text = base64.b64decode(msg["data"]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            ui.message(self.get_toplevel(), "Cannot edit this file", "It is not a UTF-8 text file.")
            self._render()
            return
        self._render()
        r = ui.form_dialog(self.get_toplevel(), f"Edit - {msg.get('file')}",
                           [("text", "Content:", "multiline", text)], "Save")
        if r is not None and r["text"] != text:
            self.app.ctrl.send({"action": "fileoperation", "fileop": "set", "path": list(key[0]),
                                "file": key[1], "data": base64.b64encode(r["text"].encode("utf-8")).decode()})
            self.status.set_text("Saved")

    # ---- transfers (HTTP) -----------------------------------------------------
    def _session(self):
        if self._web is None:
            self._web = WebSession(self.app.ctrl)
        return self._web

    def _progress(self, text, done, total):
        self.progress.show()
        self.progress.set_text(text)
        if total:
            self.progress.set_fraction(min(1.0, done / total))
        else:
            self.progress.pulse()

    def download(self):
        files = [(k, s) for k, d, s in self._selected() if not d]
        if not files:
            return
        top = self.get_toplevel()
        if len(files) == 1:
            ch = Gtk.FileChooserNative.new("Save file", top, Gtk.FileChooserAction.SAVE, "_Save", "_Cancel")
            ch.set_current_name(files[0][0])
            ch.set_do_overwrite_confirmation(True)
        else:
            ch = Gtk.FileChooserNative.new("Download to folder", top, Gtk.FileChooserAction.SELECT_FOLDER,
                                           "_Download", "_Cancel")
        dl = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if dl:
            ch.set_current_folder(dl)
        if ch.run() != Gtk.ResponseType.ACCEPT:
            ch.destroy()
            return
        target = ch.get_filename()
        ch.destroy()
        jobs = [(k, s, target if len(files) == 1 else os.path.join(target, k)) for k, s in files]
        self._download_next(jobs, list(self.path))

    def _download_next(self, jobs, path):
        if not jobs:
            self.progress.hide()
            self.status.set_text("Download complete")
            self.app.notify("Download complete", "")
            return
        name, size, dest = jobs[0]
        link = "/".join(path + [name])

        def done(err):
            if err and size < EDIT_MAX:
                self._download_small(path, name, dest, lambda ok: self._download_next(jobs[1:], path) if ok else None)
                return
            if err:
                self.progress.hide()
                ui.message(self.get_toplevel(), f"Download of {name} failed", err, Gtk.MessageType.ERROR)
                return
            self._download_next(jobs[1:], path)
        self._session().download(link, dest, lambda d, t: self._progress(f"Downloading {name}", d, t or size), done)

    def _download_small(self, path, name, dest, cont):
        """Fallback when the HTTP sign-in is not possible: websocket 'get' (< 200 KB)."""
        def on_reply(msg):
            if msg.get("fileop") == "get" and msg.get("file") == name and list(msg.get("path") or []) == path \
                    and "data" in msg:
                self.app.ctrl.off("fileoperation", on_reply)
                try:
                    with open(dest, "wb") as f:
                        f.write(base64.b64decode(msg["data"]))
                    cont(True)
                except OSError as ex:
                    ui.message(self.get_toplevel(), "Cannot save file", str(ex), Gtk.MessageType.ERROR)
                    cont(False)
        self.app.ctrl.on("fileoperation", on_reply)
        self.app.ctrl.send({"action": "fileoperation", "fileop": "get", "path": path, "file": name})

    def upload(self):
        if not self.path:
            return
        ch = Gtk.FileChooserNative.new("Upload files", self.get_toplevel(), Gtk.FileChooserAction.OPEN,
                                       "_Upload", "_Cancel")
        ch.set_select_multiple(True)
        if ch.run() != Gtk.ResponseType.ACCEPT:
            ch.destroy()
            return
        paths = ch.get_filenames()
        ch.destroy()
        existing = set((self._folder(self.path) or {}).keys())
        clash = [os.path.basename(p) for p in paths if os.path.basename(p) in existing]
        if clash and not ui.confirm(self.get_toplevel(), "Overwrite existing files?",
                                    ", ".join(clash[:6]), "Overwrite", destructive=True):
            return
        self._upload_next(paths, self._link())

    def _upload_next(self, paths, link):
        if not paths:
            self.progress.hide()
            self.status.set_text("Upload complete")
            self.app.ctrl.send({"action": "files"})
            return
        p = paths[0]
        name = os.path.basename(p)

        def done(err):
            if err:
                self.progress.hide()
                ui.message(self.get_toplevel(), f"Upload of {name} failed", err, Gtk.MessageType.ERROR)
                return
            self._upload_next(paths[1:], link)
        self._session().upload(link, p, lambda d, t: self._progress(f"Uploading {name}", d, t), done)
