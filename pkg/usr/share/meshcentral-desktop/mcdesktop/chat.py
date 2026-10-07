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
from .osdep import IS_WINDOWS

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
# dark look of the floating chat in fullscreen (like the fullscreen toolbar); above the Windows look's sheet
_DARK_CSS = b"""
.mcd-chat-float { background-color: #1e2126; border: 1px solid rgba(255, 255, 255, 0.22); }
.mcd-chat-float, .mcd-chat-float label { color: #eceef1; }
.mcd-chat-float .dim-label { color: #9aa0a8; }
.mcd-chat-float .mcd-chat-head { border-bottom-color: rgba(255, 255, 255, 0.12); background-color: #262a30; }
.mcd-chat-float .mcd-chat-input { border-top-color: rgba(255, 255, 255, 0.12); }
.mcd-chat-float list, .mcd-chat-float row, .mcd-chat-float scrolledwindow, .mcd-chat-float viewport {
    background-color: transparent; }
.mcd-chat-float .mcd-chat-me, .mcd-chat-float .mcd-chat-me label { background-color: #2f6fd6; color: #ffffff; }
.mcd-chat-float .mcd-chat-them, .mcd-chat-float .mcd-chat-them label { background-color: #353a42; color: #eceef1; }
.mcd-chat-float .mcd-chat-me label, .mcd-chat-float .mcd-chat-them label { background-color: transparent; }
.mcd-chat-float button { background-color: transparent; background-image: none; border: none; box-shadow: none;
    color: #eceef1; }
.mcd-chat-float button:hover { background-color: rgba(255, 255, 255, 0.12); }
.mcd-chat-float button image { color: #eceef1; }
.mcd-chat-float button.suggested-action { background-color: #2f6fd6; color: #ffffff; }
.mcd-chat-float entry { background-color: #2b2f36; color: #eceef1; border: 1px solid rgba(255, 255, 255, 0.18);
    box-shadow: none; caret-color: #eceef1; }
.mcd-chat-float entry text { color: #eceef1; }
.mcd-chat-bubble-btn { background-color: #2f6fd6; background-image: none; border: none; border-radius: 0;
    min-width: 52px; min-height: 52px; padding: 0; box-shadow: none; color: #ffffff; }
.mcd-chat-bubble-btn:hover { background-color: #3b7de8; }
.mcd-chat-bubble-btn image, .mcd-chat-bubble-btn label { color: #ffffff; }
.mcd-chat-bubble-btn .mcd-chat-unread { font-weight: bold; font-size: 9pt; }
.mcd-chat-bubble-btn.flash { background-color: #e8892f; }
window.mcd-chat-bubble-win { background-color: transparent; }
"""
_css_done = False


def _install_css():
    global _css_done
    if not _css_done:
        prov = Gtk.CssProvider()
        prov.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        dark = Gtk.CssProvider()
        dark.load_from_data(_DARK_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), dark,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 30)
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
        self.set_hexpand(False)          # the entry's hexpand must not spread to the panel
        self._transcript = []
        self._typing_sent = False
        self._last_day = None

        head = Gtk.Box(spacing=4)
        head.get_style_context().add_class("mcd-chat-head")
        self.head_ev = Gtk.EventBox()               # drag handle of the floating chat (fullscreen)
        self.head_ev.add(head)
        self.on_minimise = self.on_incoming = None
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
                              ("edit-clear-all-symbolic", "Clear the conversation", self._clear),
                              ("window-close-symbolic", "End the chat", self._close_clicked)):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_valign(Gtk.Align.CENTER)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_a, f=cb: f())
            head.pack_start(b, False, False, 0)
            if icon == "edit-clear-all-symbolic":
                mb = self.min_btn = Gtk.Button.new_from_icon_name("go-down-symbolic", Gtk.IconSize.BUTTON)
                mb.set_relief(Gtk.ReliefStyle.NONE)
                mb.set_valign(Gtk.Align.CENTER)
                mb.set_tooltip_text("Minimise the chat to a bubble")
                mb.set_no_show_all(True)
                mb.connect("clicked", lambda *_: self.on_minimise and self.on_minimise())
                head.pack_start(mb, False, False, 0)
        self.pack_start(self.head_ev, False, False, 0)

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

    def do_get_preferred_width(self):
        # a fixed width: the natural width of the long notes / messages (wrapping labels) would otherwise make
        # the panel take half of the remote screen (verified on Windows CI: 704 px instead of 330)
        return self.WIDTH, self.WIDTH

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
        return row

    def _clear(self):
        """Like the page's Clear: empties this side's view and transcript (files still moving stay)."""
        busy = {f["row"] for f in self._files.values() if f.get("busy")}
        for row in self.list.get_children():
            if row not in busy:
                self.list.remove(row)
        self._files = {k: f for k, f in self._files.items() if f.get("busy")}
        self._transcript = []

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
        if not mine and self.on_incoming:
            self.on_incoming()
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
        f = self._files[ChatSession._key(fid)] = {"bar": bar, "info": info, "button": btn, "name": name, "size": size,
                                                  "mine": mine, "data": None, "id": fid, "busy": True}
        f["row"] = self._row(box)
        if not mine and self.on_incoming:
            self.on_incoming()
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
        f["busy"] = False
        if data is None:
            f["info"].set_text(ui.fmt_size(f["size"]) + " - cancelled")
            f["button"].set_no_show_all(True)
            f["button"].hide()
            return
        f["bar"].set_fraction(1.0)
        if f["mine"]:
            f["info"].set_text(ui.fmt_size(f["size"]) + " - sent")
            f["button"].set_no_show_all(True)
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
        flt = Gtk.FileFilter()
        flt.set_name("Text file (*.txt)")
        flt.add_pattern("*.txt")
        d.add_filter(flt)
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


def _round_corners(win):
    """Windows 11 / Server 2025: rounded corners and a border drawn by Windows (an undecorated GTK window's
    corners are square and solid)."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from .osdep import window_handle
        hwnd = window_handle(win)
        if hwnd:
            pref = ctypes.c_int(2)                                            # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(pref),
                                                       ctypes.sizeof(pref))   # DWMWA_WINDOW_CORNER_PREFERENCE
    except Exception:
        pass


def _keep_above(win):
    """Windows: above the fullscreen toolbar, which is a topmost window itself (pinned, it covered the chat)."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from .osdep import window_handle
        hwnd = window_handle(win)
        if hwnd:
            ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                              0x0001 | 0x0002)                # TOPMOST, NOSIZE | NOMOVE
    except Exception:
        pass


class OverlayChat:
    """Linux: the floating chat drawn INSIDE the fullscreen window, in the remote screen's Gtk.Overlay (WebKitGTK
    is a GTK widget). A separate window cannot be placed there: on Wayland the compositor decides where a window
    goes (GNOME centred the chat and its bubble). Same interface as FloatingChat; drag by the header, resize from
    the corner grip, minimise to a bubble in the bottom-right corner."""

    W, H, GAP = 360, 480, 24

    def __init__(self, overlay, bar_area=None):
        _install_css()
        self.overlay = overlay
        self.bar_area = bar_area
        self.panel = None
        self._sigs = []
        self.unread = 0
        self._flash_timer = None
        self._off = None                         # (right, bottom) distance the user dragged it to
        self._size = [self.W, self.H]
        self._drag_from = None
        self.win = self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.END,
                                        valign=Gtk.Align.END, no_show_all=True)
        self.frame.get_style_context().add_class("mcd-chat-float")
        self.frame.set_size_request(*self._size)
        grip_row = Gtk.Box()
        grip = Gtk.EventBox(halign=Gtk.Align.END)
        grip.set_size_request(16, 8)
        grip.set_tooltip_text("Resize")
        grip.add_events(Gdk.EventMask.BUTTON_MOTION_MASK)
        grip.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "nw-resize")))
        grip.connect("button-press-event", self._resize_start)
        grip.connect("motion-notify-event", self._resize_move)
        grip_row.pack_end(grip, False, False, 0)
        self.slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.pack_start(self.slot, True, True, 0)
        self.frame.pack_start(grip_row, False, False, 0)
        overlay.add_overlay(self.frame)

        self.bubble = Gtk.Box(halign=Gtk.Align.END, valign=Gtk.Align.END, no_show_all=True)
        self.bubble_btn = Gtk.Button(tooltip_text="Show the chat")
        self.bubble_btn.get_style_context().add_class("mcd-chat-bubble-btn")
        bb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        bb.pack_start(Gtk.Image.new_from_icon_name("user-available-symbolic", Gtk.IconSize.LARGE_TOOLBAR),
                      False, False, 0)
        self.unread_lbl = Gtk.Label(no_show_all=True)
        self.unread_lbl.get_style_context().add_class("mcd-chat-unread")
        bb.pack_start(self.unread_lbl, False, False, 0)
        self.bubble_btn.add(bb)
        self.bubble_btn.connect("clicked", lambda *_: self.restore())
        self.bubble.add(self.bubble_btn)
        overlay.add_overlay(self.bubble)

    @property
    def visible(self):
        return self.frame.get_visible()

    def attach(self, panel):
        if self.panel is not panel:
            old = panel.get_parent()
            if old is not None:
                old.remove(panel)
            self.slot.pack_start(panel, True, True, 0)
            self.panel = panel
            panel.min_btn.show()
            panel.on_minimise = self.minimise
            panel.on_incoming = self._incoming
            panel.head_ev.add_events(Gdk.EventMask.BUTTON_MOTION_MASK)
            self._sigs = [(panel.head_ev, panel.head_ev.connect("button-press-event", self._drag_start)),
                          (panel.head_ev, panel.head_ev.connect("motion-notify-event", self._drag_move))]
        self.restore(place=True)

    def detach(self):
        panel, self.panel = self.panel, None
        self.frame.hide()
        self.bubble.hide()
        if panel is None:
            return None
        for w, sig in self._sigs:
            w.disconnect(sig)
        self._sigs = []
        panel.min_btn.hide()
        panel.on_minimise = panel.on_incoming = None
        self.slot.remove(panel)
        return panel

    def hide(self):
        self.frame.hide()
        self.bubble.hide()

    def _corner(self):
        """Distance from the right and bottom edges: clear of a pinned toolbar on the right or bottom."""
        dx = dy = self.GAP
        area = self.bar_area() if self.bar_area else None
        if area and area[0] == "right":
            dx += area[1]
        elif area and area[0] == "bottom":
            dy += area[1]
        return dx, dy

    def _place(self, widget, off):
        widget.set_margin_end(max(0, int(off[0])))
        widget.set_margin_bottom(max(0, int(off[1])))

    def restore(self, place=False):
        self.bubble.hide()
        self.unread = 0
        self._update_bubble()
        if place or self._off is None:
            self._off = self._corner()
        self._place(self.frame, self._off)
        for c in self.frame.get_children():      # no_show_all: the frame's own show_all() does nothing
            c.show_all()
        self.frame.show()
        if self.panel:
            GLib.idle_add(self.panel.entry.grab_focus)

    def minimise(self):
        self.frame.hide()
        self._place(self.bubble, self._corner())
        self.bubble_btn.show_all()
        self.bubble.show()
        self._update_bubble()

    def _drag_start(self, _w, ev):
        if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 1:
            self._drag_from = (ev.x_root, ev.y_root, self._off[0], self._off[1])
        return False

    def _drag_move(self, _w, ev):
        if not self._drag_from or not (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        x0, y0, r0, b0 = self._drag_from
        ow, oh = self.overlay.get_allocated_width(), self.overlay.get_allocated_height()
        fw, fh = self.frame.get_allocated_width(), self.frame.get_allocated_height()
        r = min(max(0, r0 - (ev.x_root - x0)), max(0, ow - fw))
        b = min(max(0, b0 - (ev.y_root - y0)), max(0, oh - fh))
        self._off = (r, b)
        self._place(self.frame, self._off)
        return True

    def _resize_start(self, _w, ev):
        if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 1:
            self._drag_from = (ev.x_root, ev.y_root, self._size[0], self._size[1], self._off[0], self._off[1])
        return True

    def _resize_move(self, _w, ev):
        d = self._drag_from
        if not d or len(d) != 6 or not (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        # the grip is at the bottom-right: grow right/down by shrinking the right/bottom distance
        dx, dy = ev.x_root - d[0], ev.y_root - d[1]
        dx = min(dx, d[4])
        dy = min(dy, d[5])
        self._size = [max(280, int(d[2] + dx)), max(320, int(d[3] + dy))]
        self.frame.set_size_request(*self._size)
        self._off = (d[4] - (self._size[0] - d[2]), d[5] - (self._size[1] - d[3]))
        self._place(self.frame, self._off)
        return True

    def destroy(self):
        self.detach()
        if self._flash_timer:
            GLib.source_remove(self._flash_timer)
        for w in (self.frame, self.bubble):
            if w.get_parent() is not None:
                w.get_parent().remove(w)
            w.destroy()


class FloatingChat:
    """Fullscreen: the chat panel in its own small dark window over the remote screen, which keeps its full
    size. A real (undecorated) window, not a popup: Windows popups never get the keyboard. Drag it by its
    header, resize it from the corner grip; minimise turns it into a round bubble with the unread count."""

    W, H, GAP = 360, 480, 24

    def __init__(self, parent_window, bar_area=None):
        _install_css()
        self.parent = parent_window
        self.bar_area = bar_area                 # () -> (edge, px) of the pinned fullscreen toolbar, or None
        self._pos = None                         # where the user left it (restored after minimise)
        self.panel = None
        self._sigs = []
        self.unread = 0
        self._flash_timer = None
        self.win = Gtk.Window(title="Chat")
        self.win.set_decorated(False)
        self.win.set_transient_for(parent_window)          # stays above the fullscreen window
        self.win.set_skip_taskbar_hint(True)
        self.win.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.win.set_default_size(self.W, self.H)
        self.win.connect("delete-event", lambda *_: (self.minimise(), True)[1])   # Alt+F4 = minimise
        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.get_style_context().add_class("mcd-chat-float")
        grip_row = Gtk.Box()
        grip = Gtk.EventBox(halign=Gtk.Align.END)
        grip.set_size_request(16, 8)
        grip.set_tooltip_text("Resize")
        grip.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "se-resize")))
        grip.connect("button-press-event", self._resize)
        grip_row.pack_end(grip, False, False, 0)
        self.slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.pack_start(self.slot, True, True, 0)
        self.frame.pack_start(grip_row, False, False, 0)
        self.win.add(self.frame)
        self.win.connect("map", _round_corners)

        self.bubble = Gtk.Window(title="Chat")
        self.bubble.set_decorated(False)
        self.bubble.set_transient_for(parent_window)
        self.bubble.set_skip_taskbar_hint(True)
        self.bubble.set_accept_focus(False)
        self.bubble.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.bubble.get_style_context().add_class("mcd-chat-bubble-win")
        self.bubble_btn = Gtk.Button(tooltip_text="Show the chat")
        self.bubble_btn.get_style_context().add_class("mcd-chat-bubble-btn")
        bb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        bb.pack_start(Gtk.Image.new_from_icon_name("user-available-symbolic", Gtk.IconSize.LARGE_TOOLBAR),
                      False, False, 0)
        self.unread_lbl = Gtk.Label(no_show_all=True)
        self.unread_lbl.get_style_context().add_class("mcd-chat-unread")
        bb.pack_start(self.unread_lbl, False, False, 0)
        self.bubble_btn.add(bb)
        self.bubble_btn.connect("clicked", lambda *_: self.restore())
        self.bubble.add(self.bubble_btn)
        self.bubble.connect("map", _round_corners)

    @property
    def visible(self):
        return self.win.get_visible()

    def attach(self, panel):
        """Move the panel (with its conversation) into the floating window and show it."""
        if self.panel is not panel:
            old = panel.get_parent()
            if old is not None:
                old.remove(panel)
            self.slot.pack_start(panel, True, True, 0)
            self.panel = panel
            panel.min_btn.show()
            panel.on_minimise = self.minimise
            panel.on_incoming = self._incoming
            self._sigs = [(panel.head_ev, panel.head_ev.connect("button-press-event", self._drag))]
        self.restore(place=True)

    def detach(self):
        """Give the panel back (leaving fullscreen) and hide the windows."""
        panel, self.panel = self.panel, None
        self.win.hide()
        self.bubble.hide()
        if panel is None:
            return None
        for w, sig in self._sigs:
            w.disconnect(sig)
        self._sigs = []
        panel.min_btn.hide()
        panel.on_minimise = panel.on_incoming = None
        self.slot.remove(panel)
        return panel

    def hide(self):
        if self.win.get_visible():
            self._pos = self.win.get_position()
        self.win.hide()
        self.bubble.hide()

    def _monitor(self):
        gw = self.parent.get_window()
        disp = Gdk.Display.get_default()
        mon = disp.get_monitor_at_window(gw) if gw else disp.get_primary_monitor()
        return mon.get_geometry() if mon else None

    def _corner(self, w, h):
        """Bottom-right of the monitor, clear of a pinned toolbar on the right or bottom edge."""
        g = self._monitor()
        if not g:
            return None
        dx = dy = self.GAP
        area = self.bar_area() if self.bar_area else None
        if area and area[0] == "right":
            dx += area[1]
        elif area and area[0] == "bottom":
            dy += area[1]
        return g.x + g.width - w - dx, g.y + g.height - h - dy

    def restore(self, place=False):
        self.bubble.hide()
        self.unread = 0
        self._update_bubble()
        if not self.win.get_realized():
            self.frame.show_all()
            place = True
        w, h = self.win.get_size()
        pos = None if place else self._pos
        pos = pos or self._corner(w, h)
        # Position BEFORE showing: GTK then marks it as user-placed. Otherwise GDK on Windows centres a
        # transient window on its (fullscreen) parent at every map, and a move after the show lost.
        if pos:
            self.win.move(*pos)
        self.win.show()
        if pos:
            self.win.move(*pos)
        _keep_above(self.win)
        self.win.present()
        if self.panel:
            GLib.idle_add(self.panel.entry.grab_focus)

    def minimise(self):
        if self.win.get_visible():
            self._pos = self.win.get_position()
        self.win.hide()
        pos = self._corner(52, 52)
        if pos:
            self.bubble.move(*pos)               # before the show, see restore()
        self.bubble.show_all()
        if pos:
            self.bubble.move(*pos)
        _keep_above(self.bubble)
        self._update_bubble()

    def _incoming(self):
        if self.win.get_visible():
            return
        self.unread += 1
        self._update_bubble()
        ctx = self.bubble_btn.get_style_context()
        ctx.add_class("flash")
        if self._flash_timer:
            GLib.source_remove(self._flash_timer)
        self._flash_timer = GLib.timeout_add(2500, self._unflash)

    def _unflash(self):
        self._flash_timer = None
        self.bubble_btn.get_style_context().remove_class("flash")
        return False

    def _update_bubble(self):
        self.unread_lbl.set_text(str(self.unread) if self.unread < 100 else "99+")
        self.unread_lbl.set_visible(self.unread > 0)
        self.bubble_btn.set_tooltip_text("Show the chat" + (" (%d new)" % self.unread if self.unread else ""))

    def _drag(self, _w, ev):
        if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 1:
            self.win.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        return False

    def _resize(self, _w, ev):
        if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 1:
            self.win.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST, ev.button, int(ev.x_root), int(ev.y_root),
                                       ev.time)
        return True

    def destroy(self):
        self.detach()
        if self._flash_timer:
            GLib.source_remove(self._flash_timer)
        self.win.destroy()
        self.bubble.destroy()


# the unread count / flash of the bubble work the same in both
OverlayChat._incoming = FloatingChat._incoming
OverlayChat._unflash = FloatingChat._unflash
OverlayChat._update_bubble = FloatingChat._update_bubble
