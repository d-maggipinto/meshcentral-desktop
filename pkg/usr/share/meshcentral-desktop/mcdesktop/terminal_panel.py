# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Embeddable terminal panel connected to the agent through the relay: a VTE terminal on Linux,
xterm.js in Edge WebView2 on Windows (winterm.XtermTerminal, same API subset)."""
from gi.repository import Gtk, Gdk, GLib

from .osdep import IS_WINDOWS

if IS_WINDOWS:
    from .winterm import XtermTerminal as _Terminal
    _TEXT = None
else:
    import gi
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte
    _Terminal = Vte.Terminal
    _TEXT = Vte.Format.TEXT

from .client import Tunnel, PROTO_TERMINAL, PROTO_POWERSHELL, PROTO_USER_SHELL, PROTO_USER_POWERSHELL
from . import ui

STATE_TEXT = {0: "Disconnected", 1: "Connecting…", 2: "Waiting for agent…", 3: "Connected"}


def shell_options(node, linuxshell=None):
    """The web UI's terminal choices: [(label, relay protocol, require login)].
    Windows: Admin Shell 1, Admin PowerShell 6, User Shell 8, User PowerShell 9.
    Linux / macOS: Root Shell 1, User Shell 8 (as the logged-in desktop user), Login Shell 1 + requireLogin.
    serverinfo.linuxshell ('root' | 'user' | 'login') forces one type on non-Windows agents."""
    if ui.is_windows(node):
        return [("Admin Shell", PROTO_TERMINAL, False), ("Admin PowerShell", PROTO_POWERSHELL, False),
                ("User Shell", PROTO_USER_SHELL, False), ("User PowerShell", PROTO_USER_POWERSHELL, False)]
    opts = {"root": ("Root Shell", PROTO_TERMINAL, False), "user": ("User Shell", PROTO_USER_SHELL, False),
            "login": ("Login Shell", PROTO_TERMINAL, True)}
    if linuxshell in opts:
        return [opts[linuxshell]]
    return [opts["root"], opts["user"], opts["login"]]


class TerminalPanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.node = app, node
        self.protocol = PROTO_TERMINAL
        self.tunnel = None
        self._started = False
        self._last_size = None
        self._ever_connected = False
        self._disc_shown = False

        # ---- inline toolbar ----
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(4)

        self.shell = Gtk.ComboBoxText()
        self.shell_protos = []                     # (protocol, require login)
        for label, p, login in shell_options(node, (app.ctrl.serverinfo or {}).get("linuxshell")):
            self.shell.append_text(label)
            self.shell_protos.append((p, login))
        self.shell.set_active(0)
        bar.pack_start(self.shell, False, False, 0)

        self.connect_btn = Gtk.Button(label="Connect")
        self.connect_btn.get_style_context().add_class("suggested-action")
        self.connect_btn.connect("clicked", self._toggle)
        bar.pack_start(self.connect_btn, False, False, 0)

        self.status_label = Gtk.Label(label="Disconnected", xalign=0)
        self.status_label.get_style_context().add_class("dim-label")
        bar.pack_start(self.status_label, False, False, 4)

        for icon, tip, cb in (
                ("edit-copy-symbolic", "Copy (Ctrl+Shift+C)",
                 lambda *_: self.term.copy_clipboard_format(_TEXT)),
                ("edit-paste-symbolic", "Paste (Ctrl+Shift+V)",
                 lambda *_: self.term.paste_clipboard()),
                ("zoom-out-symbolic", "Smaller text", lambda *_: self._zoom(-0.1)),
                ("zoom-in-symbolic", "Bigger text", lambda *_: self._zoom(0.1))):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            bar.pack_end(b, False, False, 0)

        self.pack_start(bar, False, False, 0)

        # ---- console-message info bar ----
        self.info = Gtk.InfoBar(show_close_button=True)
        self.info.set_revealed(False)
        self.info.connect("response", lambda *_: self.info.set_revealed(False))
        self.info_label = Gtk.Label(wrap=True, xalign=0)
        self.info.get_content_area().add(self.info_label)
        self.pack_start(self.info, False, False, 0)

        # ---- terminal ----
        self.term = _Terminal()
        self.term.set_scrollback_lines(10000)
        self.term.set_mouse_autohide(True)
        self.term.connect("commit", self._on_commit)
        self.term.connect("char-size-changed", lambda *_: self._send_size())
        self.term.connect("key-press-event", self._on_key)
        self.term.connect("size-allocate", lambda *_: GLib.idle_add(self._send_size))
        # VTE scrolls inside a ScrolledWindow; xterm.js has its own scrollbar
        self.pack_start(self.term if IS_WINDOWS else ui.scrolled(self.term), True, True, 0)

    # ---- lifecycle ----
    def on_shown(self):
        if self._started:
            return
        self._started = True             # no auto-connect: pick the shell, then press Connect
        self.term.feed(b"Choose a shell and press Connect.\r\n")

    def teardown(self):
        self.disconnect_tunnel()

    # ---- helpers ----
    def _zoom(self, d):
        self.term.set_font_scale(max(0.5, min(3.0, self.term.get_font_scale() + d)))

    def _on_key(self, _w, ev):
        ctrl_shift = (ev.state & Gdk.ModifierType.CONTROL_MASK) and (ev.state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl_shift and ev.keyval in (Gdk.KEY_C, Gdk.KEY_c):
            self.term.copy_clipboard_format(_TEXT)
            return True
        if ctrl_shift and ev.keyval in (Gdk.KEY_V, Gdk.KEY_v):
            self.term.paste_clipboard()
            return True
        return False

    def _toggle(self, *_):
        if self.tunnel and self.tunnel.state:
            self.disconnect_tunnel()
        else:
            self.connect_tunnel()

    def connect_tunnel(self):
        self.disconnect_tunnel()
        self.protocol, login = self.shell_protos[self.shell.get_active()]
        self.term.reset(True, True)
        cols, rows = self.term.get_column_count(), self.term.get_row_count()
        opts = {"cols": cols, "rows": rows, "xterm": True}
        if login:
            opts["requireLogin"] = True            # the agent runs `login` instead of bash
        self.tunnel = Tunnel(self.app.ctrl, self.node["_id"], self.protocol, options=opts)
        self.tunnel.on_state = self._on_state
        self.tunnel.on_text = lambda s: self.term.feed(s.encode("utf-8"))
        self.tunnel.on_binary = lambda b: self.term.feed(bytes(b))
        self.tunnel.on_console = self._on_console
        self._last_size = (cols, rows)
        self.tunnel.start()

    def disconnect_tunnel(self):
        if self.tunnel:
            t, self.tunnel = self.tunnel, None
            t.on_state = None
            t.stop()
        self._on_state(0)

    def _on_state(self, s):
        self.status_label.set_text(STATE_TEXT.get(s, ""))
        self.connect_btn.set_label("Disconnect" if s else "Connect")
        ctx = self.connect_btn.get_style_context()
        if s:
            ctx.remove_class("suggested-action")
            self._disc_shown = False
        else:
            ctx.add_class("suggested-action")
        self.shell.set_sensitive(s == 0)
        if s == 3:
            self._ever_connected = True
            self.term.grab_focus()
            GLib.timeout_add(300, self._send_size)
        if s == 0 and not getattr(self, "_disc_shown", False) and self._ever_connected:
            # Make a closed session unmistakable (any disconnect path), without wiping
            # the scrollback the user may still want to read.
            self._disc_shown = True
            self.term.feed(b"\r\n\x1b[41;97m  Disconnected \xe2\x80\x94 click Connect to start a new session  \x1b[0m\r\n")

    def _on_console(self, msg):
        if msg:
            self.info_label.set_text(msg)
            self.info.set_message_type(Gtk.MessageType.WARNING)
            self.info.set_revealed(True)

    def _on_commit(self, _t, text, _size):
        if self.tunnel and self.tunnel.state == 3:
            self.tunnel.send(text)

    def _send_size(self):
        if self.tunnel and self.tunnel.state == 3:
            size = (self.term.get_column_count(), self.term.get_row_count())
            if size != self._last_size:
                self._last_size = size
                self.tunnel.send_ctrl({"type": "termsize", "cols": size[0], "rows": size[1]})
        return False
