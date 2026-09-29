"""Device information panels: General, Hardware, Network, Events, Notes.

Each is an embeddable Gtk.Box following the panel contract (see PANEL_CONTRACT.md):
__init__(self, app, node), on_shown(self) for lazy loading, teardown(self) for cleanup.
"""
import json

from gi.repository import Gtk, GLib, Pango

from . import ui


# MeshCentral agent type ids -> names (same table as the web UI's agentsStr).
AGENT_TYPES = ["Unknown", "Windows 32bit console", "Windows 64bit console", "Windows 32bit service",
               "Windows 64bit service", "Linux 32bit", "Linux 64bit", "MIPS", "XENx86", "Android", "Linux ARM",
               "macOS x86-32bit", "Android x86", "PogoPlug ARM", "Android", "Linux Poky x86-32bit",
               "macOS x86-64bit", "ChromeOS", "Linux Poky x86-64bit", "Linux NoKVM x86-32bit",
               "Linux NoKVM x86-64bit", "Windows MinCore console", "Windows MinCore service", "NodeJS",
               "ARM-Linaro", "ARMv6l / ARMv7l", "ARMv8 64bit", "ARMv6l / ARMv7l / NoKVM", "MIPS24KC (OpenWRT)",
               "Apple Silicon", "FreeBSD x86-64", "Unknown", "Linux ARM 64 bit", "Alpine Linux x86 64 Bit (MUSL)",
               "Assistant (Windows)", "Armada370 - ARM32/HF (libc/2.26)", "OpenWRT x86-64", "OpenBSD x86-64",
               "Unknown", "Unknown", "MIPSEL24KC (OpenWRT)", "ARMADA/CORTEX-A53/MUSL (OpenWRT)",
               "Windows ARM 64bit console", "Windows ARM 64bit service", "ARMVIRT32 (OpenWRT)", "RISC-V x86-64"]


def agent_description(node):
    """'Linux 64bit' (+ ' v<ver>' only when non-zero, like the web UI; modern agents report 0)."""
    agent = node.get("agent") or {}
    aid = agent.get("id")
    if aid is None:
        return ""
    name = AGENT_TYPES[aid] if 0 <= aid < len(AGENT_TYPES) else AGENT_TYPES[0]
    if agent.get("ver"):
        name += f" v{agent['ver']}"
    if aid == 14 and agent.get("core"):
        name = agent["core"]
    if agent.get("root") is False and ui.is_online(node):
        name += ", Restricted"
    return name


def _group_name(app, node):
    meshid = node.get("meshid")
    for src in (getattr(app, "meshes", None),
                getattr(getattr(app, "main_win", None), "meshes", None)):
        if isinstance(src, dict) and meshid in src:
            return src[meshid].get("name") or meshid
    return meshid or ""


class GeneralPanel(Gtk.Box):
    """Static key/value summary of a device. No network access needed."""

    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False

        self.grid = Gtk.Grid(row_spacing=8, column_spacing=16, margin=16)
        self.add(ui.scrolled(self.grid))
        self.refresh(node)

    def _row(self, row, key, value):
        klabel = Gtk.Label(label=key, xalign=0, yalign=0)
        klabel.get_style_context().add_class("dim-label")
        vlabel = Gtk.Label(label=str(value), xalign=0, yalign=0, selectable=True,
                           wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        vlabel.set_hexpand(True)
        self.grid.attach(klabel, 0, row, 1, 1)
        self.grid.attach(vlabel, 1, row, 1, 1)

    def refresh(self, node):
        self.node = node
        for child in self.grid.get_children():
            self.grid.remove(child)

        tags = node.get("tags")
        if isinstance(tags, list):
            tags = ", ".join(tags)
        agent = node.get("agent") or {}
        rows = [
            ("Name", node.get("name", "")),
            ("Status", "Online" if ui.is_online(node) else "Offline"),
            ("Operating system", ui.node_os(node)),
            ("Group", _group_name(self.app, node)),
            ("IP address", node.get("ip", "")),
            ("Host", node.get("host", "")),
            ("Tags", tags or ""),
            ("Description", node.get("desc", "")),
            ("Mesh agent", agent_description(node)),
            # The meaningful version on modern agents: the running core's build string.
            ("Agent core", agent.get("core", "")),
            ("Node ID", node.get("_id", "")),
        ]
        r = 0
        for key, value in rows:
            if value in (None, ""):
                continue
            self._row(r, key, value)
            r += 1
        self.grid.show_all()

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.refresh(self.node)

    def teardown(self):
        pass


class _JsonInfoPanel(Gtk.Box):
    """Shared base: a toolbar with Refresh + a scrolled ui.json_tree of a server reply."""

    reply_action = ""      # subclasses set these
    request_action = ""
    empty_text = "No information available."

    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._handler = None

        bar = Gtk.Box(spacing=6, margin=8)
        btn = Gtk.Button(label="Refresh",
                         image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                         always_show_image=True)
        btn.connect("clicked", lambda *_: self._request())
        bar.pack_start(btn, False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.placeholder = Gtk.Label(label="Loading…")
        self.placeholder.get_style_context().add_class("dim-label")
        self.body.pack_start(self.placeholder, True, True, 0)
        self.pack_start(self.body, True, True, 0)

    # subclasses override to pull the payload dict out of the message
    def _extract(self, message):
        raise NotImplementedError

    def _request_payload(self):
        return {"action": self.request_action, "nodeid": self.node["_id"]}

    def _on_reply(self, message):
        if message.get("nodeid") not in (None, self.node["_id"]):
            return
        data = self._extract(message)
        for child in self.body.get_children():
            self.body.remove(child)
        if isinstance(data, (dict, list)) and data:
            self.body.pack_start(ui.scrolled(ui.json_tree(data if isinstance(data, dict) else {"items": data})),
                                 True, True, 0)
        else:
            lbl = Gtk.Label(label=self.empty_text)
            lbl.get_style_context().add_class("dim-label")
            self.body.pack_start(lbl, True, True, 0)
        self.body.show_all()

    def _request(self):
        self.app.ctrl.send(self._request_payload())

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self._handler = self._on_reply
        self.app.ctrl.on(self.reply_action, self._handler)
        self._request()

    def teardown(self):
        if self._handler is not None:
            self.app.ctrl.off(self.reply_action, self._handler)
            self._handler = None


class HardwarePanel(_JsonInfoPanel):
    reply_action = "getsysinfo"
    request_action = "getsysinfo"
    empty_text = "No hardware information reported by the agent."

    def _request_payload(self):
        return {"action": "getsysinfo", "nodeid": self.node["_id"], "cache": True, "nodeinfo": True}

    def _extract(self, message):
        return message.get("hardware")


class NetworkPanel(_JsonInfoPanel):
    reply_action = "getnetworkinfo"
    request_action = "getnetworkinfo"
    empty_text = "No network information reported by the agent."

    def _extract(self, message):
        # Ground truth: interface data lives in message.netif2, an object keyed by
        # interface name whose values are lists of address entries. Older/other agents
        # may send netif as a JSON string instead, so fall back to that.
        data = message.get("netif2")
        if data:
            return data
        netif = message.get("netif")
        if isinstance(netif, str):
            try:
                netif = json.loads(netif)
            except Exception:
                netif = None
        return netif

    def _on_reply(self, message):
        if message.get("nodeid") not in (None, self.node["_id"]):
            return
        data = self._extract(message)
        for child in self.body.get_children():
            self.body.remove(child)
        self.body.pack_start(self._build_view(data), True, True, 0)
        self.body.show_all()

    def _build_view(self, data):
        if not isinstance(data, dict) or not data:
            lbl = Gtk.Label(label=self.empty_text)
            lbl.get_style_context().add_class("dim-label")
            return lbl
        # TreeStore grouped by interface name; each address entry is a child row with
        # its detail fields underneath.
        store = Gtk.TreeStore(str, str)
        detail_keys = ("mac", "type", "family", "address", "netmask", "gateway", "status")
        for ifname, entries in data.items():
            parent = store.append(None, [str(ifname), ""])
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        fam = entry.get("family") or entry.get("type") or ""
                        addr = entry.get("address") or entry.get("mac") or ""
                        label = f"{fam} {addr}".strip() or "(address)"
                        child = store.append(parent, [label, ""])
                        for k in detail_keys:
                            v = entry.get(k)
                            if v not in (None, ""):
                                store.append(child, [k, str(v)])
                        # include any extra keys not in the standard set
                        for k, v in entry.items():
                            if k not in detail_keys and v not in (None, ""):
                                store.append(child, [str(k), str(v)])
                    else:
                        store.append(parent, ["", str(entry)])
            elif isinstance(entries, dict):
                for k, v in entries.items():
                    store.append(parent, [str(k), "" if v is None else str(v)])
            else:
                store.append(parent, ["", str(entries)])
        tv = Gtk.TreeView(model=store, headers_visible=True)
        for i, title in enumerate(("Interface / Property", "Value")):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            tv.append_column(col)
        tv.expand_all()
        return ui.scrolled(tv)


class EventsPanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._handler = None

        bar = Gtk.Box(spacing=6, margin=8)
        btn = Gtk.Button(label="Refresh",
                         image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                         always_show_image=True)
        btn.connect("clicked", lambda *_: self._request())
        bar.pack_start(btn, False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.store = Gtk.ListStore(str, str, str)
        tv = Gtk.TreeView(model=self.store)
        for i, title in enumerate(("Time", "Action", "Message")):
            tv.append_column(ui.text_column(title, i, expand=(i == 2)))
        ui.row_tooltip(tv, 2)
        self.pack_start(ui.scrolled(tv), True, True, 0)

    def _on_reply(self, message):
        if "events" not in message:
            return
        self.store.clear()
        for e in message.get("events") or []:
            msg = e.get("msg")
            self.store.append([ui.fmt_time(e.get("time")), e.get("action", ""),
                               msg if isinstance(msg, str) else ""])

    def _request(self):
        self.app.ctrl.send({"action": "events", "nodeid": self.node["_id"], "limit": 200})

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self._handler = self._on_reply
        self.app.ctrl.on("events", self._handler)
        self._request()

    def teardown(self):
        if self._handler is not None:
            self.app.ctrl.off("events", self._handler)
            self._handler = None


class NotesPanel(Gtk.Box):
    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._handler = None

        bar = Gtk.Box(spacing=6, margin=8)
        save = Gtk.Button(label="Save",
                          image=Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON),
                          always_show_image=True)
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save)
        bar.pack_start(save, False, False, 0)
        reload_btn = Gtk.Button(label="Reload",
                                image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                                always_show_image=True)
        reload_btn.connect("clicked", lambda *_: self._request())
        bar.pack_start(reload_btn, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        bar.pack_start(self.status, True, True, 6)
        self.pack_start(bar, False, False, 0)

        hint = Gtk.Label(label="Notes for this device (visible to other administrators):",
                         xalign=0)
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_start(8)
        self.pack_start(hint, False, False, 0)

        # Editable so notes can be created even when the device has none yet.
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, editable=True)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        self.view.set_top_margin(8)
        scr = ui.scrolled(self.view)
        scr.set_min_content_height(240)
        frame = Gtk.Frame(margin=8)
        frame.add(scr)
        self.pack_start(frame, True, True, 0)
        self._saved_pending = False
        self.show_all()

    def _on_reply(self, message):
        if message.get("id") not in (None, self.node["_id"]):
            return
        notes = message.get("notes")
        self.view.get_buffer().set_text(notes if isinstance(notes, str) else "")
        if self._saved_pending:
            self._saved_pending = False
            self.status.set_text("Saved ✓")
        elif not getattr(self, "_readonly", False):
            self.status.set_text("")

    def _request(self):
        self.app.ctrl.send({"action": "getNotes", "id": self.node["_id"]})

    def _save(self, *_):
        buf = self.view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.app.ctrl.send({"action": "setNotes", "id": self.node["_id"], "notes": text})
        self.app.notify("Notes saved", self.node.get("name", ""))
        self.status.set_text("Saving…")
        # setNotes has no reply; re-read to confirm the round-trip.
        self._saved_pending = True
        GLib.timeout_add(300, lambda: (self._request(), False)[1])

    def on_shown(self):
        if self._started:
            return
        self._started = True
        from . import rights
        if not rights.node_caps(self.app.ctrl, self.app.meshes, self.node).notes:
            self.view.set_editable(False)
            for w in self.get_children()[0].get_children():
                if isinstance(w, Gtk.Button) and w.get_label() == "Save":
                    w.set_sensitive(False)
            self._readonly = True
            self.status.set_text("Read-only, your account may not edit notes on this device")
        self._handler = self._on_reply
        self.app.ctrl.on("getNotes", self._handler)
        self._request()

    def teardown(self):
        if self._handler is not None:
            self.app.ctrl.off("getNotes", self._handler)
            self._handler = None
