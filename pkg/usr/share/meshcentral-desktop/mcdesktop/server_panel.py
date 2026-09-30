# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
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
  {action:'serverconfig'} -> {data}   (config.json: sensitive)
  {action:'serverconsole', value} -> {action:'serverconsole', value}
  GET /backup.zip, POST /restoreserver.ashx (datafile)  : web session (client.WebSession)
"""
import json
import math
import os
import time
from datetime import datetime

from gi.repository import Gtk, Gdk, GLib, Pango

from . import ui, rights
from .client import WebSession

STATS_INTERVAL_MS = 10000
STATE_NAMES = [("UserAccounts", "User Accounts"), ("DeviceGroups", "Device Groups"),
               ("AgentSessions", "Agent Sessions"), ("ConnectedUsers", "Connected Users"),
               ("UsersSessions", "Users Sessions"), ("RelaySessions", "Relay Sessions"),
               ("RelayCount", "Relay Count"), ("ConnectedIntelAMT", "Connected Intel® AMT"),
               ("ConnectedIntelAMTCira", "Connected Intel® AMT CIRA"), ("RelayErrors", "Relay Errors")]
# Server warning texts by id (same table as the web UI; {0}, {1} = args)
WARNINGS = {
    2: "Missing WebDAV parameters.", 3: "Unrecognized configuration option \"{0}\".",
    4: "WebSocket compression is disabled, this feature is broken in NodeJS v11.11 to v12.15 and v13.2",
    5: "Unable to load Intel AMT TLS root certificate for default domain.",
    6: "Unable to load Intel AMT TLS root certificate for domain {0}.",
    7: "CIRA local FQDN's ignored when server in LAN-only or WAN-only mode.",
    8: "Can't have more than 4 CIRA local FQDN's. Ignoring value.",
    9: "Agent hash checking is being skipped, this is unsafe.", 10: "Missing Let's Encrypt email address.",
    11: "Invalid Let's Encrypt host names.", 12: "Invalid Let's Encrypt names, can't contain a *.",
    13: "Unable to setup Let's Encrypt module.", 14: "Invalid Let's Encrypt names, unable to resolve: {0}",
    15: "Invalid Let's Encrypt email address, unable to resolve: {0}",
    16: "Unable to load CloudFlare trusted proxy IPv6 address list.",
    17: "SendGrid server has limited use in LAN mode.", 18: "SMTP server has limited use in LAN mode.",
    19: "SMS gateway has limited use in LAN mode.", 20: "Invalid \"LoginCookieEncryptionKey\" in config.json.",
    21: "Backup path can't be set within meshcentral-data folder, backup settings ignored.",
    22: "Failed to sign agent {0}: {1}", 23: "Unable to load agent icon file: {0}.",
    24: "Unable to load agent logo file: {0}.", 25: "This NodeJS version does not support OpenID.",
    26: "This NodeJS version does not support Discord.js.",
    27: "Firebase now requires a service account JSON file, Firebase disabled.",
}
# Short explanations for warnings admins commonly ask about
WARNING_HINTS = {
    22: "MeshCentral re-signs its Windows agent installers and timestamps the signature through an online "
        "timestamp server. This usually means the server could not reach it (outbound HTTP, DNS or IPv6). "
        "Linux agents and existing agents are not affected.",
}


def warning_text(w):
    if isinstance(w, str):
        return w, None
    tmpl = WARNINGS.get(w.get("id"))
    if tmpl is None:
        return str(w.get("msg") or w), None
    args = [str(a) for a in (w.get("args") or [])]
    for i, a in enumerate(args):
        tmpl = tmpl.replace("{%d}" % i, a)
    return tmpl, WARNING_HINTS.get(w.get("id"))


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


# ---- Stats page: same charts, series, colours and ranges as the web UI (p40) --------
RANGES = [("Last 3 hours", 3), ("Last 8 hours", 8), ("Last day", 24), ("Last week", 168), ("Last 30 days", 720)]
CHART_KINDS = [("connections", "Connections"), ("memory", "Memory"), ("cpu", "CPU"),
               ("in", "Inbound traffic"), ("out", "Outbound traffic")]
CONN_SERIES = [("Agents", "ca", (158, 151, 16)), ("Users", "cu", (16, 84, 158)),
               ("User Sessions", "us", (255, 99, 132)), ("Relay Sessions", "rs", (39, 158, 16)),
               ("Intel AMT", "am", (134, 16, 158)), ("Intel AMT CIRA", "amc", (255, 155, 0))]
MEM_SERIES = [("External", "external", (158, 151, 16)), ("Heap Used", "heapUsed", (16, 84, 158)),
              ("Heap Total", "heapTotal", (255, 99, 132)), ("RSS", "rss", (39, 158, 16))]
TRAFFIC_NAMES = ["Agent", "CIRA", "AMT-OS", "HTTP", "Relay", "Terminal", "Desktop", "Files", "WebRDP",
                 "WebSSH", "WebVNC", "Desktop Multiplex"]
TRAFFIC_COLORS = [(158, 151, 16), (16, 84, 158), (255, 99, 132), (39, 158, 16), (134, 16, 158), (0, 148, 255),
                  (255, 216, 0), (255, 127, 237), (109, 213, 255), (89, 94, 255), (179, 104, 255), (179, 104, 255)]
Y_TITLES = {"connections": "Connection count", "memory": "Megabytes", "cpu": "Load (1 min)",
            "in": "Megabytes", "out": "Megabytes"}
_MB = 1024 * 1024


def _cpu1(cpu):
    """1-minute load from a sample's `cpu`. Like the web UI (typeof cpu == 'object' && typeof cpu[0]
    == 'number') accept a list OR an object keyed "0"/0, the shape depends on the server's database."""
    if isinstance(cpu, (list, tuple)):
        v = cpu[0] if cpu else None
    elif isinstance(cpu, dict):
        v = cpu.get("0", cpu.get(0))
    else:
        v = None
    return v if isinstance(v, (int, float)) else None


def _traffic_values(tr, inbound):
    """12 traffic values (MB per 5-minute sample) in TRAFFIC_NAMES order."""
    d = "In" if inbound else "Out"
    relay = tr.get("relay" + d) or []

    def rel(i):
        if isinstance(relay, list):
            return relay[i] if len(relay) > i else 0
        if isinstance(relay, dict):
            return relay.get(str(i)) or relay.get(i) or 0
        return 0
    vals = [tr.get("AgentCtrl" + d), tr.get("CIRA" + d), tr.get("LMS" + d), tr.get("http" + d)]
    vals += [rel(i) for i in (0, 1, 2, 5, 10, 11, 12)]
    vals.append((tr.get("desktopMultiplex") or {}).get("in" if inbound else "out"))
    return [(v or 0) / _MB for v in vals]


def build_series(samples, kind):
    """-> list of (name, (r,g,b), [(epoch, value or None)]). None = gap (server restarted:
    the sample carries first=true, like the web UI's NaN break)."""
    samples = [s for s in samples if _epoch(s.get("time")) is not None]
    servers = [s.get("s") for s in samples if s.get("s") is not None]
    if servers:                                   # multi-server (peering): first server, like the web UI
        samples = [s for s in samples if s.get("s") == servers[0]]
    samples.sort(key=lambda s: _epoch(s.get("time")))

    def series_from(spec, getter):
        out = []
        for name, key, col in spec:
            pts = []
            for s in samples:
                t = _epoch(s["time"])
                if s.get("first"):
                    pts.append((t - 0.001, None))
                v = getter(s, key)
                if isinstance(v, (int, float)):
                    pts.append((t, float(v)))
            if key != "amc" or any(v is not None for _t, v in pts):
                out.append((name, col, pts))
        return out

    if kind == "connections":
        return series_from(CONN_SERIES, lambda s, k: (s.get("conn") or {}).get(k))
    if kind == "memory":
        return series_from(MEM_SERIES, lambda s, k: ((s.get("mem") or {}).get(k) or 0) / _MB if s.get("mem") else None)
    if kind == "cpu":
        return series_from([("CPU", 0, (158, 151, 16))], lambda s, k: _cpu1(s.get("cpu")))
    inbound = kind == "in"
    rows = [(s, _traffic_values(s.get("traffic") or {}, inbound)) for s in samples if s.get("traffic") is not None]
    used = [i for i in range(len(TRAFFIC_NAMES)) if any(v[i] > 0 for _s, v in rows)]
    out = []
    for i in used:
        pts = []
        for s, v in rows:
            t = _epoch(s["time"])
            if s.get("first"):
                pts.append((t - 0.001, None))
            pts.append((t, v[i]))
        out.append((TRAFFIC_NAMES[i], TRAFFIC_COLORS[i], pts))
    return out


def _nice_step(span, target):
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


_TIME_STEPS = [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800]


class TimeChart(Gtk.DrawingArea):
    """Time-series area chart (cairo): fixed time window, smooth filled lines with sample points,
    gaps, optional stacking (traffic) and log scale, legend on top, y-axis title, hover crosshair
    with the exact values."""
    PAD_L, PAD_R, PAD_T, PAD_B = 72, 20, 40, 34

    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 360)
        self.series, self.t0, self.t1 = [], 0, 1
        self.y_title, self.stacked, self.log = "", False, False
        self.empty_text = "No data"
        self.hover = None
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self._draw)
        self.connect("motion-notify-event", lambda w, e: self._set_hover(e.x))
        self.connect("leave-notify-event", lambda *_: self._set_hover(None))

    def set_data(self, series, t0, t1, y_title, stacked=False, log=False, empty_text="No data"):
        self.series, self.t0, self.t1 = series, t0, max(t1, t0 + 60)
        self.y_title, self.stacked, self.log, self.empty_text = y_title, stacked, log, empty_text
        self.queue_draw()

    def _set_hover(self, x):
        self.hover = x
        self.queue_draw()

    # -- geometry helpers
    def _layers(self):
        """[(name, col, [(t, top, bottom) | None])], stacked sums for traffic."""
        out, base = [], {}
        for name, col, pts in self.series:
            layer = []
            for t, v in pts:
                if v is None:
                    layer.append(None)
                    continue
                if t < self.t0 or t > self.t1:
                    continue
                b = base.get(t, 0.0) if self.stacked else 0.0
                layer.append((t, b + v, b))
                if self.stacked:
                    base[t] = b + v
            out.append((name, col, layer))
        return out

    def _draw(self, w, cr):
        a = w.get_allocation()
        fg = w.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        L, R, T, B = self.PAD_L, self.PAD_R, self.PAD_T, self.PAD_B
        pw, ph = a.width - L - R, a.height - T - B
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        layers = self._layers()
        vals = [p[1] for _n, _c, l in layers for p in l if p]
        if pw < 80 or ph < 60:
            return False
        # legend (top, centered)
        items = [(n, c) for n, c, _l in layers]
        widths = [16 + 6 + cr.text_extents(n).x_advance + 18 for n, _c in items]
        x = L + max(0, (pw - sum(widths)) / 2)
        for (n, c), wd in zip(items, widths):
            r, g, b = (v / 255 for v in c)
            cr.set_source_rgba(r, g, b, 0.25)
            cr.rectangle(x, 12, 16, 10)
            cr.fill_preserve()
            cr.set_source_rgb(r, g, b)
            cr.set_line_width(1.5)
            cr.stroke()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.8)
            cr.move_to(x + 22, 21)
            cr.show_text(n)
            x += wd
        if not vals:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
            ext = cr.text_extents(self.empty_text)
            cr.move_to(L + (pw - ext.width) / 2, T + ph / 2)
            cr.show_text(self.empty_text)
            return False
        # y scale
        vmax = max(vals) or 1.0
        if self.log:
            pos = [v for v in vals if v > 0] or [1]
            lo = 10 ** math.floor(math.log10(min(pos)))
            hi = 10 ** math.ceil(math.log10(max(max(pos), lo * 10)))
            Y = lambda v: T + ph - (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * ph
            ticks = [lo * 10 ** i for i in range(int(round(math.log10(hi / lo))) + 1)]
        else:
            step = _nice_step(vmax, 5)
            top = math.ceil(vmax * 1.05 / step) * step
            Y = lambda v: T + ph - max(v, 0) / top * ph
            ticks = [i * step for i in range(int(round(top / step)) + 1)]
        X = lambda t: L + (t - self.t0) / (self.t1 - self.t0) * pw
        # grid + y labels
        cr.set_line_width(1)
        for v in ticks:
            y = Y(v)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.10)
            cr.move_to(L, y)
            cr.line_to(L + pw, y)
            cr.stroke()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.65)
            lab = (f"{v:g}" if v >= 1 or v == 0 else f"{v:.2g}")
            ext = cr.text_extents(lab)
            cr.move_to(L - 8 - ext.x_advance, y + 4)
            cr.show_text(lab)
        # y title (rotated)
        cr.save()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
        ext = cr.text_extents(self.y_title)
        cr.move_to(16, T + ph / 2 + ext.width / 2)
        cr.rotate(-math.pi / 2)
        cr.show_text(self.y_title)
        cr.restore()
        # x ticks: adaptive interval, aligned to local time
        span = self.t1 - self.t0
        step = next((s for s in _TIME_STEPS if pw / (span / s) >= 90), _TIME_STEPS[-1])
        fmt = "%H:%M" if step < 86400 else "%d %b"
        tz = time.localtime(self.t0).tm_gmtoff
        t = math.ceil((self.t0 + tz) / step) * step - tz
        while t <= self.t1:
            x = X(t)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.07)
            cr.move_to(x, T)
            cr.line_to(x, T + ph)
            cr.stroke()
            lab = time.strftime(fmt, time.localtime(t))
            if step >= 86400 or time.localtime(t).tm_hour == 0 and time.localtime(t).tm_min == 0 and span > 86400:
                lab = time.strftime("%d %b" if step >= 86400 else "%d %b %H:%M", time.localtime(t))
            ext = cr.text_extents(lab)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.65)
            cr.move_to(x - ext.x_advance / 2, T + ph + 18)
            cr.show_text(lab)
            t += step
        # axes
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
        cr.move_to(L, T)
        cr.line_to(L, T + ph)
        cr.line_to(L + pw, T + ph)
        cr.stroke()
        # series: fill, line, points (clip to plot area)
        cr.save()
        cr.rectangle(L, T - 2, pw, ph + 4)
        cr.clip()
        npts = max((sum(1 for p in l if p) for _n, _c, l in layers), default=0)
        for name, col, layer in (reversed(layers) if self.stacked else layers):
            r, g, b = (v / 255 for v in col)
            for seg in self._segments(layer):
                pts = [(X(t), Y(top)) for t, top, _b in seg]
                base = [(X(t), Y(bot)) for t, _top, bot in seg]
                if len(pts) == 1:
                    cr.set_source_rgb(r, g, b)
                    cr.arc(pts[0][0], pts[0][1], 3, 0, 2 * math.pi)
                    cr.fill()
                    continue
                self._path(cr, pts, smooth=not self.stacked)
                for bx, by in reversed(base):
                    cr.line_to(bx, by)
                cr.close_path()
                cr.set_source_rgba(r, g, b, 0.14 if not self.stacked else 0.45)
                cr.fill()
                self._path(cr, pts, smooth=not self.stacked)
                cr.set_source_rgb(r, g, b)
                cr.set_line_width(2)
                cr.stroke()
                if npts <= 160:
                    for px, py in pts:
                        cr.arc(px, py, 2.4, 0, 2 * math.pi)
                        cr.fill()
        cr.restore()
        # hover crosshair + values
        if self.hover is not None and L <= self.hover <= L + pw:
            times = sorted({p[0] for _n, _c, l in layers for p in l if p})
            if times:
                ht = min(times, key=lambda tt: abs(X(tt) - self.hover))
                hx = X(ht)
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
                cr.set_line_width(1)
                cr.move_to(hx, T)
                cr.line_to(hx, T + ph)
                cr.stroke()
                rows = [time.strftime("%a %d %b %H:%M", time.localtime(ht))]
                cols = [None]
                for (name, col, pts) in self.series:
                    v = next((vv for tt, vv in pts if tt == ht and vv is not None), None)
                    if v is not None:
                        rows.append(f"{name}: {v:.2f}" if not float(v).is_integer() else f"{name}: {int(v)}")
                        cols.append(col)
                wbox = max(cr.text_extents(s).x_advance for s in rows) + 30
                hbox = 16 * len(rows) + 10
                bx = hx + 12 if hx + 12 + wbox < L + pw else hx - 12 - wbox
                by = T + 8
                cr.set_source_rgba(0.1, 0.11, 0.13, 0.92)
                cr.rectangle(bx, by, wbox, hbox)
                cr.fill()
                for i, (s, c) in enumerate(zip(rows, cols)):
                    yy = by + 18 + 16 * i
                    if c:
                        cr.set_source_rgb(*(v / 255 for v in c))
                        cr.rectangle(bx + 8, yy - 9, 10, 10)
                        cr.fill()
                    cr.set_source_rgb(0.93, 0.93, 0.94)
                    cr.move_to(bx + (24 if c else 8), yy)
                    cr.show_text(s)
        return False

    @staticmethod
    def _segments(layer):
        seg = []
        for p in layer:
            if p is None:
                if seg:
                    yield seg
                seg = []
            else:
                seg.append(p)
        if seg:
            yield seg

    @staticmethod
    def _path(cr, pts, smooth=True):
        cr.move_to(*pts[0])
        if not smooth or len(pts) < 3:
            for p in pts[1:]:
                cr.line_to(*p)
            return
        # Catmull-Rom → Bézier, control points clamped to the neighbouring y range (no overshoot)
        for i in range(len(pts) - 1):
            p0 = pts[i - 1] if i > 0 else pts[i]
            p1, p2 = pts[i], pts[i + 1]
            p3 = pts[i + 2] if i + 2 < len(pts) else p2
            lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, min(max(p1[1] + (p2[1] - p0[1]) / 6, lo), hi))
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, min(max(p2[1] - (p3[1] - p1[1]) / 6, lo), hi))
            cr.curve_to(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])


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


# Server trace sources, grouped exactly like the web UI's "Server Tracing" dialog (p41)
TRACE_GROUPS = [
    ("Core Server", [("cookie", "Cookie encoder"), ("dispatch", "Message Dispatcher"),
                     ("main", "Main Server Messages"), ("peer", "MeshCentral Server Peering"),
                     ("agent", "MeshAgent traffic"), ("agentupdate", "MeshAgent update"),
                     ("cert", "Server Certificate"), ("db", "Server Database"),
                     ("email", "Email/SMS/Push Traffic")]),
    ("Web Server", [("web", "Web Server"), ("webrequest", "Web Server Requests"),
                    ("relay", "Web Socket Relay"), ("httpheaders", "Web Server HTTP Headers"),
                    ("authlog", "User Authentication Log")]),
    ("Intel\u00ae AMT", [("amt", "Intel AMT manager"), ("webrelay", "Connection Relay"),
                         ("mps", "CIRA Server"), ("mpscmd", "CIRA Server Commands")]),
]
TRACE_NAMES = {k: n for _g, items in TRACE_GROUPS for k, n in items}
TRACE_LIMITS = [100, 250, 500, 1000]


class StatsRecorder:
    """Records the server's live 5-minute stats samples (event 'servertimelinestats', sent to the
    whole session, no page needs to be open) from sign-in, and keeps their CPU load on disk.

    Why: MeshCentral's MongoDB / NeDB backends drop `cpu` when returning the stats history, so a
    client only ever has the CPU samples it received live. The web UI shows those while its page
    is open; the app records them for as long as it runs and remembers them across restarts, so
    its CPU chart shows the same points as the web UI (and more over time)."""
    KEEP_S = 30 * 86400

    def __init__(self, ctrl, data_dir):
        host = "".join(c if c.isalnum() or c in "-." else "_" for c in ctrl.server.host)
        self.path = os.path.join(data_dir, f"serverstats-{host}.json")
        self.samples = []            # [{"time": iso, "cpu": [..], "first": bool}]
        self._load()
        ctrl.on("event", self._on_event)

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.samples = [s for s in data if isinstance(s, dict) and _epoch(s.get("time"))]
        except (OSError, ValueError):
            self.samples = []

    def _save(self):
        cutoff = time.time() - self.KEEP_S
        self.samples = [s for s in self.samples if (_epoch(s["time"]) or 0) >= cutoff]
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.samples, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _on_event(self, msg):
        ev = msg.get("event") or {}
        d = ev.get("data")
        if ev.get("action") != "servertimelinestats" or not isinstance(d, dict) or _cpu1(d.get("cpu")) is None:
            return
        rec = {"time": d.get("time"), "cpu": d.get("cpu"), "first": bool(d.get("first"))}
        if d.get("s") is not None:
            rec["s"] = d["s"]
        key = round(_epoch(rec["time"]) or 0)
        if any(round(_epoch(s["time"]) or 0) == key for s in self.samples[-20:]):
            return
        self.samples.append(rec)
        self._save()

    def merge_into(self, history):
        """History samples + recorded CPU: fill `cpu` where the history lacks it (same timestamp)
        and add recorded samples the history does not contain."""
        by_time = {}
        merged = []
        for s in history:
            t = _epoch(s.get("time"))
            if t is None:
                continue
            s = dict(s)
            by_time[round(t)] = s
            merged.append(s)
        for r in self.samples:
            k = round(_epoch(r["time"]) or 0)
            h = by_time.get(k)
            if h is None:
                merged.append(dict(r))
            elif _cpu1(h.get("cpu")) is None:
                h["cpu"] = r["cpu"]
        return merged


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
        self.stack.add_titled(self._build_trace(), "trace", "Trace")
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

        # Server warnings (sent once at sign-in; cached by ControlConnection)
        self.warn_head = _section("Server warnings")
        self.warn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8)
        for w in (self.warn_head, self.warn_box):
            w.set_no_show_all(True)
            box.pack_start(w, False, False, 0)
        return box

    def _render_warnings(self, warnings):
        for c in self.warn_box.get_children():
            self.warn_box.remove(c)
        for w in warnings or []:
            text, hint = warning_text(w)
            l = Gtk.Label(xalign=0, wrap=True, selectable=True)
            l.set_markup("<span foreground='#e01b24'><b>WARNING: " + GLib.markup_escape_text(text) + "</b></span>")
            self.warn_box.pack_start(l, False, False, 0)
            if hint:
                h = Gtk.Label(label=hint, xalign=0, wrap=True, max_width_chars=110)
                h.get_style_context().add_class("dim-label")
                self.warn_box.pack_start(h, False, False, 0)
        show = bool(warnings)
        self.warn_head.set_visible(show)
        self.warn_box.set_visible(show)
        self.warn_box.show_all()

    def _on_warnings(self, msg):
        self._render_warnings(msg.get("warnings") or [])

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
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>My Server Stats</span>")
        box.pack_start(title, False, False, 0)
        bar = Gtk.Box(spacing=8)
        refresh = Gtk.Button(label="Refresh", image=Gtk.Image.new_from_icon_name("view-refresh-symbolic",
                             Gtk.IconSize.BUTTON), always_show_image=True)
        refresh.connect("clicked", lambda *_: self._request_timeline())
        self.chart_log = Gtk.CheckButton(label="Log scale")
        self.chart_log.set_tooltip_text("Logarithmic value axis (the web UI's “Log-X”)")
        self.chart_log.connect("toggled", lambda *_: self._render_chart())
        self.chart_kind = Gtk.ComboBoxText()
        for _k, label in CHART_KINDS:
            self.chart_kind.append_text(label)
        self.chart_kind.set_active(0)
        self.chart_kind.connect("changed", lambda *_: self._render_chart())
        self.chart_range = Gtk.ComboBoxText()
        for label, _h in RANGES:
            self.chart_range.append_text(label)
        self.chart_range.set_active(0)
        self.chart_range.connect("changed", lambda *_: self._request_timeline())
        dl = Gtk.Button.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON)
        dl.set_tooltip_text("Download data points (.csv)")
        dl.connect("clicked", lambda *_: self._download_csv())
        for w in (refresh, self.chart_log):
            bar.pack_start(w, False, False, 0)
        for w in (dl, self.chart_range, self.chart_kind):
            bar.pack_end(w, False, False, 0)
        self.chart_info = Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)
        self.chart_info.get_style_context().add_class("dim-label")
        bar.pack_end(self.chart_info, True, True, 8)
        box.pack_start(bar, False, False, 0)
        self.chart = TimeChart()
        box.pack_start(self.chart, True, True, 0)
        self._timeline = []
        return box

    def _hours(self):
        return RANGES[self.chart_range.get_active()][1]

    def _request_timeline(self):
        self.chart_info.set_text("Loading…")
        self.ctrl.send({"action": "servertimelinestats", "hours": self._hours()})

    def _on_timeline(self, msg):
        self._timeline = msg.get("events") or []
        self._render_chart()

    def _on_live_sample(self, msg):
        # The server events every new 5-minute sample: {action:'event', event:{action:'servertimelinestats', data}}
        ev = msg.get("event") or {}
        if ev.get("action") == "servertimelinestats" and isinstance(ev.get("data"), dict):
            self._timeline.append(ev["data"])
            GLib.idle_add(lambda: (self._render_chart(), False)[1])

    def _render_chart(self):
        kind = CHART_KINDS[self.chart_kind.get_active()][0]
        now = time.time()
        series = build_series(self._timeline, kind)
        cpu_note = ""
        if kind == "cpu":
            hist_has_cpu = any(_cpu1(s.get("cpu")) is not None for s in self._timeline)
            rec = getattr(self.app, "stats_recorder", None)
            if rec is not None:
                series = build_series(rec.merge_into(self._timeline), kind)
            if not hist_has_cpu:
                cpu_note = (" · CPU is not kept in this server's history (NeDB/MongoDB), showing the "
                            "5-minute samples this app recorded while running, like the web UI")
        # The window starts at now - range (client clock, like the web UI's x.min) but ENDS at the
        # newest sample if that is later: a server clock slightly ahead of ours must not hide the
        # most recent samples (e.g. the only CPU samples right after a server upgrade).
        newest = max((t for _n, _c, pts in series for t, v in pts if v is not None), default=now)
        self.chart.set_data(series, now - self._hours() * 3600, max(now, newest), Y_TITLES[kind],
                            stacked=kind in ("in", "out"), log=self.chart_log.get_active(),
                            empty_text="No samples in this range. The server records one every 5 minutes.")
        t0 = now - self._hours() * 3600
        n = sum(1 for s in self._timeline if (_epoch(s.get("time")) or 0) >= t0)
        with_data = len({t for _n, _c, pts in series for t, v in pts if v is not None and t >= t0})

        info = f"{n} sample{'s' if n != 1 else ''}"
        if with_data < n:
            what = {"cpu": "CPU", "in": "traffic", "out": "traffic"}.get(kind, "chart")
            info += f" · {with_data} with {what} data"
        self.chart_info.set_text(info + (cpu_note or " · hover the chart for values"))
        self.chart_info.set_tooltip_text(self.chart_info.get_text())

    def _download_csv(self):
        ch = Gtk.FileChooserNative.new("Save data points", self.get_toplevel(), Gtk.FileChooserAction.SAVE,
                                       "_Save", "_Cancel")
        ch.set_current_name("ServerStats.csv")
        ch.set_do_overwrite_confirmation(True)
        if ch.run() != Gtk.ResponseType.ACCEPT:
            ch.destroy()
            return
        dest = ch.get_filename()
        ch.destroy()
        cols = ["time", "conn.agent", "conn.users", "conn.usersessions", "conn.relaysession", "conn.intelamt",
                "conn.intelamtcira", "mem.external", "mem.heapused", "mem.heaptotal", "mem.rss",
                "cpu.load1", "cpu.load5", "cpu.load15", "traffic.in.mb", "traffic.out.mb"]
        lines = [",".join(cols)]
        for s in sorted(self._timeline, key=lambda s: _epoch(s.get("time")) or 0):
            t = _epoch(s.get("time"))
            if t is None:
                continue
            c, m, cpu = s.get("conn") or {}, s.get("mem") or {}, s.get("cpu") or []
            tr = s.get("traffic") or {}
            row = [time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)),
                   c.get("ca"), c.get("cu"), c.get("us"), c.get("rs"), c.get("am"), c.get("amc"),
                   m.get("external"), m.get("heapUsed"), m.get("heapTotal"), m.get("rss")]
            row += [(cpu[i] if isinstance(cpu, list) and len(cpu) > i else
                     cpu.get(str(i), "") if isinstance(cpu, dict) else "") for i in range(3)]
            row += [round(sum(_traffic_values(tr, True)), 4) if tr else "",
                    round(sum(_traffic_values(tr, False)), 4) if tr else ""]
            lines.append(",".join("" if v is None else str(v) for v in row))
        try:
            with open(dest, "w") as f:
                f.write("\r\n".join(lines) + "\r\n")
            self.chart_info.set_text(f"Saved {len(lines) - 1} samples to {os.path.basename(dest)}")
        except OSError as ex:
            ui.message(self.get_toplevel(), "Cannot save file", str(ex), Gtk.MessageType.ERROR)
    # ---- Console ----------------------------------------------------------------
    def _build_console(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if not self.full_admin:
            l = Gtk.Label(label="The server console is only available to full administrators.")
            l.get_style_context().add_class("dim-label")
            box.pack_start(l, True, True, 0)
            self.console_view = None
            return box
        hint = Gtk.Label(label="MeshCentral server console: type “help” for the list of commands.",
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

    # ---- Trace ---------------------------------------------------------------------
    # {action:'traceinfo', traceSources:[...]} sets the server-wide trace sources (full admins only;
    # [] = off). Every full-admin session then receives {action:'trace', source, args, time}. The
    # current sources arrive at sign-in and as event {action:'traceinfo'} whenever anyone changes them.
    def _build_trace(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=16, margin_top=4, spacing=8)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>My Server Tracing</span>")
        box.pack_start(title, False, False, 0)
        self._trace = []                                  # newest first
        if not self.full_admin:
            l = Gtk.Label(label="Server tracing is only available to full administrators.")
            l.get_style_context().add_class("dim-label")
            box.pack_start(l, True, True, 0)
            self.trace_tree = None
            return box
        bar = Gtk.Box(spacing=8)
        b = Gtk.Button(label="Tracing\u2026", image=Gtk.Image.new_from_icon_name("system-search-symbolic",
                       Gtk.IconSize.BUTTON), always_show_image=True)
        b.set_tooltip_text("Choose which server components to trace")
        b.connect("clicked", lambda *_: self._trace_dialog())
        bar.pack_start(b, False, False, 0)
        self.trace_status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        bar.pack_start(self.trace_status, True, True, 0)
        dl = Gtk.Button.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON)
        dl.set_tooltip_text("Download trace (.csv)")
        dl.connect("clicked", lambda *_: self._trace_download())
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda *_: self._trace_clear())
        self.trace_limit = Gtk.ComboBoxText()
        for n in TRACE_LIMITS:
            self.trace_limit.append_text(f"Last {n}")
        self.trace_limit.set_active(0)
        self.trace_limit.connect("changed", lambda *_: self._trace_trim())
        for w in (dl, clear, self.trace_limit, Gtk.Label(label="Show")):
            bar.pack_end(w, False, False, 0)
        box.pack_start(bar, False, False, 0)
        # time, SOURCE, message, index into self._trace
        self.trace_store = Gtk.ListStore(str, str, str, int)   # column 3 = stable event id
        self._trace_seq = 0
        self.trace_tree = Gtk.TreeView(model=self.trace_store, enable_search=True, search_column=2)
        for i, (t, expand) in enumerate((("Time", False), ("Source", False), ("Message", True))):
            self.trace_tree.append_column(ui.text_column(t, i, expand))
        ui.row_tooltip(self.trace_tree, 2)
        self.trace_tree.connect("row-activated", lambda tv, path, _c: self._trace_show(path))
        box.pack_start(ui.scrolled(self.trace_tree), True, True, 0)
        self.trace_hint = Gtk.Label(xalign=0, wrap=True)
        self.trace_hint.get_style_context().add_class("dim-label")
        box.pack_start(self.trace_hint, False, False, 0)
        self._trace_status(self.ctrl.tracesources)
        return box

    def _trace_status(self, sources):
        if self.trace_tree is None:
            return
        sources = sources or []
        names = [TRACE_NAMES.get(s, s) for s in sources]
        if sources:
            self.trace_status.set_markup("<b>Active:</b> " + GLib.markup_escape_text(", ".join(names)))
            self.trace_hint.set_text("Tracing is server-wide: every full administrator receives these messages, "
                                     "and it stays on until switched off (Tracing\u2026 \u2192 Delete). Double-click a "
                                     "line for details.")
        else:
            self.trace_status.set_markup("<span alpha='60%'>None</span>")
            self.trace_hint.set_text("Tracing is off. Use Tracing\u2026 to choose server components.")
        self.trace_status.set_tooltip_text(", ".join(names) or "None")
        self._trace_sources = list(sources)

    def _on_traceinfo(self, msg):
        self._trace_status(msg.get("traceSources"))

    def _on_trace_event(self, msg):
        ev = msg.get("event") or {}
        if ev.get("action") == "traceinfo":
            self._trace_status(ev.get("traceSources"))

    @staticmethod
    def _trace_text(args):
        return ", ".join(json.dumps(a) if isinstance(a, (dict, list)) else str(a) for a in (args or []))

    def _on_trace(self, msg):
        if self.trace_tree is None:
            return
        self._trace_seq += 1
        msg = dict(msg, _id=self._trace_seq)
        self._trace.insert(0, msg)
        t = msg.get("time")
        ts = time.strftime("%H:%M:%S", time.localtime(t / 1000)) if isinstance(t, (int, float)) else ""
        self.trace_store.prepend([ts, str(msg.get("source") or "").upper(),
                                  self._trace_text(msg.get("args")).replace("\n", " "), self._trace_seq])
        self._trace_trim()

    def _trace_trim(self):
        limit = TRACE_LIMITS[max(0, self.trace_limit.get_active())]
        del self._trace[limit:]
        keep = {e["_id"] for e in self._trace}
        it = self.trace_store.get_iter_first()
        while it is not None:
            nxt = self.trace_store.iter_next(it)
            if self.trace_store[it][3] not in keep:
                self.trace_store.remove(it)
            it = nxt

    def _trace_clear(self):
        self._trace = []
        self.trace_store.clear()

    def _trace_show(self, path):
        eid = self.trace_tree.get_model()[path][3]          # works whatever the sort order
        e = next((x for x in self._trace if x["_id"] == eid), None)
        if e is None:
            return
        parts = [json.dumps(a, indent=2) if isinstance(a, (dict, list)) else str(a) for a in (e.get("args") or [])]
        self._text_dialog(f"Server trace \u2014 {str(e.get('source') or '').upper()}", "\n\n".join(parts))

    def _trace_dialog(self):
        d = Gtk.Dialog(title="Server Tracing", transient_for=self.get_toplevel(), modal=True)
        d.set_default_size(380, 520)
        area = d.get_content_area()
        area.set_border_width(10)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        checks = {}
        for group, items in TRACE_GROUPS:
            h = Gtk.Label(xalign=0, margin_top=8)
            h.set_markup(f"<b>{GLib.markup_escape_text(group)}</b>")
            inner.pack_start(h, False, False, 0)
            inner.pack_start(Gtk.Separator(), False, False, 2)
            for key, name in items:
                cb = Gtk.CheckButton(label=name, active=key in self._trace_sources)
                if key in ("httpheaders", "authlog"):
                    cb.set_tooltip_text("May include sensitive data (headers, cookies, user names)")
                checks[key] = cb
                inner.pack_start(cb, False, False, 0)
        area.pack_start(ui.scrolled(inner), True, True, 0)
        d.add_button("Delete", 2).get_style_context().add_class("destructive-action")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("OK", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        d.show_all()
        r = d.run()
        chosen = [k for k, cb in checks.items() if cb.get_active()]
        d.destroy()
        if r == Gtk.ResponseType.OK:
            self.ctrl.send({"action": "traceinfo", "traceSources": chosen})
        elif r == 2:
            self.ctrl.send({"action": "traceinfo", "traceSources": []})

    def _trace_download(self):
        ch = Gtk.FileChooserNative.new("Save server trace", self.get_toplevel(), Gtk.FileChooserAction.SAVE,
                                       "_Save", "_Cancel")
        ch.set_current_name("servertrace.csv")
        ch.set_do_overwrite_confirmation(True)
        if ch.run() != Gtk.ResponseType.ACCEPT:
            ch.destroy()
            return
        dest = ch.get_filename()
        ch.destroy()
        q = lambda v: '"' + str(v).replace('"', '""') + '"'
        lines = ["time,source,message"]
        for e in reversed(self._trace):                   # oldest first in the file
            t = e.get("time")
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t / 1000)) if isinstance(t, (int, float)) else ""
            lines.append(",".join((q(ts), q(e.get("source") or ""), q(self._trace_text(e.get("args"))))))
        try:
            with open(dest, "w") as f:
                f.write("\r\n".join(lines) + "\r\n")
        except OSError as ex:
            ui.message(self.get_toplevel(), "Cannot save file", str(ex), Gtk.MessageType.ERROR)

    # ---- lifecycle ----------------------------------------------------------------
    def on_shown(self):
        if self._started:
            return
        self._started = True
        self._render_warnings(self.ctrl.serverwarnings)
        for action, cb in (("serverstats", self._on_stats), ("servertimelinestats", self._on_timeline),
                           ("serverconsole", self._on_console), ("serverwarnings", self._on_warnings),
                           ("event", self._on_live_sample), ("trace", self._on_trace),
                           ("traceinfo", self._on_traceinfo), ("event", self._on_trace_event)):
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
        # Listen for the ACTION, not the responseid: the server answers {action:'serverversion'}
        # with {action:'serverversion', tags} without needing an echo, so this works on older
        # releases too. The server asks the npm registry, which can take a while.
        self._progress_show("Checking the server version… (the server asks the npm registry)", 0, 0)
        pulse = GLib.timeout_add(200, lambda: (self.progress.pulse(), True)[1])

        def stop_pulse():
            GLib.source_remove(pulse)
            self.progress.hide()

        def timeout():
            stop_pulse()
            ui.message(self.get_toplevel(), "No answer from the server",
                       "The server did not report its version within 30 seconds. It may be unable to reach "
                       "the npm registry, or version checks are disabled for this domain (myserver.upgrade).")

        def got(msg):
            stop_pulse()
            self._version_dialog(msg)
        self._once("serverversion", got, timeout_s=30, on_timeout=timeout)
        self.ctrl.send({"action": "serverversion"})

    def _version_dialog(self, msg):
        if msg.get("result") not in (None, "OK"):
            ui.message(self.get_toplevel(), "Cannot check the server version", str(msg.get("result")))
            return
        tags = msg.get("tags") or {}
        cur, latest, stable = tags.get("current"), tags.get("latest"), tags.get("stable")
        if not cur:
            ui.message(self.get_toplevel(), "Cannot check the server version",
                       "The server could not determine the available versions (npm registry unreachable?).")
            return
        d = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                              message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.NONE,
                              text=f"MeshCentral {cur}")
        d.format_secondary_text(f"Current version: {cur}\nStable version: {stable}\nLatest version: {latest}")
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
