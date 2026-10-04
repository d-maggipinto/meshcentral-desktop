# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Dialogs of the remote desktop toolbar, like the web UI's desktop bar:
- notification (toast / message box / alert box), open a web address, Tools (processes and services).

Messages (same as the web UI): toast {action:'toast', nodeids, title, msg}; message box {action:'msg',
type:'messagebox', nodeid, title, msg, timeout ms}; alert box {type:'alertbox'}; web address {type:'openUrl', url}.
"""
from gi.repository import Gtk, GLib

from . import device_list as dl, ui
from .tools_panel import ProcessesPanel, ServicesPanel


def notify_dialog(parent, ctrl, node):
    """Web UI deviceToastFunction: toast, message box (with a time limit) or the old-style alert box."""
    d, area, ok = dl._dialog(parent, "Display a notification", "Send", 480)
    kind = dl._combo([(2, "Toast notification"), (1, "Message box"), (3, "Alert box")])
    title = Gtk.Entry(placeholder_text="Title", max_length=256)
    tv, fr = dl._text_view("", 120)
    tmo = dl._combo([(2, "Show for 2 minutes (default)"), (10, "Show for 10 minutes"), (30, "Show for 30 minutes"),
                     (60, "Show for 60 minutes"), (0, "Show until dismissed by the user")])
    tmo_note = Gtk.Label(label="Only applies to message boxes.", xalign=0)
    tmo_note.get_style_context().add_class("dim-label")
    for w in (kind, title, fr, tmo, tmo_note):
        area.pack_start(w, w is fr, w is fr, 0)
    kind.connect("changed", lambda *_: tmo.set_sensitive(kind.get_active_id() == "1"))
    tmo.set_sensitive(False)
    ok.set_sensitive(False)
    tv.get_buffer().connect("changed", lambda *_: ok.set_sensitive(bool(dl._buf_text(tv).strip())))
    if dl._run(d):
        msg, t = dl._buf_text(tv), title.get_text().strip() or "MeshCentral"
        op = kind.get_active_id()
        if op == "2":
            ctrl.send({"action": "toast", "nodeids": [node["_id"]], "title": t, "msg": msg})
        elif op == "1":
            ctrl.send({"action": "msg", "type": "messagebox", "nodeid": node["_id"], "title": t, "msg": msg,
                       "timeout": int(tmo.get_active_id()) * 60000})
        else:
            ctrl.send({"action": "msg", "type": "alertbox", "nodeid": node["_id"], "title": t, "msg": msg})
    d.destroy()


def valid_url(text):
    """What the web UI accepts: http:// or https:// followed by something."""
    x = (text or "").strip().lower()
    return (x.startswith("http://") and len(x) > 7) or (x.startswith("https://") and len(x) > 8)


def open_url_dialog(parent, ctrl, node, on_result=None, sender=None):
    """sender(url): open it another way (Linux devices: in the user's session); default = the agent's openUrl."""
    """Web UI deviceUrlFunction: the agent opens the page in the remote user's browser."""
    d, area, ok = dl._dialog(parent, "Open a web address on the remote computer", "Open", 480)
    entry = Gtk.Entry(placeholder_text="https://example.com", activates_default=True)
    area.pack_start(entry, False, False, 0)
    ok.set_sensitive(False)
    entry.connect("changed", lambda *_: ok.set_sensitive(valid_url(entry.get_text())))
    url = entry.get_text().strip() if dl._run(d) and valid_url(entry.get_text()) else None
    d.destroy()
    if url and sender:
        sender(url)
    elif url:
        if on_result:
            _watch_open_url(ctrl, node, on_result)
        ctrl.send({"action": "msg", "type": "openUrl", "nodeid": node["_id"], "url": url})


def _watch_open_url(ctrl, node, on_result):
    """The agent answers {type:'openUrl', success}: report it (the web UI ignores it)."""
    state = {"done": False}

    def reply(msg):
        if msg.get("type") != "openUrl" or state["done"]:
            return
        state["done"] = True
        ctrl.off("msg", reply)
        if msg.get("success"):
            on_result("The web address was opened on the remote computer")
        else:
            on_result("The remote computer could not open the web address" +
                      ("" if ui.is_windows(node) else
                       " (on Linux the agent's xdg-open must reach the user's desktop session)"))

    def timeout():
        if not state["done"]:
            state["done"] = True
            ctrl.off("msg", reply)
            on_result("No answer from the agent about the web address")
        return False
    ctrl.on("msg", reply)
    on_result("Opening the web address on the remote computer...")
    GLib.timeout_add_seconds(20, timeout)


class ToolsWindow(Gtk.Window):
    """Web UI desktop "Tools": the device's processes (double-click = details) and services next to the
    remote screen, in their own window so the screen stays visible."""
    _open = {}

    @classmethod
    def show_for(cls, app, node, parent=None):
        w = cls._open.get(node["_id"])
        if w is None:
            w = cls(app, node, parent)
        w.present()
        return w

    def __init__(self, app, node, parent=None):
        super().__init__(title=f"Tools - {node.get('name', '')}")
        self.set_default_size(560, 640)
        if parent is not None:
            self.set_transient_for(parent)
        self.nodeid = node["_id"]
        nb = Gtk.Notebook()
        self.panels = [ProcessesPanel(app, node), ServicesPanel(app, node)]
        for p, label in zip(self.panels, ("Processes", "Services")):
            nb.append_page(p, Gtk.Label(label=label))
        nb.connect("switch-page", lambda _nb, page, _n: page.on_shown())
        self.add(nb)
        ToolsWindow._open[self.nodeid] = self
        self.connect("destroy", self._on_destroy)
        self.show_all()
        self.panels[0].on_shown()

    def _on_destroy(self, *_):
        ToolsWindow._open.pop(self.nodeid, None)
        for p in self.panels:
            p.teardown()
