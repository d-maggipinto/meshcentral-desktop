# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Embeddable device-tool panels: Processes, Services and Agent Console.

Each panel talks to the agent over the control channel using the "msg" envelope
(ps / pskill / services / serviceStart|Stop|Restart / console), exactly like the
MeshCentral web UI's device tools.
"""
import json
import secrets

from gi.repository import Gtk, GLib, Pango

from . import ui


class _MsgPanel(Gtk.Box):
    """Common plumbing for panels that listen on the 'msg' action for one node."""

    def __init__(self, app, node):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self.nodeid = node["_id"] if node else None
        self._started = False
        self._listening = False

    def _listen(self):
        if not self._listening:
            self.app.ctrl.on("msg", self._on_msg)
            self._listening = True

    def _on_msg(self, message):
        if message.get("nodeid") not in (None, self.nodeid):
            return
        self._handle_msg(message)

    # subclasses override
    def _handle_msg(self, message):
        pass

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self._listen()
        self._first_load()

    def _first_load(self):
        pass

    def teardown(self):
        if self._listening:
            self.app.ctrl.off("msg", self._on_msg)
            self._listening = False


# psinfo fields the web UI shows, in its order (agents use camelCase, PascalCase or snake_case)
_PSINFO = [("processName", "Process name", None), ("machineName", "Machine name", None),
           ("cmd", "Command line", None), ("mainWindowTitle", "Window title", None),
           ("processUser", "User", None), ("processDomain", "Domain", None), ("startTime", "Start time", None),
           ("priorityBoostEnabled", "Priority boost", "bool"), ("sessionId", "Session ID", None),
           ("handleCount", "Handle count", None),
           ("privilegedProcessorTime", "Privileged processor time", "s"),
           ("totalProcessorTime", "Total processor time", "s"), ("userProcessorTime", "User processor time", "s"),
           ("nonpagedSystemMemorySize", "Non-paged memory", "b"), ("pagedMemorySize", "Paged memory", "b"),
           ("privateMemorySize", "Private memory", "b"), ("virtualMemorySize", "Virtual memory", "b"),
           ("workingSet", "Working set", "b"), ("peakWorkingSet", "Peak working set", "b"),
           ("peakPagedMemorySize", "Peak paged memory", "b"), ("peakVirtualMemorySize", "Peak virtual memory", "b")]


def process_details(value, cmd=""):
    """psinfo value -> [(label, text)] like the web UI's Process Details dialog."""
    if not isinstance(value, dict) or not value:
        return []
    if {"PPid", "State", "Tgid", "VmRSS"} & set(value):
        return _linux_details(value)
    norm = {}
    for k, v in value.items():                    # web UI: jsonToCamel
        key = str(k).replace("_", "")
        norm[key[:1].lower() + key[1:]] = v
    low = {k.lower(): v for k, v in norm.items()}
    if not low.get("cmd") and low.get("path"):
        norm["cmd"] = low["path"]
    user = low.get("username") or ""
    if not low.get("processuser") and "\\" in str(user):
        norm["processDomain"], norm["processUser"] = str(user).split("\\", 1)
    low = {k.lower(): v for k, v in norm.items()}
    out = []
    for key, label, kind in _PSINFO:
        v = low.get(key.lower())
        if v in (None, "", [], {}):
            continue
        if kind == "bool":
            v = "Enabled" if v else "Disabled"
        elif kind == "s":
            v = f"{v} seconds"
        elif kind == "b":
            try:
                v = ui.fmt_size(float(v))
            except (TypeError, ValueError):
                pass
        out.append((label, str(v)))
    # Windows agents send PowerShell Get-Process fields: the ones the web UI does not show, in plain words
    windows = [("description", "Description", None), ("company", "Company", None), ("product", "Product", None),
               ("fileversion", "File version", None), ("cpu", "Processor time", "s"), ("si", "Session ID", None),
               ("basepriority", "Base priority", None), ("ws", "Working set", "b"), ("pm", "Private memory", "b"),
               ("npm", "Non-paged memory", "b"), ("vm", "Virtual memory", "b")]
    shown = {label for label, _v in out}
    for key, label, kind in windows:
        v = low.get(key)
        if v in (None, "", [], {}) or label in shown:
            continue
        if kind == "s":
            v = f"{v} seconds"
        elif kind == "b":
            try:
                v = ui.fmt_size(float(v))
            except (TypeError, ValueError):
                pass
        out.append((label, str(v)))
    if low.get("name") and "Process name" not in shown:
        out.insert(0, ("Process name", str(low["name"])))
    return out


def _linux_details(value):
    """Linux agents send /proc/<pid>/status as is: the useful lines first, in plain words, then the rest."""
    out = []
    linux = [("Name", "Process name"), ("State", "State"), ("Pid", "Process ID"), ("PPid", "Parent process ID"),
             ("Uid", "User ID (real, effective, saved, fs)"), ("Gid", "Group ID (real, effective, saved, fs)"),
             ("Threads", "Threads"), ("VmRSS", "Memory in use (RSS)"), ("VmSize", "Virtual memory"),
             ("VmPeak", "Peak virtual memory"), ("VmHWM", "Peak memory in use"), ("VmSwap", "Swapped out")]
    raw = {str(k): v for k, v in value.items()}
    for key, label in linux:
        if raw.get(key) not in (None, ""):
            out.append((label, str(raw.pop(key)).replace("\t", "  ")))
    out += [(k, str(v).replace("\t", "  ")) for k, v in sorted(raw.items())]
    return out


class ProcessesPanel(_MsgPanel):
    def __init__(self, app, node):
        super().__init__(app, node)

        bar = Gtk.Box(spacing=6, margin=8)
        refresh = Gtk.Button(label="Refresh",
                             image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                             always_show_image=True)
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.pack_start(refresh, False, False, 0)
        self.kill_btn = Gtk.Button(label="Kill process",
                                   image=Gtk.Image.new_from_icon_name("process-stop-symbolic", Gtk.IconSize.BUTTON),
                                   always_show_image=True)
        self.kill_btn.get_style_context().add_class("destructive-action")
        self.kill_btn.connect("clicked", lambda *_: self.kill_selected())
        details = Gtk.Button(label="Details",
                             image=Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.BUTTON),
                             always_show_image=True)
        details.set_tooltip_text("Process details (also: double-click a process)")
        details.connect("clicked", lambda *_: self.details_selected())
        bar.pack_start(details, False, False, 0)
        bar.pack_start(self.kill_btn, False, False, 0)
        self.count = Gtk.Label(xalign=1)
        self.count.get_style_context().add_class("dim-label")
        bar.pack_end(self.count, False, False, 0)
        self.pack_start(bar, False, False, 0)

        # pid (int, for sort), pid_str, user, command
        self.store = Gtk.ListStore(int, str, str, str)
        self.tree = Gtk.TreeView(model=self.store, enable_search=True, search_column=3)
        for title, col, expand in (("PID", 1, False), ("User", 2, False), ("Command", 3, True)):
            self.tree.append_column(ui.text_column(title, col, expand, sort_col=0 if col == 1 else col))
        ui.row_tooltip(self.tree, 3)
        # double-click = details, like the web UI (it used to ask to kill the process)
        self.tree.connect("row-activated", lambda *_: self.details_selected())
        self._details = {}                       # pid -> (dialog, content box) waiting for psinfo
        self.pack_start(ui.scrolled(self.tree), True, True, 0)

    def _first_load(self):
        self.refresh()

    def refresh(self):
        self.count.set_text("Loading…")
        self.app.ctrl.send_node_msg(self.nodeid, "ps")

    def _handle_msg(self, message):
        if message.get("type") == "psinfo":
            self._show_details(message)
            return
        if message.get("type") != "ps":
            return
        try:
            procs = json.loads(message.get("value") or "{}")
        except Exception:
            return
        self.store.clear()
        for pid, info in procs.items():
            try:
                ipid = int(pid)
            except (TypeError, ValueError):
                continue
            if ipid == 0:
                continue
            self.store.append([ipid, str(ipid), info.get("user") or "", info.get("cmd") or ""])
        self.count.set_text(f"{len(self.store)} processes")

    def details_selected(self):
        model, it = self.tree.get_selection().get_selected()
        if it:
            self.show_details(model[it][0], model[it][3])

    def show_details(self, pid, cmd=""):
        """Web UI "Process Details": psinfo request, answered with a {name: value} object (Windows agents
        report much more than Linux ones)."""
        if pid in self._details:
            self._details[pid][0].present()
            return
        d = Gtk.Dialog(title=f"Process details, #{pid}", transient_for=self.get_toplevel(), modal=False)
        d.set_default_size(520, 420)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        d.connect("response", lambda *_: d.destroy())
        d.connect("destroy", lambda *_: self._details.pop(pid, None))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        box.pack_start(Gtk.Label(label="Requesting process details…", xalign=0), False, False, 0)
        d.get_content_area().pack_start(ui.scrolled(box), True, True, 0)
        self._details[pid] = (d, box, cmd)
        self._details_retries = getattr(self, "_details_retries", {})
        self._details_retries[pid] = 2
        d.show_all()
        self.app.ctrl.send_node_msg(self.nodeid, "psinfo", pid=pid)
        # Windows agents run PowerShell for this: it can take a while on a busy machine
        GLib.timeout_add_seconds(45, lambda: (self._details_timeout(pid), False)[1])

    def _details_timeout(self, pid):
        if pid in self._details and len(self._details[pid][1].get_children()) == 1:
            self._fill_details(pid, None)           # a late answer still fills the dialog

    def _show_details(self, message):
        try:
            pid = int(message.get("pid"))
        except (TypeError, ValueError):
            return
        if pid in self._details:
            value = message.get("value")
            # a busy Windows agent sometimes answers with an empty object: ask again before giving up
            if not value and self._details_retries.get(pid, 0) > 0:
                self._details_retries[pid] -= 1
                GLib.timeout_add(2000, lambda: (pid in self._details and
                                                self.app.ctrl.send_node_msg(self.nodeid, "psinfo", pid=pid), False)[1])
                return
            self._fill_details(pid, value)

    def _fill_details(self, pid, value):
        _d, box, cmd = self._details[pid]
        for c in box.get_children():
            box.remove(c)
        rows = process_details(value, cmd)
        if not rows:
            box.pack_start(Gtk.Label(label="No information provided by the agent.", xalign=0), False, False, 0)
        grid = Gtk.Grid(row_spacing=6, column_spacing=14)
        for i, (k, v) in enumerate(rows):
            kl = Gtk.Label(label=k, xalign=0, yalign=0)
            kl.get_style_context().add_class("dim-label")
            vl = Gtk.Label(label=v, xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.CHAR,
                           max_width_chars=60)
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(vl, 1, i, 1, 1)
        box.pack_start(grid, False, False, 0)
        box.show_all()

    def kill_selected(self):
        model, it = self.tree.get_selection().get_selected()
        if not it:
            return
        pid, cmd = model[it][0], model[it][3]
        if not ui.confirm(self.get_toplevel(), f"Kill process {pid}?", cmd, "Kill process", destructive=True):
            return
        self.app.ctrl.send_node_msg(self.nodeid, "pskill", value=pid)
        GLib.timeout_add(400, lambda: (self.refresh(), False)[1])


class ServicesPanel(_MsgPanel):
    def __init__(self, app, node):
        super().__init__(app, node)

        bar = Gtk.Box(spacing=6, margin=8)
        refresh = Gtk.Button(label="Refresh",
                             image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                             always_show_image=True)
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.pack_start(refresh, False, False, 0)
        for label, action, icon in (("Start", "serviceStart", "media-playback-start-symbolic"),
                                     ("Stop", "serviceStop", "media-playback-stop-symbolic"),
                                     ("Restart", "serviceRestart", "view-refresh-symbolic")):
            b = Gtk.Button(label=label,
                           image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON),
                           always_show_image=True)
            b.connect("clicked", lambda _w, a=action, l=label: self.control(a, l))
            bar.pack_start(b, False, False, 0)
        self.count = Gtk.Label(xalign=1)
        self.count.get_style_context().add_class("dim-label")
        bar.pack_end(self.count, False, False, 0)
        self.pack_start(bar, False, False, 0)

        hint = Gtk.Label(
            label="Start / Stop / Restart require the agent to be running as root (Linux) or SYSTEM "
                  "(Windows); otherwise they have no effect.",
            xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_start(8)
        hint.set_margin_end(8)
        self.pack_start(hint, False, False, 0)

        # display name, type, state, service name (for control)
        self.store = Gtk.ListStore(str, str, str, str)
        self.tree = Gtk.TreeView(model=self.store, enable_search=True, search_column=0)
        for title, col, expand in (("Service", 0, True), ("Type", 1, False), ("State", 2, False)):
            self.tree.append_column(ui.text_column(title, col, expand))
        ui.row_tooltip(self.tree, 0)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)

    def _first_load(self):
        self.refresh()

    # Linux: the agent's own "services" enumeration is slow (3+ s locally, far more over a
    # tunnel) and returns every unit twice. systemctl answers in milliseconds, so on Linux
    # we ask it through the documented runcommands API (output comes back as a separate
    # {action:'msg', type:'runcommands', result, responseid}) and only fall back to the
    # agent enumeration if that gets no answer.
    _SYSTEMCTL = ("systemctl list-units --type=service --all --no-legend --no-pager --plain 2>/dev/null; "
                  "echo ===MCD===; "
                  "systemctl list-unit-files --type=service --no-legend --no-pager 2>/dev/null")
    _SYSTEMCTL_TIMEOUT_S = 10

    def refresh(self):
        self.count.set_text("Loading…")
        from . import rights
        caps = rights.node_caps(self.app.ctrl, self.app.meshes, self.node)
        if ui.is_windows(self.node) or not caps.run_commands:
            # systemctl goes through "Run commands", which needs its own right.
            self.app.ctrl.send_node_msg(self.nodeid, "services")
            return
        self._svc_rid = "mcdsvc" + secrets.token_hex(6)
        self.app.ctrl.send({"action": "runcommands", "nodeids": [self.nodeid], "type": 3,
                            "cmds": self._SYSTEMCTL, "runAsUser": 0, "reply": True,
                            "responseid": self._svc_rid})
        rid = self._svc_rid
        GLib.timeout_add_seconds(self._SYSTEMCTL_TIMEOUT_S, self._systemctl_timeout, rid)

    def _systemctl_timeout(self, rid):
        if rid == getattr(self, "_svc_rid", None):          # never answered: use the agent's list
            self._svc_rid = None
            self.app.ctrl.send_node_msg(self.nodeid, "services")
        return False

    def _handle_systemctl(self, text):
        if "===MCD===" not in text:
            return False
        units, files = text.split("===MCD===", 1)
        info = {}
        for line in units.splitlines():
            parts = line.split(None, 4)                     # unit load active sub description
            if len(parts) < 4 or not parts[0].endswith(".service"):
                continue
            info[parts[0][:-8]] = {"sub": parts[3], "active": parts[2],
                                   "desc": parts[4] if len(parts) > 4 else ""}
        startup = {}
        for line in files.splitlines():
            parts = line.split()                             # unit state [preset]
            if len(parts) >= 2 and parts[0].endswith(".service") and "@." not in parts[0]:
                startup[parts[0][:-8]] = parts[1]
        if not info and not startup:
            return False
        rows = []
        running = 0
        for name in set(info) | set(startup):
            u = info.get(name, {})
            sub = u.get("sub", "dead")
            state = {"running": "Running", "exited": "Exited", "dead": "Inactive",
                     "failed": "Failed"}.get(sub, sub.capitalize())
            if u.get("active") == "failed":
                state = "Failed"
            running += sub == "running"
            kind = "systemd" + (f" · {startup[name]}" if name in startup else "")
            rows.append([u.get("desc") or name, kind, state, name])
        self._fill(rows, running)
        return True

    def _fill(self, rows, running):
        # Detach the model while filling: far faster than letting the view re-sort and
        # redraw on every append.
        self.tree.set_model(None)
        self.store.clear()
        for r in rows:
            self.store.append(r)
        self.store.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        self.tree.set_model(self.store)
        self.count.set_text(f"{len(rows)} services · {running} running")

    def _handle_msg(self, message):
        if message.get("type") == "runcommands" and message.get("responseid") == getattr(self, "_svc_rid", None):
            result = message.get("result")
            if isinstance(result, str) and result != "OK":
                self._svc_rid = None
                if not self._handle_systemctl(result):      # not systemd / no output: agent list
                    self.app.ctrl.send_node_msg(self.nodeid, "services")
            return
        if message.get("type") != "services":
            return
        try:
            services = json.loads(message.get("value") or "[]")
        except Exception:
            return
        # The agent lists each unit twice (e.g. /lib and /etc copies); collapse by
        # name, preferring the copy that carries a running state.
        by_name = {}
        for svc in services:
            if not isinstance(svc, dict):
                continue
            key = svc.get("name") or svc.get("displayName") or svc.get("description")
            if key is None:
                continue
            prev = by_name.get(key)
            if prev is None or (not self._svc_state_raw(prev) and self._svc_state_raw(svc)):
                by_name[key] = svc

        rows = []
        running = 0
        for svc in by_name.values():
            if svc.get("status"):                     # Windows: live SCM state
                raw = (svc["status"].get("state") or "")
                state = raw.capitalize() or "Unknown"
                svc_type = "service"
                display = svc.get("displayName") or svc.get("name") or ""
            else:                                     # Linux/systemd
                raw = self._svc_state_raw(svc)
                state = "Running" if raw else "Inactive"
                svc_type = svc.get("serviceType") or "service"
                display = svc.get("description") or svc.get("name") or ""
            if state in ("Running",):
                running += 1
            name = svc.get("name") or display
            rows.append([display, svc_type, state, name])
        self._fill(rows, running)

    @staticmethod
    def _svc_state_raw(svc):
        # Linux entries only carry 'state' (e.g. "RUNNING") when the unit is active.
        return svc.get("state") or (svc.get("status") or {}).get("state")

    def control(self, action, label):
        model, it = self.tree.get_selection().get_selected()
        if not it:
            return
        name, display = model[it][3], model[it][0]
        if not ui.confirm(self.get_toplevel(), f"{label} service?", display, label):
            return
        self.app.ctrl.send_node_msg(self.nodeid, action, serviceName=name)
        GLib.timeout_add(800, lambda: (self.refresh(), False)[1])


class ConsolePanel(_MsgPanel):
    def __init__(self, app, node):
        super().__init__(app, node)

        hint = Gtk.Label(
            label="Runs MeshAgent commands (type 'help'; e.g. ls, ps, services, cpuinfo). "
                  "For a real shell use the Terminal tab.",
            xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_start(8)
        hint.set_margin_end(8)
        hint.set_margin_top(6)
        self.pack_start(hint, False, False, 0)

        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log.set_left_margin(6)
        self.log.set_top_margin(6)
        self.buffer = self.log.get_buffer()
        self.pack_start(ui.scrolled(self.log), True, True, 0)

        entry_bar = Gtk.Box(spacing=6, margin=8)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Agent console command (e.g. help)")
        self.entry.connect("activate", lambda *_: self.send())
        entry_bar.pack_start(self.entry, True, True, 0)
        send = Gtk.Button(label="Send")
        send.get_style_context().add_class("suggested-action")
        send.connect("clicked", lambda *_: self.send())
        entry_bar.pack_start(send, False, False, 0)
        self.pack_start(entry_bar, False, False, 0)

    def _first_load(self):
        self._online = ui.is_online(self.node)
        self._append("Agent console ready. Type 'help' for the list of MeshAgent commands.\n")

    def on_node_update(self, node):
        self.node = node
        online = ui.is_online(node)
        if getattr(self, "_online", online) != online:
            self._append("*** Agent is back online ***\n" if online else
                         "*** Agent went offline (restarting or updating?), waiting for it to reconnect ***\n")
        self._online = online

    def _append(self, text):
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, text)
        self.log.scroll_to_mark(self.buffer.get_insert(), 0.0, False, 0, 0)

    def send(self):
        cmd = self.entry.get_text().strip()
        if not cmd:
            return
        self.entry.set_text("")
        self._append(f"> {cmd}\n")
        if not getattr(self, "_online", True):
            self._append("(agent is offline. Command not sent)\n")
            return
        self.app.ctrl.send_node_msg(self.nodeid, "console", value=cmd)

    def _handle_msg(self, message):
        if message.get("type") != "console":
            return
        val = message.get("value")
        if val and ("MCDCLIP" in str(val) or "MCDPATCH" in str(val)):
            return            # the desktop panel's private clipboard traffic
        if val:
            self._append(str(val) + "\n")
