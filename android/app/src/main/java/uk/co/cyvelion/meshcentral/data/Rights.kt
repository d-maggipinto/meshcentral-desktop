// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.data

import org.json.JSONObject

/**
 * Account permissions, port of the desktop app's rights.py (the web UI's GetMeshRights / GetNodeRights /
 * removeUserRights). The server enforces everything; this only decides what the app offers.
 */
object Rights {
    const val FULL = 0xFFFFFFFFL
    const val REMOTECONTROL = 0x8L
    const val AGENTCONSOLE = 0x10L
    const val WAKEDEVICE = 0x40L
    const val REMOTEVIEWONLY = 0x100L
    const val NOTERMINAL = 0x200L
    const val NOFILES = 0x400L
    const val CHATNOTIFY = 0x4000L
    const val NODESKTOP = 0x10000L
    const val REMOTECOMMAND = 0x20000L
    const val RESETOFF = 0x40000L
    const val NOREGISTRY = 0x400000L
    const val NOSOFTWARE = 0x800000L
    private const val UNINSTALL = 0x8000L

    private fun removeUserRights(rights: Long, userinfo: JSONObject?): Long {
        val rr = userinfo?.optLong("removeRights") ?: 0L
        if (rr == 0L) return rights
        var add = 0L
        var sub = 0L
        for (bit in listOf(NODESKTOP, REMOTEVIEWONLY, NOTERMINAL, NOFILES, NOREGISTRY, NOSOFTWARE)) if (rr and bit != 0L) add = add or bit
        for (bit in listOf(REMOTECONTROL, AGENTCONSOLE, UNINSTALL, REMOTECOMMAND, WAKEDEVICE, RESETOFF)) if (rr and bit != 0L) sub = sub or bit
        val r = if (rights == FULL) (1L + 2 + 4 + 8 + 32 + 64 + 128 + 16384 + 32768 + 131072 + 262144 + 524288 + 1048576) else rights
        return (r or add) and (FULL - sub)
    }

    private fun linkRights(links: JSONObject?, id: String): Long? =
        links?.optJSONObject(id)?.let { if (it.has("rights")) it.optLong("rights") else 0L }

    fun mesh(serverinfo: JSONObject, userinfo: JSONObject?, mesh: JSONObject?): Long {
        if (serverinfo.optBoolean("manageAllDeviceGroups")) return removeUserRights(FULL, userinfo)
        val uid = userinfo?.optString("_id") ?: ""
        val links = mesh?.optJSONObject("links")
        var rights = 0L
        linkRights(links, uid)?.let { if (it == FULL) return removeUserRights(FULL, userinfo); rights = it }
        userinfo?.optJSONObject("links")?.keys()?.forEach { gid ->     // rights through user groups
            if (gid.startsWith("ugrp/")) linkRights(links, gid)?.let { gr ->
                if (gr == FULL) return removeUserRights(FULL, userinfo)
                rights = rights or gr
            }
        }
        return removeUserRights(rights, userinfo)
    }

    fun node(serverinfo: JSONObject, userinfo: JSONObject?, mesh: JSONObject?, node: JSONObject): Long {
        var r = mesh(serverinfo, userinfo, mesh)
        if (r == FULL) return r
        val uid = userinfo?.optString("_id") ?: ""
        val links = node.optJSONObject("links")
        linkRights(links, uid)?.let { r = r or it }
        val ulinks = userinfo?.optJSONObject("links")
        links?.keys()?.forEach { gid -> if (gid.startsWith("ugrp/") && ulinks?.has(gid) == true) r = r or (linkRights(links, gid) ?: 0L) }
        return removeUserRights(r, userinfo)
    }
}

/** Feature switches for one device (rights.py NodeCaps). */
class NodeCaps(val rights: Long) {
    private val full = rights == Rights.FULL
    private fun has(bit: Long) = rights and bit != 0L
    val agent = full || has(Rights.REMOTECONTROL) || has(Rights.REMOTEVIEWONLY)
    val viewOnly = !full && has(Rights.REMOTEVIEWONLY) && !has(Rights.REMOTECONTROL)
    val desktop = agent && (full || !has(Rights.NODESKTOP))
    val desktopInput = desktop && (full || (has(Rights.REMOTECONTROL) && !has(Rights.REMOTEVIEWONLY)))
    val terminal = full || (has(Rights.REMOTECONTROL) && !has(Rights.NOTERMINAL) && !has(Rights.REMOTEVIEWONLY))
    val files = full || (has(Rights.REMOTECONTROL) && !has(Rights.NOFILES) && !has(Rights.REMOTEVIEWONLY))
    val console = full || (has(Rights.REMOTECONTROL) && has(Rights.AGENTCONSOLE))
    val runCommands = full || has(Rights.REMOTECOMMAND)
    val wake = full || has(Rights.WAKEDEVICE)
    val power = full || has(Rights.RESETOFF)
    val messages = full || has(Rights.REMOTECONTROL)
    val chat = full || has(Rights.CHATNOTIFY)
    /** rename, description, tags, consent (web UI: MESHRIGHT_MANAGECOMPUTERS 4) */
    val edit = full || has(4L)
    /** notes: edit needs 128 (MESHRIGHT_SETNOTES) */
    val notesEdit = full || has(128L)
    /** Windows registry over relay protocol 4 */
    val registry = full || (has(Rights.REMOTECONTROL) && !has(Rights.NOREGISTRY))
    /** installed software list / uninstall */
    val software = full || (has(Rights.REMOTECONTROL) && !has(Rights.NOSOFTWARE))
    /** processes, services: agent rights (8) like the web UI */
    val tools = full || has(Rights.REMOTECONTROL)
    /** device events: anyone who sees the device */
    val events = true
}

const val NO_PERMISSION = "Your account does not have permission for this on this device."

/** Site rights of the signed-in account (user.siteadmin); 0xFFFFFFFF = full administrator. */
object Site {
    const val BACKUP = 1L; const val MANAGEUSERS = 2L; const val RESTORE = 4L; const val FILEACCESS = 8L
    const val UPDATE = 16L; const val LOCKED = 32L; const val NONEWGROUPS = 64L; const val NOTOOLS = 128L
    const val USERGROUPS = 256L; const val RECORDINGS = 512L; const val LOCKSETTINGS = 1024L
    fun rights(userinfo: JSONObject?): Long = userinfo?.optLong("siteadmin", 0L) ?: 0L
    fun full(userinfo: JSONObject?) = rights(userinfo) == Rights.FULL
    fun has(userinfo: JSONObject?, bit: Long) = full(userinfo) || (rights(userinfo) and bit) != 0L
}
