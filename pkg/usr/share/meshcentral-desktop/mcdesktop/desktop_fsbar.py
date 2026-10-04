# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Auto-hiding toolbar of the remote desktop in fullscreen (like the RDP connection bar).

In fullscreen the desktop panel's own toolbar (connect, Ctrl+Alt+Del, clipboard, all the desktop tools) moves
into a bar on one edge of the screen, in its compact form (icons only, a status dot), with the image settings
and the bar's position (top, bottom, left, right; remembered) in a popover, a pin and Exit fullscreen; it
moves back when fullscreen ends, so there is one set of buttons. The bar is shown for a few seconds when
fullscreen starts, then hides; a thin handle on that edge brings it back on hover, and it hides again shortly
after the pointer leaves it (unless pinned or a menu is open). A border, an accent line on the inner side and
a shadow keep it apart from the remote computer's own panels.

Linux: the bar lives in the panel's Gtk.Overlay above the web view (WebKitGTK is a GTK widget).
Windows: the remote screen is a native Edge WebView2 window that GTK cannot draw over, so the bar and the
handle are small always-on-top popup windows placed on the edge of the monitor.
"""
from gi.repository import Gdk, GLib, Gtk

from .osdep import IS_WINDOWS

POSITIONS = [("top", "pan-up-symbolic", "Top"), ("bottom", "pan-down-symbolic", "Bottom"),
             ("left", "pan-start-symbolic", "Left"), ("right", "pan-end-symbolic", "Right")]
CSS = b"""
.mcd-fs-bar { background-color: rgba(30, 33, 38, 0.96); padding: 4px 6px;
              border: 1px solid rgba(255, 255, 255, 0.22);
              box-shadow: 0 3px 14px rgba(0, 0, 0, 0.55); }
.mcd-fs-bar.top { border-top-width: 0; border-radius: 0 0 10px 10px; border-bottom: 2px solid #4c8bf5; }
.mcd-fs-bar.bottom { border-bottom-width: 0; border-radius: 10px 10px 0 0; border-top: 2px solid #4c8bf5; }
.mcd-fs-bar.left { border-left-width: 0; border-radius: 0 10px 10px 0; border-right: 2px solid #4c8bf5; }
.mcd-fs-bar.right { border-right-width: 0; border-radius: 10px 0 0 10px; border-left: 2px solid #4c8bf5; }
.mcd-fs-bar.win-popup { border-radius: 0; border-width: 0; }
.mcd-fs-bar.win-popup.top { border-bottom: 2px solid #4c8bf5; }
.mcd-fs-bar.win-popup.bottom { border-top: 2px solid #4c8bf5; }
.mcd-fs-bar.win-popup.left { border-right: 2px solid #4c8bf5; }
.mcd-fs-bar.win-popup.right { border-left: 2px solid #4c8bf5; }
.mcd-fs-panel.win-popup { border-radius: 0; }
.mcd-fs-bar label { color: #eceef1; }
.mcd-fs-bar .mcd-fs-title { font-weight: bold; margin: 0 6px 0 4px; }
.mcd-fs-bar .mcd-fs-dot { font-size: 14pt; margin: 0 4px; }
.mcd-fs-bar .mcd-fs-dot.on { color: #2ecc71; }
.mcd-fs-bar .mcd-fs-dot.off { color: #8a8f98; }
.mcd-fs-bar.left button, .mcd-fs-bar.right button { min-width: 30px; padding: 3px; }
.mcd-fs-bar button { background-color: rgba(255, 255, 255, 0.07); background-image: none; color: #eceef1;
                     border: 1px solid rgba(255, 255, 255, 0.10); box-shadow: none; text-shadow: none;
                     min-width: 26px; min-height: 26px; padding: 2px 4px; }
.mcd-fs-bar button:hover { background-color: rgba(255, 255, 255, 0.15); }
.mcd-fs-bar button:active, .mcd-fs-bar button:checked { background-color: rgba(255, 255, 255, 0.24); }
.mcd-fs-bar button:disabled, .mcd-fs-bar button:disabled label { color: rgba(236, 238, 241, 0.35); }
.mcd-fs-bar button.suggested-action { background-color: #2f6fd6; border-color: #2f6fd6; }
.mcd-fs-bar button image { color: #eceef1; }
.mcd-fs-panel { background-color: rgba(30, 33, 38, 0.98); border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 8px; }
.mcd-fs-panel label { color: #eceef1; }
.mcd-fs-handle { background-color: rgba(76, 139, 245, 0.85); border-radius: 3px; }
.mcd-fs-handle-area { background-color: transparent; }
window.mcd-fs-handle-win { background-color: #4c8bf5; }
.mcd-fs-handle-area.win-popup, .mcd-fs-handle-area.win-popup .mcd-fs-handle { background-color: #4c8bf5;
                                                                           border-radius: 0; }
"""
_css_done = False
HIDE_MS = 900
SHOW_FIRST_MS = 3000
HANDLE_LONG, HANDLE_THICK = 160, 5
EDGE_PX = 3              # the pointer within this distance of the bar's edge, anywhere along it, shows the bar
EDGE_POLL_MS = 60
EDGE_DWELL = 2           # polls in a row at the edge (about 0.1 s: not when the pointer only passes by)


def _install_css():
    global _css_done
    if not _css_done:
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 20)
        _css_done = True


def _topmost(win):
    """Windows: GTK popups are not above other windows by themselves (an app opened on the same screen would
    cover the bar): HWND_TOPMOST, without moving or activating it."""
    try:
        import ctypes
        from .osdep import window_handle
        hwnd = window_handle(win)
        if hwnd:
            ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                              0x0001 | 0x0002 | 0x0010)    # NOSIZE | NOMOVE | NOACTIVATE
            # rounded corners, border and shadow drawn by Windows (11 / Server 2025): GTK paints a popup
            # window's corners solid, so the style sheet's border-radius cannot show there
            pref = ctypes.c_int(2)                                            # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(pref),
                                                       ctypes.sizeof(pref))   # DWMWA_WINDOW_CORNER_PREFERENCE
    except Exception:
        pass


class FullscreenBar:
    def __init__(self, panel, overlay, toolbar, settings_box, title, position="top"):
        """toolbar / settings_box: the panel's widgets that move into the bar while fullscreen lasts."""
        _install_css()
        self.panel, self.overlay, self.toolbar, self.settings_box = panel, overlay, toolbar, settings_box
        self.position = position if position in [p for p, _i, _l in POSITIONS] else "top"
        self.active = self.shown = self.pinned = False
        self._timer = None
        self._edge_timer = None
        self._edge_hits = 0
        self._edge_armed = True              # the edge triggers again only after the pointer has left it
        self._homes = {}                                    # widget -> (parent, position) to put it back

        self.content = Gtk.Box(spacing=4)
        self.content.get_style_context().add_class("mcd-fs-bar")
        if IS_WINDOWS:
            self.content.get_style_context().add_class("win-popup")
        self.title = Gtk.Label(label=title, max_width_chars=16, ellipsize=3)
        self.title.get_style_context().add_class("mcd-fs-title")
        self.content.pack_start(self.title, False, False, 0)
        self.dot = Gtk.Label(label="●")
        self.dot.get_style_context().add_class("mcd-fs-dot")
        self.content.pack_start(self.dot, False, False, 0)
        self.slot = Gtk.Box()
        self.content.pack_start(self.slot, True, True, 0)
        tip = "Image quality, display, clipboard, hotkeys and toolbar position"
        # Windows: the bar is a small popup window and GTK 3 draws a popover INSIDE its window there (clipped to
        # the 42 px bar, so nothing appears): the settings get their own popup window next to the bar instead
        self.settings = Gtk.ToggleButton(tooltip_text=tip) if IS_WINDOWS else Gtk.MenuButton(tooltip_text=tip)
        self.settings.set_image(Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON))
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=8)
        prow = Gtk.Box(spacing=8)
        prow.pack_start(Gtk.Label(label="Toolbar position:"), False, False, 0)
        group = Gtk.Box()
        group.get_style_context().add_class("linked")
        self.pos_btns = {}
        first = None
        for pid, icon, label in POSITIONS:
            b = Gtk.RadioButton.new_from_widget(first)
            first = first or b
            b.set_mode(False)
            b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            b.set_tooltip_text(label)
            b.set_active(pid == self.position)
            b.connect("toggled", lambda w, p=pid: w.get_active() and self.set_position(p))
            group.add(b)
            self.pos_btns[pid] = b
        prow.pack_start(group, False, False, 0)
        pbox.pack_start(prow, False, False, 0)
        self.pop_box = Gtk.Box()
        pbox.pack_start(self.pop_box, False, False, 0)
        pbox.show_all()
        if IS_WINDOWS:
            self.settings_win = Gtk.Window(type=Gtk.WindowType.POPUP)
            panel_box = Gtk.EventBox()
            panel_box.get_style_context().add_class("mcd-fs-panel")
            panel_box.get_style_context().add_class("win-popup")
            panel_box.add(pbox)
            self.settings_win.add(panel_box)
            self.settings_win.set_keep_above(True)
            panel_box.connect("enter-notify-event", lambda *_: self._cancel_hide())
            self.settings.connect("toggled", self._on_settings_toggled)
        else:
            pop = Gtk.Popover()
            pop.add(pbox)
            self.settings.set_popover(pop)
            pop.connect("closed", lambda *_: self._schedule_hide())
        self.content.pack_start(self.settings, False, False, 0)
        self.pin = Gtk.ToggleButton(tooltip_text="Keep the toolbar shown")
        self.pin.set_image(Gtk.Image.new_from_icon_name("view-pin-symbolic", Gtk.IconSize.BUTTON))
        self.pin.connect("toggled", self._on_pin)
        self.content.pack_start(self.pin, False, False, 0)
        self.exit_btn = Gtk.Button(tooltip_text="Exit fullscreen (Ctrl+Alt+F)",
                                   image=Gtk.Image.new_from_icon_name("view-restore-symbolic", Gtk.IconSize.BUTTON))
        self.exit_btn.get_style_context().add_class("suggested-action")
        self.exit_btn.connect("clicked", lambda *_: GLib.idle_add(lambda: (panel.exit_fullscreen(), False)[1]))
        self.content.pack_start(self.exit_btn, False, False, 0)

        self.frame = Gtk.EventBox()
        self.frame.add(self.content)
        self.frame.connect("enter-notify-event", lambda *_: self._cancel_hide())
        self.frame.connect("leave-notify-event", self._on_leave)

        self.handle_line = Gtk.Box()
        self.handle_line.get_style_context().add_class("mcd-fs-handle")
        self.handle = Gtk.EventBox()
        self.handle.get_style_context().add_class("mcd-fs-handle-area")
        self.handle.add(self.handle_line)
        self.handle.set_tooltip_text("Toolbar")
        if IS_WINDOWS:
            self.handle.get_style_context().add_class("win-popup")
        self.handle.connect("enter-notify-event", lambda *_: self.show(hold=True))
        self.handle.connect("button-press-event", lambda *_: self.show(hold=True))

        if IS_WINDOWS:
            self.bar_win = Gtk.Window(type=Gtk.WindowType.POPUP)
            self.bar_win.add(self.frame)
            self.handle_win = Gtk.Window(type=Gtk.WindowType.POPUP)
            self.handle_win.get_style_context().add_class("mcd-fs-handle-win")
            self.handle_win.add(self.handle)
            for w in (self.bar_win, self.handle_win):
                w.set_keep_above(True)
        else:
            self.rev = Gtk.Revealer(transition_duration=160)
            self.rev.add(self.frame)
            self.rev.set_no_show_all(True)
            self.handle.set_no_show_all(True)
            overlay.add_overlay(self.handle)
            overlay.add_overlay(self.rev)
        self._layout()

    # ---- position -------------------------------------------------------------------------------------
    @property
    def vertical(self):
        return self.position in ("left", "right")

    def _layout(self):
        """Orientation, side styles, handle shape and (Linux) where the bar slides in from."""
        vertical = self.vertical
        self.content.set_orientation(Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL)
        self.slot.set_orientation(self.content.get_orientation())
        style = self.content.get_style_context()
        for p, _i, _l in POSITIONS:
            style.remove_class(p)
        style.add_class(self.position)
        self.title.set_visible(not vertical)
        self.title.set_no_show_all(vertical)
        for w in (self.settings, self.pin, self.exit_btn, self.dot):
            w.set_halign(Gtk.Align.CENTER if vertical else Gtk.Align.FILL)
        long_, thick = HANDLE_LONG, HANDLE_THICK
        self.handle_line.set_size_request(thick if vertical else long_, long_ if vertical else thick)
        if IS_WINDOWS:
            # a popup window cannot be see-through here: the transparent hover area around the line showed as
            # a white box, so the window is exactly the line (the edge polling still brings the bar back)
            self.handle.set_size_request(thick if vertical else long_, long_ if vertical else thick)
        else:
            self.handle.set_size_request(14 if vertical else 260, 260 if vertical else 14)
        align = {"top": (Gtk.Align.CENTER, Gtk.Align.START), "bottom": (Gtk.Align.CENTER, Gtk.Align.END),
                 "left": (Gtk.Align.START, Gtk.Align.CENTER), "right": (Gtk.Align.END, Gtk.Align.CENTER)}
        h, v = align[self.position]
        for w in (self.handle, self.handle_line):
            w.set_halign(h)
            w.set_valign(v)
        if not IS_WINDOWS:
            self.rev.set_halign(h)
            self.rev.set_valign(v)
            self.rev.set_transition_type({
                "top": Gtk.RevealerTransitionType.SLIDE_DOWN, "bottom": Gtk.RevealerTransitionType.SLIDE_UP,
                "left": Gtk.RevealerTransitionType.SLIDE_RIGHT,
                "right": Gtk.RevealerTransitionType.SLIDE_LEFT}[self.position])

    def set_position(self, position):
        if position == self.position:
            return
        self.position = position
        self.panel.save_bar_position(position)
        self.panel.set_compact(True, self.vertical)
        self._layout()
        if IS_WINDOWS:
            self.bar_win.resize(1, 1)                    # shrink to the new orientation's natural size
            self.handle_win.resize(1, 1)
        if self.active:
            self.show(hold=self.settings.get_active())
            if IS_WINDOWS and self.settings.get_active():
                GLib.idle_add(lambda: (self._on_settings_toggled(self.settings), False)[1])   # follow the bar

    def _place(self, win):
        """Windows: a popup window centred on the bar's edge of the monitor."""
        g = self._monitor_geometry()
        if not g:
            return
        # the natural size of the new layout: right after a change of orientation get_size() is still the old one
        nat = win.get_child().get_preferred_size()[1] if win.get_child() else None
        w, h = (nat.width, nat.height) if nat else win.get_size()
        win.resize(w, h)
        x = {"left": g.x, "right": g.x + g.width - w}.get(self.position, g.x + max(0, (g.width - w) // 2))
        y = {"top": g.y, "bottom": g.y + g.height - h}.get(self.position, g.y + max(0, (g.height - h) // 2))
        win.move(x, y)
        _topmost(win)

    # ---- status ---------------------------------------------------------------------------------------
    def set_status(self, text, connected):
        style = self.dot.get_style_context()
        style.remove_class("on" if not connected else "off")
        style.add_class("on" if connected else "off")
        self.dot.set_tooltip_text(text or ("Connected" if connected else "Not connected"))

    # ---- moving the panel's toolbar in and out -------------------------------------------------------
    def _move(self, widget, new_parent):
        old = widget.get_parent()
        if old is not None:
            if widget not in self._homes:
                pos = old.get_children().index(widget) if isinstance(old, Gtk.Box) else 0
                self._homes[widget] = (old, pos)
            old.remove(widget)
        new_parent.pack_start(widget, True, True, 0)
        widget.show()

    def _move_home(self, widget):
        home = self._homes.pop(widget, None)
        parent = widget.get_parent()
        if parent is not None:
            parent.remove(widget)
        if home:
            old, pos = home
            old.pack_start(widget, False, False, 0)
            old.reorder_child(widget, pos)
        widget.show()

    # ---- fullscreen on / off ---------------------------------------------------------------------------
    def enter(self, title=None):
        if self.active:
            return
        self.active = True
        if title:
            self.title.set_text(title)
        self._layout()
        self.content.show_all()                       # before the toolbar moves in: show_all would undo compact
        self.title.set_visible(not self.vertical)
        self.frame.show()
        self.handle_line.show()
        self._move(self.toolbar, self.slot)
        self._move(self.settings_box, self.pop_box)
        self.panel.set_compact(True, self.vertical)
        if not IS_WINDOWS:
            self.rev.show()
        self.show()
        self._schedule_hide(SHOW_FIRST_MS)
        self._edge_timer = GLib.timeout_add(EDGE_POLL_MS, self._poll_edge)

    def leave(self):
        if not self.active:
            return
        self.active = self.shown = False
        self._cancel_hide()
        if self._edge_timer:
            GLib.source_remove(self._edge_timer)
            self._edge_timer = None
        self.pin.set_active(False)
        self.settings.set_active(False)
        if IS_WINDOWS:
            self.bar_win.hide()
            self.handle_win.hide()
            self.settings_win.hide()
        else:
            self.rev.set_reveal_child(False)
            self.rev.hide()
            self.handle.hide()
        self._move_home(self.settings_box)
        self._move_home(self.toolbar)
        self.panel.set_compact(False, False)

    def destroy(self):
        self.leave()
        if IS_WINDOWS:
            self.bar_win.destroy()
            self.handle_win.destroy()
            self.settings_win.destroy()

    # ---- show / hide ----------------------------------------------------------------------------------
    def _monitor_geometry(self):
        top = self.panel.get_toplevel()
        gdkwin = top.get_window() if top else None
        display = Gdk.Display.get_default()
        mon = display.get_monitor_at_window(gdkwin) if gdkwin else display.get_primary_monitor()
        return mon.get_geometry() if mon else None

    def show(self, hold=False):
        if not self.active:
            return False
        self._cancel_hide()
        self.shown = True
        if IS_WINDOWS:
            self.handle_win.hide()
            self.bar_win.show()                       # not show_all: the compact toolbar hides some widgets
            self._place(self.bar_win)
        else:
            self.handle.hide()
            self.rev.set_reveal_child(True)
        if not hold:
            self._schedule_hide()
        return False

    def hide(self):
        self._timer = None
        if not self.active or self.pinned or self.settings.get_active():
            return False
        self.shown = False
        if IS_WINDOWS:
            self.bar_win.hide()
            self.handle.show()
            self.handle_win.show()
            self._place(self.handle_win)
        else:
            self.rev.set_reveal_child(False)
            self.handle.show()                  # no_show_all: show_all() would not show it
        self.panel.focus_remote()               # keys go to the remote screen again
        return False

    def _poll_edge(self):
        """While the bar is hidden: the pointer resting on the bar's edge of the screen, anywhere along it,
        brings the bar back (the handle alone is a small target)."""
        if not self.active:
            self._edge_timer = None
            return False
        g = self._monitor_geometry()
        top = self.panel.get_toplevel()
        gdkwin = top.get_window() if top else None
        seat = Gdk.Display.get_default().get_default_seat()
        if not g or gdkwin is None or seat is None or seat.get_pointer() is None:
            return True
        _w, x, y, _m = gdkwin.get_device_position(seat.get_pointer())     # window = whole monitor in fullscreen
        ox, oy = gdkwin.get_origin()[1:]
        x, y = x + ox - g.x, y + oy - g.y                                   # monitor coordinates
        inside = 0 <= x < g.width and 0 <= y < g.height
        at_edge = inside and {"top": y <= EDGE_PX, "bottom": y >= g.height - 1 - EDGE_PX,
                              "left": x <= EDGE_PX, "right": x >= g.width - 1 - EDGE_PX}[self.position]
        if not at_edge:
            self._edge_armed = True               # also while the bar is shown: leaving the edge re-arms it
        if self.shown or self.pinned:
            self._edge_hits = 0
            return True
        self._edge_hits = self._edge_hits + 1 if at_edge and self._edge_armed else 0
        if self._edge_hits >= EDGE_DWELL:
            self._edge_hits = 0
            self._edge_armed = False
            self.show(hold=True)
            self._schedule_hide(2500)                 # hides again if the pointer never reaches the bar
        return True

    def _schedule_hide(self, ms=HIDE_MS):
        self._cancel_hide()
        if self.active and not self.pinned:
            self._timer = GLib.timeout_add(ms, self.hide)

    def _cancel_hide(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        return False

    def _on_leave(self, _w, ev):
        if ev.detail != Gdk.NotifyType.INFERIOR:            # not just moving onto a button inside the bar
            self._schedule_hide()
        return False

    def _on_settings_toggled(self, btn):
        """Windows: show / hide the settings panel next to the bar (on its inner side)."""
        if not btn.get_active():
            self.settings_win.hide()
            self._schedule_hide()
            return
        self._cancel_hide()
        self.settings_win.show_all()
        nat = self.settings_win.get_child().get_preferred_size()[1]
        self.settings_win.resize(nat.width, nat.height)
        g = self._monitor_geometry()
        (bx, by), (bw, bh) = self.bar_win.get_position(), self.bar_win.get_size()
        w, h = nat.width, nat.height
        x, y = {"top": (bx + bw - w, by + bh + 4), "bottom": (bx + bw - w, by - h - 4),
                "left": (bx + bw + 4, by + bh - h), "right": (bx - w - 4, by + bh - h)}[self.position]
        if g:
            x = min(max(g.x, x), g.x + g.width - w)
            y = min(max(g.y, y), g.y + g.height - h)
        self.settings_win.move(x, y)
        _topmost(self.settings_win)

    def _on_pin(self, btn):
        self.pinned = btn.get_active()
        if self.pinned:
            self._cancel_hide()
        else:
            self._schedule_hide()
