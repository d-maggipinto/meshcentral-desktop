# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Embedded web view with the same API on Linux (WebKitGTK) and Windows (Edge WebView2).

Used by the remote desktop panel and the server-page windows (chat, Web-VNC / RDP / SSH). Both
backends apply the same rules: a view bound to the server never navigates to another origin,
pages cannot open windows, download files or read the clipboard, and page dialogs never block
(beforeunload is confirmed, confirm() is declined, alert() text is passed to on_alert).
"""
import json
import os
import urllib.parse

from .osdep import IS_WINDOWS

if IS_WINDOWS:
    from . import winweb
else:
    import gi
    gi.require_version("WebKit2", "4.1")
    from gi.repository import WebKit2


def server_origin(url):
    """'https://host:port' of a server URL (what location.origin reports)."""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def navigation_allowed(uri, server_url):
    """Same-origin rule for views bound to the MeshCentral server."""
    uri = uri or ""
    if uri.startswith(("about:", "data:", "blob:")):
        return True
    return server_origin(uri) == server_origin(server_url)


def same_origin_policy(_view, decision, kind, server_url):
    """WebKit decide-policy handler for views that must stay on the MeshCentral server: refuse
    navigation to other origins and every new-window request. Returns True when handled."""
    if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
        decision.ignore()
        return True
    if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
        uri = decision.get_navigation_action().get_request().get_uri() or ""
        if not navigation_allowed(uri, server_url):
            decision.ignore()
            return True
    return False


def js_string(value):
    """A JS result as WebKit's JSCValue.to_string() gives it (WebView2 returns JSON values)."""
    if value is None:
        return "undefined"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


class WebView:
    """Hooks: on_load_finished(), on_alert(text), on_focus_changed(focused),
    on_accelerator(vk, kind) -> bool (Windows: keys the page would get while it has focus)."""

    def __init__(self, app, server_url=None, webgl=False):
        self.server_url = server_url
        self.on_load_finished = self.on_alert = self.on_focus_changed = self.on_accelerator = None
        self._focused = False
        if IS_WINDOWS:
            w = winweb.WebView2Widget(allow_insecure_tls=os.environ.get("MCD_TEST_INSECURE_TLS") == "1")
            if server_url:
                w.allow_navigation = lambda uri: navigation_allowed(uri, server_url)
            w.on_load_finished = lambda ok: self.on_load_finished and self.on_load_finished()
            w.on_script_dialog = self._win_dialog
            w.on_focus_changed = self._set_focus
            w.on_accelerator = lambda vk, kind: bool(self.on_accelerator and self.on_accelerator(vk, kind))
            self.widget = w
        else:
            v = WebKit2.WebView.new_with_context(app.web_context())
            s = v.get_settings()
            s.set_enable_webgl(bool(webgl))
            # The app does all clipboard work itself (getclip/setclip): the page gets NO clipboard
            # access (in WebKitGTK this setting also allows a script to paste = read the local clipboard)
            # and cannot open windows.
            s.set_javascript_can_access_clipboard(False)
            s.set_javascript_can_open_windows_automatically(False)
            if webgl:
                s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
            v.connect("load-changed", self._wk_load)
            # The page's dialogs would be invisible behind a cover and block forever -
            # notably MeshCentral's "leave page?" beforeunload confirm on reconnect.
            v.connect("script-dialog", self._wk_dialog)
            if server_url:
                v.connect("decide-policy", lambda vw, d, t: same_origin_policy(vw, d, t, server_url))
            v.connect("focus-in-event", lambda *_: (self._set_focus(True), False)[1])
            v.connect("focus-out-event", lambda *_: (self._set_focus(False), False)[1])
            self.widget = v
            self._ctx = app.web_context()

    # ---- events ----------------------------------------------------------------
    def _set_focus(self, focused):
        self._focused = bool(focused)
        if self.on_focus_changed:
            self.on_focus_changed(self._focused)

    def _wk_load(self, _v, event):
        if event == WebKit2.LoadEvent.FINISHED and self.on_load_finished:
            self.on_load_finished()

    def _wk_dialog(self, _v, dialog):
        t = dialog.get_dialog_type()
        if t == WebKit2.ScriptDialogType.BEFORE_UNLOAD_CONFIRM:
            dialog.confirm_set_confirmed(True)       # always allow leaving/reloading
        elif t == WebKit2.ScriptDialogType.CONFIRM:
            dialog.confirm_set_confirmed(False)
        elif t == WebKit2.ScriptDialogType.ALERT:
            msg = (dialog.get_message() or "").strip()
            if msg and self.on_alert:
                self.on_alert(msg)
        return True                                  # handled: never show a hidden dialog

    def _win_dialog(self, kind, message):
        if kind == "alert" and (message or "").strip() and self.on_alert:
            self.on_alert(message.strip())
        return False                                 # confirm / prompt declined (beforeunload: winweb)

    # ---- API -------------------------------------------------------------------
    def load_uri(self, uri):
        self.widget.load_uri(uri)

    def run_js(self, code, cb=None):
        """Run JS in the page; cb(text) with the result as a string ('' on error)."""
        if IS_WINDOWS:
            self.widget.run_javascript(code, (lambda v: cb(js_string(v))) if cb else None)
            return

        def done(view, res):
            try:
                val = view.run_javascript_finish(res).get_js_value().to_string()
            except Exception:
                val = ""
            if cb:
                cb(val)
        try:
            self.widget.run_javascript(code, None, done)
        except Exception:
            pass

    def grab_focus(self):
        self.widget.grab_focus()
        if IS_WINDOWS:
            self.widget.focus_page()

    def has_focus(self):
        return self._focused if IS_WINDOWS else self.widget.has_focus()

    def set_page_visible(self, on):
        """Windows: hide the page while a GTK cover is shown (GTK cannot draw over the native view)."""
        if IS_WINDOWS:
            self.widget.set_page_visible(on)

    def add_cookies(self, url, cookies, done):
        """Session cookies [(name, value, path, secure)] for url's host (host-only, never stored on
        disk, https only, HttpOnly); then done()."""
        host = urllib.parse.urlsplit(url).hostname
        https = urllib.parse.urlsplit(url).scheme == "https"
        if IS_WINDOWS:
            for name, value, path, secure in cookies:
                self.widget.add_cookie(name, value, host, path, secure or https)
            self.widget.after_pending(done)
            return
        gi.require_version("Soup", "3.0")
        from gi.repository import Soup
        mgr, left = self._ctx.get_cookie_manager(), [len(cookies)]

        def added(_m, res):
            try:
                mgr.add_cookie_finish(res)
            except Exception:
                pass
            left[0] -= 1
            if left[0] == 0:
                done()
        if not cookies:
            done()
        for name, value, path, secure in cookies:
            c = Soup.Cookie.new(name, value, host, path, -1)    # host-only, not stored (-1)
            # never sent over plain http, even when the server marks it non-secure (TLS offload)
            c.set_secure(secure or https)
            c.set_http_only(True)
            mgr.add_cookie(c, None, added)


def clear_site_data(app):
    """Sign-out: the next account must not inherit cookies or web storage."""
    if IS_WINDOWS:
        winweb.clear_browsing_data()
        return
    try:
        dm = app.web_context().get_website_data_manager()
        dm.clear(WebKit2.WebsiteDataTypes.COOKIES | WebKit2.WebsiteDataTypes.SESSION_STORAGE
                 | WebKit2.WebsiteDataTypes.LOCAL_STORAGE, 0, None, None, None)
    except Exception:
        pass


def new_web_context(data_dir):
    """Linux: the shared WebKit context (persistent cookies in the app's private data folder)."""
    dm = WebKit2.WebsiteDataManager(
        base_data_directory=os.path.join(data_dir, "webkit"),
        base_cache_directory=os.path.join(data_dir, "webkit-cache"))
    ctx = WebKit2.WebContext.new_with_website_data_manager(dm)
    cm = ctx.get_cookie_manager()
    cm.set_persistent_storage(os.path.join(data_dir, "webkit", "cookies.sqlite"),
                              WebKit2.CookiePersistentStorage.SQLITE)
    # No page may save files on its own (the app's downloads go through WebSession).
    ctx.connect("download-started", lambda _c, d: d.cancel())
    return ctx
