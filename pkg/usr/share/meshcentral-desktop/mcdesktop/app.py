# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Application object: owns config, the control connection, and top-level windows."""
import json
import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gio, GLib, WebKit2, Gdk

from .login import LoginWindow
from .mainwindow import MainWindow

APP_ID = "uk.co.cyvelion.MeshCentralDesktop"
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "meshcentral-desktop")
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "meshcentral-desktop")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.config = {}
        self.ctrl = None
        self.meshes = {}
        self.login_win = None
        self.main_win = None
        self._web_context = None

    # ---- config ------------------------------------------------------------
    def load_config(self):
        try:
            with open(CONFIG_FILE) as f:
                self.config = json.load(f)
        except Exception:
            self.config = {}

    def save_config(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    # ---- lifecycle ---------------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.load_config()
        os.makedirs(DATA_DIR, exist_ok=True)
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

    def sign_out(self):
        if self.ctrl:
            self.ctrl.close()
            self.ctrl = None
        if self.main_win:
            self.main_win.destroy()
            self.main_win = None
        self._web_context = None
        self._show_login()

    # ---- shared web context for desktop viewer -----------------------------
    def web_context(self):
        if self._web_context is None:
            dm = WebKit2.WebsiteDataManager(
                base_data_directory=os.path.join(DATA_DIR, "webkit"),
                base_cache_directory=os.path.join(DATA_DIR, "webkit-cache"))
            self._web_context = WebKit2.WebContext.new_with_website_data_manager(dm)
            cm = self._web_context.get_cookie_manager()
            cm.set_persistent_storage(os.path.join(DATA_DIR, "webkit", "cookies.sqlite"),
                                      WebKit2.CookiePersistentStorage.SQLITE)
        return self._web_context


    # ---- helpers -----------------------------------------------------------
    def open_uri(self, uri):
        try:
            Gtk.show_uri_on_window(self.main_win, uri, Gdk.CURRENT_TIME)
        except Exception:
            pass

    def notify(self, title, body):
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
    return App().run(sys.argv)
