"""Groups: the web UI's "My User Groups" list and "User Group - <name>" page (views 50 / 51).

Control-channel actions (same as the web UI):
  usergroups → {ugroups:{id:{name, desc, links:{user/…:{name, rights}, mesh/…:{rights}, node/…:{rights}},
               consent?, flags?, membershipType?}}}
  createusergroup {name, desc[, clone: ugrp id][, domain]} → {result:'ok', ugrpid} | error
  deleteusergroup {ugrpid} → {result:'ok'} | error
  editusergroup {ugrpid, name?, desc?, consent?, flags?}          (no reply; event usergroupchange)
  addusertousergroup {ugrpid, usernames:[short ids]} → {result:'ok', added, failed}
  removeuserfromusergroup {ugrpid, userid}
  addmeshuser {meshid, meshname, userids:[ugrp id], meshadmin} / removemeshuser {meshid, userid: ugrp id}
  adddeviceuser {nodeid, nodename, userids:[ugrp id], rights[, remove]}
Group edits need site right 256 (SITERIGHT_USERGROUPS); groups synced from an identity provider
(membershipType set) keep their name and members.
"""
from gi.repository import Gtk, GLib, Pango

from . import ui, rights
from .admin_panel import _TablePanel, BroadcastDialog
from .user_panel import (_dialog, _run, _check, consent_text, group_rights_text, device_rights_text,
                         list_section, consent_dialog, mesh_rights_dialog, device_rights_dialog)

SITE_USERGROUPS = 256


def _counts(g):
    links = g.get("links") or {}
    return tuple(sum(1 for k in links if k.startswith(p)) for p in ("user/", "mesh/", "node/"))


def group_dialog(parent, title, groups=None, domains=None, name="", desc="", name_ro=False):
    """New Group / Duplicate Group / Edit User Group form → dict(name, desc, clone?, domain?) or None."""
    d, area, ok = _dialog(parent, title, width=440)
    grid = Gtk.Grid(row_spacing=8, column_spacing=12)
    area.pack_start(grid, True, True, 0)
    r = 0
    src = dom = None
    if groups:
        src = Gtk.ComboBoxText(hexpand=True)
        for gid, g in sorted(groups.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
            src.append(gid, g.get("name") or gid)
        src.set_active(0)
        grid.attach(Gtk.Label(label="User Group", xalign=1), 0, r, 1, 1)
        grid.attach(src, 1, r, 1, 1)
        r += 1
    if domains:
        dom = Gtk.ComboBoxText(hexpand=True)
        for x in domains:
            dom.append_text(x or "Default")
        dom.set_active(0)
        grid.attach(Gtk.Label(label="Domain", xalign=1), 0, r, 1, 1)
        grid.attach(dom, 1, r, 1, 1)
        r += 1
    e = Gtk.Entry(text=name, hexpand=True, max_length=64, activates_default=True, sensitive=not name_ro)
    grid.attach(Gtk.Label(label="Name", xalign=1), 0, r, 1, 1)
    grid.attach(e, 1, r, 1, 1)
    tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
    tv.get_buffer().set_text(desc or "")
    scr = Gtk.ScrolledWindow(min_content_height=80, hexpand=True)
    scr.add(tv)
    fr = Gtk.Frame()
    fr.add(scr)
    grid.attach(Gtk.Label(label="Description", xalign=1, yalign=0), 0, r + 1, 1, 1)
    grid.attach(fr, 1, r + 1, 1, 1)
    if groups:
        note = Gtk.Label(label="The copy gets the same members and device group permissions "
                               "(the server does not copy per-device permissions).", xalign=0, wrap=True,
                         max_width_chars=50)
        note.get_style_context().add_class("dim-label")
        area.pack_start(note, False, False, 0)
    e.connect("changed", lambda *_: ok.set_sensitive(len(e.get_text().strip()) > 0))
    ok.set_sensitive(len(e.get_text().strip()) > 0)
    res = None
    if _run(d):
        b = tv.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        res = {"name": e.get_text().strip(), "desc": text[:1024]}
        if src is not None:
            res["clone"] = src.get_active_id()
        if dom is not None:
            res["domain"] = domains[dom.get_active()]
    d.destroy()
    return res


class GroupPage(Gtk.Box):
    """One user group, re-rendered by the Groups panel whenever the usergroups list changes."""

    def __init__(self, panel, group):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel, self.app, self.ctrl = panel, panel.app, panel.app.ctrl
        self.group = group
        head = Gtk.Box(spacing=8, margin=8)
        back = Gtk.Button(image=Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON),
                          tooltip_text="Back to the user group list")
        back.connect("clicked", lambda *_: self.panel.close_group())
        head.pack_start(back, False, False, 0)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        head.pack_start(self.title, False, False, 0)
        self.rename_btn = Gtk.Button(image=Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.MENU),
                                     relief=Gtk.ReliefStyle.NONE, tooltip_text="Edit the user group name")
        self.rename_btn.connect("clicked", lambda *_: self.edit_group())
        head.pack_start(self.rename_btn, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self.pack_start(ui.scrolled(self.body), True, True, 0)
        self.show_all()
        self.render()                                  # after show_all: render() hides what must stay hidden

    # ---- helpers ----------------------------------------------------------------------------
    def _top(self):
        return self.get_toplevel()

    def _sa(self):
        return rights.site_rights(self.ctrl)

    def _can_edit(self):
        return bool(self._sa() & SITE_USERGROUPS)

    def _meshes(self):
        return getattr(self.app, "meshes", None) or {}

    def _nodes(self):
        mw = getattr(self.app, "main_win", None)
        return getattr(mw, "nodes", None) or {}

    def _gid(self):
        return self.group.get("_id", "")

    def _reply(self, what):
        def cb(msg):
            if "success" in msg:
                ok = msg.get("success", 0) > 0 and not msg.get("failed")
            elif "added" in msg:
                ok = not msg.get("failed")
            else:
                ok = msg.get("result") in (None, "ok")
            if not ok:
                ui.message(self._top(), f"{what} failed", str(msg.get("result")), Gtk.MessageType.ERROR)
            self.panel.refresh_soon()
        return cb

    def _edit(self, **fields):
        self.ctrl.send(dict(action="editusergroup", ugrpid=self._gid(), **fields))
        self.panel.refresh_soon()

    # ---- render -------------------------------------------------------------------------------
    def set_group(self, group):
        self.group = group
        self.render()

    def render(self):
        g, si = self.group, (self.ctrl.serverinfo or {})
        synced = g.get("membershipType") is not None
        can = self._can_edit()
        self.title.set_markup("<big><b>User Group - %s</b></big>" % GLib.markup_escape_text(g.get("name") or "None"))
        self.rename_btn.set_visible(can and not synced)
        for c in self.body.get_children():
            self.body.remove(c)
        top = Gtk.Box(spacing=12)
        grid = Gtk.Grid(row_spacing=6, column_spacing=16)
        top.pack_start(grid, True, True, 0)
        icon = Gtk.Image.new_from_icon_name("system-users-symbolic", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(96)
        icon.set_valign(Gtk.Align.START)
        top.pack_end(icon, False, False, 0)
        self.body.pack_start(top, False, False, 0)
        n = [0]

        def row(key, value, edit=None, italic=False):
            k = Gtk.Label(label=key, xalign=0, valign=Gtk.Align.CENTER)
            k.get_style_context().add_class("dim-label")
            grid.attach(k, 0, n[0], 1, 1)
            box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            v = Gtk.Label(xalign=0, selectable=True, wrap=True, max_width_chars=70)
            t = GLib.markup_escape_text(value)
            v.set_markup(f"<i>{t}</i>" if italic else t)
            box.pack_start(v, False, False, 0)
            if edit:
                b = Gtk.Button(image=Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.MENU),
                               relief=Gtk.ReliefStyle.NONE, tooltip_text=f"Change {key.lower()}")
                b.connect("clicked", lambda *_: edit())
                box.pack_start(b, False, False, 0)
            grid.attach(box, 1, n[0], 1, 1)
            n[0] += 1

        gid = self._gid()
        dom = gid.split("/")[1] if gid.count("/") == 2 else ""
        row("Domain", dom or "Default", italic=not dom)
        row("Group Identifier", gid)
        if synced:
            row("Group Type", str(g.get("membershipType")))
        desc = g.get("desc") or ""
        row("Description", desc or "None", (lambda: self.edit_group(focus_desc=True)) if can else None,
            italic=not desc)
        if si.get("userGroupsSessionRecording") == 1:
            row("Features", "Record Sessions" if (g.get("flags") or 0) & 2 else "None", self.edit_features if can else None,
                italic=not (g.get("flags") or 0) & 2)
        ct = consent_text(g, si)
        row("User Consent", ct, self.edit_consent, italic=ct == "None")
        users, meshes, devices = _counts(g)
        row("Users", str(users))
        row("Device Groups", str(meshes))
        row("Devices", str(devices))
        if can:
            b = Gtk.Button(label="Broadcast", halign=Gtk.Align.START, margin_top=6,
                           tooltip_text="Send a notice to all users in this group")
            b.set_sensitive(bool(self._sa() & 2) and users > 0)
            b.connect("clicked", lambda *_: BroadcastDialog(self._top(), self.ctrl, gid, g.get("name")))
            self.body.pack_start(b, False, False, 0)
        self._section_members(synced, can)
        self._section_groups()
        self._section_devices()
        if (not synced or users == 0) and can:
            bottom = Gtk.Box(margin_top=10)
            d = Gtk.Button(label="Delete User Group…")
            d.get_style_context().add_class("destructive-action")
            d.connect("clicked", lambda *_: self.delete_group())
            bottom.pack_end(d, False, False, 0)
            self.body.pack_start(bottom, False, False, 0)
        self.body.show_all()

    def _section_members(self, synced, can):
        links = self.group.get("links") or {}
        me = self.ctrl.userinfo or {}
        rows = []
        members = []
        for uid, l in links.items():
            if not uid.startswith("user/"):
                continue
            name = (l or {}).get("name") or uid.split("/")[2]
            if uid == me.get("_id"):
                name = me.get("name") or name
            members.append((name, uid))
        for name, uid in sorted(members, key=lambda x: x[0].lower()):
            rm = (lambda u=uid, nm=name: self.remove_member(u, nm)) if not synced and can else None
            rows.append((name, "", None, rm, "Remove this user from the group",
                         (lambda u=uid: self.panel.open_user(u)) if self.panel.can_open_users() else None))
        list_section(self.body, "Group Members", "Add Users", self.add_users if (not synced and can) else None,
                     rows, "No Members")

    def _section_groups(self):
        g, meshes = self.group, self._meshes()
        links = g.get("links") or {}
        dom = self._gid().split("/")[1]
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        rows = []
        for mid in sorted((m for m in links if m.startswith("mesh/") and m in meshes),
                          key=lambda m: (meshes[m].get("name") or "").lower()):
            r = links[mid].get("rights") or 0
            can = bool(rights.mesh_rights(self.ctrl, meshes[mid]) & 2)
            rows.append((meshes[mid].get("name") or mid, group_rights_text(r, guest),
                         (lambda m=mid: self.group_rights(m)) if can else None,
                         (lambda m=mid: self.remove_mesh(m)) if can else None,
                         "Remove user group rights to this device group"))
        avail = [m for m in meshes if m.split("/")[1] == dom and m not in links]
        list_section(self.body, "Common Device Groups", "Add Device Group", self.group_rights if avail else None,
                     rows, "No device groups in common")

    def _section_devices(self):
        g, nodes = self.group, self._nodes()
        links = g.get("links") or {}
        guest = (self.ctrl.serverinfo or {}).get("guestdevicesharing") is not False
        rows = []
        for nid in sorted((n for n in links if n.startswith("node/") and n in nodes),
                          key=lambda n: (nodes[n].get("name") or "").lower()):
            r = links[nid].get("rights") or 0
            can = bool(rights.node_rights(self.ctrl, self._meshes(), nodes[nid]) & 2)
            rows.append((nodes[nid].get("name") or nid, device_rights_text(r, guest),
                         (lambda n=nid: self.device_rights(n)) if can else None,
                         (lambda n=nid: self.remove_device(n)) if can else None,
                         "Remove user group rights to this device"))
        same = self._gid().split("/")[1] == ((self.ctrl.userinfo or {}).get("_id") or "//").split("/")[1]
        list_section(self.body, "Common Devices", "Add Device", self.device_rights if same else None,
                     rows, "No devices in common")

    # ---- edits --------------------------------------------------------------------------------
    def edit_group(self, focus_desc=False):
        g = self.group
        r = group_dialog(self._top(), "Edit User Group", name=g.get("name") or "", desc=g.get("desc") or "",
                         name_ro=g.get("membershipType") is not None)
        if r:
            self._edit(name=r["name"], desc=r["desc"])

    def edit_features(self):
        d, area, _ok = _dialog(self._top(), "Edit User Group Features")
        rec = _check("Record sessions", (self.group.get("flags") or 0) & 2)
        area.pack_start(rec, False, False, 0)
        if _run(d):
            self._edit(flags=2 if rec.get_active() else 0)
        d.destroy()

    def edit_consent(self):
        v = consent_dialog(self._top(), "Edit User Group User Consent", self.group.get("consent") or 0,
                           (self.ctrl.serverinfo or {}).get("consent") or 0)
        if v is not None:
            self._edit(consent=v)

    def add_users(self):
        """web UI p51showAddUserDialog: comma separated user names (with completion)."""
        d, area, ok = _dialog(self._top(), "Add Users to User Group", width=460)
        area.pack_start(Gtk.Label(label="Enter one or more user names, separated by commas.", xalign=0, wrap=True),
                        False, False, 0)
        e = Gtk.Entry(placeholder_text="user1, user2, user3", activates_default=True, hexpand=True)
        dom = self._gid().split("/")[1]
        present = set((self.group.get("links") or {}).keys())
        cands = [u for u in self.panel.users.values() if u.get("_id", "").split("/")[1] == dom
                 and u.get("_id") not in present]
        store = Gtk.ListStore(str, str)
        for u in sorted(cands, key=lambda u: (u.get("name") or "").lower()):
            store.append([u.get("name") or "", u["_id"].split("/")[2]])
        comp = Gtk.EntryCompletion(model=store, text_column=0, inline_selection=True)

        def match(_c, key, it):
            last = e.get_text().split(",")[-1].strip().lower()
            return bool(last) and (last in store[it][0].lower() or last in store[it][1])

        def selected(_c, model, it):
            parts = [p.strip() for p in e.get_text().split(",")]
            parts[-1] = model[it][1]
            e.set_text(", ".join(parts))
            e.set_position(-1)
            return True
        comp.set_match_func(match)
        comp.connect("match-selected", selected)
        e.set_completion(comp)
        area.pack_start(e, False, False, 0)
        hint = Gtk.Label(xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        if (self.ctrl.serverinfo or {}).get("features", 0) & 0x80000:
            hint.set_text("Users need to sign in to this server once before they can be added.")
        area.pack_start(hint, False, False, 0)

        def valid(*_):
            parts = [p.strip() for p in e.get_text().split(",")]
            ok.set_sensitive(all(p and '"' not in p for p in parts))
        e.connect("changed", valid)
        valid()
        if _run(d):
            names = [p.strip() for p in e.get_text().split(",") if p.strip()]
            self.ctrl.send({"action": "addusertousergroup", "ugrpid": self._gid(), "usernames": names},
                           self._reply("Adding users"))
        d.destroy()

    def remove_member(self, userid, name):
        if ui.confirm(self._top(), "Remove User Membership", f"Confirm membership removal of user “{name}”?",
                      "Remove", True):
            self.ctrl.send({"action": "removeuserfromusergroup", "ugrpid": self._gid(), "userid": userid},
                           self._reply("Removing the member"))

    def group_rights(self, meshid=None):
        r = mesh_rights_dialog(self._top(), self.ctrl, self._meshes(), self.group.get("links") or {},
                               self._gid().split("/")[1], meshid)
        if r:
            mid, value, title = r
            self.ctrl.send({"action": "addmeshuser", "meshid": mid, "meshname": self._meshes()[mid].get("name"),
                            "userids": [self._gid()], "meshadmin": value}, self._reply(title))

    def remove_mesh(self, meshid):
        name = self._meshes().get(meshid, {}).get("name", meshid)
        if ui.confirm(self._top(), "Remove Device Group Permissions",
                      f"Confirm removal of access rights for device group “{name}”?", "Remove", True):
            self.ctrl.send({"action": "removemeshuser", "meshid": meshid, "userid": self._gid()},
                           self._reply("Removing the device group permissions"))

    def device_rights(self, nodeid=None):
        r = device_rights_dialog(self._top(), self.ctrl, self._meshes(), self._nodes(),
                                 self.group.get("links") or {}, nodeid)
        if r:
            nid, value, title = r
            self.ctrl.send({"action": "adddeviceuser", "nodeid": nid, "nodename": self._nodes()[nid].get("name"),
                            "userids": [self._gid()], "rights": value}, self._reply(title))

    def remove_device(self, nodeid):
        node = self._nodes().get(nodeid, {})
        if ui.confirm(self._top(), "Remove Device Permissions",
                      f"Confirm removal of access rights for device “{node.get('name', nodeid)}”?", "Remove", True):
            self.ctrl.send({"action": "adddeviceuser", "nodeid": nodeid, "nodename": node.get("name"),
                            "userids": [self._gid()], "rights": 0, "remove": True},
                           self._reply("Removing the device permissions"))

    def delete_group(self):
        name = self.group.get("name")
        if not ui.confirm(self._top(), "Delete User Group", f"Delete user group {name}?", "Delete", True):
            return

        def done(msg):
            if msg.get("result") not in (None, "ok"):
                ui.message(self._top(), "Deleting the user group failed", str(msg.get("result")), Gtk.MessageType.ERROR)
                return
            self.panel.close_group()
            self.panel.refresh_soon()
        self.ctrl.send({"action": "deleteusergroup", "ugrpid": self._gid()}, done)


class UserGroupsPanel(_TablePanel):
    """Web UI "My User Groups": checkboxes + Select All / None, Group Action (delete), New Group…,
    Duplicate Group…, columns Users / Device Groups / Devices; double-click → GroupPage."""
    COLUMNS = [("Name", True)]           # replaced in _build_tree
    ACTION = "usergroups"
    C_CHECK, C_NAME, C_USERS, C_MESHES, C_NODES, C_ID, C_TIP = range(7)

    def __init__(self, app, node=None):
        super().__init__(app, node)
        self.groups = {}
        self.users = {}                  # for member names / "Add Users" completion
        self._checked = set()
        self.page = None
        self._soon = None
        self._build_tree()
        can = rights.has_site(app.ctrl, SITE_USERGROUPS)
        bar = self.get_children()[0]
        self.select_btn = Gtk.Button(label="Select All")
        self.select_btn.connect("clicked", lambda *_: self.toggle_select_all())
        self.group_btn = Gtk.Button(label="Group Action…", sensitive=False,
                                    tooltip_text="Perform an operation on all selected user groups")
        self.group_btn.connect("clicked", lambda *_: self.group_action())
        self.new_btn = Gtk.Button(label="New Group…", image=Gtk.Image.new_from_icon_name("list-add-symbolic",
                                                                                          Gtk.IconSize.BUTTON),
                                  always_show_image=True)
        self.new_btn.connect("clicked", lambda *_: self.new_group())
        self.dup_btn = Gtk.Button(label="Duplicate Group…", sensitive=False,
                                  tooltip_text="Create a new user group with the same members and permissions")
        self.dup_btn.connect("clicked", lambda *_: self.new_group(duplicate=True))
        for w in (self.select_btn, self.group_btn, self.new_btn, self.dup_btn):
            w.set_no_show_all(not can)                # web UI: operations only with site right 256
            bar.pack_start(w, False, False, 0)
        bar.show_all()
        app.ctrl.on("event", self._on_event)
        app.ctrl.on("users", self._on_users)

    # ---- table --------------------------------------------------------------------------------
    def _build_tree(self):
        scr = self.get_children()[-1]
        self.remove(scr)
        self.store = Gtk.ListStore(bool, str, str, str, str, str, str)
        tv = Gtk.TreeView(model=self.store)
        chk = Gtk.CellRendererToggle()
        chk.connect("toggled", self._on_toggled)
        col = Gtk.TreeViewColumn("", chk, active=self.C_CHECK)
        col.set_visible(rights.has_site(self.app.ctrl, SITE_USERGROUPS))
        tv.append_column(col)
        tv.append_column(ui.text_column("Name", self.C_NAME, True))
        for title, c in (("Users", self.C_USERS), ("Device Groups", self.C_MESHES), ("Devices", self.C_NODES)):
            tv.append_column(ui.text_column(title, c))
        ui.row_tooltip(tv, self.C_TIP)
        tv.connect("row-activated", lambda t, path, _c: self.open_group(self.store[path][self.C_ID]))
        self.tree = tv
        self.pack_start(ui.scrolled(tv), True, True, 0)

    def _on_toggled(self, _r, path):
        row = self.store[path]
        row[self.C_CHECK] = not row[self.C_CHECK]
        (self._checked.add if row[self.C_CHECK] else self._checked.discard)(row[self.C_ID])
        self._update_buttons()

    def _update_buttons(self):
        self._checked &= set(self.groups)
        n = len(self._checked)
        self.select_btn.set_label("Select None" if n else "Select All")
        self.group_btn.set_sensitive(n > 0)
        self.dup_btn.set_sensitive(bool(self.groups))

    def toggle_select_all(self):
        self._checked = set() if self._checked else set(self.groups)
        self._render()

    def _render(self):
        self.store.clear()
        cross = (self.app.ctrl.serverinfo or {}).get("crossDomain") is not None
        for gid, g in sorted(self.groups.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
            u, m, n = _counts(g)
            name = g.get("name") or ""
            dom = gid.split("/")[1] if gid.count("/") == 2 else ""
            if cross and dom:
                name += f", {dom}"
            tip = name + (f" - {g['desc']}" if g.get("desc") else "")
            self.store.append([gid in self._checked, name, str(u), str(m), str(n), gid, tip])
        self.status.set_text("%d group(s), double-click a group to open it" % len(self.groups)
                             if self.groups else "No groups found.")
        self._update_buttons()

    def request(self):
        self.app.ctrl.send({"action": "usergroups"})
        if rights.has_site(self.app.ctrl, rights.SITE_MANAGEUSERS) and not self.users:
            self.app.ctrl.send({"action": "users"})

    def _fill(self, msg):
        groups = msg.get("ugroups") or {}
        if isinstance(groups, list):
            groups = {g.get("_id", str(i)): g for i, g in enumerate(groups)}
        self.groups = groups
        self._render()
        if self.page is not None:
            g = groups.get(self.page.group.get("_id"))
            if g is None:
                self.close_group()
            else:
                self.page.set_group(g)

    def _on_users(self, msg):
        ul = msg.get("users")
        if isinstance(ul, dict):
            ul = list(ul.values())
        if isinstance(ul, list):
            self.users = {u.get("_id"): u for u in ul if u.get("_id")}

    def _on_event(self, msg):
        act = (msg.get("event") or {}).get("action")
        if act in ("createusergroup", "deleteusergroup", "usergroupchange", "meshchange", "createmesh",
                   "deletemesh", "changenode", "removenode", "accountcreate", "accountremove") and self._started:
            if act in ("accountcreate", "accountremove"):
                self.app.ctrl.send({"action": "users"})
            self.refresh_soon(1000)

    def refresh_soon(self, ms=700):
        if self._soon:
            GLib.source_remove(self._soon)
        self._soon = GLib.timeout_add(ms, self._refresh_now)

    def _refresh_now(self):
        self._soon = None
        self.refresh()
        return False

    # ---- pages / actions ------------------------------------------------------------------------
    def open_group(self, gid):
        g = self.groups.get(gid)
        if g is None:
            return None
        if self.page is not None:
            self.page.destroy()
        for w in self.get_children():
            w.hide()
        self.page = GroupPage(self, g)
        self.pack_start(self.page, True, True, 0)
        self.page.show()
        return self.page

    def close_group(self):
        if self.page is not None:
            self.page.destroy()
            self.page = None
        for w in self.get_children():
            w.show()

    def can_open_users(self):
        mw = getattr(self.app, "main_win", None)
        return mw is not None and rights.has_site(self.app.ctrl, rights.SITE_MANAGEUSERS)

    def open_user(self, userid):
        """Member name → the user's page on the Users page (like the web UI's links)."""
        mw = self.app.main_win
        mw.show_page("users")
        users_panel = mw._pages.get("users")

        def go(tries=[20]):
            if users_panel is None:
                return False
            if any(u.get("_id") == userid for u in users_panel._users):
                users_panel.open_user(userid)
                return False
            tries[0] -= 1
            return tries[0] > 0                     # wait for the list to load (first visit)
        GLib.timeout_add(250, go)

    def new_group(self, duplicate=False):
        si = self.app.ctrl.serverinfo or {}
        if duplicate:
            r = group_dialog(self.get_toplevel(), "Duplicate User Group", groups=self.groups)
        else:
            doms = si.get("crossDomain") if isinstance(si.get("crossDomain"), list) else None
            r = group_dialog(self.get_toplevel(), "Create User Group", domains=doms)
        if not r:
            return
        msg = {"action": "createusergroup", "name": r["name"], "desc": r["desc"]}
        if r.get("clone"):
            msg["clone"] = r["clone"]
        if r.get("domain") is not None:
            msg["domain"] = r["domain"]

        def done(m):
            if m.get("result") != "ok":
                ui.message(self.get_toplevel(), "Creating the user group failed", str(m.get("result")),
                           Gtk.MessageType.ERROR)
            self.refresh_soon(300)
        self.app.ctrl.send(msg, done)

    def group_action(self):
        ids = list(self._checked)
        if not ids:
            return
        d = Gtk.Dialog(title="Group Action", transient_for=self.get_toplevel(), modal=True)
        area = d.get_content_area()
        area.set_spacing(8)
        area.set_border_width(12)
        area.pack_start(Gtk.Label(label=f"Select an operation to perform on the {len(ids)} selected user group(s).",
                                  xalign=0), False, False, 0)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label="Operation"), False, False, 0)
        combo = Gtk.ComboBoxText(hexpand=True)
        combo.append("delete", "Delete group")
        combo.set_active(0)
        row.pack_start(combo, True, True, 0)
        area.pack_start(row, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        op = combo.get_active_id()
        d.destroy()
        if not ok or op != "delete":
            return
        if not ui.confirm(self.get_toplevel(), "Delete User Groups",
                          f"Confirm deletion of {len(ids)} selected user group(s)?", "Delete", True):
            return
        for gid in ids:
            self.app.ctrl.send({"action": "deleteusergroup", "ugrpid": gid})
        self._checked.clear()
        self.refresh_soon(1200)

    def teardown(self):
        super().teardown()
        self.app.ctrl.off("event", self._on_event)
        self.app.ctrl.off("users", self._on_users)
        if self._soon:
            GLib.source_remove(self._soon)
            self._soon = None
        if self.page is not None:
            self.page.destroy()
            self.page = None
