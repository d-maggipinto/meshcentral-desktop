# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows 11 look for the GTK interface (Windows only).

GTK's own theme (Adwaita) looks like a Linux desktop. On Windows this module lays a style sheet over it
that follows the Windows 11 design: Segoe UI, the system light / dark mode and accent colour (read from
the registry and re-read every few seconds, so a change in Settings applies at once), rounded controls,
Windows caption buttons, the content area as a raised layer next to the navigation rail. Windows that
keep a native title bar (dialogs) get the matching dark / light caption through DWM.

For development the look can be previewed on Linux: MCD_WIN11_STYLE=dark (or light) before starting.
"""
import ctypes
import os

from gi.repository import Gdk, GLib, GObject, Gtk

from . import osdep

_PREVIEW = os.environ.get("MCD_WIN11_STYLE", "").lower()
_POLL_MS = 2000
DEFAULT_ACCENT = "#0078d4"                     # Windows 11 default blue


def enabled():
    return osdep.IS_WINDOWS or _PREVIEW in ("dark", "light")


# ---- system settings -------------------------------------------------------------------------------
def _reg(path, name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _hex(r, g, b):
    return "#%02x%02x%02x" % (r, g, b)


def _mix(c, other, t):
    """c mixed with other by t (0..1), both '#rrggbb'."""
    a = [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return _hex(*[round(x + (y - x) * t) for x, y in zip(a, b)])


def system_scheme():
    """(dark: bool, accent palette dict) as Windows has them now."""
    if not osdep.IS_WINDOWS:
        return _PREVIEW != "light", _palette(None)
    light = _reg(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme")
    pal = _reg(r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent", "AccentPalette")
    return light == 0, _palette(pal)


def _palette(raw):
    """Windows stores 8 RGBA colours: light 3..1, base, dark 1..3 (+ one unused). Fallback: derived from
    the default blue the way the Settings palette looks."""
    if isinstance(raw, (bytes, bytearray)) and len(raw) >= 28:
        c = [_hex(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, 28, 4)]
        return dict(zip(("light3", "light2", "light1", "base", "dark1", "dark2", "dark3"), c))
    base = DEFAULT_ACCENT
    return {"light3": "#99ebff", "light2": "#4cc2ff", "light1": "#0091f8", "base": base,
            "dark1": "#005fb8", "dark2": "#004c87", "dark3": _mix(base, "#000000", 0.6)}


def _font():
    """Segoe UI Variable (Windows 11) when installed, else Segoe UI; 10 pt = the 14 px body text."""
    try:
        gi_pc = __import__("gi.repository.PangoCairo", fromlist=["PangoCairo"])
        names = {f.get_name() for f in gi_pc.FontMap.get_default().list_families()}
    except Exception:
        names = set()
    for fam in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"):
        if fam in names:
            return fam + " 10"
    return None                                   # keep GTK's default (preview on Linux)


# ---- colours -----------------------------------------------------------------------------------------
def colours(dark, pal):
    if dark:
        c = dict(bg="#202020", layer="#272727", layer_border="rgba(255,255,255,0.055)",
                 fg="#ffffff", fg2="rgba(255,255,255,0.786)", fg3="rgba(255,255,255,0.45)",
                 ctrl="rgba(255,255,255,0.061)", ctrl_hover="rgba(255,255,255,0.084)",
                 ctrl_press="rgba(255,255,255,0.033)", ctrl_border="rgba(255,255,255,0.093)",
                 ctrl_border_b="rgba(255,255,255,0.07)", ctrl_strong="rgba(255,255,255,0.544)",
                 ctrl_alt="rgba(0,0,0,0.1)", input_focus="#1f1f1f", input_line="rgba(255,255,255,0.544)",
                 subtle_hover="rgba(255,255,255,0.061)", subtle_press="rgba(255,255,255,0.042)",
                 sel_row="rgba(255,255,255,0.07)", border="rgba(255,255,255,0.083)",
                 popup="#2c2c2c", popup_border="rgba(255,255,255,0.09)", shadow="rgba(0,0,0,0.45)",
                 slider_outer="#454545", accent=pal["light2"], on_accent="#000000", accent_text=pal["light3"],
                 caption="#202020", caption_text="#ffffff")
    else:
        c = dict(bg="#f3f3f3", layer="#f9f9f9", layer_border="rgba(0,0,0,0.0578)",
                 fg="#1b1b1b", fg2="rgba(0,0,0,0.62)", fg3="rgba(0,0,0,0.42)",
                 ctrl="rgba(255,255,255,0.7)", ctrl_hover="rgba(249,249,249,0.5)",
                 ctrl_press="rgba(249,249,249,0.3)", ctrl_border="rgba(0,0,0,0.0578)",
                 ctrl_border_b="rgba(0,0,0,0.1622)", ctrl_strong="rgba(0,0,0,0.446)",
                 ctrl_alt="rgba(0,0,0,0.024)", input_focus="#ffffff", input_line="rgba(0,0,0,0.446)",
                 subtle_hover="rgba(0,0,0,0.037)", subtle_press="rgba(0,0,0,0.024)",
                 sel_row="rgba(0,0,0,0.055)", border="rgba(0,0,0,0.08)",
                 popup="#f9f9f9", popup_border="rgba(0,0,0,0.1)", shadow="rgba(0,0,0,0.2)",
                 slider_outer="#ffffff", accent=pal["dark1"], on_accent="#ffffff", accent_text=pal["dark2"],
                 caption="#f3f3f3", caption_text="#1b1b1b")
    return c


_CSS = """
@define-color theme_bg_color %(bg)s;
@define-color theme_fg_color %(fg)s;
@define-color theme_base_color %(layer)s;
@define-color theme_text_color %(fg)s;
@define-color theme_selected_bg_color %(accent)s;
@define-color theme_selected_fg_color %(on_accent)s;
@define-color insensitive_fg_color %(fg3)s;
@define-color borders %(border)s;

* { -gtk-icon-shadow: none; text-shadow: none; outline-color: alpha(%(fg)s, 0.6); outline-style: solid;
    outline-width: 1px; -gtk-outline-radius: 4px; }

window, window.background, .background, dialog .dialog-vbox, messagedialog .dialog-vbox {
    background-color: %(bg)s; color: %(fg)s; }
window.csd decoration { border-radius: 8px; }
window.csd { border-radius: 0 0 8px 8px; }
window.csd decoration { box-shadow: 0 8px 24px %(shadow)s, 0 0 0 1px %(layer_border)s; margin: 10px; }
window.csd:backdrop decoration { box-shadow: 0 4px 12px %(shadow)s, 0 0 0 1px %(layer_border)s; }
window.maximized, window.maximized decoration, window.fullscreen, window.fullscreen decoration,
window.tiled decoration { border-radius: 0; }
window.popup decoration, window.popup { border-radius: 0; box-shadow: none; }

/* title bar with Windows caption buttons */
headerbar, .titlebar:not(headerbar) {
    background-color: %(bg)s; background-image: none; border: none; box-shadow: none; color: %(fg)s;
    min-height: 40px; padding: 0 0 0 6px; border-radius: 8px 8px 0 0; }
headerbar:backdrop { background-color: %(bg)s; color: %(fg3)s; }
window.maximized headerbar, window.fullscreen headerbar { border-radius: 0; }
headerbar .title { font-weight: normal; }
headerbar .subtitle { color: %(fg2)s; font-size: 8pt; }
headerbar button.titlebutton {
    min-width: 46px; min-height: 40px; margin: 0; padding: 0; border: none; border-radius: 0;
    background: none; box-shadow: none; color: %(fg)s; }
headerbar button.titlebutton:hover { background-color: %(subtle_hover)s; }
headerbar button.titlebutton:active { background-color: %(subtle_press)s; color: %(fg2)s; }
headerbar button.titlebutton.close:hover { background-color: #c42b1c; color: #ffffff; }
headerbar button.titlebutton.close:active { background-color: #c83c31; color: rgba(255,255,255,0.7); }
window.csd:not(.maximized):not(.fullscreen) headerbar button.titlebutton.close { border-top-right-radius: 8px; }
headerbar separator.titlebutton, headerbar .titlebutton + separator { opacity: 0; }
headerbar button:not(.titlebutton) { margin-top: 4px; margin-bottom: 4px; }
headerbar button.titlebutton:backdrop { color: %(fg3)s; }
headerbar button.titlebutton.close:hover:backdrop { color: #ffffff; }

/* buttons */
button {
    background-color: %(ctrl)s; background-image: none; border: 1px solid %(ctrl_border)s;
    border-bottom-color: %(ctrl_border_b)s; border-radius: 4px; box-shadow: none; color: %(fg)s;
    padding: 4px 11px; min-height: 22px; }
button:hover { background-color: %(ctrl_hover)s; }
button:active { background-color: %(ctrl_press)s; color: %(fg2)s; border-bottom-color: %(ctrl_border)s; }
button:checked { background-color: %(accent)s; color: %(on_accent)s; border-color: alpha(%(accent)s, 0.9); }
button:checked:hover { background-color: alpha(%(accent)s, 0.9); }
button:disabled { background-color: %(ctrl_press)s; color: %(fg3)s; border-color: %(ctrl_border)s; }
button:disabled label, button:disabled image { color: %(fg3)s; }
button.image-button { padding: 4px 7px; }
button.flat, headerbar button:not(.titlebutton), .mcd-rail-btn, notebook > header button {
    background-color: transparent; border-color: transparent; }
button.flat:hover, headerbar button:not(.titlebutton):hover, notebook > header button:hover {
    background-color: %(subtle_hover)s; }
button.flat:active, headerbar button:not(.titlebutton):active { background-color: %(subtle_press)s; }
button.flat:checked, headerbar button:not(.titlebutton):checked { background-color: %(subtle_hover)s; color: %(fg)s; }
button.suggested-action { background-color: %(accent)s; color: %(on_accent)s; border-color: alpha(%(accent)s, 0.9);
    border-bottom-color: alpha(#000000, 0.25); }
button.suggested-action:hover { background-color: alpha(%(accent)s, 0.9); }
button.suggested-action:active { background-color: alpha(%(accent)s, 0.8); color: alpha(%(on_accent)s, 0.7); }
button.suggested-action label, button.suggested-action image { color: %(on_accent)s; }
button.destructive-action { background-color: #c42b1c; color: #ffffff; border-color: #c42b1c; }
button.destructive-action:hover { background-color: #b0281a; }
button.destructive-action label { color: #ffffff; }
.linked > button { border-radius: 0; }
.linked > button:first-child { border-radius: 4px 0 0 4px; }
.linked > button:last-child { border-radius: 0 4px 4px 0; }
.linked > button:only-child { border-radius: 4px; }
button.combo { padding: 4px 8px 4px 11px; }
button.combo arrow, button arrow, menubutton arrow { color: %(fg2)s; }

/* selector bar (Overview / Remote / Tools, Server tabs) */
stackswitcher { background-color: %(ctrl_alt)s; border: 1px solid %(ctrl_border)s; border-radius: 6px; padding: 2px; }
stackswitcher > button { background-color: transparent; border-color: transparent; border-radius: 4px;
    color: %(fg2)s; padding: 4px 14px; }
stackswitcher > button:hover { background-color: %(subtle_hover)s; color: %(fg)s; }
stackswitcher > button:checked { background-color: %(ctrl_hover)s; border-color: %(ctrl_border)s;
    border-bottom-color: %(ctrl_border_b)s; color: %(fg)s; box-shadow: inset 0 -2px %(accent)s; }
stackswitcher > button:checked label { color: %(fg)s; }

/* tabs = pivot */
notebook { background-color: transparent; border: none; }
notebook > header { background-color: transparent; border: none; box-shadow: inset 0 -1px %(border)s; padding: 0 4px; }
notebook > header > tabs > tab { background: none; border: none; box-shadow: none; color: %(fg2)s;
    padding: 6px 12px; margin: 2px 2px 0 2px; border-radius: 4px 4px 0 0; min-height: 22px; }
notebook > header > tabs > tab:hover { color: %(fg)s; background-color: %(subtle_hover)s; box-shadow: none; }
notebook > header > tabs > tab:checked { color: %(fg)s; box-shadow: inset 0 -3px %(accent)s; }
notebook > header > tabs > tab:checked label { font-weight: 600; }
notebook > stack:not(:only-child) { background-color: transparent; }

/* text fields */
entry, spinbutton:not(.vertical) {
    background-color: %(ctrl)s; background-image: none; border: 1px solid %(ctrl_border)s;
    border-bottom-color: %(input_line)s; border-radius: 4px; box-shadow: none; color: %(fg)s;
    min-height: 30px; caret-color: %(fg)s; }
entry { padding: 0 10px; }
entry:hover, spinbutton:hover { background-color: %(ctrl_hover)s; }
entry:focus, spinbutton:focus-within, spinbutton:focus { background-color: %(input_focus)s;
    border-bottom-color: %(accent)s; box-shadow: inset 0 -1px %(accent)s; }
entry:disabled { background-color: %(ctrl_press)s; color: %(fg3)s; border-bottom-color: %(ctrl_border)s; }
entry selection, textview text selection, label selection { background-color: %(accent)s; color: %(on_accent)s; }
entry image { color: %(fg2)s; }
entry placeholder, entry .placeholder { color: %(fg3)s; }
spinbutton entry { background: none; border: none; box-shadow: none; }
spinbutton button { background: none; border: none; color: %(fg2)s; }
spinbutton button:hover { background-color: %(subtle_hover)s; }

/* check boxes, radio buttons, toggle switches */
check, radio { min-width: 18px; min-height: 18px; margin: 0 6px 0 0; border: 1px solid %(ctrl_strong)s;
    border-radius: 4px; background-color: %(ctrl_alt)s; background-image: none; box-shadow: none;
    color: %(on_accent)s; -gtk-icon-source: none; }
check:hover, radio:hover { background-color: %(subtle_hover)s; }
check:checked, check:indeterminate { background-color: %(accent)s; border-color: %(accent)s;
    -gtk-icon-source: -gtk-icontheme("object-select-symbolic"); }
check:indeterminate { -gtk-icon-source: -gtk-icontheme("list-remove-symbolic"); }
radio { border-radius: 100%%; }
radio:checked { background-color: %(on_accent)s; border: 5px solid %(accent)s; min-width: 10px; min-height: 10px; }
check:disabled, radio:disabled { border-color: %(fg3)s; background-color: transparent; }
switch { min-width: 38px; min-height: 18px; border-radius: 10px; border: 1px solid %(ctrl_strong)s;
    background-color: %(ctrl_alt)s; background-image: none; box-shadow: none; color: transparent; font-size: 0; }
switch:hover { background-color: %(subtle_hover)s; }
switch slider { min-width: 12px; min-height: 12px; margin: 3px; border-radius: 100%%; border: none;
    background-color: %(fg2)s; background-image: none; box-shadow: none; }
switch:hover slider { min-width: 14px; min-height: 14px; margin: 2px; }
switch:checked { background-color: %(accent)s; border-color: %(accent)s; }
switch:checked slider { background-color: %(on_accent)s; }
switch image { color: transparent; }

/* lists and tables */
.view, treeview.view, textview text, iconview, list, listbox { background-color: transparent; color: %(fg)s; }
treeview.view:selected, treeview.view:selected:focus, row:selected {
    background-color: %(sel_row)s; color: %(fg)s; }
treeview.view:selected label, row:selected label { color: %(fg)s; }
row:hover { background-color: %(subtle_hover)s; }
row:selected:hover { background-color: %(ctrl_hover)s; }
treeview.view header button { background-color: transparent; border: none; border-radius: 0;
    box-shadow: inset 0 -1px %(border)s; color: %(fg2)s; padding: 4px 8px; }
treeview.view header button:hover { background-color: %(subtle_hover)s; color: %(fg)s; }
treeview.view.expander { color: %(fg2)s; }
treeview.view.expander:hover { color: %(fg)s; }
treeview.view check, treeview.view radio { margin: 0; }
treeview.view:disabled { color: %(fg3)s; }

/* scrolling, separators, frames */
scrollbar { background: transparent; border: none; }
scrollbar slider { background-color: %(ctrl_strong)s; border-radius: 6px; min-width: 6px; min-height: 6px;
    border: 3px solid transparent; background-clip: padding-box; }
scrollbar slider:hover { background-color: %(fg2)s; }
scrollbar.overlay-indicator:not(.dragging):not(.hovering) slider { min-width: 3px; min-height: 3px; margin: 2px; border: none; }
scrolledwindow undershoot, scrolledwindow overshoot { background: none; box-shadow: none; }
separator { background-color: %(border)s; min-width: 1px; min-height: 1px; }
paned > separator { background-color: transparent; background-image: image(%(border)s); background-size: 1px 1px; }
frame > border, .frame { border: 1px solid %(border)s; border-radius: 4px; }

/* menus, popovers, tooltips */
popover, popover.background { background-color: %(popup)s; border: 1px solid %(popup_border)s; border-radius: 8px;
    box-shadow: 0 8px 16px %(shadow)s; padding: 4px; color: %(fg)s; }
popover modelbutton, popover button.model { border-radius: 4px; padding: 6px 12px; min-height: 0; }
popover modelbutton:hover { background-color: %(subtle_hover)s; }
menu, .menu, .context-menu { background-color: %(popup)s; border: 1px solid %(popup_border)s; padding: 4px; color: %(fg)s; }
menuitem { border-radius: 4px; padding: 6px 12px; min-height: 20px; color: %(fg)s; }
menuitem:hover { background-color: %(subtle_hover)s; color: %(fg)s; }
menuitem:disabled, menuitem:disabled label { color: %(fg3)s; }
menu separator, popover separator { margin: 4px 0; }
tooltip, tooltip.background { background-color: %(popup)s; border: 1px solid %(popup_border)s; border-radius: 4px; }
tooltip *, tooltip label { color: %(fg)s; }

/* progress, sliders */
progressbar trough { background-color: %(ctrl_strong)s; border: none; border-radius: 2px; min-height: 1px; }
progressbar progress { background-color: %(accent)s; border: none; border-radius: 2px; min-height: 3px; }
progressbar text { color: %(fg2)s; }
scale trough { background-color: %(ctrl_strong)s; border: none; border-radius: 2px; min-height: 4px; min-width: 4px; }
scale highlight { background-color: %(accent)s; border: none; border-radius: 2px; }
scale slider { min-width: 20px; min-height: 20px; border-radius: 100%%; border: 1px solid %(ctrl_border)s;
    background-color: %(accent)s; background-image: none; box-shadow: inset 0 0 0 5px %(slider_outer)s; }
scale slider:hover { box-shadow: inset 0 0 0 4px %(slider_outer)s; }
levelbar block.filled { background-color: %(accent)s; }

/* dialogs */
dialog .dialog-action-area, messagedialog .dialog-action-area { padding: 12px 0 0 0; }
messagedialog.csd .dialog-action-area button { border-radius: 4px; }
infobar, infobar > revealer > box { background-color: %(layer)s; border: 1px solid %(border)s; }

/* the app's own pieces */
.mcd-pages { background-color: %(layer)s; border-top: 1px solid %(layer_border)s; border-left: 1px solid %(layer_border)s;
    border-radius: 8px 0 0 0; }
window.maximized .mcd-pages, window.fullscreen .mcd-pages { border-radius: 0; }
window.fullscreen .mcd-pages { border-width: 0; }     /* remote desktop fullscreen: no light line top / left */
.mcd-rail { background-color: transparent; padding: 0 4px 4px 4px; }
.mcd-rail-sep { opacity: 0; min-width: 0; background: none; }
.mcd-rail-btn { border-radius: 6px; padding: 6px 2px; color: %(fg)s; box-shadow: none; }
.mcd-rail-btn:hover { background-color: %(subtle_hover)s; }
.mcd-rail-btn:active { background-color: %(subtle_press)s; }
.mcd-rail-btn:checked { background-color: %(subtle_hover)s; color: %(fg)s; }
.mcd-rail-btn:checked label, .mcd-rail-btn label { color: %(fg)s; }
.mcd-rail-pill { min-width: 3px; min-height: 16px; border-radius: 2px; background-color: transparent; }
.mcd-rail-btn:checked .mcd-rail-pill { background-color: %(accent)s; }
.mcd-rail-caption { font-size: 8pt; }
.mcd-link { color: %(accent_text)s; }
.mcd-link:hover { background-color: %(subtle_hover)s; }
.mcd-notify { background-color: %(popup)s; color: %(fg)s; border: 1px solid %(popup_border)s; border-radius: 8px;
    box-shadow: 0 8px 16px %(shadow)s; }
.dim-label { color: %(fg2)s; opacity: 1; }
"""


def css(dark, pal):
    return _CSS % colours(dark, pal)


# ---- applying it ------------------------------------------------------------------------------------
class Win11Style:
    """Installed once at start-up (App.do_startup); keeps following the Windows settings."""

    def __init__(self):
        self.provider = Gtk.CssProvider()
        self.scheme = None
        self.dark = True
        self._hooked = False

    def install(self):
        settings = Gtk.Settings.get_default()
        font = _font()
        if font:
            settings.set_property("gtk-font-name", font)
        settings.set_property("gtk-dialogs-use-header", False)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
        self.refresh()
        if osdep.IS_WINDOWS:
            GObject.add_emission_hook(Gtk.Window, "map", self._on_map)
            GLib.timeout_add(_POLL_MS, self._poll)

    def refresh(self):
        dark, pal = system_scheme()
        if (dark, pal) == self.scheme:
            return False
        self.scheme = (dark, pal)
        self.dark = dark
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", dark)
        self.provider.load_from_data(css(dark, pal).encode("utf-8"))
        if osdep.IS_WINDOWS:
            for w in Gtk.Window.list_toplevels():
                self._caption(w)
        return True

    def _poll(self):
        try:
            self.refresh()
        except Exception:
            pass
        return True

    def _on_map(self, widget, *_):
        if isinstance(widget, Gtk.Window):
            self._caption(widget)
        return True

    def _caption(self, win):
        """Native title bars (dialogs): dark / light caption in the app's colours, rounded corners."""
        if win.get_window() is None or win.get_window().get_window_type() != Gdk.WindowType.TOPLEVEL:
            return
        hwnd = osdep.window_handle(win)
        if not hwnd:
            return
        c = colours(self.dark, self.scheme[1])
        dwm = ctypes.windll.dwmapi

        def attr(n, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), n, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(h):
            return int(h[5:7], 16) << 16 | int(h[3:5], 16) << 8 | int(h[1:3], 16)
        try:
            attr(20, 1 if self.dark else 0)                 # DWMWA_USE_IMMERSIVE_DARK_MODE
            attr(33, 2)                                     # DWMWA_WINDOW_CORNER_PREFERENCE: round
            attr(35, colorref(c["caption"]))                # DWMWA_CAPTION_COLOR
            attr(36, colorref(c["caption_text"]))           # DWMWA_TEXT_COLOR
        except Exception:
            pass


# ---- caption buttons -------------------------------------------------------------------------------
# GTK draws its own title-bar buttons from theme icons, which CSS cannot replace. On Windows the header
# bars get these instead: the thin Windows 11 glyphs, drawn in the button's current text colour (so
# dark / light, hover, the red Close and inactive windows all follow the style sheet).
def _glyph(kind, win):
    def draw(area, cr):
        a = area.get_allocation()
        col = area.get_style_context().get_color(area.get_style_context().get_state())
        cr.set_source_rgba(col.red, col.green, col.blue, col.alpha)
        cr.set_line_width(1)
        s = 10                                                    # glyph size at 100 %, like Windows
        x0, y0 = (a.width - s) // 2 + 0.5, (a.height - s) // 2 + 0.5
        if kind == "minimize":
            cr.move_to(x0, y0 + s / 2)
            cr.line_to(x0 + s, y0 + s / 2)
        elif kind == "maximize" and not win.is_maximized():
            _rounded(cr, x0, y0, s - 1, s - 1, 1.5)
        elif kind == "maximize":                                  # restore: two overlapping squares
            _rounded(cr, x0, y0 + 2, s - 3, s - 3, 1.5)
            cr.move_to(x0 + 2, y0 + 1)
            cr.line_to(x0 + 3, y0)
            cr.line_to(x0 + s - 2, y0)
            cr.curve_to(x0 + s - 1, y0, x0 + s - 1, y0, x0 + s - 1, y0 + 1)
            cr.line_to(x0 + s - 1, y0 + s - 3)
            cr.line_to(x0 + s - 2, y0 + s - 2)
        else:                                                     # close
            cr.move_to(x0, y0)
            cr.line_to(x0 + s - 1, y0 + s - 1)
            cr.move_to(x0 + s - 1, y0)
            cr.line_to(x0, y0 + s - 1)
        cr.stroke()
        return True
    return draw


def _rounded(cr, x, y, w, h, r):
    import math
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def caption_buttons(win, headerbar):
    """Windows 11 minimise / maximise / close at the right end of the header bar (call before packing
    anything else at the end). No-op without the Windows 11 look."""
    if not active():
        return
    headerbar.set_show_close_button(False)
    kinds = [("close", win.close, "Close")]
    if win.get_resizable():
        kinds.append(("maximize", lambda: win.unmaximize() if win.is_maximized() else win.maximize(), "Maximize"))
    kinds.append(("minimize", win.iconify, "Minimize"))
    areas = []
    for kind, action, tip in kinds:
        b = Gtk.Button(tooltip_text=tip, can_focus=False, relief=Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("titlebutton")
        b.get_style_context().add_class(kind)
        area = Gtk.DrawingArea(width_request=16, height_request=16)
        area.connect("draw", _glyph(kind, win))
        b.add(area)
        b.connect("clicked", lambda _b, f=action: f())
        headerbar.pack_end(b)
        areas.append(area)
    win.connect("window-state-event", lambda *_: [a.queue_draw() for a in areas] and False)


_style = None


def install():
    """Start the Windows 11 look (no-op elsewhere). Returns True when it is active."""
    global _style
    if not enabled():
        return False
    if _style is None:
        _style = Win11Style()
        _style.install()
    return True


def active():
    return _style is not None
