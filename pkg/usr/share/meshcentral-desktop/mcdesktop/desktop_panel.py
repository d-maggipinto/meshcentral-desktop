"""Remote desktop panel, embeds MeshCentral's OWN web desktop KVM viewer but wraps it
in NATIVE controls so it feels like part of the app rather than a web page.

Flow (verified live -> status "Connected"):
  1. load the server root
  2. if the login form is shown, fill username/password and submit
  3. navigate to  ?gotonode=<short-id>&viewmode=11&hide=15   (short id = _id after last '/')
  4. once routed to the device desktop, click its hidden "Connect" button
  5. once connected, hide the web viewer's own control rows + bottom toolbar, leaving
     only the remote screen, and drive everything from the NATIVE toolbar below.

We deliberately do NOT reimplement the KVM/screen/input protocol; the native buttons
call the viewer's own JS API (desktop.m.sendcad, SendCompressionLevel, the clipboard
functions, connectDesktop) via run_javascript.
"""
import json

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, WebKit2, GLib

# Native combo choices -> viewer values
_QUALITY = [("Low", 30), ("Medium", 50), ("High", 80)]
_SPEED = [("Fast", 100), ("Medium", 300), ("Slow", 700)]          # ms between frames
_ENCODING = [("WEBP", 4), ("JPEG", 1), ("PNG", 2)]                # SendCompressionLevel type


class DesktopPanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.node = app, node
        self._started = False
        self._closing = False
        self._logged_in = False
        self._navigated = False
        self._connect_tried = False
        self._connected = False
        self._ctrl_widgets = []
        self._polling = False
        self._clip_handler = None
        self._clip_get_timer = None
        self._clip_set_timer = None

        # --- toolbar row 1: session + view ---
        self._toolbar = bar = Gtk.Box(spacing=6, margin=6)
        self.connect_btn = Gtk.Button(label="Disconnect",
            image=Gtk.Image.new_from_icon_name("network-wired-symbolic", Gtk.IconSize.BUTTON),
            always_show_image=True)
        self.connect_btn.connect("clicked", self._toggle_connect)
        bar.pack_start(self.connect_btn, False, False, 0)

        cad = Gtk.Button(label="Ctrl+Alt+Del")
        cad.set_tooltip_text("Send Ctrl+Alt+Del to the remote computer")
        cad.connect("clicked", lambda *_: self._send_cad())
        bar.pack_start(cad, False, False, 0)
        self._ctrl_widgets.append(cad)

        clip = Gtk.Box()
        clip.get_style_context().add_class("linked")
        paste = Gtk.Button.new_from_icon_name("edit-paste-symbolic", Gtk.IconSize.BUTTON)
        paste.set_tooltip_text("Send this computer's clipboard to the remote computer")
        paste.connect("clicked", lambda *_: self._clip_to_remote())
        copyr = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
        copyr.set_tooltip_text("Copy the remote clipboard to this computer")
        copyr.connect("clicked", lambda *_: self._clip_from_remote())
        clip.add(paste)
        clip.add(copyr)
        bar.pack_start(clip, False, False, 0)
        self._ctrl_widgets += [paste, copyr]

        full = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic", Gtk.IconSize.BUTTON)
        full.set_tooltip_text("Fullscreen")
        full.connect("clicked", lambda *_: self._toggle_fullscreen())
        bar.pack_start(full, False, False, 0)
        self.reconnect_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.reconnect_btn.set_tooltip_text("Reconnect")
        self.reconnect_btn.connect("clicked", lambda *_: self.start_flow())
        bar.pack_start(self.reconnect_btn, False, False, 0)

        self.status = Gtk.Label(xalign=1)
        self.status.get_style_context().add_class("dim-label")
        bar.pack_end(self.status, True, True, 6)
        self.pack_start(bar, False, False, 0)

        # --- toolbar row 2: image quality controls ---
        self._qbar = qbar = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_bottom=4)
        self.quality = self._combo("Quality", _QUALITY, 1, qbar)
        self.speed = self._combo("Speed", _SPEED, 0, qbar)
        # Default to JPEG: WebKitGTK's WebP tile decoding can leave green/torn-tile
        # artifacts on the canvas. JPEG renders cleanly. (index 1 = JPEG)
        self.encoding = self._combo("Encoding", _ENCODING, 1, qbar)
        for c in (self.quality, self.speed, self.encoding):
            c.connect("changed", lambda *_: self._apply_compression())
            self._ctrl_widgets.append(c)
        self.pack_start(qbar, False, False, 0)

        self.info = Gtk.InfoBar(revealed=False, show_close_button=True)
        self.info.connect("response", lambda *_: self.info.set_revealed(False))
        self.info_label = Gtk.Label(wrap=True, xalign=0)
        self.info.get_content_area().add(self.info_label)
        self.pack_start(self.info, False, False, 0)

        self.view = WebKit2.WebView.new_with_context(app.web_context())
        s = self.view.get_settings()
        s.set_enable_webgl(True)
        s.set_javascript_can_access_clipboard(True)
        s.set_javascript_can_open_windows_automatically(True)
        s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
        self.view.connect("load-changed", self._on_load)
        self.view.connect("size-allocate", self._on_view_resize)
        self._resize_timer = None
        self.pack_start(self.view, True, True, 0)
        self.show_all()
        self._set_controls_enabled(False)

    def _combo(self, label, items, active, bar):
        bar.pack_start(Gtk.Label(label=label + ":"), False, False, 0)
        c = Gtk.ComboBoxText()
        for text, _val in items:
            c.append_text(text)
        c.set_active(active)
        bar.pack_start(c, False, False, 0)
        return c

    # ---- lifecycle ---------------------------------------------------------
    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.start_flow()

    def start_flow(self):
        self._logged_in = False
        self._navigated = False
        self._connect_tried = False
        self._retry_connect = False
        self._connected = False
        self._set_controls_enabled(False)
        self._set_status("Opening…")
        self.view.load_uri(self.app.ctrl.server.url + "/")

    def teardown(self):
        self._closing = True
        self._clip_unlisten()
        try:
            self.view.load_uri("about:blank")
        except Exception:
            pass

    # ---- helpers -----------------------------------------------------------
    @property
    def short_id(self):
        return self.node["_id"].split("/")[-1]

    @property
    def desk_url(self):
        # hide=15 removes MeshCentral's masthead, top device-tab bar, footer and titles.
        return f"{self.app.ctrl.server.url}/?gotonode={self.short_id}&viewmode=11&hide=15"

    # Injected before connect: drop the outer web chrome (safe, leaves the desktop
    # controls so the auto-connect click still works).
    _CHROME_CSS = ("#page_leftbar{display:none!important;}"
                   "#page_content{left:0!important;margin-left:0!important;}"
                   "#masthead,#topbar,#footer{display:none!important;}")

    # Injected AFTER connect: hide only the viewer's own header toolbar (#deskarea1:
    # Actions/Settings/Connect/status) and its footer toolbar (#deskarea4). NEVER hide
    # #deskarea0, it is the OUTER container that also holds the screen canvas
    # (#deskarea3x > #DeskParent > #Desk); hiding it turns the whole view black.
    # Our native toolbar provides those actions instead.
    # Hide the header/footer toolbars AND make the screen container fill the whole
    # WebView, so the viewer's deskAdjust() sizes the canvas to the full area (this is
    # what makes the remote screen actually fill the panel, not sit letterboxed-small).
    # #deskarea3x is pinned to the viewport (position:fixed) so no ancestor offset can
    # shift it, and max-height is overridden too: the viewer sets an inline
    # max-height:calc(100vh - 74px) on it, which left a black strip at the bottom.
    # #DeskFocus is the viewer's red dotted "focus area" rectangle, never wanted here.
    _DESK_CSS = (
        "html,body{overflow:hidden!important;}"
        "#deskarea1,#deskarea4,#DeskFocus{display:none!important;}"
        "#deskarea3x{position:fixed!important;top:0!important;left:0!important;right:0!important;"
        "bottom:0!important;width:auto!important;height:auto!important;max-height:none!important;"
        "margin:0!important;overflow:hidden!important;z-index:9999!important;background:#000!important;}"
        "#DeskParent{position:absolute!important;top:0!important;left:0!important;width:100%!important;"
        "height:100%!important;overflow:hidden!important;margin:0!important;}"
        "#Desk{outline:none!important;}"
    )

    def _inject_style(self, style_id, css):
        # Create or UPDATE a <style> element by id.
        self._js(
            "(function(){try{var id=" + json.dumps(style_id) + ";"
            "var s=document.getElementById(id);"
            "if(!s){s=document.createElement('style');s.id=id;document.head.appendChild(s);}"
            "s.textContent=" + json.dumps(css) + ";return 'ok';}catch(e){return 'err';}})()")

    def _remove_style(self, style_id):
        self._js("(function(){try{var s=document.getElementById(" + json.dumps(style_id) +
                 ");if(s)s.remove();return 'ok';}catch(e){return 'err';}})()")

    def _set_status(self, text):
        self.status.set_text(text)

    def _note(self, text):
        self.info_label.set_text(text)
        self.info.set_message_type(Gtk.MessageType.WARNING)
        self.info.set_revealed(True)

    def _set_controls_enabled(self, on):
        for w in self._ctrl_widgets:
            w.set_sensitive(on)

    def _js(self, code, cb=None):
        def done(view, res):
            if self._closing:
                return
            try:
                val = view.run_javascript_finish(res).get_js_value().to_string()
            except Exception:
                val = ""
            if cb:
                cb(val)
        try:
            self.view.run_javascript(code, None, done)
        except Exception:
            pass

    def _call(self, method):
        """Call desktop.m.<method>() only when the KVM session is live (State===3)."""
        self._js(
            "(function(){try{if(typeof desktop!=='undefined'&&desktop&&desktop.State===3"
            f"&&desktop.m&&typeof {method}==='function'){{{method}();return 'ok';}}"
            "return 'notready';}catch(e){return 'err';}})()")

    def _call_fn(self, fn):
        """Call a global page function like deskClipboardOutFunction()."""
        self._js(
            "(function(){try{if(typeof " + fn + "==='function'){" + fn + "();return 'ok';}"
            "return 'notready';}catch(e){return 'err';}})()")

    def _apply_compression(self):
        if not self._connected:
            return
        q = _QUALITY[self.quality.get_active()][1]
        fr = _SPEED[self.speed.get_active()][1]
        enc = _ENCODING[self.encoding.get_active()][1]
        self._js(
            "(function(){try{if(typeof desktop!=='undefined'&&desktop&&desktop.State===3"
            "&&desktop.m&&desktop.m.SendCompressionLevel){"
            f"desktop.m.SendCompressionLevel({enc},{q},1024,{fr});return 'ok';}}"
            "return 'notready';}catch(e){return 'err';}})()")

    def _toggle_connect(self, *_):
        if self._connected:
            self._js("(function(){try{if(typeof connectDesktop==='function'){connectDesktop(null,0);"
                     "return 'ok';}return 'no';}catch(e){return 'err';}})()")
            self._connected = False
            self._set_controls_enabled(False)
            self.connect_btn.set_label("Connect")
            self._set_status("Disconnected")
        else:
            self._connect_tried = False
            self._retry_connect = False
            self._click_connect()

    def _toggle_fullscreen(self):
        # Ask the main window for TRUE fullscreen: hide its sidebar/tabs/action bar and
        # fill the whole screen with just the remote desktop (Esc to exit). Falls back
        # to plain window fullscreen if the main window doesn't support it.
        mw = self.app.main_win if getattr(self.app, "main_win", None) else None
        if mw is not None and hasattr(mw, "toggle_desktop_fullscreen"):
            mw.toggle_desktop_fullscreen(self)      # calls refit_soon() itself
        else:
            win = self.get_toplevel()
            if isinstance(win, Gtk.Window):
                gdkwin = win.get_window()
                if gdkwin and gdkwin.get_state() & Gdk.WindowState.FULLSCREEN:
                    win.unfullscreen()
                else:
                    win.fullscreen()
            self.refit_soon()

    def refit_soon(self):
        # The fullscreen transition can take well over a second on some WMs; keep
        # refitting until the allocation has settled.
        for delay in (150, 400, 800, 1500, 2500):
            GLib.timeout_add(delay, self._refit_canvas)

    def set_chrome_visible(self, visible):
        # Hide/show this panel's own toolbars (used by true fullscreen).
        for w in (getattr(self, "_toolbar", None), getattr(self, "_qbar", None)):
            if w is not None:
                w.set_visible(visible)

    def _on_view_resize(self, _widget, _alloc):
        # Refit whenever the panel/WebView is resized (window resize, fullscreen, pane
        # drag). Debounced so we don't spam deskAdjust during a live drag.
        if getattr(self, "_resize_timer", None):
            GLib.source_remove(self._resize_timer)
        self._resize_timer = GLib.timeout_add(150, self._refit_canvas)

    def _refit_canvas(self):
        self._resize_timer = None
        if not self._connected:
            return False
        # deskAspectRatio 0 = keep aspect and fit the container; deskAdjust() sizes the
        # canvas (in px, so mouse mapping stays correct) to the container, which the
        # persistent desk CSS has made fill the WebView.
        self._js("(function(){try{"
                 "if(typeof deskAspectRatio!=='undefined'){deskAspectRatio=0;}"
                 "window.dispatchEvent(new Event('resize'));"
                 "if(typeof deskAdjust==='function'){deskAdjust();}"
                 "return 'ok';}catch(e){return 'err';}})()")
        return False

    # ---- Ctrl+Alt+Del: inject the real key sequence (works on Linux too, like NoMachine) ----
    def _send_cad(self):
        # Ctrl(17) + Alt(18) + Delete(46, extended) down, then up in reverse. This is a
        # real key-combo injection, which Linux desktops act on, unlike the Windows-only
        # sendcad() "secure attention" command the Linux agent ignores.
        self._js(
            "(function(){try{"
            "if(typeof desktop==='undefined'||!desktop||desktop.State!==3||!desktop.m)return 'notready';"
            "var m=desktop.m;"
            "m.SendKeyMsgKC(1,17,false);m.SendKeyMsgKC(1,18,false);m.SendKeyMsgKC(1,46,true);"
            "m.SendKeyMsgKC(2,46,true);m.SendKeyMsgKC(2,18,false);m.SendKeyMsgKC(2,17,false);"
            "return 'ok';}catch(e){return 'err';}})()",
            lambda r: self._set_status("Ctrl+Alt+Del sent" if r == "ok" else "Connect the desktop first"))

    # ---- clipboard: native, over OUR control connection ------------------------
    # getclip/setclip are plain control-channel messages; the agent's reply is routed
    # back to the session that asked (with nodeid set), so we don't need the web page,
    # its document.hasFocus() gate or a navigator.clipboard shim at all. Note both are
    # dropped SILENTLY by the server when domain ClipboardGet/ClipboardSet is false, and
    # the agent only answers getclip when the remote clipboard has text, hence timeouts.
    _CLIP_TIMEOUT_MS = 6000

    # The web page must NOT touch the clipboard: if the server enables auto-clipboard,
    # the viewer polls readText() every second and would push stale text to the remote.
    _CLIP_SHIM = ("(function(){try{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{"
                  "writeText:function(){return Promise.resolve();},"
                  "readText:function(){return Promise.reject(new Error('disabled'));}}});"
                  "return 'ok';}catch(e){return 'err';}})()")

    def _install_clip_shim(self):
        self._js(self._CLIP_SHIM)

    def _clip_listen(self):
        if not self._clip_handler:
            self._clip_handler = self._on_clip_msg
            self.app.ctrl.on("msg", self._clip_handler)

    def _clip_unlisten(self):
        if self._clip_handler:
            self.app.ctrl.off("msg", self._clip_handler)
            self._clip_handler = None
        for attr in ("_clip_get_timer", "_clip_set_timer"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, None)

    def _clip_to_remote(self):
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        if not text:
            self._note("This computer's clipboard is empty (no text to send).")
            return
        self._clip_listen()
        self.app.ctrl.send_node_msg(self.node["_id"], "setclip", data=text)
        self._set_status("Sending clipboard…")
        if self._clip_set_timer:
            GLib.source_remove(self._clip_set_timer)
        self._clip_set_timer = GLib.timeout_add(self._CLIP_TIMEOUT_MS, self._clip_set_timeout)

    def _clip_from_remote(self):
        self._clip_listen()
        self.app.ctrl.send_node_msg(self.node["_id"], "getclip", tag=2)
        self._set_status("Reading remote clipboard…")
        if self._clip_get_timer:
            GLib.source_remove(self._clip_get_timer)
        self._clip_get_timer = GLib.timeout_add(self._CLIP_TIMEOUT_MS, self._clip_get_timeout)

    def _on_clip_msg(self, msg):
        if self._closing or msg.get("nodeid") != self.node["_id"]:
            return
        t = msg.get("type")
        if t == "getclip" and msg.get("tag") == 2:
            if self._clip_get_timer:
                GLib.source_remove(self._clip_get_timer)
                self._clip_get_timer = None
            data = msg.get("data")
            if isinstance(data, str) and data:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(data, -1)
                self._set_status(f"Remote clipboard copied here ({len(data)} chars)")
        elif t == "setclip":
            if self._clip_set_timer:
                GLib.source_remove(self._clip_set_timer)
                self._clip_set_timer = None
            self._set_status("Clipboard sent to remote" if msg.get("success") else "Remote rejected the clipboard")

    def _clip_get_timeout(self):
        self._clip_get_timer = None
        self._set_status("")
        self._note("No clipboard came back from the remote computer. Either its clipboard is empty "
                   "(text only), clipboard reading is disabled on the server (ClipboardGet), or the "
                   "agent cannot reach the logged-in desktop's clipboard.")
        return False

    def _clip_set_timeout(self):
        self._clip_set_timer = None
        self._set_status("")
        self._note("The remote computer did not confirm the clipboard. Clipboard writing may be "
                   "disabled on the server (ClipboardSet), or the agent cannot reach the "
                   "logged-in desktop's clipboard.")
        return False

    # ---- state machine -----------------------------------------------------
    def _on_load(self, view, event):
        if event != WebKit2.LoadEvent.FINISHED or self._closing:
            return
        self._js(
            "(function(){"
            "var u=document.getElementById('username');"
            "var t=document.getElementById('tokenInput');"
            "if(t&&t.offsetParent!==null)return 'token';"
            "if(u&&u.offsetParent!==null)return 'login';"
            "return 'app';})()",
            self._route)

    def _route(self, kind):
        if self._closing:
            return
        if kind == "token":
            self._set_status("Two-factor code required")
            self._note("This account needs a two-factor code. Sign in to the web UI once in "
                       "this session, or use an account without 2FA for the embedded desktop.")
            return
        if kind == "login" and not self._logged_in:
            self._logged_in = True
            self._set_status("Signing in…")
            u = json.dumps(self.app.ctrl.username)
            p = json.dumps(self.app.ctrl.password or "")
            self._js(
                "(function(){"
                f"var u=document.getElementById('username');var p=document.getElementById('password');"
                f"if(!u||!p)return 'noform';u.value={u};p.value={p};"
                "var b=document.getElementById('loginButton');"
                "if(b){b.disabled=false;b.click();return 'ok';}"
                "var f=document.forms[0];if(f){f.submit();return 'ok';}return 'noform';})()",
                self._after_login_submit)
            return
        if not self._navigated:
            self._navigated = True
            self._set_status("Opening desktop…")
            GLib.timeout_add(300, lambda: (self.view.load_uri(self.desk_url), False)[1])
            return
        # On the device desktop view: strip outer chrome, then click Connect.
        self._inject_style("mcd-chrome-css", self._CHROME_CSS)
        GLib.timeout_add(2500, self._click_connect)

    def _after_login_submit(self, result):
        if result == "noform":
            self._note("Could not find the login form on this server's page.")

    def _click_connect(self):
        if self._closing or self._connect_tried:
            return False
        self._connect_tried = True
        self._js(
            "(function(){try{"
            "var b=document.getElementById('connectbutton1');"
            "if(b&&b.offsetParent!==null){b.click();return 'connected';}"
            "if(typeof connectDesktop==='function'&&typeof currentNode!=='undefined'&&currentNode){"
            "connectDesktop(null,1);return 'connected';}"
            "return 'nobtn';}catch(e){return 'err';}})()",
            self._after_connect)
        return False

    def _after_connect(self, result):
        if result == "connected":
            self._set_status("Connecting…")
            # Now safe to hide the viewer's own control row + bottom toolbar.
            self._inject_style("mcd-desk-css", self._DESK_CSS)
            self._install_clip_shim()
            if not self._polling:          # one poll loop per panel, not one per reconnect
                self._polling = True
                GLib.timeout_add(1500, self._poll_status)
            # Apply the encoding/quality defaults (JPEG) once the stream is live.
            GLib.timeout_add(2500, lambda: (self._apply_compression(), False)[1])
        elif result == "nobtn":
            if not self._retry_connect:
                self._retry_connect = True
                self._connect_tried = False
                GLib.timeout_add(2000, self._click_connect)
            else:
                self._note("The desktop did not start. Click Reconnect, or check the device is online.")
        else:
            self._note("Could not start the desktop session. Click Reconnect to try again.")

    def _poll_status(self):
        if self._closing:
            self._polling = False
            return False
        self._js("(function(){var d=document.getElementById('deskstatus');"
                 "return d?d.innerText.trim():'';})()", self._on_status)
        return False

    def _on_status(self, text):
        if self._closing:
            return
        self._set_status(text or "")
        now_connected = text.lower().startswith("connected")
        if now_connected and not self._connected:
            self._connected = True
            self._set_controls_enabled(True)
            self.connect_btn.set_label("Disconnect")
        elif not now_connected and self._connected:
            self._connected = False
            self._set_controls_enabled(False)
            self.connect_btn.set_label("Connect")
        # keep polling while the panel is alive
        GLib.timeout_add(2000, self._poll_status)
