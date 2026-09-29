"""My Server (web UI viewmode=6): General (server actions, live statistics, server state),
Stats (history charts) and Console (server console).

Protocol (meshuser.js / webserver.js), all gated server-side by site rights
(backup 1, restore 4, update 16; statistics need any of them; console needs full admin):
  {action:'serverstats', interval:<ms>} -> periodic {action:'serverstats', totalmem, freemem,
        availablemem, cpuavg:[1,5,15 min], values:{ServerState:{...}, AgentErrorCounters?:{...}}}
        {action:'serverstats'} (no interval) stops the timer
  {action:'servertimelinestats', hours} -> {events:[{time, conn:{ca,cu,us,rs,am,amc?},
        mem:{rss,heapTotal,heapUsed,external}, cpu:[..], traffic}]}  (a sample every 5 minutes)
  {action:'serverversion', responseid} -> {result:'OK', tags:{current, latest, stable}}
  {action:'serverupdate', version?}      (server downloads the version and restarts)
  {action:'servererrors'} -> {data}   {action:'serverclearerrorlog'}
  {action:'serverconfig'} -> {data}   (config.json, sensitive)
  {action:'serverconsole', value} -> {action:'serverconsole', value}
  GET /backup.zip, POST /restoreserver.ashx (datafile)  , web session (client.WebSession)
"""
import math
import os
import time
from datetime import datetime

from gi.repository import Gtk, GLib, Pango

from . import ui, rights
from .client import WebSession

STATS_INTERVAL_MS = 10000
STATE_NAMES = [("UserAccounts", "User Accounts"), ("DeviceGroups", "Device Groups"),
               ("AgentSessions", "Agent Sessions"), ("ConnectedUsers", "Connected Users"),
               ("UsersSessions", "Users Sessions"), ("RelaySessions", "Relay Sessions"),
               ("RelayCount", "Relay Count"), ("ConnectedIntelAMT", "Connected Intel® AMT"),
               ("ConnectedIntelAMTCira", "Connected Intel® AMT CIRA"), ("RelayErrors", "Relay Errors")]
RANGES = [("Last hour", 1), ("Last 6 hours", 6), ("Last 24 hours", 24), ("Last 7 days", 168),
          ("Last 30 days", 720)]
CHARTS = {
    "Connections": [("Agents", "ca", (0.20, 0.60, 0.86)), ("Users", "cu", (0.18, 0.80, 0.44)),
                    ("User sessions", "us", (0.95, 0.61, 0.07)), ("Relay sessions", "rs", (0.91, 0.30, 0.24))],
    "Memory (MB)": [("RSS", "rss", (0.20, 0.60, 0.86)), ("Heap total", "heapTotal", (0.18, 0.80, 0.44)),
                    ("Heap used", "heapUsed", (0.95, 0.61, 0.07)), ("External", "external", (0.61, 0.35, 0.71))],
    "CPU load": [("1 min load", 0, (0.20, 0.60, 0.86))],
}


# ---- small drawing widgets ---------------------------------------------------------
class Gauge(Gtk.DrawingArea):
    """Ring gauge like the web UI's CPU / memory indicators."""

    def __init__(self, size=56, levels=True):
        super().__init__()
        self.set_size_request(size, size)
        self.fraction = 0.0
        self.levels = levels          # colour by usage (memory); CPU load has no fixed 100 %
        self.connect("draw", self._draw)

    def set_fraction(self, f):
        self.fraction = max(0.0, min(1.0, f or 0.0))
        self.queue_draw()

    def _draw(self, w, cr):
        a = w.get_allocation()
        r = min(a.width, a.height) / 2 - 4
        cx, cy = a.width / 2, a.height / 2
        cr.set_line_width(7)
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        f = self.fraction
        col = (0.18, 0.80, 0.44)
        if self.levels:
            col = col if f < 0.7 else (0.95, 0.61, 0.07) if f < 0.9 else (0.91, 0.30, 0.24)
        cr.set_source_rgb(*col)
        cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * max(f, 0.01))
        cr.stroke()
        return False


class LineChart(Gtk.DrawingArea):
    """Minimal time-series chart: series = [(name, (r,g,b), [(epoch, value), ...])]."""

    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 320)
        self.series = []
        self.empty_text = "No data"
        self.connect("draw", self._draw)

    def set_series(self, series, empty_text="No data"):
        self.series = series
        self.empty_text = empty_text
        self.queue_draw()

    def _draw(self, w, cr):
        a = w.get_allocation()
        sc = w.get_style_context()
        fg = sc.get_color(Gtk.StateFlags.NORMAL)
        L, R, T, B = 60, 16, 16, 64
        pw, ph = a.width - L - R, a.height - T - B
        pts = [p for _n, _c, d in self.series for p in d]
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        if not pts or pw < 50 or ph < 50:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
            ext = cr.text_extents(self.empty_text)
            cr.move_to((a.width - ext.width) / 2, a.height / 2)
            cr.show_text(self.empty_text)
            return False
        t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
        if t1 <= t0:
            t1 = t0 + 60
        vmax = max(p[1] for p in pts) or 1
        mag = 10 ** math.floor(math.log10(vmax))
        vmax = math.ceil(vmax / mag * 1.1) * mag                   # round up for a clean axis
        X = lambda t: L + (t - t0) / (t1 - t0) * pw
        Y = lambda v: T + ph - v / vmax * ph
        # grid + y labels
        cr.set_line_width(1)
        for i in range(5):
            v = vmax * i / 4
            y = Y(v)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.12)
            cr.move_to(L, y)
            cr.line_to(L + pw, y)
            cr.stroke()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
            lab = f"{v:.2f}" if vmax < 5 else f"{v:.0f}"
            ext = cr.text_extents(lab)
            cr.move_to(L - 8 - ext.width, y + 4)
            cr.show_text(lab)
        # x labels
        span = t1 - t0
        fmt = "%H:%M" if span <= 2 * 86400 else "%d %b"
        for i in range(5):
            t = t0 + span * i / 4
            lab = time.strftime(fmt, time.localtime(t))
            ext = cr.text_extents(lab)
            cr.move_to(min(max(X(t) - ext.width / 2, L), L + pw - ext.width), T + ph + 18)
            cr.show_text(lab)
        # lines
        cr.set_line_width(2)
        for _name, col, data in self.series:
            if not data:
                continue
            cr.set_source_rgb(*col)
            for k, (t, v) in enumerate(sorted(data)):
                (cr.move_to if k == 0 else cr.line_to)(X(t), Y(v))
            cr.stroke()
        # legend
        x = L
        for name, col, _d in self.series:
            cr.set_source_rgb(*col)
            cr.rectangle(x, a.height - 22, 12, 12)
            cr.fill()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.85)
            cr.move_to(x + 17, a.height - 12)
            cr.show_text(name)
            x += 17 + cr.text_extents(name).width + 22
        return False


def _section(text):
    l = Gtk.Label(xalign=0, margin_top=14, margin_bottom=4)
    l.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return l


def _epoch(t):
    if isinstance(t, (int, float)):
        return t / 1000 if t > 1e11 else t
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class MyServerPanel(Gtk.Box):
    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.ctrl = app.ctrl
        self._started = False
        self._handlers = []
        self._web = None
        self.full_admin = rights.site_rights(self.ctrl) == rights.FULL
        self.can_backup = rights.has_site(self.ctrl, rights.SITE_BACKUP)
        self.can_restore = rights.has_site(self.ctrl, rights.SITE_RESTORE)
        self.can_update = rights.has_site(self.ctrl, rights.SITE_UPDATE)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=100)
        sw = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.START, margin=8)
        self.pack_start(sw, False, False, 0)
        self.pack_start(self.stack, True, True, 0)
        self.stack.add_titled(ui.scrolled(self._build_general()), "general", "General")
        self.stack.add_titled(self._build_stats(), "stats", "Stats")
        self.stack.add_titled(self._build_console(), "console", "Console")
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_page())
        self.show_all()

    # ---- General ------------------------------------------------------------
    def _build_general(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=16, margin_top=4)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>My Server</span>")
        box.pack_start(title, False, False, 0)

        box.pack_start(_section("Server actions"), False, False, 0)
        acts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                           column_spacing=6, row_spacing=6, homogeneous=False)
        for label, icon, cb, allowed, why in (
                ("Download server backup", "document-save-symbolic", self.download_backup, self.can_backup,
                 "Requires the server backup permission"),
                ("Restore server with backup", "document-revert-symbolic", self.restore_backup, self.can_restore,
                 "Requires the server restore permission"),
                ("Check server version", "software-update-available-symbolic", self.check_version, self.can_update,
                 "Requires the server update permission"),
                ("Show server error log", "dialog-warning-symbolic", self.show_errors, self.can_update,
                 "Requires the server update permission"),
                ("Show server configuration", "text-x-generic-symbolic", self.show_config, self.can_update,
                 "Requires the server update permission")):
            b = Gtk.Button(label=label, image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON),
                           always_show_image=True)
            b.connect("clicked", lambda *_, c=cb: c())
            b.set_sensitive(allowed)
            if not allowed:
                b.set_tooltip_text(why)
            acts.add(b)
        box.pack_start(acts, False, False, 0)
        self.progress = Gtk.ProgressBar(show_text=True, margin_top=6)
        self.progress.set_no_show_all(True)
        box.pack_start(self.progress, False, False, 0)

        box.pack_start(_section("Server statistics"), False, False, 0)
        stats = Gtk.Box(spacing=48, margin_start=8)
        # Like the web UI: ring = min(1-minute load, 1). A load average is relative to the
        # number of CPU cores (unknown here), so it is not coloured as an alarm.
        self.cpu_gauge, self.cpu_label = Gauge(levels=False), Gtk.Label(xalign=0)
        self.cpu_label.set_tooltip_text("Load average over the last 1, 5 and 15 minutes")
        self.mem_gauge, self.mem_label = Gauge(), Gtk.Label(xalign=0)
        for g, head, lab in ((self.cpu_gauge, "CPU load", self.cpu_label),
                             (self.mem_gauge, "Available memory", self.mem_label)):
            item = Gtk.Box(spacing=12)
            item.pack_start(g, False, False, 0)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=2)
            h = Gtk.Label(label=head, xalign=0)
            h.get_style_context().add_class("dim-label")
            txt.pack_start(h, False, False, 0)
            txt.pack_start(lab, False, False, 0)
            item.pack_start(txt, False, False, 0)
            stats.pack_start(item, False, False, 0)
        box.pack_start(stats, False, False, 0)

        box.pack_start(_section("Server state"), False, False, 0)
        self.tiles = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5,
                                 min_children_per_line=2, column_spacing=8, row_spacing=8, homogeneous=True)
        box.pack_start(self.tiles, False, False, 0)
        self.updated = Gtk.Label(xalign=0, margin_top=10)
        self.updated.get_style_context().add_class("dim-label")
        box.pack_start(self.updated, False, False, 0)
        return box

    def _tile(self, name, value, alert=False):
        f = Gtk.Frame()
        b = Gtk.Box(spacing=12, margin=10)
        b.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
        v = Gtk.Label(xalign=1)
        val = GLib.markup_escape_text(str(value))
        if alert:
            val = "<span foreground='#e01b24'>" + val + "</span>"
        v.set_markup("<b>" + val + "</b>")
        b.pack_start(v, False, False, 0)
        f.add(b)
        return f

    def _on_stats(self, msg):
        cpu = msg.get("cpuavg") or []
        if cpu:
            self.cpu_gauge.set_fraction(cpu[0])
            self.cpu_label.set_markup("<b>" + ", ".join(f"{c:.2f}".rstrip("0").rstrip(".") for c in cpu) + "</b>")
        total = msg.get("totalmem") or 0
        avail = msg.get("availablemem") or msg.get("freemem") or 0
        if total:
            self.mem_gauge.set_fraction(1 - avail / total)
            self.mem_label.set_markup(f"<b>{ui.fmt_size(avail)}</b> free, <b>{ui.fmt_size(total)}</b> total")
        values = msg.get("values") or {}
        state = values.get("ServerState") or {}
        errs = values.get("AgentErrorCounters") or {}
        for c in self.tiles.get_children():
            self.tiles.remove(c)
        for key, name in STATE_NAMES:
            if key in state:
                self.tiles.add(self._tile(name, state[key], alert=(key == "RelayErrors")))
        for key, val in errs.items():
            self.tiles.add(self._tile(f"Agent errors: {key}", val, alert=True))
        self.tiles.show_all()
        self.updated.set_text("Updated " + time.strftime("%H:%M:%S") + f" · refreshes every {STATS_INTERVAL_MS // 1000} s")

    # ---- Stats (history) --------------------------------------------------------
    def _build_stats(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=16, margin_top=4, spacing=8)
        bar = Gtk.Box(spacing=8)
        self.chart_kind = Gtk.ComboBoxText()
        for k in CHARTS:
            self.chart_kind.append_text(k)
        self.chart_kind.set_active(0)
        self.chart_range = Gtk.ComboBoxText()
        for label, _h in RANGES:
            self.chart_range.append_text(label)
        self.chart_range.set_active(2)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Refresh")
        refresh.connect("clicked", lambda *_: self._request_timeline())
        self.chart_kind.connect("changed", lambda *_: self._render_chart())
        self.chart_range.connect("changed", lambda *_: self._request_timeline())
        for w in (Gtk.Label(label="Chart:"), self.chart_kind, Gtk.Label(label="Range:"), self.chart_range, refresh):
            bar.pack_start(w, False, False, 0)
        self.chart_info = Gtk.Label(xalign=1)
        self.chart_info.get_style_context().add_class("dim-label")
        bar.pack_end(self.chart_info, True, True, 0)
        box.pack_start(bar, False, False, 0)
        self.chart = LineChart()
        box.pack_start(self.chart, True, True, 0)
        self._timeline = []
        return box

    def _request_timeline(self):
        self.chart_info.set_text("Loading…")
        self.ctrl.send({"action": "servertimelinestats", "hours": RANGES[self.chart_range.get_active()][1]})

    def _on_timeline(self, msg):
        self._timeline = msg.get("events") or []
        self._render_chart()

    def _render_chart(self):
        kind = self.chart_kind.get_active_text()
        series = []
        for name, key, col in CHARTS[kind]:
            data = []
            for e in self._timeline:
                t = _epoch(e.get("time"))
                if t is None:
                    continue
                if kind == "Connections":
                    v = (e.get("conn") or {}).get(key)
                elif kind.startswith("Memory"):
                    v = (e.get("mem") or {}).get(key)
                    v = v / (1024 * 1024) if isinstance(v, (int, float)) else None
                else:
                    c = e.get("cpu")
                    v = c[key] if isinstance(c, list) and len(c) > key else None
                if isinstance(v, (int, float)):
                    data.append((t, float(v)))
            series.append((name, col, data))
        self.chart.set_series(series, "No samples yet, the server records one every 5 minutes.")
        n = len(self._timeline)
        self.chart_info.set_text(f"{n} sample{'s' if n != 1 else ''}")

    # ---- Console ----------------------------------------------------------------
    def _build_console(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if not self.full_admin:
            l = Gtk.Label(label="The server console is only available to full administrators.")
            l.get_style_context().add_class("dim-label")
            box.pack_start(l, True, True, 0)
            self.console_view = None
            return box
        hint = Gtk.Label(label="MeshCentral server console, type “help” for the list of commands.",
                         xalign=0, margin=8)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        self.console_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                         wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.console_view.set_left_margin(8)
        self.console_view.set_top_margin(6)
        box.pack_start(ui.scrolled(self.console_view), True, True, 0)
        row = Gtk.Box(spacing=6, margin=8)
        self.console_entry = Gtk.Entry(hexpand=True, placeholder_text="Server console command (e.g. help, info)")
        self.console_entry.connect("activate", lambda *_: self._console_send())
        send = Gtk.Button(label="Send")
        send.get_style_context().add_class("suggested-action")
        send.connect("clicked", lambda *_: self._console_send())
        row.pack_start(self.console_entry, True, True, 0)
        row.pack_start(send, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    def _console_append(self, text):
        buf = self.console_view.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        self.console_view.scroll_to_mark(buf.get_insert(), 0.0, False, 0, 0)

    def _console_send(self):
        cmd = self.console_entry.get_text().strip()
        if not cmd:
            return
        self.console_entry.set_text("")
        self._console_append(f"> {cmd}\n")
        self.ctrl.send({"action": "serverconsole", "value": cmd})

    def _on_console(self, msg):
        if self.console_view is not None and msg.get("value") is not None:
            self._console_append(str(msg["value"]).rstrip("\n") + "\n")

    # ---- lifecycle ----------------------------------------------------------------
    def on_shown(self):
        if self._started:
            return
        self._started = True
        for action, cb in (("serverstats", self._on_stats), ("servertimelinestats", self._on_timeline),
                           ("serverconsole", self._on_console)):
            self.ctrl.on(action, cb)
            self._handlers.append((action, cb))
        self.ctrl.send({"action": "serverstats", "interval": STATS_INTERVAL_MS})

    def _on_page(self):
        if self.stack.get_visible_child_name() == "stats" and not self._timeline:
            self._request_timeline()
        if self.stack.get_visible_child_name() == "console" and self.console_view is not None:
            self.console_entry.grab_focus()

    def teardown(self):
        if self._started:
            self.ctrl.send({"action": "serverstats"})          # no interval -> server stops the timer
        for action, cb in self._handlers:
            self.ctrl.off(action, cb)
        self._handlers = []

    # ---- actions ----------------------------------------------------------------------
    def _session(self):
        if self._web is None:
            self._web = WebSession(self.ctrl)
        return self._web

    def _text_dialog(self, title, text, warning=None, extra=None):
        d = Gtk.Dialog(title=title, transient_for=self.get_toplevel(), modal=True)
        d.set_default_size(820, 560)
        area = d.get_content_area()
        area.set_spacing(6)
        area.set_border_width(8)
        if warning:
            info = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
            info.get_content_area().add(Gtk.Label(label=warning, wrap=True, xalign=0))
            area.pack_start(info, False, False, 0)
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(text or "")
        tv.set_left_margin(8)
        area.pack_start(ui.scrolled(tv), True, True, 0)
        for label, resp in (extra or []):
            d.add_button(label, resp)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        d.show_all()
        r = d.run()
        d.destroy()
        return r

    def _once(self, action, cb, timeout_s=15, on_timeout=None):
        """Listen for a single reply of a broadcast-style action."""
        state = {"done": False}

        def handler(msg):
            if state["done"]:
                return
            state["done"] = True
            self.ctrl.off(action, handler)
            cb(msg)

        def expire():
            if not state["done"]:
                state["done"] = True
                self.ctrl.off(action, handler)
                if on_timeout:
                    on_timeout()
            return False
        self.ctrl.on(action, handler)
        GLib.timeout_add_seconds(timeout_s, expire)

    def show_errors(self):
        def got(msg):
            data = msg.get("data") or ""
            r = self._text_dialog("Server error log", data or "The server error log is empty.",
                                  extra=[("Clear log", 1)] if data else None)
            if r == 1 and ui.confirm(self.get_toplevel(), "Clear the server error log?", "", "Clear",
                                     destructive=True):
                self.ctrl.send({"action": "serverclearerrorlog"})
        self._once("servererrors", got, on_timeout=lambda: ui.message(
            self.get_toplevel(), "No answer from the server",
            "The error log may be disabled for this domain (myserver.errorlog)."))
        self.ctrl.send({"action": "servererrors"})

    def show_config(self):
        self._once("serverconfig", lambda m: self._text_dialog(
            "Server configuration (config.json)", m.get("data") or "",
            warning="This file can contain secrets (passwords, keys). Do not share it."),
            on_timeout=lambda: ui.message(self.get_toplevel(), "No answer from the server",
                                          "Viewing the configuration may be disabled (myserver.config)."))
        self.ctrl.send({"action": "serverconfig"})

    def check_version(self):
        def reply(msg):
            if msg.get("result") != "OK":
                ui.message(self.get_toplevel(), "Cannot check the server version", str(msg.get("result")))
                return
            tags = msg.get("tags") or {}
            cur, latest, stable = tags.get("current"), tags.get("latest"), tags.get("stable")
            d = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                  message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.NONE,
                                  text=f"MeshCentral {cur}")
            d.format_secondary_text(f"Latest version: {latest}\nStable version: {stable}")
            offers = []
            if latest and latest != cur:
                offers.append((f"Update to {latest}", latest))
            if stable and stable != cur and stable != latest:
                offers.append((f"Install {stable} (stable)", stable))
            for i, (label, _v) in enumerate(offers):
                d.add_button(label, 100 + i)
            d.add_button("Close", Gtk.ResponseType.CLOSE)
            r = d.run()
            d.destroy()
            if r >= 100:
                version = offers[r - 100][1]
                if ui.confirm(self.get_toplevel(), f"Install MeshCentral {version}?",
                              "The server downloads the new version and RESTARTS. All users and agents are "
                              "disconnected for a short time.", "Install and restart", destructive=True):
                    self.ctrl.send({"action": "serverupdate", "version": version})
                    self.app.notify("Server update started", f"Installing MeshCentral {version}")
        self.ctrl.send({"action": "serverversion"}, reply)

    def _progress_show(self, text, done, total):
        self.progress.show()
        self.progress.set_text(text)
        if total:
            self.progress.set_fraction(min(1.0, done / total))
        else:
            self.progress.pulse()

    def download_backup(self):
        ch = Gtk.FileChooserNative.new("Save server backup", self.get_toplevel(), Gtk.FileChooserAction.SAVE,
                                       "_Save", "_Cancel")
        ch.set_current_name(time.strftime("meshcentral-backup-%Y%m%d-%H%M.zip"))
        ch.set_do_overwrite_confirmation(True)
        dl = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if dl:
            ch.set_current_folder(dl)
        if ch.run() != Gtk.ResponseType.ACCEPT:
            ch.destroy()
            return
        dest = ch.get_filename()
        ch.destroy()
        self._progress_show("Creating backup on the server… (can take up to 2 minutes)", 0, 0)
        pulse = GLib.timeout_add(200, lambda: (self.progress.pulse(), True)[1])

        def done(err):
            GLib.source_remove(pulse)
            self.progress.hide()
            if err:
                hint = ""
                if "403" in err:
                    hint = "\n\nBackups are disabled in the server configuration (settings.autobackup)."
                elif "401" in err:
                    hint = "\n\nDownloading backups is not allowed for this account or domain (myserver.backup)."
                ui.message(self.get_toplevel(), "Backup failed", err + hint, Gtk.MessageType.ERROR)
            else:
                self.app.notify("Server backup saved", os.path.basename(dest))
                ui.message(self.get_toplevel(), "Server backup saved", dest)
        self._session().fetch("/backup.zip", dest,
                              lambda d, t: self._progress_show("Downloading backup", d, t), done, timeout=300)

    def restore_backup(self):
        ch = Gtk.FileChooserNative.new("Choose a server backup (.zip)", self.get_toplevel(),
                                       Gtk.FileChooserAction.OPEN, "_Open", "_Cancel")
        flt = Gtk.FileFilter()
        flt.set_name("Backup (*.zip)")
        flt.add_pattern("*.zip")
        ch.add_filter(flt)
        if ch.run() != Gtk.ResponseType.ACCEPT:
            ch.destroy()
            return
        path = ch.get_filename()
        ch.destroy()
        if not ui.confirm(self.get_toplevel(), "Restore the ENTIRE server from this backup?",
                          f"{os.path.basename(path)}\n\nThis REPLACES the server database (all users, device "
                          "groups, devices, settings) with the backup and restarts the server. Everyone is "
                          "disconnected. This cannot be undone.", "Restore server", destructive=True):
            return
        self._session().post_file("/restoreserver.ashx", {}, "datafile", path,
                                  lambda d, t: self._progress_show("Uploading backup", d, t),
                                  lambda err: (self.progress.hide(), ui.message(
                                      self.get_toplevel(), "Restore failed" if err else "Restore started",
                                      err or "The server is restoring the backup and will restart.",
                                      Gtk.MessageType.ERROR if err else Gtk.MessageType.INFO)))
