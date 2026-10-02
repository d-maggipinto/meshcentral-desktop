# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Remote desktop panel: embeds MeshCentral's OWN web desktop KVM viewer but wraps it
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
import urllib.parse
import time

from . import rights, ui
from .osdep import IS_WINDOWS
from .webview import WebView, server_origin, same_origin_policy  # noqa: F401 (re-exported for callers)
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

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
.mcd-hint { background-color: rgba(20, 22, 26, 0.88); color: #eceef1; border-radius: 8px;
            padding: 8px 16px; font-weight: bold; }
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
        # Automatic two-way clipboard sync (NoMachine-style), see "clipboard sync" below.
        self._sync_timer = None
        self._sync_owner_sig = None
        self._sync_focus_sig = None
        self._sync_last_local = None
        self._sync_last_remote = None
        self._sync_baseline = True
        self._status_hold = 0.0          # keep a transient status (e.g. clipboard) visible briefly
        self._kb_seat = None             # set while we hold the keyboard grab (hotkeys -> remote)
        # True while the user wants a session (connect/reconnect) and has not pressed
        # Disconnect/Cancel: an agent restart (e.g. agentupdate) then reconnects by itself.
        self._want_session = False
        self._waiting_agent = False
        self._hint_timer = None

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
        self._input_widgets = [cad]                    # disabled for view-only accounts

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
        self._input_widgets += [paste, typeb]

        full = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic", Gtk.IconSize.BUTTON)
        full.set_tooltip_text("Fullscreen (Ctrl+Alt+F)")
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
        # Default WebP like the web UI (desktopsettings.agentencoding 4). The format the agent
        # really sends is read from the tiles and shown after every change (_check_format).
        self.encoding = self._combo("Encoding", _ENCODING, 0, qbar)
        self.scale = self._combo("Scale", _SCALE, 0, qbar)
        qbar.pack_start(Gtk.Label(label="Clipboard sync:"), False, False, 0)
        self.clip_sync = Gtk.Switch(valign=Gtk.Align.CENTER,
                                    active=bool(app.config.get("clipboard_sync", True)))
        self.clip_sync.set_tooltip_text("Automatically share the clipboard both ways while connected")
        self.clip_sync.connect("notify::active", self._on_sync_toggled)
        qbar.pack_start(self.clip_sync, False, False, 0)
        qbar.pack_start(Gtk.Label(label="Send hotkeys:"), False, False, 0)
        self.hotkeys = Gtk.Switch(valign=Gtk.Align.CENTER,
                                  active=bool(app.config.get("desktop_hotkeys", True)))
        self.hotkeys.set_tooltip_text(
            "Send system shortcuts (Super, Alt+Tab, Alt+F4, Ctrl+Alt+…) to the remote computer while "
            "its screen has focus. Ctrl+Alt+F always toggles fullscreen; Super+Esc (GNOME) restores "
            "local shortcuts.")
        self.hotkeys.connect("notify::active", self._on_hotkeys_toggled)
        qbar.pack_start(self.hotkeys, False, False, 0)
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

        # Embedded web view (WebKitGTK / Edge WebView2): no page clipboard access, no windows,
        # page dialogs never block (beforeunload confirmed), only the configured server.
        self.web = WebView(app, server_url=app.ctrl.server.url, webgl=True)
        self.view = self.web.widget
        self.web.on_load_finished = self._on_load
        self.web.on_alert = lambda msg: self._note("Message from the server page: " + msg[:300])
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
        self._hint = Gtk.Label()
        self._hint.get_style_context().add_class("mcd-hint")
        self._hint_rev = Gtk.Revealer(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margin_top=24,
                                      transition_type=Gtk.RevealerTransitionType.CROSSFADE)
        self._hint_rev.add(self._hint)
        self._hint_rev.set_no_show_all(True)
        overlay.add_overlay(self._hint_rev)
        overlay.set_overlay_pass_through(self._hint_rev, True)
        # Keyboard grab follows the remote screen's focus (see "keyboard" section).
        self.web.on_focus_changed = lambda on: self._kb_update() if on else GLib.idle_add(self._kb_update)
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
        self._started = True             # no auto-connect: the cover offers Connect
        self._set_status("Disconnected")
        self._cover_show("Not connected", busy=False, button="Connect")

    _FLOW_TIMEOUT_S = 45

    # JS that ends the viewer's session and drops its "leave page?" guard.
    _END_SESSION_JS = ("(function(){try{window.onbeforeunload=null;"
                       "if(typeof desktop!=='undefined'&&desktop&&typeof connectDesktop==='function')"
                       "{connectDesktop(null,0);}return 'ok';}catch(e){return 'err';}})()")

    def _set_phase(self, phase):
        was_connected = self._phase == "connected"
        self._phase = phase
        self._connected = phase == "connected"
        if self._connected and not was_connected:
            self._sync_start()
        elif was_connected and not self._connected:
            self._sync_stop()
        self._kb_update()
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
        self._want_session = True
        self._waiting_agent = False
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
                self.web.load_uri(self.app.ctrl.server.url + "/")
        self._js(self._END_SESSION_JS, go)

    def teardown(self):
        self._sync_stop()
        self._kb_ungrab()
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
            self.web.load_uri("about:blank")
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
        self.web.set_page_visible(False)     # Windows: GTK cannot draw over the native page

    def _cover_hide(self):
        self._cover_spinner.stop()
        self._cover.hide()
        self.web.set_page_visible(True)
        self.web.grab_focus()            # keyboard goes straight to the remote screen

    def _cover_action(self):
        if self._cover_btn.get_label() == "Retry":
            self.start_flow()
        else:
            self._toggle_connect()          # "Connect", or "Cancel" while waiting for the agent

    def on_node_update(self, node):
        """Called by the main window on every device refresh."""
        self.node = node
        online = bool((node.get("conn") or 0) & 1)
        if not online and self._want_session and not self._waiting_agent and not self._closing:
            # Agent went away (update/restart): end the dead session and wait for it.
            self._gen += 1
            self._js(self._END_SESSION_JS)
            self._set_phase("idle")
            self._waiting_agent = True
            self._set_status("Agent offline")
            self._cover_show("The remote agent went offline (restarting or updating?).\n"
                             "Reconnecting automatically as soon as it is back…", button="Cancel")
        elif online and self._waiting_agent and not self._closing:
            self._waiting_agent = False
            self.start_flow()

    @property
    def caps(self):
        return rights.node_caps(self.app.ctrl, self.app.meshes, self.node)

    def _set_controls_enabled(self, on):
        for w in self._ctrl_widgets:
            w.set_sensitive(on)
        if on and not self.caps.desktop_input:
            # View-only account: the agent ignores our input anyway; say so instead.
            for w in self._input_widgets:
                w.set_sensitive(False)
                w.set_tooltip_text("View only. Your account may not control this device")
            self.hotkeys.set_sensitive(False)
            self._flash_status("View only", 5)

    def _js(self, code, cb=None):
        def done(val):
            if not self._closing and cb:
                cb(val)
        self.web.run_js(code, done)

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
            # no native size yet: keep the current scale but still send encoding / quality / speed
            f"var sc={sc};if(sc===0){{var n=window.__mcdNative;if(!n){{sc=m.ScalingLevel||1024;}}else{{"
            "var p=document.getElementById('DeskParent');var r=window.devicePixelRatio||1;"
            "var vw=((p&&p.clientWidth)||innerWidth)*r,vh=((p&&p.clientHeight)||innerHeight)*r;"
            "sc=Math.max(256,Math.min(1024,Math.floor(1024*Math.min(vw/n[0],vh/n[1]))));"
            "sc=Math.round(sc/32)*32;}}"
            f"var key=[{enc},{q},sc,{fr}].join(',');"
            f"if(!{str(force).lower()}&&window.__mcdComp===key)return 'same';"
            + self._FMT_HOOK_JS +
            f"window.__mcdComp=key;window.__mcdFmt=null;m.SendCompressionLevel({enc},{q},sc,{fr});"
            # a static screen sends no new tiles: ask for a full frame so the change shows
            f"if({str(force).lower()}&&m.SendRefresh)m.SendRefresh();return 'ok:'+sc;}}"
            "catch(e){return 'err';}})()", lambda r: self._after_compression(r, enc, force))

    # Records the image format of the tiles the agent sends (first bytes: JPEG FF D8, PNG 89 50,
    # WebP 'RI'FF). The viewer labels every tile image/jpeg and lets the decoder sniff it.
    _FMT_HOOK_JS = ("if(!m.__mcdFmtHook&&m.ProcessPictureMsg){var o=m.ProcessPictureMsg;"
                    "m.ProcessPictureMsg=function(d,x,y){try{var t=d.slice(4);"
                    "if(t instanceof ArrayBuffer)t=new Uint8Array(t);var a=t[0],b=t[1];"
                    "window.__mcdFmt=(a==255&&b==216)?'JPEG':(a==137&&b==80)?'PNG':(a==82&&b==73)?'WEBP':'?';"
                    "}catch(e){}return o.call(m,d,x,y);};m.__mcdFmtHook=1;}")

    def _after_compression(self, result, enc, force):
        if force and result.startswith("ok"):
            gen = self._gen
            GLib.timeout_add(2500, lambda: (self._check_format(enc, gen), False)[1])

    def _check_format(self, enc, gen):
        """Show which format the agent actually sends after an encoding change."""
        if self._closing or gen != self._gen or not self._connected:
            return
        want = dict((v, k) for k, v in _ENCODING)[enc]

        def got(fmt):
            fmt = (fmt or "").strip('"')
            if fmt in ("", "null", "undefined", "?"):
                self.encoding.set_tooltip_text(f"Requested {want}; no new image received yet")
                return
            if fmt == want:
                self.encoding.set_tooltip_text(f"The agent is sending {fmt}")
                self._flash_status(f"Encoding: {fmt}", 3)
            else:
                self.encoding.set_tooltip_text(f"Requested {want}, the agent is sending {fmt}")
                self._flash_status(f"Requested {want}, the agent sends {fmt}", 8)
        self._js("(function(){return String(window.__mcdFmt);})()", got)

    def _toggle_connect(self, *_):
        if self._phase != "idle" or self._waiting_agent:
            # Disconnect when connected, Cancel while loading/connecting/waiting.
            self._want_session = False
            self._waiting_agent = False
            self._gen += 1
            self._js(self._END_SESSION_JS)
            self._set_phase("idle")
            self._set_status("Disconnected")
            self._cover_show("Disconnected", busy=False, button="Connect")
        elif self._page_ready:
            # The device view is already loaded: just start a new KVM session.
            self._want_session = True
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

    # ---- Ctrl+Alt+Del ----------------------------------------------------------------
    # Windows: Ctrl+Alt+Del is the secure attention sequence, which Windows NEVER acts on
    # when it arrives as injected keys -> the viewer's own CTRLALTDEL message (sendcad, like
    # the web UI's button; the agent service calls SendSAS). Linux ignores that message
    # but acts on the real key combo: Ctrl(17) + Alt(18) + Delete(46, extended).
    def _send_cad(self):
        if ui.is_windows(self.node):
            body = "m.SendCtrlAltDelMsg();"
        else:
            body = ("m.SendKeyMsgKC(1,17,false);m.SendKeyMsgKC(1,18,false);m.SendKeyMsgKC(1,46,true);"
                    "m.SendKeyMsgKC(2,46,true);m.SendKeyMsgKC(2,18,false);m.SendKeyMsgKC(2,17,false);")
        self._js(
            "(function(){try{"
            "if(typeof desktop==='undefined'||!desktop||desktop.State!==3||!desktop.m)return 'notready';"
            "var m=desktop.m;" + body +
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
        self.web.grab_focus()

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

    # ---- keyboard: hotkeys + layout --------------------------------------------
    # Hotkeys: GNOME/X take Super, Alt+Tab, Alt+F4, Ctrl+Alt+arrows... before the app sees
    # them. While the remote screen has focus we grab the keyboard; on Wayland GTK turns a
    # keyboard grab into zwp_keyboard_shortcuts_inhibit (GNOME asks the user once; Super+Esc
    # restores local shortcuts), on X11 it is a real XGrabKeyboard. Released on focus loss.
    def _on_hotkeys_toggled(self, sw, _pspec):
        self.app.config["desktop_hotkeys"] = sw.get_active()
        self.app.save_config()
        self._kb_update()

    def _kb_update(self):
        want = (self._connected and not self._closing and self.hotkeys.get_active()
                and self.caps.desktop_input
                and self.web.has_focus())
        if want and not self._kb_seat and IS_WINDOWS:
            # Windows: a GTK grab would take the keys away from WebView2; a low-level hook takes
            # only the system shortcuts away from Windows instead (winkeys.py)
            from . import winkeys, winweb
            top = self.get_toplevel()
            if isinstance(top, Gtk.Window) and top.get_window() is not None:
                self._kb_seat = winkeys.KeyboardHook(self._send_vk, winweb._hwnd_of(top.get_window()))
                self._kb_seat.start()
        elif want and not self._kb_seat:
            top = self.get_toplevel()
            gdkwin = top.get_window() if isinstance(top, Gtk.Window) else None
            seat = Gdk.Display.get_default().get_default_seat()
            if gdkwin is not None and seat is not None:
                st = seat.grab(gdkwin, Gdk.SeatCapabilities.KEYBOARD, True, None, None, None, None)
                if st == Gdk.GrabStatus.SUCCESS:
                    self._kb_seat = seat
        elif not want and self._kb_seat:
            self._kb_ungrab()
        return False

    def _send_vk(self, vk, down, ext):
        """A key taken by the Windows hook, sent to the remote as a key code."""
        self._js("(function(){try{if(desktop&&desktop.State===3&&desktop.m)"
                 "desktop.m.SendKeyMsgKC(%d,%d,%s);}catch(e){}})()" % (1 if down else 2, vk, "true" if ext else "false"))

    def _kb_ungrab(self):
        if self._kb_seat:
            try:
                (self._kb_seat.stop if IS_WINDOWS else self._kb_seat.ungrab)()
            except Exception:
                pass
            self._kb_seat = None

    # Layout: printable keys already go to the remote as Unicode (layout-independent), but
    # on Linux AltGr arrives as its own key ("AltGraph") and the viewer forwards it as a
    # held Right-Alt BEFORE the composed character, so the remote sees e.g. Alt+@ and
    # garbles @ # [ ] { } € on non-US layouts. Swallow AltGraph; the character that
    # AltGr produced still arrives as Unicode.
    # Super / Windows key: WebKitGTK reports it with keyCode 0 and metaKey false, so the
    # viewer sent key 0 (nothing) and typed Win+R's "r" as Unicode text, which Windows
    # never treats as a shortcut. Send Super as VK_LWIN/VK_RWIN (extended, like the web
    # UI's own Start button) and, while it is held, printable keys as key codes; their
    # key-up goes out as the same code. handleReleaseKeys (focus loss) forgets it all.
    # Ctrl+Alt+Delete typed on the keyboard: on a Windows target (m.__mcdWin, set after the
    # hook) it becomes the secure attention message, see _send_cad.
    _KEYS_JS = ("(function(){try{var m=desktop.m;if(!m||m.__mcdKeys)return 'skip';"
                "var kd=m.handleKeyDown,ku=m.handleKeyUp,kp=m.handleKeys,rk=m.handleReleaseKeys;"
                "var sup={},held={};"
                "function ag(e){return !!e&&e.key==='AltGraph';}"
                "function sk(e){if(!e)return 0;var c=e.code||'',k=e.key||'';"
                "if(c==='OSRight'||c==='MetaRight')return 92;"
                "if(c==='OSLeft'||c==='MetaLeft'||k==='Super'||k==='Meta'||k==='OS')return 91;return 0;}"
                "function on(){for(var x in sup)return true;return false;}"
                "function no(e){if(e.preventDefault)e.preventDefault();if(e.stopPropagation)e.stopPropagation();return false;}"
                "function live(){return m.stopInput!==true&&m.State==3;}"
                "m.handleKeyDown=function(e){if(ag(e))return no(e);var w=sk(e);"
                "if(w){if(live()){sup[w]=1;m.SendKeyMsgKC(1,w,true);}return no(e);}"
                "if(m.__mcdWin&&e.keyCode==46&&e.ctrlKey&&e.altKey){if(live()){held['cad']=1;m.SendCtrlAltDelMsg();}return no(e);}"
                "if(on()&&live()&&typeof e.key=='string'&&e.key.length==1&&e.keyCode){"
                "held[e.code||e.keyCode]=e.keyCode;m.SendKeyMsgKC(1,e.keyCode,false);return no(e);}"
                "return kd.apply(m,arguments);};"
                "m.handleKeyUp=function(e){if(ag(e))return no(e);var w=sk(e);"
                "if(w){if(sup[w]){delete sup[w];if(live())m.SendKeyMsgKC(2,w,true);}return no(e);}"
                "if(e&&e.keyCode==46&&held['cad']){delete held['cad'];return no(e);}"
                "var h=e&&held[e.code||e.keyCode];"
                "if(h){delete held[e.code||e.keyCode];if(live())m.SendKeyMsgKC(2,h,false);return no(e);}"
                "return ku.apply(m,arguments);};"
                "m.handleKeys=function(e){if(on())return no(e);return kp.apply(m,arguments);};"
                "m.handleReleaseKeys=function(){sup={};held={};return rk.apply(m,arguments);};"
                "m.__mcdKeys=1;return 'ok';}catch(e){return 'err';}})()")

    def show_hint(self, text, secs=3):
        self._hint.set_text(text)
        self._hint.show()
        self._hint_rev.show()
        self._hint_rev.set_reveal_child(True)
        if self._hint_timer:
            GLib.source_remove(self._hint_timer)

        def hide():
            self._hint_timer = None
            self._hint_rev.set_reveal_child(False)
            return False
        self._hint_timer = GLib.timeout_add_seconds(secs, hide)

    # ---- clipboard sync (automatic, both directions) ----------------------------
    # On connect we patch the running agent ONCE (in memory; reverts on agent restart):
    #  * monitor-info.getXInfo: when it returns an empty display (the user's Kali target),
    #    fall back to DISPLAY/XAUTHORITY of a desktop-user process from /proc;
    #  * clipboard.dispatchWrite (Linux + xclip): keep the xclip that owns the selection
    #    alive until someone else copies, the stock writer SIGKILLs it after 20 s, which
    #    silently empties the remote clipboard.
    # After that the agent's own getclip/setclip work, so sync uses them: getclip tag:3
    # every second (the web UI's auto-clipboard path; the agent does NOT event-log tag 3)
    # and setclip on local changes. Only the one-time patch goes through console eval.
    _AGENT_PATCH = 'eval "(function(){var A=require(\'MeshAgent\');if(A.__mcdPatch==\'mcd1\'){return \'MCDPATCH:already\';}var fs=require(\'fs\'),NL=String.fromCharCode(10);function scan(uid){var ps=fs.readdirSync(\'/proc\');for(var i=0;i<ps.length;i++){var p=ps[i];if(!(parseInt(p)>0))continue;try{var ls=fs.readFileSync(\'/proc/\'+p+\'/status\').toString().split(NL);var u=-1;for(var j=0;j<ls.length;j++){if(ls[j].indexOf(\'Uid:\')==0){u=parseInt(ls[j].substring(4).trim());break;}}if(u!=uid)continue;var b=fs.readFileSync(\'/proc/\'+p+\'/environ\');var e={},st=0;for(var k=0;k<=b.length;k++){if(k==b.length||b[k]==0){if(k>st){var kv=b.slice(st,k).toString();var q=kv.indexOf(\'=\');if(q>0){e[kv.substring(0,q)]=kv.substring(q+1);}}st=k+1;}}if(e.DISPLAY){return {d:e.DISPLAY,a:e.XAUTHORITY};}}catch(x){}}return null;}var mi=require(\'monitor-info\');var o=A.__mcdOrigXInfo||mi.getXInfo;A.__mcdOrigXInfo=o;mi.getXInfo=function(uid){var r=null;try{r=o.call(mi,uid);}catch(e){}if(r&&r.display){return r;}var f=scan(uid);if(!f){return r;}if(!r){r={tty:\'?\',exportEnv:function(){return {XAUTHORITY:this.xauthority||\'\',DISPLAY:this.display};}};}r.display=f.d;if(f.a){r.xauthority=f.a;}return r;};var cb=require(\'clipboard\');var xc=cb.xclip;if(xc&&process.platform==\'linux\'){cb.dispatchWrite=function(data){var uid=require(\'user-sessions\').consoleUid();var xi=mi.getXInfo(uid);if(!xi||!xi.display){return;}var env={DISPLAY:xi.display};if(xi.xauthority){env.XAUTHORITY=xi.xauthority;}var c=require(\'child_process\').execFile(xc,[\'xclip\',\'-selection\',\'clipboard\',\'-i\'],{uid:uid,env:env});c.stdout.on(\'data\',function(){});c.stderr.on(\'data\',function(){});c.stdin.write(\'\'+data,function(){this.end();});A.__mcdWriter=c;};}A.__mcdPatch=\'mcd1\';return \'MCDPATCH:ok:\'+(xc?\'xclip\':\'native\');})()"'
    _SYNC_POLL_MS = 1000

    def _on_sync_toggled(self, sw, _pspec):
        self.app.config["clipboard_sync"] = sw.get_active()
        self.app.save_config()
        if sw.get_active() and self._connected:
            self._sync_start()
        elif not sw.get_active():
            self._sync_stop()

    def _sync_start(self):
        if not self.clip_sync.get_active() or self._sync_timer:
            return
        self._clip_listen()
        if self.caps.console:
            # The in-memory agent patch needs agent-console rights (it is a console eval).
            # Without them, sync still uses plain getclip/setclip (fine on healthy agents).
            self.app.ctrl.send_node_msg(self.node["_id"], "console", value=self._AGENT_PATCH)
        # Baselines: only CHANGES made after connecting are synced (connecting must not
        # overwrite either side's clipboard).
        self._sync_baseline = True
        self._sync_last_remote = None
        self._sync_last_local = None
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.request_text(lambda _c, text: setattr(self, "_sync_last_local", text))
        if not self._sync_owner_sig:
            self._sync_owner_sig = cb.connect("owner-change", lambda *_: self._sync_check_local())
        if not getattr(self, "_sync_map_sig", None):     # back on the Desktop page: check again
            self._sync_map_sig = self.connect("map", lambda *_: self._sync_check_local())
        top = self.get_toplevel()
        if isinstance(top, Gtk.Window) and not self._sync_focus_sig:
            # Wayland only tells a client about clipboard changes while it has focus, so
            # also re-check whenever the window gets focus back.
            self._sync_focus_sig = (top, top.connect("focus-in-event",
                                                     lambda *_: (self._sync_check_local(), False)[1]))
        self._sync_timer = GLib.timeout_add(self._SYNC_POLL_MS, self._sync_poll)

    def _sync_stop(self):
        if self._sync_timer:
            GLib.source_remove(self._sync_timer)
            self._sync_timer = None
        if self._sync_owner_sig:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).disconnect(self._sync_owner_sig)
            self._sync_owner_sig = None
        if getattr(self, "_sync_map_sig", None):
            self.disconnect(self._sync_map_sig)
            self._sync_map_sig = None
        if self._sync_focus_sig:
            top, sig = self._sync_focus_sig
            try:
                top.disconnect(sig)
            except Exception:
                pass
            self._sync_focus_sig = None

    def _flash_status(self, text, secs=3.0):
        self._set_status(text)
        self._status_hold = time.monotonic() + secs

    def _sync_poll(self):
        if self._closing or not self._connected or not self.clip_sync.get_active():
            self._sync_timer = None
            return False
        self.app.ctrl.send_node_msg(self.node["_id"], "getclip", tag=3)
        return True

    _SYNC_MAX = 256 * 1024                            # chars; bigger clipboards are not synced

    def _sync_active(self):
        """Sync only while the user is looking at this remote screen: Desktop page shown and the
        app window active. A device cannot rewrite the local clipboard, and local copies are not
        sent, while the session sits in the background."""
        top = self.get_toplevel()
        return self.get_mapped() and isinstance(top, Gtk.Window) and top.is_active()

    def _sync_on_remote(self, data):
        if not isinstance(data, str) or not self._sync_timer or len(data) > self._SYNC_MAX:
            return
        if not self._sync_baseline and not self._sync_active():
            return                                    # not remembered: applied when the user is back
        if self._sync_baseline:
            self._sync_baseline = False
            self._sync_last_remote = data
            return
        if data == self._sync_last_remote:
            return
        self._sync_last_remote = data
        if data != self._sync_last_local:
            self._sync_last_local = data              # so owner-change doesn't echo it back
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(data, -1)
            self._flash_status(f"Clipboard ← remote ({len(data)} chars)")

    def _sync_check_local(self):
        if not self._sync_timer:
            return

        def got(_c, text):
            if not text or not self._sync_timer or text == self._sync_last_local or len(text) > self._SYNC_MAX:
                return
            if not self._sync_active():
                return                                # re-checked on focus-in / when the page is shown
            self._sync_last_local = text
            if text != self._sync_last_remote and self.caps.desktop_input:
                self._sync_last_remote = text         # so the next poll doesn't echo it back
                self.app.ctrl.send_node_msg(self.node["_id"], "setclip", data=text)
                self._flash_status(f"Clipboard → remote ({len(text)} chars)")
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_text(got)

    # ---- clipboard: native, over OUR control connection ------------------------
    # getclip/setclip are plain control-channel messages; the agent's reply is routed
    # back to the session that asked (with nodeid set), so we don't need the web page,
    # its document.hasFocus() gate or a navigator.clipboard shim at all. Note both are
    # dropped SILENTLY by the server when domain ClipboardGet/ClipboardSet is false, and
    # the agent only answers getclip when the remote clipboard has text, hence timeouts.
    _CLIP_TIMEOUT_MS = 6000

    # Fallback read via the agent console (admin "eval"). The agent's own getclip
    # swallows every read error (no reply at all), which is what happens on a Linux
    # agent running as a root service. Here the same dispatchRead() runs, but its result
    # OR its error is parked on the agent and fetched by a second eval. eval replies go
    # only to OUR session (console output without a sessionid would be broadcast to
    # every admin's console, so the clipboard text is never printed that way).
    # Agent-side read, run via console eval (no double quotes / backslashes allowed: it
    # travels inside  eval "<js>" ). Mirrors the agent's own xclip read, but fixes the bug
    # seen on the user's Kali target: the agent's display lookup (monitor-info getXInfo)
    # returns an EMPTY display, so xclip fails with "Can't open display:". If that happens
    # we take DISPLAY/XAUTHORITY from a process of the desktop user (/proc/<pid>/environ,
    # parsed byte-wise: the agent's Buffer.toString() stops at the first NUL), then run
    # xclip as that user. Without xclip it falls back to the agent's dispatchRead().
    _CLIP_EVAL_START = 'eval "(function(){var A=require(\'MeshAgent\');A.__mcdc=null;var d={};try{var fs=require(\'fs\');var NL=String.fromCharCode(10);var uid=require(\'user-sessions\').consoleUid();d.uid=uid;var xi={};try{xi=require(\'monitor-info\').getXInfo(uid)||{};}catch(e){d.xierr=\'\'+e;}var disp=xi.display,auth=xi.xauthority;d.agent=[disp||\'\',auth||\'\'];if(!disp){var ps=fs.readdirSync(\'/proc\');for(var i=0;i<ps.length&&!disp;i++){var p=ps[i];if(!(parseInt(p)>0))continue;try{var ls=fs.readFileSync(\'/proc/\'+p+\'/status\').toString().split(NL);var u=-1;for(var j=0;j<ls.length;j++){if(ls[j].indexOf(\'Uid:\')==0){u=parseInt(ls[j].substring(4).trim());break;}}if(u!=uid)continue;var b=fs.readFileSync(\'/proc/\'+p+\'/environ\');var e2={},st=0;for(var k=0;k<=b.length;k++){if(k==b.length||b[k]==0){if(k>st){var kv=b.slice(st,k).toString();var q=kv.indexOf(\'=\');if(q>0){e2[kv.substring(0,q)]=kv.substring(q+1);}}st=k+1;}}if(e2.DISPLAY){disp=e2.DISPLAY;auth=e2.XAUTHORITY;d.from=\'pid \'+p;}}catch(x){}}}d.used=[disp||\'\',auth||\'\'];var xc=require(\'clipboard\').xclip;d.xclip=xc||\'\';if(!disp){A.__mcdc={err:\'No X display found for the desktop user (uid \'+uid+\')\',diag:d};return \'MCDCLIP0:nodisp\';}if(!xc){require(\'clipboard\').dispatchRead().then(function(s){A.__mcdc={ok:(s==null?\'\':\'\'+s)};},function(e){A.__mcdc={err:\'\'+e,diag:d};});return \'MCDCLIP0:native\';}var env={DISPLAY:disp};if(auth){env.XAUTHORITY=auth;}var c=require(\'child_process\').execFile(xc,[\'xclip\',\'-selection\',\'clipboard\',\'-o\'],{uid:uid,env:env});A.__mcdchild=c;c.stdout.s=\'\';c.stderr.s=\'\';c.stdout.on(\'data\',function(b){this.s+=b.toString();});c.stderr.on(\'data\',function(b){this.s+=b.toString();});c.on(\'exit\',function(){var o=this.stdout.s,er=this.stderr.s.trim();A.__mcdc=(o.length||!er)?{ok:o}:{err:er,diag:d};A.__mcdchild=null;});}catch(e){A.__mcdc={err:\'\'+e,diag:d};}return \'MCDCLIP0:started\';})()"'
    _CLIP_EVAL_FETCH = ('eval "(function(){var A=require(\'MeshAgent\');var r=A.__mcdc;'
                        'if(r){A.__mcdc=null;}return \'MCDCLIP1:\'+JSON.stringify(r);})()"')

    # The web page must NOT touch the clipboard: if the server enables auto-clipboard,
    # the viewer polls readText() every second and would push stale text to the remote.
    _CLIP_SHIM = ("(function(){try{Object.defineProperty(navigator,'clipboard',{configurable:false,writable:false,value:{"
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
        # getclip and the eval read run in parallel; whichever answers first wins.
        self._clip_eval_start(self._clip_read_gen)

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
            err = str(r.get("err") or "unknown error")
            d = r.get("diag") or {}
            used = (d.get("used") or ["", ""])[0]
            if "target STRING not available" in err or "target UTF8_STRING not available" in err:
                self._note("The remote clipboard is empty (or holds no text). On the remote computer, "
                           "copy with Ctrl+C (Ctrl+Shift+C in a terminal), just selecting text is not enough.")
                return
            self._note(f"The remote agent could not read its clipboard: {err}  "
                       f"[user uid {d.get('uid')}, display {used or 'none found'}"
                       f"{' via ' + d['from'] if d.get('from') else ''}]")

    def _on_clip_msg(self, msg):
        if self._closing or msg.get("nodeid") != self.node["_id"]:
            return
        t = msg.get("type")
        if t == "getclip" and msg.get("tag") == 3:
            self._sync_on_remote(msg.get("data"))
        elif t == "getclip" and msg.get("tag") == 2:
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
    def _on_load(self):
        if self._closing:
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
            origin = json.dumps(server_origin(self.app.ctrl.server.url))
            self._js(
                # fill the password only into the configured server's own page (https origin)
                "(function(){if(location.origin!==" + origin + ")return 'foreign';"
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
            self.web.load_uri(self.desk_url)
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
        if self._connected and time.monotonic() >= self._status_hold:
            self._set_status(text or "")
        # Only a session WE started counts: a stale "Connected" from the page being left
        # behind during a reconnect is ignored because the phase isn't "connecting".
        if now_connected and self._phase == "connecting":
            self._set_phase("connected")
            self._set_controls_enabled(True)
            self._js(self._KEYS_JS)
            self._js("desktop.m.__mcdWin=%d;" % (1 if ui.is_windows(self.node) else 0))
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
