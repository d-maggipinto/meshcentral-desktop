# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Auto-hiding toolbar of the remote desktop in fullscreen (like the RDP connection bar).

In fullscreen the desktop panel's own toolbar (connect, Ctrl+Alt+Del, clipboard, all the desktop tools) moves
into a bar at the top of the screen, with the image settings in a popover, a pin and an Exit fullscreen button;
it moves back when fullscreen ends, so there is one set of buttons. The bar is shown for a few seconds when
fullscreen starts, then hides; a thin handle at the top edge brings it back on hover, and it hides again
shortly after the pointer leaves it (unless pinned or a menu is open).

Linux: the bar lives in the panel's Gtk.Overlay above the web view (WebKitGTK is a GTK widget).
Windows: the remote screen is a native Edge WebView2 window that GTK cannot draw over, so the bar and the
handle are small always-on-top popup windows placed at the top of the monitor.
"""
from gi.repository import Gdk, GLib, Gtk

from .osdep import IS_WINDOWS

CSS = b"""
.mcd-fs-bar { background-color: rgba(28, 30, 34, 0.94); border-radius: 0 0 10px 10px; padding: 4px 8px;
              box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45); }
.mcd-fs-bar label { color: #eceef1; }
.mcd-fs-bar button { background-color: rgba(255, 255, 255, 0.07); background-image: none; color: #eceef1;
                     border: 1px solid rgba(255, 255, 255, 0.10); box-shadow: none; text-shadow: none; }
.mcd-fs-bar button:hover { background-color: rgba(255, 255, 255, 0.15); }
.mcd-fs-bar button:active, .mcd-fs-bar button:checked { background-color: rgba(255, 255, 255, 0.24); }
.mcd-fs-bar button:disabled, .mcd-fs-bar button:disabled label { color: rgba(236, 238, 241, 0.35); }
.mcd-fs-bar button.suggested-action { background-color: #2f6fd6; border-color: #2f6fd6; }
.mcd-fs-bar button image { color: #eceef1; }
.mcd-fs-bar .mcd-fs-title { font-weight: bold; margin: 0 8px 0 4px; }
.mcd-fs-handle { background-color: rgba(255, 255, 255, 0.40); border-radius: 0 0 4px 4px;
                 min-width: 140px; min-height: 5px; }
.mcd-fs-handle-area { background-color: transparent; }
"""
_css_done = False
HIDE_MS = 900
SHOW_FIRST_MS = 3000


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
    except Exception:
        pass


def _install_css():
    global _css_done
    if not _css_done:
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 20)
        _css_done = True


class FullscreenBar:
    def __init__(self, panel, overlay, toolbar, settings_box, title):
        """toolbar / settings_box: the panel's widgets that move into the bar while fullscreen lasts."""
        _install_css()
        self.panel, self.toolbar, self.settings_box = panel, toolbar, settings_box
        self.active = self.shown = self.pinned = False
        self._timer = None
        self._homes = {}                                    # widget -> (parent, position) to put it back

        self.content = Gtk.Box(spacing=6)
        self.content.get_style_context().add_class("mcd-fs-bar")
        self.title = Gtk.Label(label=title, max_width_chars=18, ellipsize=3)
        self.title.get_style_context().add_class("mcd-fs-title")
        self.content.pack_start(self.title, False, False, 0)
        self.slot = Gtk.Box()
        self.content.pack_start(self.slot, True, True, 0)
        self.settings = Gtk.MenuButton(tooltip_text="Image quality, display, clipboard and hotkey settings")
        self.settings.set_image(Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON))
        pop = Gtk.Popover()
        self.pop_box = Gtk.Box(margin=8)
        pop.add(self.pop_box)
        self.settings.set_popover(pop)
        pop.connect("closed", lambda *_: self._schedule_hide())
        self.content.pack_start(self.settings, False, False, 0)
        self.pin = Gtk.ToggleButton(tooltip_text="Keep the toolbar shown")
        self.pin.set_image(Gtk.Image.new_from_icon_name("view-pin-symbolic", Gtk.IconSize.BUTTON))
        self.pin.connect("toggled", self._on_pin)
        self.content.pack_start(self.pin, False, False, 0)
        exit_btn = Gtk.Button(label="Exit fullscreen", tooltip_text="Exit fullscreen (Ctrl+Alt+F)",
                              image=Gtk.Image.new_from_icon_name("view-restore-symbolic", Gtk.IconSize.BUTTON),
                              always_show_image=True)
        exit_btn.get_style_context().add_class("suggested-action")
        self.exit_btn = exit_btn
        exit_btn.connect("clicked", lambda *_: GLib.idle_add(lambda: (panel.exit_fullscreen(), False)[1]))
        self.content.pack_start(exit_btn, False, False, 0)

        self.frame = Gtk.EventBox(above_child=False)
        self.frame.add(self.content)
        self.frame.connect("enter-notify-event", lambda *_: self._cancel_hide())
        self.frame.connect("leave-notify-event", self._on_leave)

        handle = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        handle.get_style_context().add_class("mcd-fs-handle")
        self.handle = Gtk.EventBox(halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.handle.get_style_context().add_class("mcd-fs-handle-area")
        self.handle.set_size_request(260, 12)              # easier to hit than the 5 px line it shows
        self.handle.add(handle)
        self.handle.set_tooltip_text("Toolbar")
        self.handle.connect("enter-notify-event", lambda *_: self.show(hold=True))
        self.handle.connect("button-press-event", lambda *_: self.show(hold=True))

        if IS_WINDOWS:
            self.bar_win = Gtk.Window(type=Gtk.WindowType.POPUP)
            self.bar_win.add(self.frame)
            self.handle_win = Gtk.Window(type=Gtk.WindowType.POPUP)
            self.handle_win.add(self.handle)
            for w in (self.bar_win, self.handle_win):
                w.set_keep_above(True)
        else:
            self.rev = Gtk.Revealer(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, transition_duration=160,
                                    transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
            self.rev.add(self.frame)
            self.rev.set_no_show_all(True)
            self.handle.set_no_show_all(True)
            overlay.add_overlay(self.handle)
            overlay.add_overlay(self.rev)

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
        self._move(self.toolbar, self.slot)
        self._move(self.settings_box, self.pop_box)
        g = self._monitor_geometry()
        narrow = g is not None and g.width < 1500             # e.g. 1280 x 800: no room for the long labels
        self.exit_btn.set_label("" if narrow else "Exit fullscreen")
        self.pop_box.show_all()
        self.content.show_all()
        self.frame.show()
        if IS_WINDOWS:
            self.frame.show_all()
            self.handle.show_all()
        else:
            self.handle.get_child().show()
            self.rev.show()
        self.show()
        self._schedule_hide(SHOW_FIRST_MS)

    def leave(self):
        if not self.active:
            return
        self.active = self.shown = False
        self._cancel_hide()
        self.pin.set_active(False)
        self.settings.set_active(False)
        if IS_WINDOWS:
            self.bar_win.hide()
            self.handle_win.hide()
        else:
            self.rev.set_reveal_child(False)
            self.rev.hide()
            self.handle.hide()
        self._move_home(self.settings_box)
        self._move_home(self.toolbar)

    def destroy(self):
        self.leave()
        if IS_WINDOWS:
            self.bar_win.destroy()
            self.handle_win.destroy()

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
            self.bar_win.show_all()
            g = self._monitor_geometry()
            if g:
                w, _h = self.bar_win.get_size()
                self.bar_win.move(g.x + max(0, (g.width - w) // 2), g.y)
            _topmost(self.bar_win)
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
            g = self._monitor_geometry()
            self.handle_win.show_all()
            if g:
                w, _h = self.handle_win.get_size()
                self.handle_win.move(g.x + max(0, (g.width - w) // 2), g.y)
            _topmost(self.handle_win)
        else:
            self.rev.set_reveal_child(False)
            self.handle.get_child().show()
            self.handle.show()              # no_show_all: show_all() would not show it
        self.panel.focus_remote()                           # keys go to the remote screen again
        return False

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

    def _on_pin(self, btn):
        self.pinned = btn.get_active()
        if self.pinned:
            self._cancel_hide()
        else:
            self._schedule_hide()
