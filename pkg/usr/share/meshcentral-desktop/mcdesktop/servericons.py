# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""The signed-in server's own icons.

MeshCentral draws its device-type, menu and status icons from sprite sheets in its public /images/
folder, and a server can replace them (meshcentral-web/public/images/) to restyle its web UI. The app
reads the same files from the server it signs in to and cuts them the way the web UI's style sheet
does, so it shows the icons the server shows: a restyled server's own set, or MeshCentral's stock
icons. Until they have arrived (or when a file is missing or unusable) the app keeps its own icons.

The files are cached per server in the private data folder, so the next start shows them at once;
each sign-in fetches them again in the background and updates the window if they changed.

Icons are registered as GTK built-in icons under names that change with every set
("mcd-srv<N>-..."), because built-in icons cannot be replaced or removed once added.
"""
import hashlib
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GdkPixbuf, GLib, Gtk

# sprite file -> (cell size, cells); cells are cut left to right like the web UI's CSS offsets
SPRITES = {
    "icons16.png": (16, 8), "icons32.png": (32, 8), "icons64.png": (64, 8),      # device types 1..8
    "leftbar-64.png": (64, 6), "leftbar-128.png": (128, 6),                       # left menu
    "notify16.png": (16, 9), "notify24.png": (24, 9), "notify48.png": (48, 9),    # status badges
    "images16.png": (16, 9),                                                      # small UI (user group)
}
# web UI: node.icon 1 desktop, 2 laptop, 3 phone, 4 server, 5 disk / NAS, 6 router, 7 board, 8 virtual machine
DEVICE_TYPES = 8
# leftbar cells (style.css .lb1 .. .lb6) -> the app's navigation pages
NAV = {"account": 0, "devices": 1, "events": 2, "files": 3, "users": 4, "server": 5}
# notify16/24/48 cells (.NotifyIconTiny1 .. 9)
STATUS = {"success": 0, "error": 1, "warning": 2, "blocked": 3, "info": 4, "question": 5,
          "shield-warning": 6, "shield-ok": 7, "shield-error": 8}
USER_GROUP_CELL = 8                       # images16.png .m4 (user group in the web UI)
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_S = 15

_gen = 0


def _cut(pix, cell, n):
    """Cells of a horizontal sprite; None for a sheet that does not have the expected shape."""
    if pix is None or pix.get_height() != cell or pix.get_width() < cell * n:
        return None
    return [pix.new_subpixbuf(i * cell, 0, cell, cell).copy() for i in range(n)]


def _blank(p):
    """A transparent cell (a slot the server's sheet leaves empty)."""
    if not p.get_has_alpha():
        return False
    data, stride, ch = p.get_pixels(), p.get_rowstride(), p.get_n_channels()
    return all(data[y * stride + x * ch + 3] < 16 for y in range(p.get_height()) for x in range(p.get_width()))


def _rows(p):
    data, stride, ch = p.get_pixels(), p.get_rowstride(), p.get_n_channels()
    return data, stride, ch


def _trimmed(p, pad=0.1):
    """The drawn part of a cell, centred on a square with a small margin (menu cells have wide empty
    borders: at 24 px the glyph would be tiny)."""
    if not p.get_has_alpha():
        return p
    data, stride, ch = _rows(p)
    w, h = p.get_width(), p.get_height()
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if data[y * stride + x * ch + 3] > 16:
                xs.append(x)
                ys.append(y)
    if not xs:
        return p
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    side = max(x1 - x0, y1 - y0)
    side += max(2, int(side * pad * 2))
    out = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, side, side)
    out.fill(0)
    p.copy_area(x0, y0, x1 - x0, y1 - y0, out, (side - (x1 - x0)) // 2, (side - (y1 - y0)) // 2)
    return out


def _mono_colour(p):
    """(r, g, b) when every drawn pixel has (about) the same colour, else None."""
    if not p.get_has_alpha():
        return None
    data, stride, ch = _rows(p)
    px = [data[y * stride + x * ch: y * stride + x * ch + 3] for y in range(p.get_height())
          for x in range(p.get_width()) if data[y * stride + x * ch + 3] > 128]
    if not px:
        return None
    mean = [sum(c[i] for c in px) / len(px) for i in range(3)]
    if any(abs(c[i] - mean[i]) > 40 for c in px for i in range(3)):
        return None
    return tuple(int(m) for m in mean)


def _tinted(p, rgb):
    """Same shape, one colour (alpha kept)."""
    out = p.copy() if p.get_has_alpha() else p.add_alpha(False, 0, 0, 0)
    data, stride, ch = _rows(out)
    buf = bytearray(data)
    for y in range(out.get_height()):
        for x in range(out.get_width()):
            i = y * stride + x * ch
            buf[i:i + 3] = bytes(rgb)
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(buf)), GdkPixbuf.Colorspace.RGB, True, 8,
                                           out.get_width(), out.get_height(), stride)


def _light(rgb):
    return rgb is not None and (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 190


DARK_ON_LIGHT = (0x2b, 0x2b, 0x2b)       # a near-white menu set, redrawn for light themes


def _dimmed(p):
    """Offline look of a device icon (the web UI shows offline devices grey and faded)."""
    grey = p.copy()
    p.saturate_and_pixelate(grey, 0.0, False)
    out = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, p.get_width(), p.get_height())
    out.fill(0)
    grey.composite(out, 0, 0, p.get_width(), p.get_height(), 0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 110)
    return out


def _png_size(data):
    """(width, height) from the PNG header, before any decoding; None when it is not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _decode(data, cell=None, n=None):
    """PNG only. With a sprite's cell size and count: the declared size must fit that sheet, so a small
    file declaring a huge image (gigabytes once decoded) is refused before it is decoded."""
    if cell:
        size = _png_size(data)
        if size is None or size[1] != cell or not cell * n <= size[0] <= cell * 64:
            return None
    try:
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")       # PNG only, whatever the server says
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except GLib.Error:
        return None


class _SameServerRedirect(urllib.request.HTTPRedirectHandler):
    """Every redirect hop must stay on the server (https, same host and port): no requests elsewhere."""

    def __init__(self, base):
        super().__init__()
        p = urllib.parse.urlsplit(base)
        self.origin = (p.hostname, p.port or 443)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urllib.parse.urlsplit(newurl)
        if p.scheme != "https" or (p.hostname, p.port or 443) != self.origin:
            raise urllib.error.HTTPError(newurl, code, "redirect to another server refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ServerIcons:
    """One server's icon set. `name(...)` gives a GTK icon name, or the fallback while it is missing."""

    def __init__(self, server_url, cache_dir, ssl_context_factory):
        self.base = server_url.rstrip("/") + "/images/"
        self.host = urllib.parse.urlsplit(server_url).hostname or ""
        self.cache = os.path.join(cache_dir, "servericons",
                                  hashlib.sha256(server_url.encode("utf-8")).hexdigest()[:16])
        self.ssl_context_factory = ssl_context_factory   # called on the download thread, once
        self._ssl = None
        self.names = {}                   # (kind, key) -> registered icon name
        self.listeners = []               # called (on the GTK thread) when the set changed
        self._digest = None
        self._closed = False

    # ---- public ------------------------------------------------------------------------------
    def name(self, kind, key, fallback):
        return self.names.get((kind, key), fallback)

    def nav(self, page, fallback, light_theme):
        """Menu icon; on a light theme the dark copy of a near-white set."""
        if light_theme and ("nav-dark", page) in self.names:
            return self.names[("nav-dark", page)]
        return self.names.get(("nav", page), fallback)

    def device(self, icon, online=True, fallback="computer-symbolic"):
        """node.icon (1..8) -> icon name; offline devices get the faded variant."""
        try:
            i = int(icon or 1)
        except (TypeError, ValueError):
            i = 1
        i = i if 1 <= i <= DEVICE_TYPES else 1
        return self.names.get(("device" if online else "device-off", i), fallback)

    def start(self):
        """Use the cached set now, then fetch the server's current files in the background."""
        cached = self._read_cache()
        if cached:
            self._apply(cached)
        threading.Thread(target=self._fetch, daemon=True).start()

    def close(self):
        self._closed = True
        self.listeners = []

    # ---- loading -----------------------------------------------------------------------------
    def _read_cache(self):
        out = {}
        for f in SPRITES:
            try:
                with open(os.path.join(self.cache, f), "rb") as fh:
                    data = fh.read(MAX_BYTES + 1)
                if len(data) <= MAX_BYTES:
                    out[f] = data
            except OSError:
                pass
        return out

    def _get(self, fname):
        url = self.base + fname
        req = urllib.request.Request(url, headers={"User-Agent": "MeshCentralDesktop (icons)"})
        if self._ssl is None:
            self._ssl = self.ssl_context_factory()
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self._ssl),
                                             _SameServerRedirect(self.base))
        with opener.open(req, timeout=TIMEOUT_S) as r:
            final = urllib.parse.urlsplit(r.geturl())
            if final.scheme != "https" or final.hostname != self.host:    # no redirects elsewhere
                return None
            data = r.read(MAX_BYTES + 1)
        return data if 0 < len(data) <= MAX_BYTES and data[:8] == b"\x89PNG\r\n\x1a\n" else None

    def _fetch(self):
        got = {}
        for f in SPRITES:
            if self._closed:
                return
            try:
                data = self._get(f)
            except Exception:
                data = None
            if data:
                got[f] = data
        if not got or self._closed:
            return
        try:
            os.makedirs(self.cache, mode=0o700, exist_ok=True)
            for f, data in got.items():
                tmp = os.path.join(self.cache, f + ".tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, os.path.join(self.cache, f))
        except OSError:
            pass
        GLib.idle_add(lambda: (self._apply(got), False)[1])

    def _apply(self, files):
        """Cut the sheets and register the icons (GTK thread). No-op when nothing changed."""
        if self._closed:
            return
        digest = hashlib.sha256(b"".join(files.get(f, b"") for f in sorted(SPRITES))).hexdigest()
        if digest == self._digest:
            return
        self._digest = digest
        global _gen
        _gen += 1
        prefix = "mcd-srv%d-" % _gen
        names = {}
        cells = {f: _cut(_decode(files[f], *SPRITES[f]), *SPRITES[f]) if f in files else None for f in SPRITES}

        def register(kind, key, sprite_cells):
            """Every size the sheets have, plus the sizes the app displays (built-in icons are not
            scaled by GTK: a missing size would show the nearest one at its own size)."""
            name = "%s%s-%s" % (prefix, kind, key)
            have = {cl.get_width(): cl for cl in sprite_cells if cl is not None and not _blank(cl)}
            if not have:
                return
            for size in (16, 24, 32, 48, 64):
                if size not in have:
                    src = min((s for s in have if s >= size), default=max(have))
                    have[size] = have[src].scale_simple(size, size, GdkPixbuf.InterpType.HYPER)
            for size, cl in have.items():
                Gtk.IconTheme.add_builtin_icon(name, size, cl)
            names[(kind, key)] = name

        for i in range(1, DEVICE_TYPES + 1):
            sheets = [cells[f] for f in ("icons16.png", "icons32.png", "icons64.png") if cells[f]]
            register("device", i, [s[i - 1] for s in sheets])
            register("device-off", i, [_dimmed(s[i - 1]) for s in sheets])
        nav = {page: [_trimmed(cells[f][cell]) for f in ("leftbar-64.png", "leftbar-128.png") if cells[f]]
               for page, cell in NAV.items()}
        if cells["images16.png"]:
            nav["usergroups"] = [_trimmed(cells["images16.png"][USER_GROUP_CELL], 0.04)]
        # one-colour menu set (like a restyled dark sidebar): the Groups icon, from another sheet, gets the
        # same colour; a near-white set also gets a dark copy for light themes ("nav-dark")
        mono = [_mono_colour(v[-1]) for k, v in nav.items() if v and k != "usergroups"]
        colour = mono[0] if mono and all(m is not None and max(abs(m[i] - mono[0][i]) for i in range(3)) < 24
                                         for m in mono) else None
        for page, cl in nav.items():
            if colour and page == "usergroups":
                cl = [_tinted(c, colour) for c in cl]
            register("nav", page, cl)
            if _light(colour):
                register("nav-dark", page, [_tinted(c, DARK_ON_LIGHT) for c in cl])
        for st, cell in STATUS.items():
            register("status", st, [cells[f][cell] for f in ("notify16.png", "notify24.png", "notify48.png")
                                    if cells[f]])
        self.names = names
        for cb in list(self.listeners):
            try:
                cb()
            except Exception:
                pass


CURRENT = None                            # the signed-in server's set (App.on_login / sign_out)


def icon(kind, key, fallback):
    """Icon name from the current server's set, or the fallback."""
    return CURRENT.name(kind, key, fallback) if CURRENT else fallback


def nav_icon(page, fallback, widget):
    """Menu icon for a page; widget = any widget of the window (tells whether the theme is light)."""
    if not CURRENT:
        return fallback
    fg = widget.get_style_context().get_color(widget.get_style_context().get_state())
    return CURRENT.nav(page, fallback, (0.299 * fg.red + 0.587 * fg.green + 0.114 * fg.blue) < 0.5)


def device_icon(node, online, fallback):
    return CURRENT.device(node.get("icon"), online, fallback) if CURRENT else fallback


def listen(cb):
    """Call cb (GTK thread) whenever the current set changes; returns a function that stops it."""
    s = CURRENT
    if s is None:
        return lambda: None
    s.listeners.append(cb)
    return lambda: cb in s.listeners and s.listeners.remove(cb)
