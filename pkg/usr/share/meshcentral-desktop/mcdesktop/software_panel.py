# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Device "Software" page like the web UI's (p18, MeshCentral 1.2.x): installed applications, with
search, Microsoft Store apps on Windows and uninstall for full administrators.

Ground truth (meshuser.js / agents/meshcore.js 1.2.5, verified on the rig):
- {action:'software', nodeid, type:'installedapps'|'installedstoreapps'} → the agent answers
  {action:'software', nodeid, value:<JSON string>}: an array of {name, version, publisher, date,
  location, arch, scope?, uninstall?, packageFullName?}, or {error} / {success:false, error}.
  A Linux agent took ~25 s for 4154 dpkg packages (700 KB). Store apps: Windows only.
- Do NOT send a responseid: the server first answers {result:'Denied'} to ANY request carrying one
  (a bug in its handler) and then routes the command anyway.
- Uninstall: type 'uninstallapp' value base64(utf-8 command), 'uninstallstoreapp' value '"<name>"'
  (quotes escaped); the agent answers {success} or {error}. Only offered with full device rights,
  like the web UI. The web UI shows the tab with rights 8 and not "no software" (0x800000).
"""
import base64
import json

from gi.repository import Gtk, GLib

from . import ui, rights

LOAD_TIMEOUT_S = 120


class SoftwarePanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.node = app, node
        self._started = False
        self._loading = None                 # 'installedapps' | 'installedstoreapps' | None
        self._timer = None
        self.data = {"desktop": [], "store": []}

        bar = Gtk.Box(spacing=6, margin=8)
        self.refresh_btn = Gtk.Button(label="Refresh", image=Gtk.Image.new_from_icon_name(
            "view-refresh-symbolic", Gtk.IconSize.BUTTON), always_show_image=True)
        self.refresh_btn.connect("clicked", lambda *_: self.load())
        bar.pack_start(self.refresh_btn, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text="Search software…", width_chars=28)
        self.search.connect("search-changed", lambda *_: self.render())
        bar.pack_start(self.search, False, False, 0)
        self.store_chk = Gtk.CheckButton(label="Show Store Apps")
        self.store_chk.connect("toggled", self._toggle_store)
        bar.pack_start(self.store_chk, False, False, 0)
        self.uninstall_btn = Gtk.Button(label="Uninstall…", sensitive=False)
        self.uninstall_btn.get_style_context().add_class("destructive-action")
        self.uninstall_btn.connect("clicked", lambda *_: self.uninstall_selected())
        bar.pack_start(self.uninstall_btn, False, False, 0)
        self.spinner = Gtk.Spinner()
        bar.pack_start(self.spinner, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        bar.pack_start(self.status, True, True, 4)
        self.pack_start(bar, False, False, 0)

        # desktop: name, version, publisher, date, location, uninstall command, tooltip
        self.dstore = Gtk.ListStore(str, str, str, str, str, str, str)
        self.dtree, dbox, self.dtitle = self._table(self.dstore, (("Name", 0, True), ("Version", 1, False),
                                                                   ("Publisher", 2, True), ("Install Date", 3, False),
                                                                   ("Location", 4, False)))
        # store: name, version, publisher, scope, uninstall name, package full name, tooltip
        self.sstore = Gtk.ListStore(str, str, str, str, str, str, str)
        self.stree, self.sbox, self.stitle = self._table(self.sstore, (("Name", 0, True), ("Version", 1, False),
                                                                        ("Package", 2, True), ("Scope", 3, False)))
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.pack1(dbox, True, False)
        paned.pack2(self.sbox, True, False)
        self.pack_start(paned, True, True, 0)
        self.show_all()
        self.sbox.hide()
        win = ui.is_windows(node)
        self.store_chk.set_visible(win)               # the agent only lists Store apps on Windows
        self.store_chk.set_no_show_all(not win)
        self.status.set_text("Click Refresh to load installed software")

    def _table(self, store, cols):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=8, margin_end=8, margin_bottom=8)
        title = Gtk.Label(xalign=0)
        box.pack_start(title, False, False, 0)
        tree = Gtk.TreeView(model=store, enable_search=True, search_column=0)
        # Name and Publisher both shrink with "…" (publishers are long e-mail addresses), so
        # Version / Install Date / Location always stay on screen
        for t, col, expand in cols:
            c = ui.text_column(t, col, expand, sort_col=col)
            if t == "Version":                        # some versions are very long: cap the width
                from gi.repository import Pango
                c.get_cells()[0].set_property("ellipsize", Pango.EllipsizeMode.END)
                c.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
                c.set_fixed_width(150)
            tree.append_column(c)
        ui.row_tooltip(tree, 6)
        tree.get_selection().connect("changed", lambda *_: self._sel_changed())
        box.pack_start(ui.scrolled(tree), True, True, 0)
        return tree, box, title

    @property
    def ctrl(self):
        return self.app.ctrl

    def _full(self):
        return rights.node_rights(self.ctrl, getattr(self.app, "meshes", None) or {}, self.node) == rights.FULL

    # ---- panel contract ----------------------------------------------------------------------
    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.ctrl.on("software", self._on_software)
        self.load()                                   # the web UI also loads when the tab opens

    def on_node_update(self, node):
        was_online = ui.is_online(self.node)
        self.node = node
        if self._started and ui.is_online(node) and not was_online and not self.data["desktop"]:
            self.load()                               # device came back: load like the web UI

    def teardown(self):
        if self._started:
            self.ctrl.off("software", self._on_software)
        self._stop_timer()

    # ---- loading ------------------------------------------------------------------------------
    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def _busy(self, kind, text):
        self._loading = kind
        self.status.set_text(text)
        self.refresh_btn.set_sensitive(kind is None)
        (self.spinner.start if kind else self.spinner.stop)()
        self._stop_timer()
        if kind:
            self._timer = GLib.timeout_add_seconds(LOAD_TIMEOUT_S, self._on_timeout)

    def _on_timeout(self):
        self._timer = None
        self._busy(None, f"No answer from the agent after {LOAD_TIMEOUT_S} s")
        return False

    def load(self):
        if self._loading:
            return
        if not ui.is_online(self.node):
            self.status.set_text("Device is offline.")
            return
        self.data = {"desktop": [], "store": []}
        self.render()
        self._busy("installedapps", "Loading installed software… (can take a minute)")
        self.ctrl.send({"action": "software", "nodeid": self.node["_id"], "type": "installedapps"})

    def _load_store(self):
        self._busy("installedstoreapps", "Loading store apps…")
        self.ctrl.send({"action": "software", "nodeid": self.node["_id"], "type": "installedstoreapps"})

    def _toggle_store(self, chk):
        if chk.get_active() and not self.data["store"] and not self._loading and ui.is_online(self.node):
            self._load_store()
        else:
            self.render()

    def _on_software(self, msg):
        if msg.get("nodeid") not in (None, self.node["_id"]) or msg.get("result") == "Denied":
            return
        value = msg.get("value")
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            data = None
        kind = self._loading
        if isinstance(data, list):
            self._busy(None, "")
            if kind == "installedstoreapps":
                self.data["store"] = data
            else:
                self.data["desktop"] = data
                if self.store_chk.get_active():
                    self._load_store()
            self.render()
        elif isinstance(data, dict) and data.get("error"):
            self._busy(None, "")
            self.status.set_text(f"Error: {data['error']}")
            self.render(keep_status=True)
        elif isinstance(data, dict) and data.get("success"):
            self.status.set_text("Done. Click Refresh to update the list.")

    # ---- display ------------------------------------------------------------------------------
    def _match(self, app, term):
        return not term or term in (app.get("name") or "").lower() or term in (app.get("publisher") or "").lower()

    def render(self, keep_status=False):
        term = self.search.get_text().strip().lower()
        key = lambda a: (a.get("name") or "").lower()
        desk = sorted((a for a in self.data["desktop"] if isinstance(a, dict) and self._match(a, term)), key=key)
        store = sorted((a for a in self.data["store"] if isinstance(a, dict) and self._match(a, term)), key=key)
        self.dstore.clear()
        for a in desk:
            loc = (a.get("location") or "-") + (f" ({a['arch']})" if a.get("arch") else "")
            self.dstore.append([a.get("name") or "-", a.get("version") or "-", a.get("publisher") or "-",
                                a.get("date") or "-", loc, a.get("uninstall") or "", _tip(a)])
        self.sstore.clear()
        for a in store:
            scope = a.get("scope") or ""
            sc = ", ".join(x for x in ("User", "System", "Prov") if x in scope) or "-"
            self.sstore.append([a.get("name") or "-", a.get("version") or "-", a.get("publisher") or "-", sc,
                                a.get("name") if a.get("uninstall") else "", a.get("packageFullName") or "",
                                _tip(a, a.get("packageFullName"))])
        self.dtitle.set_markup(f"<b>Desktop Applications ({len(desk)})</b>")
        self.stitle.set_markup(f"<b>Microsoft Store Apps ({len(store)})</b>")
        show_store = self.store_chk.get_active()
        self.sbox.set_visible(show_store)
        if not self._loading and not keep_status and (self.data["desktop"] or self.data["store"]):
            s = f"Desktop: {len(desk)}/{len(self.data['desktop'])}"
            if show_store:
                s += f" | Store: {len(store)}/{len(self.data['store'])}"
            self.status.set_text(s)
        self._sel_changed()

    def _selected(self):
        for tree, kind in ((self.dtree, "desktop"), (self.stree, "store")):
            model, it = tree.get_selection().get_selected()
            if it is not None and model[it][4 if kind == "store" else 5]:
                return kind, model[it]
        return None, None

    def _sel_changed(self):
        kind, _row = self._selected()
        full = self._full()
        self.uninstall_btn.set_sensitive(bool(kind) and full and ui.is_online(self.node))
        self.uninstall_btn.set_tooltip_text(None if full else "Uninstalling needs full rights on this device")

    def uninstall_selected(self):
        kind, row = self._selected()
        if not kind or not self._full():
            return
        top = self.get_toplevel()
        if kind == "desktop":
            cmd = row[5]
            if not ui.confirm(top, "Uninstall this software?", f"{row[0]}\n\n{cmd}\n\nA silent uninstall will be "
                              "performed.", "Uninstall", destructive=True):
                return
            value = base64.b64encode(cmd.encode("utf-8")).decode()
            self.ctrl.send({"action": "software", "nodeid": self.node["_id"], "type": "uninstallapp", "value": value})
            self.status.set_text("Uninstall started. Click Refresh to update.")
        else:
            name = row[4]
            if not ui.confirm(top, "Remove this Store app?", name, "Remove", destructive=True):
                return
            self.ctrl.send({"action": "software", "nodeid": self.node["_id"], "type": "uninstallstoreapp",
                            "value": '"' + name.replace('"', '\\"') + '"'})
            self.status.set_text("Remove command sent. Click Refresh to update.")


def _tip(app, extra=None):
    """Hover text: the full name, version and publisher (the columns may be cut with "…")."""
    rows = [app.get("name") or "-", "Version: " + (app.get("version") or "-"), app.get("publisher") or ""]
    if extra:
        rows.append(extra)
    return "\n".join(r for r in rows if r)
