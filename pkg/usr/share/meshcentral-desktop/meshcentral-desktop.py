#!/usr/bin/env python3
"""MeshCentral Desktop - a native GTK/WebKit window for a MeshCentral server."""
import os
import sys
import configparser
from urllib.parse import urlparse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, Gio, GLib, WebKit2

APP_ID = "uk.co.cyvelion.MeshCentralDesktop"
APP_NAME = "MeshCentral Desktop"
DEFAULT_URL = "https://mesh.example.com"

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "meshcentral-desktop")
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "meshcentral-desktop")
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "meshcentral-desktop")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")


def load_config():
    cfg = configparser.ConfigParser()
    cfg["main"] = {"url": DEFAULT_URL, "zoom": "1.0", "width": "1400", "height": "900"}
    # System-wide override, then per-user override
    cfg.read(["/etc/meshcentral-desktop.conf", CONFIG_FILE])
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)


class BrowserWindow(Gtk.ApplicationWindow):
    def __init__(self, app, uri, related_view=None, is_popup=False):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.set_icon_name("meshcentral-desktop")
        if is_popup:
            self.set_default_size(1100, 750)
        else:
            self.set_default_size(app.cfg.getint("main", "width"), app.cfg.getint("main", "height"))

        if related_view is not None:
            self.view = WebKit2.WebView.new_with_related_view(related_view)
        else:
            self.view = WebKit2.WebView.new_with_context(app.web_context)
        self._configure_view()

        # Header bar with navigation controls
        hb = Gtk.HeaderBar(show_close_button=True)
        hb.props.title = APP_NAME
        self.set_titlebar(hb)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        nav.get_style_context().add_class("linked")
        self.back_btn = self._btn("go-previous-symbolic", "Back (Alt+Left)", lambda *_: self.view.go_back())
        self.fwd_btn = self._btn("go-next-symbolic", "Forward (Alt+Right)", lambda *_: self.view.go_forward())
        nav.add(self.back_btn)
        nav.add(self.fwd_btn)
        hb.pack_start(nav)
        hb.pack_start(self._btn("view-refresh-symbolic", "Reload (F5)", lambda *_: self.view.reload()))
        hb.pack_start(self._btn("go-home-symbolic", "Home", lambda *_: self.view.load_uri(app.home_url)))
        hb.pack_end(self._menu_button())

        self.progress = Gtk.ProgressBar()
        self.progress.get_style_context().add_class("osd")
        overlay = Gtk.Overlay()
        overlay.add(self.view)
        self.progress.set_valign(Gtk.Align.START)
        overlay.add_overlay(self.progress)
        self.add(overlay)

        self.view.connect("notify::title", self._on_title)
        self.view.connect("notify::estimated-load-progress", self._on_progress)
        self.view.connect("load-changed", self._on_load_changed)
        self.view.connect("create", self._on_create)
        self.view.connect("ready-to-show", lambda *_: self.show_all())
        self.view.connect("close", lambda *_: self.destroy())
        self.view.connect("decide-policy", self._on_decide_policy)
        self.view.connect("permission-request", self._on_permission)
        self.view.connect("load-failed", self._on_load_failed)
        self.view.connect("load-failed-with-tls-errors", self._on_tls_error)
        self.connect("key-press-event", self._on_key)
        if not is_popup:
            self.connect("delete-event", self._on_main_close)

        if uri:
            self.view.load_uri(uri)

    # --- setup -------------------------------------------------------------
    def _configure_view(self):
        s = self.view.get_settings()
        s.set_enable_developer_extras(True)
        s.set_javascript_can_access_clipboard(True)
        s.set_javascript_can_open_windows_automatically(True)
        s.set_enable_webgl(True)
        s.set_enable_media_stream(True)
        s.set_enable_webrtc(True)
        s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
        s.set_user_agent_with_application_details("MeshCentralDesktop", "1.0")
        try:
            self.view.set_zoom_level(self.app.cfg.getfloat("main", "zoom"))
        except ValueError:
            pass

    def _btn(self, icon, tip, cb):
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        b.set_tooltip_text(tip)
        b.connect("clicked", cb)
        return b

    def _menu_button(self):
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Zoom In (Ctrl +)", "win.zoom-in")
        section.append("Zoom Out (Ctrl -)", "win.zoom-out")
        section.append("Reset Zoom (Ctrl 0)", "win.zoom-reset")
        section.append("Fullscreen (F11)", "win.fullscreen")
        menu.append_section(None, section)
        section2 = Gio.Menu()
        section2.append("Change Server URL…", "win.set-url")
        section2.append("Open in Web Browser", "win.open-external")
        section2.append("Web Inspector (Ctrl+Shift+I)", "win.inspector")
        section2.append("Clear Cookies & Cache…", "win.clear-data")
        menu.append_section(None, section2)
        section3 = Gio.Menu()
        section3.append("About", "win.about")
        menu.append_section(None, section3)

        for name, cb in [
            ("zoom-in", lambda *_: self._zoom(0.1)),
            ("zoom-out", lambda *_: self._zoom(-0.1)),
            ("zoom-reset", lambda *_: self._zoom(None)),
            ("fullscreen", lambda *_: self._toggle_fullscreen()),
            ("set-url", lambda *_: self._set_url_dialog()),
            ("open-external", lambda *_: Gtk.show_uri_on_window(self, self.view.get_uri() or self.app.home_url, Gdk.CURRENT_TIME)),
            ("inspector", lambda *_: self.view.get_inspector().show()),
            ("clear-data", lambda *_: self._clear_data()),
            ("about", lambda *_: self._about()),
        ]:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

        mb = Gtk.MenuButton()
        mb.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        mb.set_menu_model(menu)
        return mb

    # --- behaviour ---------------------------------------------------------
    def _zoom(self, delta):
        z = 1.0 if delta is None else max(0.3, min(3.0, self.view.get_zoom_level() + delta))
        self.view.set_zoom_level(z)
        self.app.cfg.set("main", "zoom", f"{z:.2f}")
        save_config(self.app.cfg)

    def _toggle_fullscreen(self):
        win = self.get_window()
        if win and win.get_state() & Gdk.WindowState.FULLSCREEN:
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_key(self, _w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        shift = ev.state & Gdk.ModifierType.SHIFT_MASK
        alt = ev.state & Gdk.ModifierType.MOD1_MASK
        k = ev.keyval
        if k == Gdk.KEY_F5 or (ctrl and k == Gdk.KEY_r):
            self.view.reload(); return True
        if k == Gdk.KEY_F11:
            self._toggle_fullscreen(); return True
        if ctrl and k in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self._zoom(0.1); return True
        if ctrl and k in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self._zoom(-0.1); return True
        if ctrl and k in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self._zoom(None); return True
        if ctrl and shift and k in (Gdk.KEY_I, Gdk.KEY_i):
            self.view.get_inspector().show(); return True
        if alt and k == Gdk.KEY_Left:
            self.view.go_back(); return True
        if alt and k == Gdk.KEY_Right:
            self.view.go_forward(); return True
        return False

    def _on_title(self, *_):
        t = self.view.get_title()
        self.get_titlebar().props.title = t or APP_NAME
        self.set_title(t or APP_NAME)

    def _on_progress(self, *_):
        p = self.view.get_estimated_load_progress()
        self.progress.set_fraction(p)
        self.progress.set_visible(p < 1.0)

    def _on_load_changed(self, _v, _ev):
        self.back_btn.set_sensitive(self.view.can_go_back())
        self.fwd_btn.set_sensitive(self.view.can_go_forward())

    def _on_create(self, view, nav_action):
        # MeshCentral opens some tools (terminal, files, desktop) in popups
        uri = nav_action.get_request().get_uri()
        if uri and not self.app.is_internal(uri):
            Gtk.show_uri_on_window(self, uri, Gdk.CURRENT_TIME)
            return None
        win = BrowserWindow(self.app, None, related_view=view, is_popup=True)
        return win.view

    def _on_decide_policy(self, _v, decision, dtype):
        if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            nav = decision.get_navigation_action()
            uri = nav.get_request().get_uri()
            # Send user-clicked external links to the system browser
            if (nav.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED
                    and not self.app.is_internal(uri)):
                Gtk.show_uri_on_window(self, uri, Gdk.CURRENT_TIME)
                decision.ignore()
                return True
        elif dtype == WebKit2.PolicyDecisionType.RESPONSE:
            if not decision.is_mime_type_supported():
                decision.download()
                return True
        return False

    def _on_permission(self, _v, request):
        # Allow notifications / clipboard / media only for the configured server
        if self.app.is_internal(self.view.get_uri() or ""):
            request.allow()
        else:
            request.deny()
        return True

    def _on_load_failed(self, _v, _ev, uri, error):
        if error.matches(WebKit2.NetworkError.quark(), WebKit2.NetworkError.CANCELLED) or \
           error.matches(WebKit2.PolicyError.quark(), WebKit2.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE):
            return False
        html = f"""<html><body style="font-family:sans-serif;background:#1e1e1e;color:#ddd;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
        <div style="text-align:center"><h2>Can't reach the MeshCentral server</h2>
        <p>{GLib.markup_escape_text(uri)}</p><p style="color:#f88">{GLib.markup_escape_text(error.message)}</p>
        <p><a style="color:#6af" href="{GLib.markup_escape_text(uri)}">Retry</a></p></div></body></html>"""
        self.view.load_alternate_html(html, uri, None)
        return True

    def _on_tls_error(self, _v, uri, _cert, errors):
        self._message(Gtk.MessageType.ERROR, "TLS certificate error",
                      f"The certificate for {uri} is not trusted ({errors}). Connection refused.")
        return True

    def _on_main_close(self, *_):
        w, h = self.get_size()
        self.app.cfg.set("main", "width", str(w))
        self.app.cfg.set("main", "height", str(h))
        save_config(self.app.cfg)
        return False

    # --- dialogs -----------------------------------------------------------
    def _message(self, mtype, title, text):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=mtype,
                              buttons=Gtk.ButtonsType.OK, text=title)
        d.format_secondary_text(text)
        d.run(); d.destroy()

    def _set_url_dialog(self):
        d = Gtk.Dialog(title="MeshCentral Server URL", transient_for=self, modal=True)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=self.app.home_url, activates_default=True, width_chars=45)
        box = d.get_content_area()
        box.set_spacing(8); box.set_border_width(12)
        box.add(Gtk.Label(label="Server address:", xalign=0))
        box.add(entry)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            url = entry.get_text().strip()
            if url and "://" not in url:
                url = "https://" + url
            if url:
                self.app.set_home(url)
                self.view.load_uri(url)
        d.destroy()

    def _clear_data(self):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.OK_CANCEL, text="Clear cookies and cache?")
        d.format_secondary_text("You will be logged out of MeshCentral.")
        if d.run() == Gtk.ResponseType.OK:
            mgr = self.app.web_context.get_website_data_manager()
            mgr.clear(WebKit2.WebsiteDataTypes.ALL, 0, None,
                      lambda m, r: (m.clear_finish(r), self.view.load_uri(self.app.home_url)))
        d.destroy()

    def _about(self):
        a = Gtk.AboutDialog(transient_for=self, modal=True, program_name=APP_NAME,
                            version="1.0.0", logo_icon_name="meshcentral-desktop",
                            comments=f"Desktop client for\n{self.app.home_url}",
                            website=self.app.home_url)
        a.run(); a.destroy()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = load_config()
        self.home_url = self.cfg.get("main", "url").rstrip("/")
        self.web_context = None

    def set_home(self, url):
        self.home_url = url.rstrip("/")
        self.cfg.set("main", "url", self.home_url)
        save_config(self.cfg)

    def is_internal(self, uri):
        if not uri or uri.startswith(("about:", "blob:", "data:")):
            return True
        return urlparse(uri).hostname == urlparse(self.home_url).hostname

    def do_startup(self):
        Gtk.Application.do_startup(self)
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        # Persistent storage so the login session / cookies survive restarts
        dm = WebKit2.WebsiteDataManager(base_data_directory=DATA_DIR, base_cache_directory=CACHE_DIR)
        self.web_context = WebKit2.WebContext.new_with_website_data_manager(dm)
        cm = self.web_context.get_cookie_manager()
        cm.set_persistent_storage(os.path.join(DATA_DIR, "cookies.sqlite"),
                                  WebKit2.CookiePersistentStorage.SQLITE)
        cm.set_accept_policy(WebKit2.CookieAcceptPolicy.NO_THIRD_PARTY)
        self.web_context.connect("download-started", self._on_download)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        uri = next((a for a in args if "://" in a), None)
        win = self.get_active_window()
        if win and not uri:
            win.present()
        else:
            BrowserWindow(self, uri or self.home_url).show_all()
        return 0

    def _on_download(self, _ctx, download):
        download.connect("decide-destination", self._decide_dest)
        download.connect("finished", lambda d: self._notify("Download finished", d.get_destination() or ""))
        download.connect("failed", lambda d, e: self._notify("Download failed", e.message))

    def _decide_dest(self, download, suggested):
        win = self.get_active_window()
        d = Gtk.FileChooserNative.new("Save File", win, Gtk.FileChooserAction.SAVE, "_Save", "_Cancel")
        d.set_do_overwrite_confirmation(True)
        d.set_current_name(suggested)
        dl_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if dl_dir:
            d.set_current_folder(dl_dir)
        if d.run() == Gtk.ResponseType.ACCEPT:
            download.set_destination(d.get_uri())
        else:
            download.cancel()
        d.destroy()
        return True

    def _notify(self, title, body):
        n = Gio.Notification.new(title)
        n.set_body(body)
        self.send_notification(None, n)


if __name__ == "__main__":
    GLib.set_prgname("meshcentral-desktop")
    GLib.set_application_name(APP_NAME)
    sys.exit(App().run(sys.argv))
