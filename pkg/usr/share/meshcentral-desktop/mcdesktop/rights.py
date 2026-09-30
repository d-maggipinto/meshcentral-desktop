# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Account permissions: what the signed-in user may do on a device and on the server.

The server enforces every right itself; this module only decides what the app OFFERS, so a
restricted account sees clear "no permission" messages instead of buttons that silently fail.
Logic mirrors the MeshCentral web UI (GetMeshRights / GetNodeRights / removeUserRights in
views/default.handlebars) and the checks in meshuser.js.
"""

FULL = 0xFFFFFFFF

# Device-group / device rights (MESHRIGHT_*)
EDITMESH = 0x1
MANAGEUSERS = 0x2
MANAGECOMPUTERS = 0x4          # rename device, edit tags
REMOTECONTROL = 0x8            # needed for ANY agent message (desktop, tools, clipboard...)
AGENTCONSOLE = 0x10
SERVERFILES = 0x20             # this group's folder in "My Files"
WAKEDEVICE = 0x40
SETNOTES = 0x80
REMOTEVIEWONLY = 0x100         # desktop view only (no input)
NOTERMINAL = 0x200
NOFILES = 0x400
NOAMT = 0x800
DESKLIMITEDINPUT = 0x1000
LIMITEVENTS = 0x2000
CHATNOTIFY = 0x4000
UNINSTALL = 0x8000
NODESKTOP = 0x10000
REMOTECOMMAND = 0x20000        # "Run commands" (and our systemctl Services listing)
RESETOFF = 0x40000             # power off / reset / sleep
DEVICEDETAILS = 0x100000

# Site rights (userinfo.siteadmin, SITERIGHT_*)
SITE_BACKUP = 0x1              # My Server: download server backup (+ stats)
SITE_MANAGEUSERS = 0x2
SITE_RESTORE = 0x4             # My Server: restore server from backup (+ stats)
SITE_UPDATE = 0x10             # My Server: version/update, error log, configuration (+ stats)
SITE_FILEACCESS = 0x8          # "My Files" at all
SITE_USERGROUPS = 0x100


def _remove_user_rights(rights, userinfo):
    """Port of the web UI's removeUserRights(): account-level restrictions (userinfo.removeRights)."""
    rr = (userinfo or {}).get("removeRights")
    if not rr:
        return rights
    add = sub = 0
    for bit in (NODESKTOP, REMOTEVIEWONLY, NOTERMINAL, NOFILES, 0x400000, 0x800000):
        if rr & bit:
            add |= bit
    for bit in (REMOTECONTROL, AGENTCONSOLE, UNINSTALL, REMOTECOMMAND, WAKEDEVICE, RESETOFF):
        if rr & bit:
            sub |= bit
    if rights == FULL:
        rights = (1 + 2 + 4 + 8 + 32 + 64 + 128 + 16384 + 32768 + 131072 + 262144 + 524288 + 1048576)
    return (rights | add) & (FULL - sub)


def mesh_rights(ctrl, mesh):
    """Rights of the signed-in user on a device group (mesh dict from the 'meshes' reply)."""
    userinfo = ctrl.userinfo or {}
    uid = userinfo.get("_id")
    if (ctrl.serverinfo or {}).get("manageAllDeviceGroups"):
        return _remove_user_rights(FULL, userinfo)
    links = (mesh or {}).get("links") or {}
    rights = 0
    r = links.get(uid)
    if r is not None:
        if r.get("rights") == FULL:
            return _remove_user_rights(FULL, userinfo)
        rights = r.get("rights") or 0
    for gid in (userinfo.get("links") or {}):          # rights through user groups
        if gid.startswith("ugrp/") and gid in links:
            gr = links[gid].get("rights") or 0
            if gr == FULL:
                return _remove_user_rights(FULL, userinfo)
            rights |= gr
    return _remove_user_rights(rights, userinfo)


def node_rights(ctrl, meshes, node):
    """Rights of the signed-in user on a device (mesh rights + direct device links)."""
    userinfo = ctrl.userinfo or {}
    uid = userinfo.get("_id")
    r = mesh_rights(ctrl, (meshes or {}).get(node.get("meshid")))
    if r == FULL:
        return r
    links = node.get("links") or {}
    if uid in links:
        r |= links[uid].get("rights") or 0
    ulinks = userinfo.get("links") or {}
    for gid, l in links.items():
        if gid.startswith("ugrp/") and gid in ulinks:
            r |= l.get("rights") or 0
    return _remove_user_rights(r, userinfo)


def site_rights(ctrl):
    sa = (ctrl.userinfo or {}).get("siteadmin")
    return sa if isinstance(sa, int) else 0


def has_site(ctrl, bit):
    sa = site_rights(ctrl)
    return sa == FULL or bool(sa & bit)


class NodeCaps:
    """Feature switches for one device, derived from node rights (server-side rules)."""

    def __init__(self, rights):
        r = self.rights = rights
        full = r == FULL
        # Every agent message is routed only with remote control OR view-only rights.
        self.agent = full or bool(r & (REMOTECONTROL | REMOTEVIEWONLY))
        self.view_only = (not full) and bool(r & REMOTEVIEWONLY) and not (r & REMOTECONTROL)
        self.desktop = self.agent and (full or not (r & NODESKTOP))
        self.desktop_input = self.desktop and (full or (bool(r & REMOTECONTROL) and not (r & REMOTEVIEWONLY)))
        self.terminal = full or (bool(r & REMOTECONTROL) and not (r & NOTERMINAL) and not (r & REMOTEVIEWONLY))
        self.files = full or (bool(r & REMOTECONTROL) and not (r & NOFILES) and not (r & REMOTEVIEWONLY))
        self.tools = full or bool(r & REMOTECONTROL)                 # processes, services, kill, start/stop
        self.console = full or (r & (REMOTECONTROL | AGENTCONSOLE)) == (REMOTECONTROL | AGENTCONSOLE)
        self.run_commands = full or bool(r & REMOTECOMMAND)
        self.wake = full or bool(r & WAKEDEVICE)
        self.power = full or bool(r & RESETOFF)
        self.notes = full or bool(r & SETNOTES)
        self.manage = full or bool(r & MANAGECOMPUTERS)
        self.messages = full or bool(r & REMOTECONTROL)             # message box / toast


def node_caps(ctrl, meshes, node):
    return NodeCaps(node_rights(ctrl, meshes, node))


NO_PERMISSION = "Your account does not have permission for this on this device."
