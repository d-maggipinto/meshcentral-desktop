// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.data

import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.net.CloseReason
import uk.co.cyvelion.meshcentral.net.ControlConnection

/** Agent type id -> OS family (the desktop app's ui.AGENT_OS). */
private val AGENT_OS = mapOf(
    1 to "Windows", 2 to "Windows", 3 to "Windows", 4 to "Windows", 5 to "Linux", 6 to "Linux", 7 to "macOS",
    8 to "Linux", 9 to "Linux", 10 to "Custom", 16 to "macOS", 21 to "Windows", 22 to "Windows", 25 to "Linux",
    26 to "Linux", 27 to "Linux", 28 to "Linux", 29 to "macOS", 30 to "FreeBSD", 32 to "Linux", 33 to "Windows",
    34 to "Windows", 36 to "Linux", 37 to "OpenBSD", 40 to "Linux", 41 to "Linux", 42 to "Windows", 43 to "Windows",
)

/** A device as the server sends it (the raw JSON is kept: the pages read many optional fields). */
class Node(val json: JSONObject, val meshId: String) {
    val id: String = json.optString("_id")
    val name: String = json.optString("name").ifEmpty { json.optString("host") }
    val host: String = json.optString("host")
    val online: Boolean get() = (json.optInt("conn") and 1) != 0
    val agentId: Int = json.optJSONObject("agent")?.optInt("id") ?: 0
    /** 2 = agent, 3 = local device (no agent: agent.id only holds the OS type, for the icon), 4 = Intel AMT. */
    val mtype: Int = json.optInt("mtype", 2)
    val hasAgent: Boolean = json.optJSONObject("agent") != null && mtype != 3
    val os: String get() = json.optString("osdesc").ifEmpty { AGENT_OS[agentId] ?: "" }
    /** Windows, Linux, macOS, Android, BSD or "" (for the icon). */
    val osFamily: String get() {
        val d = json.optString("osdesc").lowercase()
        return when {
            d.contains("windows") -> "Windows"
            d.contains("android") || agentId == 9 || agentId == 12 || agentId == 14 -> "Android"
            d.contains("mac") || d.contains("darwin") -> "macOS"
            d.contains("bsd") -> "BSD"
            listOf("linux", "ubuntu", "debian", "fedora", "centos", "red hat", "suse", "arch").any { d.contains(it) } -> "Linux"
            else -> when (val f = AGENT_OS[agentId]) { "FreeBSD", "OpenBSD" -> "BSD"; null, "Custom" -> ""; else -> f }
        }
    }
    val isWindows: Boolean get() = AGENT_OS[agentId] == "Windows" || json.optString("osdesc").contains("windows", true)
    val description: String = json.optString("desc")
    val tags: List<String> = json.optJSONArray("tags")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
    val icon: Int = json.optInt("icon", 1)

    /** The id the web UI uses in URLs (?gotonode=): the part after "node/<domain>/". */
    val shortId: String get() = id.substringAfterLast('/')
}

class Mesh(val json: JSONObject) {
    val id: String = json.optString("_id")
    val name: String = json.optString("name")
    val type: Int = json.optInt("mtype", 2)
}

/**
 * The signed-in session: the control connection plus the device and group lists as Compose state.
 * Lives in the Application (survives screen rotation and navigation).
 */
class Session(val ctrl: ControlConnection) {
    var nodes by mutableStateOf<List<Node>>(emptyList())
        private set
    var meshes by mutableStateOf<Map<String, Mesh>>(emptyMap())
        private set
    /** null while connected; the reason once the connection is gone. */
    var lost by mutableStateOf<CloseReason?>(null)
        private set
    var loaded by mutableStateOf(false)
        private set
    /** The connection dropped and is being re-established (ControlConnection reconnects by itself). */
    var reconnecting by mutableStateOf(false)
        private set

    private val main = Handler(Looper.getMainLooper())
    private val refresh = Runnable { load() }

    private val onNodes: (JSONObject) -> Unit = { msg ->
        val out = ArrayList<Node>()
        msg.optJSONObject("nodes")?.let { all ->
            all.keys().forEach { meshId ->
                val list = all.optJSONArray(meshId) ?: return@forEach
                for (i in 0 until list.length()) list.optJSONObject(i)?.let { out.add(Node(it, meshId)) }
            }
        }
        nodes = out
        loaded = true
    }
    private val onMeshes: (JSONObject) -> Unit = { msg ->
        val a = msg.optJSONArray("meshes")
        meshes = if (a == null) emptyMap() else (0 until a.length()).mapNotNull { a.optJSONObject(it) }
            .map { Mesh(it) }.filter { it.id.isNotEmpty() }.associateBy { it.id }
    }
    private val onEvent: (JSONObject) -> Unit = { msg ->
        when (msg.optJSONObject("event")?.optString("action")) {
            // coalesce bursts of events into one refresh, like the desktop app
            "addnode", "removenode", "changenode", "nodeconnect", "meshchange", "createmesh", "deletemesh",
            "nodemeshchange" -> {
                main.removeCallbacks(refresh)
                main.postDelayed(refresh, 1500)
            }
        }
    }

    init {
        ctrl.on("nodes", onNodes)
        ctrl.on("meshes", onMeshes)
        ctrl.on("event", onEvent)
        ctrl.onClose = { reconnecting = false; lost = it ?: CloseReason("closed", null) }
        ctrl.onReconnecting = { on ->
            reconnecting = on
            if (!on) load()                     // signed in again: the lists may have changed meanwhile
        }
    }

    fun load() {
        ctrl.send("action" to "meshes")
        ctrl.send("action" to "nodes")
    }

    fun node(id: String): Node? = nodes.firstOrNull { it.id == id }

    /** What the signed-in account may do on this device. */
    fun caps(node: Node): NodeCaps =
        NodeCaps(Rights.node(ctrl.serverinfo, ctrl.userinfo, meshes[node.meshId]?.json, node.json))

    fun close() {
        main.removeCallbacks(refresh)
        ctrl.off("nodes", onNodes)
        ctrl.off("meshes", onMeshes)
        ctrl.off("event", onEvent)
        ctrl.close()
    }
}
