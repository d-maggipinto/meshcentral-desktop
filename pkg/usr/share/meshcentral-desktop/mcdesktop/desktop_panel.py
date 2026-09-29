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
_SPEED = [("Fastest", 50), ("Fast", 100), ("Medium", 300), ("Slow", 700)]   # ms between frames
_ENCODING = [("WEBP", 4), ("JPEG", 1), ("PNG", 2)]                # SendCompressionLevel type
# Agent-side scaling (1024 = 100%). "Auto" streams at the size we actually display, so a
# big / multi-monitor remote isn't sent at full resolution just to be shrunk locally.
_SCALE = [("Auto", 0), ("100%", 1024), ("75%", 768), ("50%", 512)]
_TYPE_MAX = 20000          # chars; typing is one key message pair per char

_COVER_CSS = b"""
.mcd-desk-cover { background-color: #16181c; }
.mcd-desk-cover label { color: #d8dade; }
.mcd-desk-cover .mcd-cover-title { font-size: 15pt; font-weight: bold; }
"""
_cover_css_installed = False


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
        self._connect_attempts = 0
        self._reveal_timer = None
        self._displays_sig = None
        self._display_updating = False
        # Connection state machine. _gen invalidates callbacks/timers of an older attempt
        # (reconnect, cancel), so a stale page or retry loop can never hijack a new one.
        self._phase = "idle"             # idle | loading | connecting | connected
        self._gen = 0
        self._page_ready = False         # the device desktop view is loaded in the WebView
        self._watchdog = None

        # --- toolbar row 1: session + view ---
        self._toolbar = bar = Gtk.Box(spacing=6, margin=6)
        self.connect_btn = Gtk.Button(label="Connect",
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
        typeb = Gtk.Button.new_from_icon_name("input-keyboard-symbolic", Gtk.IconSize.BUTTON)
        typeb.set_tooltip_text("Type this computer's clipboard text into the remote computer "
                               "(works even when clipboard sharing does not)")
        typeb.connect("clicked", lambda *_: self._type_clipboard())
        clip.add(paste)
        clip.add(typeb)
        clip.add(copyr)
        bar.pack_start(clip, False, False, 0)
        self._ctrl_widgets += [paste, typeb, copyr]

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
        self.speed = self._combo("Speed", _SPEED, 1, qbar)
        # Default to JPEG: WebKitGTK's WebP tile decoding can leave green/torn-tile
        # artifacts on the canvas. JPEG renders cleanly. (index 1 = JPEG)
        self.encoding = self._combo("Encoding", _ENCODING, 1, qbar)
        self.scale = self._combo("Scale", _SCALE, 0, qbar)
        for c in (self.quality, self.speed, self.encoding, self.scale):
            c.connect("changed", lambda *_: self._apply_compression(force=True))
            self._ctrl_widgets.append(c)
        # Display picker: only populated/shown when the agent reports >1 display
        # (SetDisplay on a number the agent didn't list breaks the stream).
        self._display_lbl = Gtk.Label(label="Display:")
        self.display = Gtk.ComboBoxText()
        self._display_ids = []
        self.display.connect("changed", self._on_display_changed)
        qbar.pack_start(self._display_lbl, False, False, 0)
        qbar.pack_start(self.display, False, False, 0)
        for w in (self._display_lbl, self.display):
            w.set_no_show_all(True)
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
        # The page's dialogs would be invisible behind our cover and block forever -
        # notably MeshCentral's "leave page?" beforeunload confirm on reconnect.
        self.view.connect("script-dialog", self._on_script_dialog)
        self.view.connect("size-allocate", self._on_view_resize)
        self._resize_timer = None

        # Native cover over the WebView: hides the web login page, SPA routing and the
        # viewer's own "connecting" UI, so the user only ever sees the remote screen.
        global _cover_css_installed
        if not _cover_css_installed:
            prov = Gtk.CssProvider()
            prov.load_from_data(_COVER_CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            _cover_css_installed = True
        self._cover = Gtk.EventBox()
        self._cover.get_style_context().add_class("mcd-desk-cover")
        cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                       halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self._cover_spinner = Gtk.Spinner()
        self._cover_spinner.set_size_request(36, 36)
        title = Gtk.Label(label=node.get("name", "Remote desktop"))
        title.get_style_context().add_class("mcd-cover-title")
        self._cover_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=60)
        self._cover_btn = Gtk.Button(label="Connect", halign=Gtk.Align.CENTER)
        self._cover_btn.get_style_context().add_class("suggested-action")
        self._cover_btn.connect("clicked", lambda *_: self._cover_action())
        self._cover_btn.set_no_show_all(True)
        for w in (self._cover_spinner, title, self._cover_label, self._cover_btn):
            cbox.pack_start(w, False, False, 0)
        self._cover.add(cbox)
        overlay = Gtk.Overlay()
        overlay.add(self.view)
        overlay.add_overlay(self._cover)
        self.pack_start(overlay, True, True, 0)
        self.show_all()
        self._set_controls_enabled(False)
        self._cover_show("Starting…")

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

    _FLOW_TIMEOUT_S = 45

    # JS that ends the viewer's session and drops its "leave page?" guard.
    _END_SESSION_JS = ("(function(){try{window.onbeforeunload=null;"
                       "if(typeof desktop!=='undefined'&&desktop&&typeof connectDesktop==='function')"
                       "{connectDesktop(null,0);}return 'ok';}catch(e){return 'err';}})()")

    def _set_phase(self, phase):
        self._phase = phase
        self._connected = phase == "connected"
        self.connect_btn.set_label({"idle": "Connect", "connected": "Disconnect"}.get(phase, "Cancel"))
        if phase != "connected":
            self._set_controls_enabled(False)
        if phase in ("idle", "connected") and self._watchdog:
            GLib.source_remove(self._watchdog)
            self._watchdog = None

    def _arm_watchdog(self):
        if self._watchdog:
            GLib.source_remove(self._watchdog)
        gen = self._gen

        def fire():
            self._watchdog = None
            if gen == self._gen and self._phase in ("loading", "connecting"):
                self._fail("The remote desktop did not start in time. Check that the device is "
                           "online and that you can reach the server, then Retry.")
            return False
        self._watchdog = GLib.timeout_add_seconds(self._FLOW_TIMEOUT_S, fire)

    def _fail(self, text):
        self._gen += 1                     # stop any pending retries of this attempt
        self._js(self._END_SESSION_JS)
        self._set_phase("idle")
        self._set_status("")
        self._cover_show(text, busy=False, button="Retry")

    def start_flow(self):
        """Full (re)connect: end any session, reload the web UI, sign in, open the device."""
        self._gen += 1
        self._logged_in = False
        self._navigated = False
        self._connect_tried = False
        self._page_ready = False
        self._connect_attempts = 0
        self._set_phase("loading")
        self._cover_show("Connecting…")
        self._set_status("Opening…")
        self._arm_watchdog()
        gen = self._gen

        def go(_v=None):
            if gen == self._gen and not self._closing:
                self.view.load_uri(self.app.ctrl.server.url + "/")
        self._js(self._END_SESSION_JS, go)

    def _on_script_dialog(self, _view, dialog):
        t = dialog.get_dialog_type()
        if t == WebKit2.ScriptDialogType.BEFORE_UNLOAD_CONFIRM:
            dialog.confirm_set_confirmed(True)       # always allow leaving/reloading
        elif t == WebKit2.ScriptDialogType.CONFIRM:
            dialog.confirm_set_confirmed(False)
        elif t == WebKit2.ScriptDialogType.ALERT:
            msg = (dialog.get_message() or "").strip()
            if msg:
                self._note(msg)
        return True                                  # handled: never show a hidden dialog

    def teardown(self):
        self._closing = True
        self._gen += 1
        if self._watchdog:
            GLib.source_remove(self._watchdog)
            self._watchdog = None
        self._clip_unlisten()
        if self._reveal_timer:
            GLib.source_remove(self._reveal_timer)
            self._reveal_timer = None
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
        if self._cover.get_visible() and self._cover_spinner.get_visible() and text:
            self._cover_label.set_text(text)

    def _note(self, text):
        if not self._connected:
            # Before the remote screen is up, errors belong on the cover itself.
            self._cover_show(text, busy=False, button="Retry")
            return
        self.info_label.set_text(text)
        self.info.set_message_type(Gtk.MessageType.WARNING)
        self.info.set_revealed(True)

    # ---- cover -------------------------------------------------------------
    def _cover_show(self, text, busy=True, button=None):
        self._cover_label.set_text(text)
        self._cover_spinner.set_visible(busy)
        (self._cover_spinner.start if busy else self._cover_spinner.stop)()
        self._cover_btn.set_visible(bool(button))
        if button:
            self._cover_btn.set_label(button)
        self._cover.show()

    def _cover_hide(self):
        self._cover_spinner.stop()
        self._cover.hide()
        self.view.grab_focus()           # keyboard goes straight to the remote screen

    def _cover_action(self):
        if self._cover_btn.get_label() == "Retry":
            self.start_flow()
        else:
            self._toggle_connect()

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

    def _apply_compression(self, force=False):
        if not self._connected:
            return
        q = _QUALITY[self.quality.get_active()][1]
        fr = _SPEED[self.speed.get_active()][1]
        enc = _ENCODING[self.encoding.get_active()][1]
        sc = _SCALE[self.scale.get_active()][1]
        # Auto scale: fit the remote's NATIVE size (recorded while still at 100%) into the
        # displayed area in device pixels; never upscale, never below 25%. Only re-sent
        # when something actually changed, since it can make the agent resend frames.
        self._js(
            "(function(){try{if(typeof desktop==='undefined'||!desktop||desktop.State!==3"
            "||!desktop.m||!desktop.m.SendCompressionLevel)return 'notready';var m=desktop.m;"
            "if(!window.__mcdNative&&(m.ScalingLevel||1024)==1024&&m.ScreenWidth>8&&m.ScreenHeight>8)"
            "{window.__mcdNative=[m.ScreenWidth,m.ScreenHeight];}"
            f"var sc={sc};if(sc===0){{var n=window.__mcdNative;if(!n)return 'nonative';"
            "var p=document.getElementById('DeskParent');var r=window.devicePixelRatio||1;"
            "var vw=((p&&p.clientWidth)||innerWidth)*r,vh=((p&&p.clientHeight)||innerHeight)*r;"
            "sc=Math.max(256,Math.min(1024,Math.floor(1024*Math.min(vw/n[0],vh/n[1]))));"
            "sc=Math.round(sc/32)*32;}"
            f"var key=[{enc},{q},sc,{fr}].join(',');"
            f"if(!{str(force).lower()}&&window.__mcdComp===key)return 'same';"
            f"window.__mcdComp=key;m.SendCompressionLevel({enc},{q},sc,{fr});return 'ok:'+sc;}}"
            "catch(e){return 'err';}})()")

    def _toggle_connect(self, *_):
        if self._phase != "idle":
            # Disconnect when connected, Cancel while loading/connecting.
            self._gen += 1
            self._js(self._END_SESSION_JS)
            self._set_phase("idle")
            self._set_status("Disconnected")
            self._cover_show("Disconnected", busy=False, button="Connect")
        elif self._page_ready:
            # The device view is already loaded: just start a new KVM session.
            self._gen += 1
            self._connect_attempts = 0
            self._set_phase("loading")
            self._cover_show("Connecting…")
            self._set_status("Starting remote session…")
            self._arm_watchdog()
            self._click_connect(self._gen)
        else:
            self.start_flow()

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
        if _SCALE[self.scale.get_active()][1] == 0:
            self._apply_compression()      # display size changed -> maybe new auto scale
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

    # ---- type clipboard as keystrokes -------------------------------------------
    # Independent of the agent's clipboard support (fragile when the agent runs as a
    # root service on Linux): the text goes over the KVM keyboard channel, the same
    # path the web UI's "Type text" uses (SendKeyUnicode), with Enter/Tab as real keys.
    def _type_clipboard(self):
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        if not text:
            self._note("This computer's clipboard is empty (no text to type).")
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text) > _TYPE_MAX:
            self._note(f"Clipboard text is too long to type ({len(text)} characters; max {_TYPE_MAX}).")
            return
        self._js(
            "(function(){try{if(typeof desktop==='undefined'||!desktop||desktop.State!==3||!desktop.m)"
            "return 'notready';var m=desktop.m,t=" + json.dumps(text) + ";"
            "for(var i=0;i<t.length;i++){var c=t.charCodeAt(i);"
            "if(c==10){m.SendKeyMsgKC(1,13,false);m.SendKeyMsgKC(2,13,false);}"
            "else if(c==9){m.SendKeyMsgKC(1,9,false);m.SendKeyMsgKC(2,9,false);}"
            "else{m.SendKeyUnicode(1,c);m.SendKeyUnicode(2,c);}}"
            "return 'ok';}catch(e){return 'err';}})()",
            lambda r: self._set_status(f"Typed {len(text)} characters" if r == "ok"
                                       else "Connect the desktop first"))
        self.view.grab_focus()

    # ---- display picker (multi-monitor remotes) ---------------------------------
    def _refresh_displays(self):
        self._js("(function(){try{var m=desktop.m;return JSON.stringify({d:m.displays||{},"
                 "s:m.selectedDisplay});}catch(e){return '';}})()", self._on_displays)

    def _on_displays(self, raw):
        try:
            info = json.loads(raw) if raw else None
        except ValueError:
            info = None
        if not info:
            return
        ids = sorted((int(k) for k in info.get("d", {})), key=lambda i: (i != 65535, i))
        sig = (tuple(ids), info.get("s"))
        if sig == self._displays_sig:
            return
        self._displays_sig = sig
        show = len(ids) > 1
        self._display_lbl.set_visible(show)
        self.display.set_visible(show)
        if not show:
            return
        self._display_updating = True
        self.display.remove_all()
        self._display_ids = ids
        for i in ids:
            self.display.append_text("All displays" if i == 65535 else f"Display {i}")
        if info.get("s") in ids:
            self.display.set_active(ids.index(info["s"]))
        self._display_updating = False
        # Re-apply a remembered choice for this device (only if the agent lists it).
        want = (self.app.config.get("desktop_display") or {}).get(self.node["_id"])
        if want in ids and want != info.get("s"):
            self.display.set_active(ids.index(want))

    def _on_display_changed(self, combo):
        if self._display_updating or not self._connected:
            return
        i = combo.get_active()
        if i < 0 or i >= len(self._display_ids):
            return
        num = self._display_ids[i]
        self.app.config.setdefault("desktop_display", {})[self.node["_id"]] = num
        self.app.save_config()
        self._js(f"(function(){{try{{desktop.m.SetDisplay({num});window.__mcdNative=null;"
                 "window.__mcdComp=null;return 'ok';}catch(e){return 'err';}})()")
        # New display = new native size: re-measure at 100% then re-apply auto scale.
        GLib.timeout_add(1500, lambda: (self._apply_compression(force=True), False)[1])
        self.refit_soon()

    # ---- clipboard: native, over OUR control connection ------------------------
    # getclip/setclip are plain control-channel messages; the agent's reply is routed
    # back to the session that asked (with nodeid set), so we don't need the web page,
    # its document.hasFocus() gate or a navigator.clipboard shim at all. Note both are
    # dropped SILENTLY by the server when domain ClipboardGet/ClipboardSet is false, and
    # the agent only answers getclip when the remote clipboard has text, hence timeouts.
    _CLIP_TIMEOUT_MS = 6000
    _CLIP_FAST_MS = 2500           # getclip gets this long before the eval fallback starts

    # Fallback read via the agent console (admin "eval"). The agent's own getclip
    # swallows every read error (no reply at all), which is what happens on a Linux
    # agent running as a root service. Here the same dispatchRead() runs, but its result
    # OR its error is parked on the agent and fetched by a second eval. eval replies go
    # only to OUR session (console output without a sessionid would be broadcast to
    # every admin's console, so the clipboard text is never printed that way).
    _CLIP_EVAL_START = ('eval "(function(){var A=require(\'MeshAgent\');A.__mcdc=null;try{'
                        'require(\'clipboard\').dispatchRead().then(function(s){A.__mcdc={ok:(s==null?'
                        '\'\':\'\'+s)};},function(e){A.__mcdc={err:\'\'+e};});}catch(e){A.__mcdc='
                        '{err:\'\'+e};}return \'MCDCLIP0:started\';})()"')
    _CLIP_EVAL_FETCH = ('eval "(function(){var A=require(\'MeshAgent\');var r=A.__mcdc;'
                        'if(r){A.__mcdc=null;}return \'MCDCLIP1:\'+JSON.stringify(r);})()"')

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
        self._clip_read_gen = getattr(self, "_clip_read_gen", 0) + 1
        self._clip_read_done = False
        self.app.ctrl.send_node_msg(self.node["_id"], "getclip", tag=2)
        self._set_status("Reading remote clipboard…")
        if self._clip_get_timer:
            GLib.source_remove(self._clip_get_timer)
        self._clip_get_timer = GLib.timeout_add(self._CLIP_FAST_MS, self._clip_eval_start,
                                                self._clip_read_gen)

    def _clip_got_text(self, data):
        self._clip_read_done = True
        if self._clip_get_timer:
            GLib.source_remove(self._clip_get_timer)
            self._clip_get_timer = None
        if data:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(data, -1)
            self._set_status(f"Remote clipboard copied here ({len(data)} chars)")
        else:
            self._set_status("")
            self._note("The remote clipboard is empty (or holds no text). On the remote computer, "
                       "copy with Ctrl+C (Ctrl+Shift+C in a terminal), just selecting text is not enough.")

    def _clip_eval_start(self, gen):
        self._clip_get_timer = None
        if gen != self._clip_read_gen or self._clip_read_done or self._closing:
            return False
        self.app.ctrl.send_node_msg(self.node["_id"], "console", value=self._CLIP_EVAL_START)
        self._clip_fetch_tries = 0
        self._clip_get_timer = GLib.timeout_add(500, self._clip_eval_fetch, gen)
        return False

    def _clip_eval_fetch(self, gen):
        self._clip_get_timer = None
        if gen != self._clip_read_gen or self._clip_read_done or self._closing:
            return False
        self._clip_fetch_tries += 1
        if self._clip_fetch_tries > 14:                 # ~7 s: agent never finished the read
            self._clip_read_done = True
            self._clip_get_timeout()
            return False
        self.app.ctrl.send_node_msg(self.node["_id"], "console", value=self._CLIP_EVAL_FETCH)
        self._clip_get_timer = GLib.timeout_add(500, self._clip_eval_fetch, gen)
        return False

    def _on_clip_eval_reply(self, value):
        # value is the JSON-encoded eval result, e.g. "\"MCDCLIP1:{\\\"ok\\\":\\\"text\\\"}\""
        try:
            v = json.loads(value)
        except (TypeError, ValueError):
            v = value
        if not isinstance(v, str) or not v.startswith("MCDCLIP1:") or self._clip_read_done:
            return
        try:
            r = json.loads(v[len("MCDCLIP1:"):])
        except ValueError:
            return
        if r is None:
            return                                      # not finished yet; keep polling
        if "ok" in r:
            self._clip_got_text(r["ok"])
        else:
            self._clip_read_done = True
            if self._clip_get_timer:
                GLib.source_remove(self._clip_get_timer)
                self._clip_get_timer = None
            self._set_status("")
            self._note("The remote agent could not read its clipboard: " + str(r.get("err")))

    def _on_clip_msg(self, msg):
        if self._closing or msg.get("nodeid") != self.node["_id"]:
            return
        t = msg.get("type")
        if t == "getclip" and msg.get("tag") == 2:
            data = msg.get("data")
            if isinstance(data, str) and data and not self._clip_read_done:
                self._clip_got_text(data)
        elif t == "console" and "MCDCLIP" in str(msg.get("value")):
            self._on_clip_eval_reply(msg.get("value"))
        elif t == "setclip":
            if self._clip_set_timer:
                GLib.source_remove(self._clip_set_timer)
                self._clip_set_timer = None
            self._set_status("Clipboard sent to remote" if msg.get("success") else "Remote rejected the clipboard")

    def _clip_get_timeout(self):
        self._clip_get_timer = None
        self._set_status("")
        self._note("The remote agent did not return its clipboard (it started the read but never "
                   "finished, and reported no error). Clipboard reading may be disabled on the server "
                   "(ClipboardGet), or your account lacks agent-console rights for the fallback.")
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
        if self._closing or self._phase != "loading":
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
            self.view.load_uri(self.desk_url)
            return
        # On the device desktop view: strip outer chrome, then click Connect as soon as
        # the viewer's button exists (polled; no fixed delay).
        self._inject_style("mcd-chrome-css", self._CHROME_CSS)
        self._page_ready = True
        if not self._connect_tried:
            self._connect_tried = True
            self._set_status("Starting remote session…")
            self._connect_attempts = 0
            self._click_connect(self._gen)

    def _after_login_submit(self, result):
        if result == "noform":
            self._note("Could not find the login form on this server's page.")

    def _click_connect(self, gen):
        if self._closing or gen != self._gen or self._phase != "loading":
            return False
        self._connect_attempts += 1
        self._js(
            "(function(){try{"
            "var b=document.getElementById('connectbutton1');"
            "if(b&&b.offsetParent!==null){b.click();return 'connected';}"
            "if(typeof connectDesktop==='function'&&typeof currentNode!=='undefined'&&currentNode){"
            "connectDesktop(null,1);return 'connected';}"
            "return 'nobtn';}catch(e){return 'err';}})()",
            lambda r: self._after_connect(r, gen))
        return False

    def _after_connect(self, result, gen):
        if gen != self._gen or self._phase != "loading":
            return
        if result == "connected":
            self._set_phase("connecting")
            self._set_status("Connecting to remote screen…")
            # Now safe to hide the viewer's own control row + bottom toolbar.
            self._inject_style("mcd-desk-css", self._DESK_CSS)
            self._install_clip_shim()
            self._js("window.__mcdNative=null;window.__mcdComp=null;'ok'")
            if not self._polling:          # one poll loop per panel, not one per reconnect
                self._polling = True
                GLib.timeout_add(300, self._poll_status)
        elif result == "nobtn":
            if self._connect_attempts < 80:          # ~20 s at 250 ms
                GLib.timeout_add(250, self._click_connect, gen)
            else:
                self._fail("The desktop did not start. Check that the device is online, then Retry.")
        else:
            self._fail("Could not start the desktop session.")

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
        now_connected = text.lower().startswith("connected")
        if self._connected:
            self._set_status(text or "")
        # Only a session WE started counts: a stale "Connected" from the page being left
        # behind during a reconnect is ignored because the phase isn't "connecting".
        if now_connected and self._phase == "connecting":
            self._set_phase("connected")
            self._set_controls_enabled(True)
            self._apply_compression(force=True)
            self._wait_first_frame(0, 0, self._gen)
        elif not now_connected and self._phase == "connected":
            self._set_phase("idle")
            self._cover_show("The remote session ended.", busy=False, button="Retry")
        if self._connected:
            self._refresh_displays()
        # keep polling while the panel is alive: fast while connecting, slow after
        GLib.timeout_add(2000 if self._connected else 300, self._poll_status)

    def _wait_first_frame(self, tries, hits, gen):
        # Reveal only once the viewer has drawn a frame, so the user never sees an empty,
        # black or half-built view. The first tile makes onResize() size the canvas to the
        # real screen and clear FirstDraw (the viewer starts with a 960x701 placeholder).
        # Require it on two consecutive checks so the first frame has time to paint.
        self._reveal_timer = None
        if self._closing or not self._connected or gen != self._gen:
            return False
        def got(v):
            if gen != self._gen or not self._connected:
                return
            h = hits + 1 if v == "drawn" else 0
            if h >= 2 or tries >= 30:              # ~6 s cap, then show whatever is there
                self._refit_canvas()
                self._cover_hide()
                self._set_status("Connected")
            else:
                self._reveal_timer = GLib.timeout_add(200, self._wait_first_frame, tries + 1, h, gen)
        self._js("(function(){try{var m=desktop.m,c=m.Canvas.canvas;"
                 "var real=!(m.ScreenWidth==960&&m.ScreenHeight==701)&&m.ScreenWidth>8&&m.ScreenHeight>8;"
                 "return (desktop.State===3&&real&&m.FirstDraw===false&&c.width===m.ScreenWidth)?'drawn':'wait';"
                 "}catch(e){return 'wait';}})()", got)
        return False
