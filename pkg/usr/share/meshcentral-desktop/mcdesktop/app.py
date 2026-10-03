# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Application object: owns config, the control connection, and top-level windows."""
import json
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk

from .login import LoginWindow
from .mainwindow import MainWindow
from . import osdep

APP_ID = "uk.co.cyvelion.MeshCentralDesktop"
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "meshcentral-desktop")
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "meshcentral-desktop")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def _private_dir(path):
    """Create (or tighten) a folder only this user can open."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.config = {}
        self.ctrl = None
        self.meshes = {}
        self.login_win = None
        self.main_win = None
        self._web_context = None
        from .update_ui import UpdateUI
        self.updates = UpdateUI(self)

    # ---- config ------------------------------------------------------------
    def load_config(self):
        try:
            with open(CONFIG_FILE) as f:
                self.config = json.load(f)
        except Exception:
            self.config = {}

    def save_config(self):
        """Private (0600 in a 0700 folder) and atomic: a crash mid-write keeps the old file."""
        try:
            _private_dir(CONFIG_DIR)
            tmp = CONFIG_FILE + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self.config, f, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            pass

    # ---- lifecycle ---------------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.load_config()
        _private_dir(DATA_DIR)             # WebKit cookies, server stats: not readable by other users
        from . import ui
        ui.set_time_format(self.config.get("date_format"))
        settings = Gtk.Settings.get_default()
        if self.config.get("dark", True):
            settings.set_property("gtk-application-prefer-dark-theme", True)

    def do_activate(self):
        if self.main_win:
            self.main_win.present()
        elif self.login_win:
            self.login_win.present()
        else:
            self._show_login()

    def _show_login(self):
        self.login_win = LoginWindow(self)
        self.login_win.present()

    def on_login(self, ctrl):
        self.ctrl = ctrl
        self.login_win = None
        # Record the server's live 5-minute stats samples from sign-in (CPU history, see
        # server_panel.StatsRecorder), independent of whether My Server is ever opened.
        from .server_panel import StatsRecorder
        self.stats_recorder = StatsRecorder(ctrl, DATA_DIR)
        self.main_win = MainWindow(self, ctrl)
        # Panels resolve device-group names via app.meshes; share the main window's dict.
        self.meshes = self.main_win.meshes
        self.main_win.present()
        # update check: at start and every 12 h (Updates dialog: on / off, channel)
        self.updates.start()
        if self.updates.info is not None and self.config.get("update_skip") != self.updates.info["text"]:
            self.updates.show_card()

    def sign_out(self):
        if self.ctrl:
            self.ctrl.close()
            self.ctrl = None
        if self.main_win:
            self.main_win.destroy()
            self.main_win = None
        # The next account must not inherit this one's web sessions: forget the HTTP session used for
        # downloads / Web-RDP and the viewer's cookies.
        self._dl_session = None
        self._clear_web_cookies()
        self._web_context = None
        self._show_login()

    def _clear_web_cookies(self):
        from . import webview
        webview.clear_site_data(self)

    # ---- shared web context for the embedded web views (Linux / WebKitGTK) ---
    def web_context(self):
        if self._web_context is None:
            from . import webview
            self._web_context = webview.new_web_context(DATA_DIR)
        return self._web_context


    # ---- helpers -----------------------------------------------------------
    def open_uri(self, uri):
        try:
            Gtk.show_uri_on_window(self.main_win, uri, Gdk.CURRENT_TIME)
        except Exception:
            pass

    def notify(self, title, body):
        if osdep.IS_WINDOWS:                     # GLib has no Windows notification backend
            win = self.main_win or self.login_win
            osdep.notify(osdep.window_handle(win), title, body)
            return
        n = Gio.Notification.new(title)
        if body:
            n.set_body(body)
        self.send_notification(None, n)


def main():
    import sys
    # Set the program name so the desktop environment matches the running window to
    # meshcentral-desktop.desktop (icon + "MeshCentral Desktop" name in the dash),
    # instead of falling back to the script name ("main.py") with no icon.
    GLib.set_prgname("meshcentral-desktop")
    GLib.set_application_name("MeshCentral Desktop")
    try:
        Gtk.Window.set_default_icon_name("meshcentral-desktop")
    except Exception:
        pass
    if osdep.IS_WINDOWS:
        # No D-Bus on Windows: without this GLib tries to auto-start a session bus at
        # Application.run() and the window only appears after a long wait. A named mutex
        # gives the single instance instead.
        os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "disabled:")
        osdep.set_app_identity()
        if not osdep.acquire_single_instance(APP_ID):
            return 0
    return App().run(sys.argv)
