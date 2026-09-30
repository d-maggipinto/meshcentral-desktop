# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Small GTK helpers shared by the windows."""
import time

from gi.repository import Gtk

AGENT_OS = {1: "Windows", 2: "Windows", 3: "Windows", 4: "Windows", 5: "Linux", 6: "Linux", 7: "macOS",
            8: "Linux", 9: "Linux", 10: "Custom", 16: "macOS", 21: "Windows", 22: "Windows", 25: "Linux",
            26: "Linux", 27: "Linux", 28: "Linux", 29: "macOS", 30: "FreeBSD", 32: "Linux", 33: "Windows",
            34: "Windows", 36: "Linux", 37: "OpenBSD", 40: "Linux", 41: "Linux", 42: "Windows", 43: "Windows"}


def node_os(node):
    return node.get("osdesc") or AGENT_OS.get((node.get("agent") or {}).get("id"), "")


def is_windows(node):
    aid = (node.get("agent") or {}).get("id")
    return AGENT_OS.get(aid) == "Windows" or "windows" in (node.get("osdesc") or "").lower()


def is_online(node):
    return bool((node.get("conn") or 0) & 1)


_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def set_time_format(fmt):
    """App-wide date/time format (My Account -> Localization settings)."""
    global _TIME_FMT
    if fmt:
        _TIME_FMT = fmt


def fmt_date(secs):
    """Date only (the date part of the app's date/time format), e.g. the Users list's Last Access."""
    if not secs:
        return ""
    fmt = _TIME_FMT.split(" ")[0] if "%H" in _TIME_FMT else _TIME_FMT
    try:
        return time.strftime(fmt, time.localtime(secs / 1000 if secs > 1e11 else secs))
    except Exception:
        return ""


def fmt_time(ms):
    if not ms:
        return ""
    # Events may carry time as an ISO-8601 string rather than epoch ms.
    if isinstance(ms, str):
        s = ms.strip()
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone().strftime(_TIME_FMT)
        except Exception:
            return s
    try:
        return time.strftime(_TIME_FMT, time.localtime(ms / 1000 if ms > 1e11 else ms))
    except Exception:
        return str(ms)


def fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def message(parent, title, text="", kind=Gtk.MessageType.INFO):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                          buttons=Gtk.ButtonsType.OK, text=title)
    if text:
        d.format_secondary_text(text)
    d.run()
    d.destroy()


def confirm(parent, title, text="", ok_label="OK", destructive=False):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                          buttons=Gtk.ButtonsType.NONE, text=title)
    if text:
        d.format_secondary_text(text)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    b = d.add_button(ok_label, Gtk.ResponseType.OK)
    if destructive:
        b.get_style_context().add_class("destructive-action")
    r = d.run()
    d.destroy()
    return r == Gtk.ResponseType.OK


def form_dialog(parent, title, fields, ok_label="OK"):
    """fields: list of (key, label, kind, default) with kind in text|password|multiline|combo:<a|b>|check|spin.
    Returns dict or None."""
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button(ok_label, Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
    d.set_default_response(Gtk.ResponseType.OK)
    grid = Gtk.Grid(row_spacing=8, column_spacing=12, margin=14)
    d.get_content_area().add(grid)
    getters = {}
    for row, (key, label, kind, default) in enumerate(fields):
        if kind != "check":
            grid.attach(Gtk.Label(label=label, xalign=1, yalign=0), 0, row, 1, 1)
        if kind in ("text", "password"):
            w = Gtk.Entry(text=default or "", activates_default=True, hexpand=True, width_chars=38)
            if kind == "password":
                w.set_visibility(False)
            getters[key] = w.get_text
        elif kind == "multiline":
            tv = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            tv.get_buffer().set_text(default or "")
            w = Gtk.ScrolledWindow(min_content_height=180, min_content_width=420, hexpand=True, vexpand=True)
            w.add(tv)
            buf = tv.get_buffer()
            getters[key] = lambda b=buf: b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        elif kind.startswith("combo:"):
            w = Gtk.ComboBoxText(hexpand=True)
            opts = kind[6:].split("|")
            for o in opts:
                w.append_text(o)
            w.set_active(opts.index(default) if default in opts else 0)
            getters[key] = w.get_active_text
        elif kind == "check":
            w = Gtk.CheckButton(label=label, active=bool(default))
            getters[key] = w.get_active
        elif kind == "spin":
            w = Gtk.SpinButton.new_with_range(0, 100000, 1)
            w.set_value(default or 0)
            getters[key] = lambda s=w: int(s.get_value())
        grid.attach(w, 1 if kind != "check" else 0, row, 1 if kind != "check" else 2, 1)
    d.show_all()
    r = d.run()
    out = {k: g() for k, g in getters.items()} if r == Gtk.ResponseType.OK else None
    d.destroy()
    return out


def text_column(title, col, expand=False, sort_col=None):
    """A readable TreeView text column. Short columns (time, user, action, state...) are NOT
    ellipsized, so they size to their content instead of collapsing to "2026-…"; only the one
    expanding column (message, command, name) is ellipsized and takes the remaining width."""
    from gi.repository import Pango
    r = Gtk.CellRendererText()
    if expand:
        r.set_property("ellipsize", Pango.EllipsizeMode.END)
    c = Gtk.TreeViewColumn(title, r, text=col)
    c.set_resizable(True)
    c.set_sort_column_id(col if sort_col is None else sort_col)
    if expand:
        c.set_expand(True)
        c.set_min_width(200)
    return c


def row_tooltip(tv, col):
    """Show a row's full text (column `col`) as a PLAIN-text tooltip. Unlike
    TreeView.set_tooltip_column this does not parse Pango markup, so messages containing
    <, & or code render correctly."""
    def query(widget, x, y, keyboard, tooltip):
        ok, _x, _y, model, path, it = widget.get_tooltip_context(x, y, keyboard)
        if not ok or it is None:
            return False
        text = model[it][col]
        if not text:
            return False
        tooltip.set_text(str(text))
        widget.set_tooltip_row(tooltip, path)
        return True
    tv.set_has_tooltip(True)
    tv.connect("query-tooltip", query)


def scrolled(child):
    s = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    s.add(child)
    return s


def json_tree(data):
    """A read-only tree view of arbitrary JSON (used for hardware / network info)."""
    store = Gtk.TreeStore(str, str)

    def add(parent, key, val):
        if isinstance(val, dict):
            it = store.append(parent, [str(key), ""])
            for k, v in val.items():
                add(it, k, v)
        elif isinstance(val, list):
            it = store.append(parent, [str(key), f"[{len(val)}]"])
            for i, v in enumerate(val):
                add(it, i, v)
        else:
            store.append(parent, [str(key), "" if val is None else str(val)])

    if isinstance(data, dict):
        for k, v in data.items():
            add(None, k, v)
    tv = Gtk.TreeView(model=store, headers_visible=True, enable_search=True)
    for i, t in enumerate(("Property", "Value")):
        c = Gtk.TreeViewColumn(t, Gtk.CellRendererText(), text=i)
        c.set_resizable(True)
        tv.append_column(c)
    tv.expand_all()
    return tv
