# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Login window: server address, username, password, optional MFA token."""
import gi
gi.require_version("Secret", "1")
from gi.repository import Gtk, GLib, Secret

from .client import ControlConnection
from . import ui

SCHEMA = Secret.Schema.new(
    "uk.co.cyvelion.MeshCentralDesktop", Secret.SchemaFlags.NONE,
    {"server": Secret.SchemaAttributeType.STRING, "username": Secret.SchemaAttributeType.STRING})


def store_password(server, username, password):
    try:
        Secret.password_store_sync(
            SCHEMA, {"server": server, "username": username}, Secret.COLLECTION_DEFAULT,
            f"MeshCentral {username}@{server}", password, None)
        return True
    except Exception:
        return False


def load_password(server, username):
    try:
        return Secret.password_lookup_sync(SCHEMA, {"server": server, "username": username}, None)
    except Exception:
        return None


def clear_password(server, username):
    try:
        Secret.password_clear_sync(SCHEMA, {"server": server, "username": username}, None)
    except Exception:
        pass


class LoginWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MeshCentral - Sign in")
        self.app = app
        self.set_default_size(420, -1)
        self.set_resizable(False)
        self.set_icon_name("meshcentral-desktop")
        self.conn = None

        hb = Gtk.HeaderBar(show_close_button=True, title="Sign in")
        self.set_titlebar(hb)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=24)
        self.add(outer)

        logo = Gtk.Image.new_from_icon_name("meshcentral-desktop", Gtk.IconSize.DIALOG)
        logo.set_pixel_size(64)
        outer.pack_start(logo, False, False, 0)
        title = Gtk.Label()
        title.set_markup("<span size='large' weight='bold'>MeshCentral Desktop</span>")
        outer.pack_start(title, False, False, 0)

        grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        outer.pack_start(grid, False, False, 0)

        cfg = app.config
        self.server = Gtk.Entry(hexpand=True, placeholder_text="https://remote.example.com",
                                text=cfg.get("server", ""), activates_default=True)
        self.username = Gtk.Entry(hexpand=True, text=cfg.get("username", ""), activates_default=True)
        self.password = Gtk.Entry(hexpand=True, visibility=False, activates_default=True)
        self.token = Gtk.Entry(hexpand=True, placeholder_text="Only if 2FA is enabled",
                               activates_default=True)
        rows = [("Server", self.server), ("Username", self.username),
                ("Password", self.password), ("2FA code", self.token)]
        for i, (label, w) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)

        self.remember = Gtk.CheckButton(label="Remember password (system keyring)",
                                        active=bool(cfg.get("remember")))
        outer.pack_start(self.remember, False, False, 0)

        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.get_style_context().add_class("dim-label")
        sbox = Gtk.Box(spacing=8)
        sbox.pack_start(self.spinner, False, False, 0)
        sbox.pack_start(self.status, True, True, 0)
        outer.pack_start(sbox, False, False, 0)

        self.button = Gtk.Button(label="Sign in")
        self.button.set_can_default(True)
        self.button.get_style_context().add_class("suggested-action")
        self.button.connect("clicked", self._on_login)
        outer.pack_start(self.button, False, False, 0)
        self.button.grab_default()

        # Prefill remembered password
        if cfg.get("server") and cfg.get("username") and cfg.get("remember"):
            pw = load_password(cfg["server"], cfg["username"])
            if pw:
                self.password.set_text(pw)

        self.username.connect("changed", self._prefill_pw)
        self.server.connect("changed", self._prefill_pw)
        self.show_all()

    def _prefill_pw(self, *_):
        if self.remember.get_active():
            pw = load_password(self.server.get_text().strip(), self.username.get_text().strip())
            if pw:
                self.password.set_text(pw)

    def _set_busy(self, busy, text=""):
        self.button.set_sensitive(not busy)
        for w in (self.server, self.username, self.password, self.token):
            w.set_sensitive(not busy)
        (self.spinner.start if busy else self.spinner.stop)()
        self.status.set_text(text)

    def _on_login(self, *_):
        server = self.server.get_text().strip()
        username = self.username.get_text().strip()
        password = self.password.get_text()
        token = self.token.get_text().strip() or None
        if not (server and username and password):
            self._set_busy(False, "Enter server, username and password.")
            return
        self._set_busy(True, "Connecting…")
        self.conn = ControlConnection(server, username, password, token)
        self.conn.on_open = self._on_open
        self.conn.on_close = self._on_close
        self.conn.connect()

    def _on_open(self):
        self.status.set_text("Authenticating…")

        # We know auth succeeded once we receive serverinfo/userinfo.
        def check():
            if self.conn and self.conn.userinfo:
                self._success()
                return False
            return True
        GLib.timeout_add(150, check)
        GLib.timeout_add(8000, self._auth_timeout)

    def _auth_timeout(self):
        if self.conn and not self.conn.userinfo and self.conn.connected:
            self._set_busy(False, "No response from server. Check the address.")
            self.conn.close()
        return False

    def _success(self):
        server = self.server.get_text().strip()
        username = self.username.get_text().strip()
        cfg = self.app.config
        cfg["server"], cfg["username"] = server, username
        cfg["remember"] = self.remember.get_active()
        self.app.save_config()
        if self.remember.get_active():
            store_password(server, username, self.password.get_text())
        else:
            clear_password(server, username)
        conn = self.conn
        self.conn = None
        self.app.on_login(conn)
        self.destroy()

    def _on_close(self, reason):
        if reason and reason.get("msg") == "tokenrequired":
            self._set_busy(False, "Two-factor code required. Enter your 2FA code and sign in again.")
            self.token.grab_focus()
        elif reason and reason.get("cause") == "noauth":
            self._set_busy(False, "Invalid username, password or 2FA code.")
        elif reason and reason.get("cause") == "error":
            self._set_busy(False, "Cannot reach server: %s" % reason.get("msg", "connection failed"))
        else:
            self._set_busy(False, "Login failed. Check your details and try again.")
