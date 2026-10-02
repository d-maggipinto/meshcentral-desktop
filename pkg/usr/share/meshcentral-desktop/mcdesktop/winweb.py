# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Microsoft Edge WebView2 embedded in a GTK 3 widget (Windows only).

WebKitGTK does not exist on Windows; this widget gives the remote desktop viewer, the terminal
and the chat window the same embedded web view through WebView2 (part of Windows 10 / 11).

How it works: the widget is a Gtk.DrawingArea whose GdkWindow is made a native child HWND;
WebView2 is created inside that HWND (WebView2Loader.dll + the WebView2.tlb type library, driven
through comtypes) and resized with the widget. GTK's Win32 event loop dispatches the window
messages WebView2 needs, so no extra thread is involved; every callback runs on the GTK thread.

comtypes does not AddRef interface pointers passed INTO a Python COM callback but releases them
when the Python object is collected, so every handler AddRefs the pointers it receives (_ref).
"""
import ctypes
import json
import os
import sys
import traceback
from ctypes import wintypes

from gi.repository import Gtk, GLib

import comtypes
import comtypes.client

_wv = None            # generated comtypes module for WebView2.tlb
_env = None           # shared ICoreWebView2Environment (one browser process for the app)
_env_waiters = []     # callbacks waiting for the environment
_env_handler = None   # keeps the creation handler alive
_env_error = None


def _search_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [os.environ.get("MCD_WEBVIEW2_DIR"), os.path.dirname(sys.executable), here,
            os.path.join(here, "webview2"), os.path.dirname(here)]
    return [d for d in dirs if d]


def _find(name):
    for d in _search_dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(name + " not found (searched: " + ", ".join(_search_dirs()) + ")")


def module():
    """The comtypes wrapper of WebView2.tlb (generated once, cached by comtypes)."""
    global _wv
    if _wv is None:
        _wv = comtypes.client.GetModule(_find("WebView2.tlb"))
    return _wv


def runtime_version():
    """Installed WebView2 runtime version, or None when the runtime is missing."""
    loader = ctypes.WinDLL(_find("WebView2Loader.dll"))
    fn = loader.GetAvailableCoreWebView2BrowserVersionString
    fn.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    fn.restype = ctypes.HRESULT
    out = ctypes.c_void_p()
    try:
        fn(None, ctypes.byref(out))
    except OSError:
        return None
    if not out.value:
        return None
    s = ctypes.wstring_at(out.value)
    ctypes.windll.ole32.CoTaskMemFree(out)
    return s


def _ref(p):
    """Balance comtypes' Release-on-collect for a pointer received in a callback."""
    if p:
        p.AddRef()
    return p


def _handler(iface, fn):
    """A COM object implementing a one-method WebView2 handler interface (Invoke)."""
    class H(comtypes.COMObject):
        _com_interfaces_ = [iface]

        def Invoke(self, this, *args):        # low-level form: comtypes passes `this`
            try:
                fn(*args)
            except Exception:
                traceback.print_exc()
            return 0
    return H()


def _ensure_environment(user_data_dir, cb):
    """Create (once) the shared WebView2 environment; cb(env_or_None, error_text)."""
    global _env_handler
    if _env is not None or _env_error is not None:
        cb(_env, _env_error)
        return
    _env_waiters.append(cb)
    if _env_handler is not None:
        return
    wv = module()

    def done(hr, env):
        global _env, _env_error
        if hr == 0 and env:
            _env = _ref(env)
        else:
            _env_error = "WebView2 environment failed (0x%08X)" % (hr & 0xFFFFFFFF)
        waiters = list(_env_waiters)
        del _env_waiters[:]
        for w in waiters:
            w(_env, _env_error)

    _env_handler = _handler(wv.ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler, done)
    loader = ctypes.WinDLL(_find("WebView2Loader.dll"))
    create = loader.CreateCoreWebView2EnvironmentWithOptions
    create.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.POINTER(wv.ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler)]
    create.restype = ctypes.HRESULT
    os.makedirs(user_data_dir, exist_ok=True)
    try:
        create(None, user_data_dir, None, _env_handler)
    except OSError as ex:
        done(getattr(ex, "winerror", -1) or -1, None)


def default_user_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "MeshCentralDesktop", "webview2")


# gdk_win32_window_get_handle(GdkWindow*) -> HWND
_gdk = None


def _hwnd_of(gdk_window):
    global _gdk
    if _gdk is None:
        _gdk = ctypes.CDLL("libgdk-3-0.dll")
        _gdk.gdk_win32_window_get_handle.restype = ctypes.c_void_p
        _gdk.gdk_win32_window_get_handle.argtypes = [ctypes.c_void_p]
        ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
        ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    ptr = ctypes.pythonapi.PyCapsule_GetPointer(gdk_window.__gpointer__, None)
    return _gdk.gdk_win32_window_get_handle(ptr)


class WebView2Widget(Gtk.DrawingArea):
    """An embedded WebView2. Calls made before WebView2 is ready are queued.

    Hooks (all optional, set as attributes):
      on_ready()                        WebView2 created
      on_error(text)                    creation failed (runtime missing...)
      allow_navigation(uri) -> bool     NavigationStarting policy (default: allow)
      on_load_finished(ok)              NavigationCompleted
      on_message(text)                  window.chrome.webview.postMessage(...)
      on_script_dialog(kind, message)   alert / confirm / prompt (beforeunload is auto-accepted)
      on_accelerator(vk, kind) -> bool  key the page would get; True = handled by the app
    """

    def __init__(self, user_data_dir=None, devtools=False, allow_insecure_tls=False):
        super().__init__(can_focus=True, hexpand=True, vexpand=True)
        self.user_data_dir = user_data_dir or default_user_data_dir()
        self.devtools = devtools
        self.allow_insecure_tls = allow_insecure_tls   # local test servers only
        self.controller = self.webview = None
        self._pending = []
        self._handlers = []          # keep COM handler objects alive
        self._closed = False
        self.on_ready = self.on_error = self.allow_navigation = self.on_load_finished = None
        self.on_message = self.on_script_dialog = self.on_accelerator = None
        self.connect("realize", self._on_realize)
        self.connect("size-allocate", lambda *_: self._update_bounds())
        self.connect("map", lambda *_: self._set_visible(True))
        self.connect("unmap", lambda *_: self._set_visible(False))
        self.connect("focus-in-event", lambda *_: self.focus_page())
        self.connect("destroy", lambda *_: self.close())

    # ---- creation ------------------------------------------------------------
    def _on_realize(self, *_):
        win = self.get_window()
        win.ensure_native()
        self._hwnd = _hwnd_of(win)
        _ensure_environment(self.user_data_dir, self._got_env)

    def _got_env(self, env, err):
        if self._closed:
            return
        if env is None:
            if self.on_error:
                self.on_error(err or "WebView2 is not available")
            return
        wv = module()
        h = _handler(wv.ICoreWebView2CreateControllerCompletedHandler, self._got_controller)
        self._handlers.append(h)
        env.CreateCoreWebView2Controller(self._hwnd, h)

    def _got_controller(self, hr, controller):
        if self._closed:
            return
        if hr != 0 or not controller:
            if self.on_error:
                self.on_error("WebView2 controller failed (0x%08X)" % (hr & 0xFFFFFFFF))
            return
        wv = module()
        self.controller = _ref(controller)
        self.webview = self.controller.CoreWebView2
        s = self.webview.Settings
        s.AreDevToolsEnabled = bool(self.devtools)
        s.AreDefaultContextMenusEnabled = bool(self.devtools)
        s.IsStatusBarEnabled = False
        s.IsZoomControlEnabled = False
        s.AreHostObjectsAllowed = False
        s.AreDefaultScriptDialogsEnabled = False     # we answer them (beforeunload behind a cover)
        s.IsWebMessageEnabled = True
        self._add(self.webview.add_NavigationStarting, wv.ICoreWebView2NavigationStartingEventHandler,
                  self._nav_starting)
        self._add(self.webview.add_NavigationCompleted, wv.ICoreWebView2NavigationCompletedEventHandler,
                  self._nav_completed)
        self._add(self.webview.add_NewWindowRequested, wv.ICoreWebView2NewWindowRequestedEventHandler,
                  self._new_window)
        self._add(self.webview.add_ScriptDialogOpening, wv.ICoreWebView2ScriptDialogOpeningEventHandler,
                  self._script_dialog)
        self._add(self.webview.add_WebMessageReceived, wv.ICoreWebView2WebMessageReceivedEventHandler,
                  self._web_message)
        self._add(self.webview.add_PermissionRequested, wv.ICoreWebView2PermissionRequestedEventHandler,
                  self._permission)
        self._add(self.controller.add_AcceleratorKeyPressed,
                  wv.ICoreWebView2AcceleratorKeyPressedEventHandler, self._accelerator)
        try:                                           # downloads: ICoreWebView2_4 (runtime 1.0.902+)
            w4 = self.webview.QueryInterface(wv.ICoreWebView2_4)
            self._add(w4.add_DownloadStarting, wv.ICoreWebView2DownloadStartingEventHandler, self._download)
        except Exception:
            pass
        try:                                           # TLS errors: ICoreWebView2_14 (runtime 1.0.1245+)
            w14 = self.webview.QueryInterface(wv.ICoreWebView2_14)
            self._add(w14.add_ServerCertificateErrorDetected,
                      wv.ICoreWebView2ServerCertificateErrorDetectedEventHandler, self._cert_error)
        except Exception:
            pass
        self._update_bounds()
        self._set_visible(self.get_mapped())
        pending, self._pending = self._pending, []
        for fn in pending:
            fn()
        if self.on_ready:
            self.on_ready()

    def _add(self, add_fn, iface, fn):
        h = _handler(iface, fn)
        self._handlers.append(h)
        add_fn(h)                       # returns the EventRegistrationToken (unused: we never remove)

    def _later(self, fn):
        if self.webview is not None:
            fn()
        elif not self._closed:
            self._pending.append(fn)

    # ---- geometry / visibility / focus -----------------------------------------
    def _update_bounds(self):
        if self.controller is None:
            return
        a = self.get_allocation()
        sc = self.get_scale_factor()
        r = module().tagRECT(0, 0, max(1, a.width * sc), max(1, a.height * sc))
        try:
            self.controller.Bounds = r
        except Exception:
            traceback.print_exc()

    def _set_visible(self, on):
        if self.controller is not None:
            try:
                self.controller.IsVisible = bool(on)
            except Exception:
                pass

    def focus_page(self):
        if self.controller is not None:
            try:
                self.controller.MoveFocus(module().COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC)
            except Exception:
                pass
        return False

    def set_page_visible(self, on):
        """Hide the page without unmapping the widget (a GTK overlay cannot cover a native window)."""
        self._set_visible(on and self.get_mapped())

    # ---- events --------------------------------------------------------------
    def _nav_starting(self, sender, args):
        _ref(sender)
        _ref(args)
        if self.allow_navigation is not None and not self.allow_navigation(args.Uri):
            args.Cancel = True

    def _nav_completed(self, sender, args):
        _ref(sender)
        _ref(args)
        if self.on_load_finished:
            self.on_load_finished(bool(args.IsSuccess))

    def _new_window(self, sender, args):
        _ref(sender)
        _ref(args)
        args.Handled = True             # no pop-up windows (same rule as the Linux build)

    def _download(self, sender, args):
        _ref(sender)
        _ref(args)
        args.Cancel = True              # pages never save files on their own

    def _permission(self, sender, args):
        _ref(sender)
        _ref(args)
        args.State = module().COREWEBVIEW2_PERMISSION_STATE_DENY   # clipboard, camera, location...

    def _cert_error(self, sender, args):
        _ref(sender)
        _ref(args)
        wv = module()
        args.Action = (wv.COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_ALWAYS_ALLOW if self.allow_insecure_tls
                       else wv.COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_CANCEL)

    def _script_dialog(self, sender, args):
        _ref(sender)
        _ref(args)
        wv = module()
        kind = args.Kind
        if kind == wv.COREWEBVIEW2_SCRIPT_DIALOG_KIND_BEFOREUNLOAD:
            args.Accept()               # "leave page?" behind the cover would block navigation forever
            return
        accept = False
        if self.on_script_dialog:
            accept = bool(self.on_script_dialog(
                {wv.COREWEBVIEW2_SCRIPT_DIALOG_KIND_ALERT: "alert",
                 wv.COREWEBVIEW2_SCRIPT_DIALOG_KIND_CONFIRM: "confirm"}.get(kind, "prompt"), args.Message))
        if accept:
            args.Accept()

    def _web_message(self, sender, args):
        _ref(sender)
        _ref(args)
        if not self.on_message:
            return
        try:
            text = args.TryGetWebMessageAsString()
        except Exception:
            text = args.WebMessageAsJson
        self.on_message(text)

    def _accelerator(self, sender, args):
        _ref(sender)
        _ref(args)
        if self.on_accelerator and self.on_accelerator(args.VirtualKey, args.KeyEventKind):
            args.Handled = True

    # ---- API -----------------------------------------------------------------
    def load_uri(self, uri):
        self._later(lambda: self.webview.Navigate(uri))

    def load_html(self, html):
        self._later(lambda: self.webview.NavigateToString(html))

    def reload(self):
        self._later(lambda: self.webview.Reload())

    def get_uri(self):
        return self.webview.Source if self.webview is not None else None

    def run_javascript(self, code, cb=None):
        """Run JS in the page; cb(value) with the JSON-decoded result (None on error)."""
        def go():
            def done(hr, result):
                if cb is None:
                    return
                val = None
                if hr == 0 and result:
                    try:
                        val = json.loads(result)
                    except ValueError:
                        val = result
                cb(val)
            h = _handler(module().ICoreWebView2ExecuteScriptCompletedHandler, done)
            self._handlers.append(h)
            self.webview.ExecuteScript(code, h)
        self._later(go)

    def add_user_script(self, js):
        """JS run in every new document before its own scripts (like a WebKit UserScript)."""
        def go():
            h = _handler(module().ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler,
                         lambda hr, ident: None)
            self._handlers.append(h)
            self.webview.AddScriptToExecuteOnDocumentCreated(js, h)
        self._later(go)

    def add_user_css(self, css):
        js = ("(function(){var c=%s;function a(){var s=document.createElement('style');s.textContent=c;"
              "(document.head||document.documentElement).appendChild(s);}"
              "if(document.documentElement)a();else document.addEventListener('DOMContentLoaded',a);})();"
              % json.dumps(css))
        self.add_user_script(js)

    def post_message(self, text):
        self._later(lambda: self.webview.PostWebMessageAsString(text))

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._pending = []
        if self.controller is not None:
            try:
                self.controller.Close()
            except Exception:
                pass
        self.controller = self.webview = None
