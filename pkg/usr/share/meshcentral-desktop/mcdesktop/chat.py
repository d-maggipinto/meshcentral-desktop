# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Native chat with the user of a remote computer.

Same protocol as the web UI's chat page (views/messenger.handlebars): both sides open
meshrelay.ashx?id=meshmessenger/<nodeid>/<userid>; the server pairs them and sends "c" ("cr" when it records
the session). Then JSON text frames: {action:'chat', msg}, {action:'outtext', value:bool} (typing),
{action:'random', random} (the larger random starts WebRTC: we send 1 so the remote page never does and
everything stays on the relay), ctrlChannel '102938' ping -> pong. Files, as the page does: the sender sends
{action:'file', id, name, size, type} and {action:'fileUploadStart', ...}, then {action:'fileData', id, data}
blocks of 4000 bytes as a "binary string" (one character per byte) and {action:'fileUploadEnd'}, each sent on a
{action:'fileUploadAck', id} from the receiver (which acks fileUploadStart twice); either side can send
{action:'fileUploadCancel', id}. The remote side is the server's own chat
page, opened by the agent (remote_session.open_chat_page: an app window when the console right allows it).
"""
import json
import os
import threading
import time
import urllib.parse

import websocket
from gi.repository import Gtk, Gdk, GLib, Pango

from . import remote_session as rs, rights, ui
from .client import CTRL, USER_AGENT, _ui

_CSS = b"""
.mcd-chat { border-left: 1px solid alpha(@theme_fg_color, 0.12); }
.mcd-chat-head { padding: 8px 6px 8px 12px; border-bottom: 1px solid alpha(@theme_fg_color, 0.12); }
.mcd-chat-title { font-weight: bold; }
.mcd-chat-list, .mcd-chat-list row { background: none; }
.mcd-chat-list row { padding: 0; }
.mcd-chat-bubble { padding: 6px 10px; border-radius: 12px; }
.mcd-chat-me { background-color: @theme_selected_bg_color; color: @theme_selected_fg_color; }
.mcd-chat-them { background-color: alpha(@theme_fg_color, 0.09); }
.mcd-chat-time { font-size: smaller; }
.mcd-chat-note { font-size: smaller; }
.mcd-chat-input { padding: 8px; border-top: 1px solid alpha(@theme_fg_color, 0.12); }
"""
_css_done = False


def _install_css():
    global _css_done
    if not _css_done:
        prov = Gtk.CssProvider()
        prov.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _css_done = True


def messenger_id(ctrl, node):
    q = urllib.parse.quote
    return "meshmessenger/" + q(node["_id"], safe="") + "/" + q((ctrl.userinfo or {}).get("_id", ""), safe="")


def remote_page_url(ctrl, node):
    """The chat page for the remote user, like the server's own (meshuser.js meshmessenger), no login cookie."""
    si = ctrl.serverinfo or {}
    path = "/messenger?id=" + messenger_id(ctrl, node)
    if si.get("domainsuffix"):
        path = "/" + si["domainsuffix"] + path
    return ctrl.server.url.rstrip("/") + path


class ChatSession:
    """Our end of the relay. State 0 closed, 1 connecting, 2 waiting for the remote user, 3 connected.
    Callbacks on the GTK loop: on_state(s), on_chat(text), on_typing(bool), on_note(text).
    File callbacks: on_file_in(fid, name, size), on_file_progress(fid, done, size), on_file_done(fid, data or
    None when cancelled). Reconnects by itself (like the web page) until stop()."""

    BLOCK = 4000
    MAX_IN = 100 * 1024 * 1024           # the page keeps a whole file in memory too

    def __init__(self, ctrl, node):
        self.ctrl, self.node = ctrl, node
        self.state = 0
        self.recorded = False
        self.on_state = self.on_chat = self.on_typing = self.on_note = None
        self.on_file_in = self.on_file_progress = self.on_file_done = None
        self._uploads = []               # [{id, name, size, data, ptr, started}], first = current
        self._downloads = {}             # key(id) -> {id, name, size, parts, got}
        self._ws = None
        self._stopped = True
        self._gen = 0
        self._queue = []                 # typed before the remote user joined
        self._lock = threading.Lock()

    def start(self):
        if not self._stopped:
            return
        self._stopped = False
        self._connect()

    def stop(self):
        self._stopped = True
        self._gen += 1
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._set_state(0)

    def _set_state(self, s):
        if s != self.state:
            self.state = s
            if self.on_state:
                self.on_state(s)

    def _connect(self):
        self._gen += 1
        gen = self._gen
        self._set_state(1)

        def got(cookie, _rcookie):
            if gen != self._gen or self._stopped:
                return
            url = (self.ctrl.server.ws("meshrelay.ashx") + "?id=" + messenger_id(self.ctrl, self.node) +
                   "&auth=" + urllib.parse.quote(cookie or "", safe=""))
            ws = websocket.WebSocketApp(
                url, header=[f"User-Agent: {USER_AGENT}"],
                on_open=lambda _w: _ui(self._opened, gen),
                on_message=lambda _w, data: _ui(self._message, gen, data),
                on_close=lambda *_: _ui(self._closed, gen),
                on_error=lambda *_: None)
            self._ws = ws
            threading.Thread(target=ws.run_forever, kwargs={"ping_interval": 30, "ping_timeout": 10},
                             daemon=True).start()
        self.ctrl.get_auth_cookie(got)

    def _opened(self, gen):
        if gen == self._gen:
            self._set_state(2)

    def _closed(self, gen):
        if gen != self._gen or self._stopped:
            return
        was = self.state
        self._ws = None
        self._set_state(1)
        self._cancel_all()
        if was == 3 and self.on_typing:
            self.on_typing(False)
        if was == 3 and self.on_note:
            self.on_note("The remote user left the chat. Waiting for them to come back...")
        GLib.timeout_add(1500 if was == 3 else 4000, lambda: (self._retry(gen), False)[1])

    def _retry(self, gen):
        if gen == self._gen and not self._stopped:
            self._connect()

    def _message(self, gen, data):
        if gen != self._gen:
            return
        if self.state < 3 and isinstance(data, str) and data in ("c", "cr"):
            self.recorded = data == "cr"
            self._set_state(3)
            self._send({"action": "random", "random": 1})
            if self.on_note:
                self.on_note("The remote user joined the chat" +
                             (". The server records this chat." if self.recorded else "."))
            queued, self._queue = self._queue, []
            for text in queued:
                self._send({"action": "chat", "msg": text})
            return
        if not isinstance(data, str) or not data.startswith("{"):
            return
        try:
            j = json.loads(data)
        except Exception:
            return
        if not isinstance(j, dict):
            return
        if str(j.get("ctrlChannel")) == CTRL:
            if j.get("type") == "ping":
                self._send({"ctrlChannel": CTRL, "type": "pong"})
            return
        a = j.get("action")
        if a == "chat" and isinstance(j.get("msg"), str):
            if self.on_typing:
                self.on_typing(False)
            if self.on_chat:
                self.on_chat(j["msg"])
        elif a == "outtext" and self.on_typing:
            self.on_typing(bool(j.get("value")))
        elif a in ("file", "fileUploadStart", "fileData", "fileUploadEnd", "fileUploadAck", "fileUploadCancel"):
            self._file_message(a, j)

    # ---- files ------------------------------------------------------------------------------------------------
    @staticmethod
    def _key(fid):
        return json.dumps(fid)

    def send_file(self, name, data):
        """Queue a file (bytes) for the remote user; returns its id. Only while connected."""
        if self.state != 3:
            return None
        fid = int.from_bytes(os.urandom(6), "big")
        self._uploads.append({"id": fid, "name": name, "size": len(data), "data": data.decode("latin-1"),
                              "ptr": 0, "started": False})
        self._send({"action": "file", "size": len(data), "id": fid, "type": "", "name": name})
        if len(self._uploads) == 1:
            self._next_upload()
        return fid

    def cancel_file(self, fid):
        k = self._key(fid)
        if any(self._key(u["id"]) == k for u in self._uploads):
            self._uploads = [u for u in self._uploads if self._key(u["id"]) != k]
            self._send({"action": "fileUploadCancel", "id": fid})
            if self._uploads and not self._uploads[0]["started"]:
                self._next_upload()
        elif k in self._downloads:
            del self._downloads[k]
            self._send({"action": "fileUploadCancel", "id": fid})
        else:
            return
        if self.on_file_done:
            self.on_file_done(fid, None)

    def _cancel_all(self):
        for u in list(self._uploads):
            if self.on_file_done:
                self.on_file_done(u["id"], None)
        for d in list(self._downloads.values()):
            if self.on_file_done:
                self.on_file_done(d["id"], None)
        self._uploads, self._downloads = [], {}

    def _next_upload(self):
        """Send the next step of the current upload (on each ack from the receiver)."""
        if not self._uploads:
            return
        u = self._uploads[0]
        if not u["started"]:
            u["started"] = True
            self._send({"action": "fileUploadStart", "size": u["size"], "id": u["id"], "type": "", "name": u["name"]})
        elif u["ptr"] >= u["size"]:
            self._send({"action": "fileUploadEnd", "size": u["size"], "id": u["id"], "type": "", "name": u["name"]})
            self._uploads.pop(0)
            if self.on_file_done:
                self.on_file_done(u["id"], b"")
            self._next_upload()
        else:
            block = u["data"][u["ptr"]:u["ptr"] + self.BLOCK]
            self._send({"action": "fileData", "id": u["id"], "data": block})
            u["ptr"] += len(block)
            if self.on_file_progress:
                self.on_file_progress(u["id"], u["ptr"], u["size"])

    def _file_message(self, a, j):
        fid = j.get("id")
        k = self._key(fid)
        if a == "fileUploadAck":
            if self._uploads and self._key(self._uploads[0]["id"]) == k:
                self._next_upload()
            elif self._uploads and not self._uploads[0]["started"]:
                self._next_upload()              # the ack of the previous file's end
            return
        if a == "fileUploadCancel":
            if any(self._key(u["id"]) == k for u in self._uploads):
                self._uploads = [u for u in self._uploads if self._key(u["id"]) != k]
                if self._uploads and not self._uploads[0]["started"]:
                    self._next_upload()
            elif k in self._downloads:
                del self._downloads[k]
            else:
                return
            if self.on_file_done:
                self.on_file_done(fid, None)
            return
        if a == "file":
            name, size = str(j.get("name") or "file"), j.get("size")
            if not isinstance(size, int) or size < 0 or size > self.MAX_IN:
                self._send({"action": "fileUploadCancel", "id": fid})
                if self.on_note:
                    self.on_note("The remote user sent a file that is too large for the chat (%s). Use the Files tab."
                                 % ui.one_line(name)[:80])
                return
            self._downloads[k] = {"id": fid, "name": name, "size": size, "parts": [], "got": 0}
            if self.on_file_in:
                self.on_file_in(fid, name, size)
            return
        d = self._downloads.get(k)
        if d is None:
            return
        if a == "fileUploadStart":
            self._send({"action": "fileUploadAck", "id": fid})       # twice, like the page: two blocks in flight
            self._send({"action": "fileUploadAck", "id": fid})
        elif a == "fileData" and isinstance(j.get("data"), str):
            part = j["data"].encode("latin-1", "replace")
            d["parts"].append(part)
            d["got"] += len(part)
            if d["got"] > d["size"]:
                self.cancel_file(fid)
                return
            self._send({"action": "fileUploadAck", "id": fid})
            if self.on_file_progress:
                self.on_file_progress(fid, d["got"], d["size"])
        elif a == "fileUploadEnd":
            del self._downloads[k]
            self._send({"action": "fileUploadAck", "id": fid})
            if self.on_file_done:
                self.on_file_done(fid, b"".join(d["parts"]))

    def _send(self, obj):
        ws = self._ws
        if ws is None:
            return
        try:
            with self._lock:
                ws.send(json.dumps(obj))
        except Exception:
            pass

    def say(self, text):
        """Send a chat line; kept until the remote user joins."""
        if self.state == 3:
            self._send({"action": "chat", "msg": text})
        else:
            self._queue.append(text)

    def typing(self, on):
        if self.state == 3:
            self._send({"action": "outtext", "value": bool(on)})


class ChatPanel(Gtk.Box):
    """The chat as a side panel (next to the remote desktop) or in its own window (ChatWindow).
    start() connects and opens the chat on the remote computer; stop() ends it; on_close() = the close button."""

    WIDTH = 330

    def __init__(self, app, node, on_close=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _install_css()
        self.app, self.node, self.on_close = app, node, on_close
        self.get_style_context().add_class("mcd-chat")
        self.set_size_request(self.WIDTH, -1)
        self._transcript = []
        self._typing_sent = False
        self._last_day = None

        head = Gtk.Box(spacing=4)
        head.get_style_context().add_class("mcd-chat-head")
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label="Chat", xalign=0)
        title.get_style_context().add_class("mcd-chat-title")
        self.status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.status.get_style_context().add_class("dim-label")
        tbox.pack_start(title, False, False, 0)
        tbox.pack_start(self.status, False, False, 0)
        head.pack_start(tbox, True, True, 0)
        for icon, tip, cb in (("window-new-symbolic", "Open the chat again on the remote computer",
                               self.open_remote),
                              ("document-save-symbolic", "Save the conversation to a text file", self._save),
                              ("window-close-symbolic", "End the chat", self._close_clicked)):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_valign(Gtk.Align.CENTER)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_a, f=cb: f())
            head.pack_start(b, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.get_style_context().add_class("mcd-chat-list")
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroll.add(self.list)
        self.pack_start(self.scroll, True, True, 0)

        self.typing_lbl = Gtk.Label(label="The remote user is typing...", xalign=0, margin_start=12,
                                    margin_bottom=2, no_show_all=True)
        self.typing_lbl.get_style_context().add_class("dim-label")
        self.typing_lbl.get_style_context().add_class("mcd-chat-note")
        self.pack_start(self.typing_lbl, False, False, 0)

        inp = Gtk.Box(spacing=6)
        inp.get_style_context().add_class("mcd-chat-input")
        self.entry = Gtk.Entry(placeholder_text="Type a message", hexpand=True, max_length=4096)
        self.entry.connect("activate", lambda *_: self._send())
        self.entry.connect("changed", lambda *_: self._typing_changed())
        send = Gtk.Button.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.BUTTON)
        send.set_tooltip_text("Send (Enter)")
        send.get_style_context().add_class("suggested-action")
        send.connect("clicked", lambda *_: self._send())
        attach = Gtk.Button.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON)
        attach.set_tooltip_text("Send a file to the remote user")
        attach.connect("clicked", lambda *_: self._pick_files())
        self.attach_btn = attach
        inp.pack_start(attach, False, False, 0)
        inp.pack_start(self.entry, True, True, 0)
        inp.pack_start(send, False, False, 0)
        self.pack_start(inp, False, False, 0)

        self.session = ChatSession(app.ctrl, node)
        self.session.on_state = self._on_state
        self.session.on_chat = lambda text: self._add(text, mine=False)
        self.session.on_typing = lambda on: self.typing_lbl.set_visible(on)
        self.session.on_note = self._note
        self.session.on_file_in = lambda fid, name, size: self._file_row(fid, name, size, mine=False)
        self.session.on_file_progress = self._file_progress
        self.session.on_file_done = self._file_done
        self._files = {}                 # key(id) -> {bar, label, button, name, size, mine, data}
        self._on_state(0)
        self.show_all()

    # ---- session ---------------------------------------------------------------------------------------------
    @property
    def active(self):
        return not self.session._stopped

    def start(self):
        if self.active:
            return
        self._note("Chat with the user of %s" % ui.one_line(self.node.get("name", "this computer")))
        self.session.start()
        self.open_remote()
        GLib.idle_add(self.entry.grab_focus)

    def stop(self):
        self.session.stop()

    def open_remote(self):
        if not self.active:
            self.start()
            return
        caps = rights.node_caps(self.app.ctrl, self.app.meshes, self.node)
        rs.open_chat_page(self.app.ctrl, self.node, caps, remote_page_url(self.app.ctrl, self.node),
                          lambda text: self._note(text))

    def _on_state(self, s):
        self.attach_btn.set_sensitive(s == 3)
        self.status.set_text({0: "Not connected", 1: "Connecting...",
                              2: "Waiting for the remote user",
                              3: "Connected" + (" (recorded)" if self.session.recorded else "")}[s])
        if s != 3:
            self.typing_lbl.hide()
            self._typing_sent = False

    def _close_clicked(self):
        self.stop()
        if self.on_close:
            self.on_close()

    # ---- messages -----------------------------------------------------------------------------------------------
    def _send(self):
        text = self.entry.get_text().strip()
        if not text or not self.active:
            return
        self.entry.set_text("")
        self.session.say(text)
        self._add(text, mine=True, queued=self.session.state != 3)

    def _typing_changed(self):
        on = bool(self.entry.get_text())
        if on != self._typing_sent and self.session.state == 3:
            self._typing_sent = on
            self.session.typing(on)

    def _row(self, child):
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.add(child)
        row.show_all()
        self.list.add(row)
        GLib.idle_add(self._scroll_end)

    def _scroll_end(self):
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _add(self, text, mine, queued=False):
        now = time.localtime()
        self._transcript.append("%s %s> %s" % (time.strftime("%H:%M:%S", now), "Me" if mine else "Remote", text))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_start=12 if not mine else 48,
                      margin_end=12 if mine else 48, margin_top=4, margin_bottom=2,
                      halign=Gtk.Align.END if mine else Gtk.Align.START)
        lbl = Gtk.Label(label=text, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True, xalign=0,
                        max_width_chars=34)
        lbl.set_can_focus(False)
        ctx = lbl.get_style_context()
        ctx.add_class("mcd-chat-bubble")
        ctx.add_class("mcd-chat-me" if mine else "mcd-chat-them")
        stamp = Gtk.Label(label=time.strftime("%H:%M", now) + ("  (sent when the remote user joins)" if queued
                                                                else ""),
                          xalign=1 if mine else 0)
        stamp.get_style_context().add_class("dim-label")
        stamp.get_style_context().add_class("mcd-chat-time")
        box.pack_start(lbl, False, False, 0)
        box.pack_start(stamp, False, False, 0)
        self._row(box)
        if not mine:
            top = self.get_toplevel()
            if not (isinstance(top, Gtk.Window) and top.is_active()) and hasattr(self.app, "notify"):
                self.app.notify("Chat - %s" % ui.one_line(self.node.get("name", "")), text[:200])

    # ---- files ----------------------------------------------------------------------------------------------
    def _pick_files(self):
        if self.session.state != 3:
            self._note("Files can be sent once the remote user has joined the chat.")
            return
        top = self.get_toplevel()
        d = Gtk.FileChooserNative.new("Send files to the remote user", top if isinstance(top, Gtk.Window) else None,
                                      Gtk.FileChooserAction.OPEN, "Send", "Cancel")
        d.set_select_multiple(True)
        paths = d.get_filenames() if d.run() == Gtk.ResponseType.ACCEPT else []
        d.destroy()
        for path in paths:
            self.send_path(path)

    def send_path(self, path):
        name = os.path.basename(path)
        try:
            if os.path.getsize(path) > ChatSession.MAX_IN:
                self._note("%s is too large for the chat (100 MB at most). Use the Files tab." % ui.one_line(name))
                return
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            self._note("%s: %s" % (ui.one_line(name), e))
            return
        fid = self.session.send_file(name, data)
        if fid is not None:
            self._transcript.append("%s Me> file %s (%d bytes)" % (time.strftime("%H:%M:%S"), name, len(data)))
            self._file_row(fid, name, len(data), mine=True)

    def _file_row(self, fid, name, size, mine):
        if not mine:
            self._transcript.append("%s Remote> file %s (%d bytes)" % (time.strftime("%H:%M:%S"), name, size))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=12 if not mine else 48,
                      margin_end=12 if mine else 48, margin_top=4, margin_bottom=2,
                      halign=Gtk.Align.END if mine else Gtk.Align.START)
        box.get_style_context().add_class("mcd-chat-bubble")
        box.get_style_context().add_class("mcd-chat-me" if mine else "mcd-chat-them")
        head = Gtk.Box(spacing=6)
        head.pack_start(Gtk.Image.new_from_icon_name("text-x-generic-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        lbl = Gtk.Label(label=name, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=24)
        lbl.set_tooltip_text(name)
        head.pack_start(lbl, True, True, 0)
        box.pack_start(head, False, False, 0)
        info = Gtk.Label(label=ui.fmt_size(size), xalign=0)
        info.get_style_context().add_class("mcd-chat-time")
        box.pack_start(info, False, False, 0)
        bar = Gtk.ProgressBar(fraction=0.0)
        box.pack_start(bar, False, False, 0)
        btn = Gtk.Button(label="Cancel", halign=Gtk.Align.START if not mine else Gtk.Align.END)
        btn.connect("clicked", lambda *_: self._file_button(fid))
        box.pack_start(btn, False, False, 0)
        self._files[ChatSession._key(fid)] = {"bar": bar, "info": info, "button": btn, "name": name, "size": size,
                                              "mine": mine, "data": None, "id": fid}
        self._row(box)
        if not mine:
            top = self.get_toplevel()
            if not (isinstance(top, Gtk.Window) and top.is_active()) and hasattr(self.app, "notify"):
                self.app.notify("Chat - %s" % ui.one_line(self.node.get("name", "")), "File: " + name[:120])

    def _file_progress(self, fid, done, size):
        f = self._files.get(ChatSession._key(fid))
        if f:
            f["bar"].set_fraction(min(1.0, done / size) if size else 1.0)

    def _file_done(self, fid, data):
        f = self._files.get(ChatSession._key(fid))
        if not f:
            return
        if data is None:
            f["info"].set_text(ui.fmt_size(f["size"]) + " - cancelled")
            f["button"].hide()
            return
        f["bar"].set_fraction(1.0)
        if f["mine"]:
            f["info"].set_text(ui.fmt_size(f["size"]) + " - sent")
            f["button"].hide()
        else:
            f["data"] = data
            f["info"].set_text(ui.fmt_size(f["size"]) + " - received")
            f["button"].set_label("Save...")
            f["button"].get_style_context().add_class("suggested-action")

    def _file_button(self, fid):
        f = self._files.get(ChatSession._key(fid))
        if not f:
            return
        if f["data"] is None:
            self.session.cancel_file(fid)
            return
        top = self.get_toplevel()
        d = Gtk.FileChooserNative.new("Save the file", top if isinstance(top, Gtk.Window) else None,
                                      Gtk.FileChooserAction.SAVE, "Save", "Cancel")
        d.set_do_overwrite_confirmation(True)
        d.set_current_name(ui.safe_filename(f["name"]))
        if d.run() == Gtk.ResponseType.ACCEPT:
            path = d.get_filename()
            try:
                tmp = path + ".part"
                with open(tmp, "wb") as out:
                    out.write(f["data"])
                os.replace(tmp, path)
                f["info"].set_text(ui.fmt_size(f["size"]) + " - saved")
            except OSError as e:
                ui.message(top, "Save the file", str(e))
        d.destroy()

    def _note(self, text):
        self._transcript.append("%s -- %s" % (time.strftime("%H:%M:%S"), text))
        lbl = Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER, margin=8, max_width_chars=40)
        lbl.get_style_context().add_class("dim-label")
        lbl.get_style_context().add_class("mcd-chat-note")
        self._row(lbl)

    def _save(self):
        top = self.get_toplevel()
        d = Gtk.FileChooserNative.new("Save the conversation", top if isinstance(top, Gtk.Window) else None,
                                      Gtk.FileChooserAction.SAVE, "Save", "Cancel")
        d.set_do_overwrite_confirmation(True)
        d.set_current_name(ui.safe_filename("Chat %s %s.txt" % (self.node.get("name", ""),
                                                                 time.strftime("%Y-%m-%d %H-%M"))))
        if d.run() == Gtk.ResponseType.ACCEPT:
            try:
                with open(d.get_filename(), "w", encoding="utf-8") as f:
                    f.write("\n".join(self._transcript) + "\n")
            except OSError as e:
                ui.message(top, "Save the conversation", str(e))
        d.destroy()


class ChatWindow(Gtk.Window):
    """The native chat in its own window, for devices whose remote desktop is not available to the account."""
    _open = {}

    @classmethod
    def show_for(cls, app, node):
        w = cls._open.get(node["_id"])
        if w is None:
            w = cls._open[node["_id"]] = cls(app, node)
        w.present()
        w.panel.start()
        return w

    def __init__(self, app, node):
        super().__init__(title="Chat - %s" % ui.one_line(node.get("name", "")))
        self.set_default_size(ChatPanel.WIDTH + 40, 560)
        if getattr(app, "main_win", None):
            self.set_transient_for(app.main_win)
        self.panel = ChatPanel(app, node, on_close=self.destroy)
        self.add(self.panel)
        self.connect("destroy", lambda *_: (self.panel.stop(), ChatWindow._open.pop(node["_id"], None)))
        self.show_all()
