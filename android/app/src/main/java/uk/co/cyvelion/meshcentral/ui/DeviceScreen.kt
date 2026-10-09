// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.Notes
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.DesktopWindows
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Session
import java.text.DateFormat
import java.util.Date

/** Agent type names (the web UI's agentsStr, same table as the desktop app's info_panel.AGENT_TYPES). */
private val AGENT_TYPES = listOf("Unknown", "Windows 32bit console", "Windows 64bit console", "Windows 32bit service",
    "Windows 64bit service", "Linux 32bit", "Linux 64bit", "MIPS", "XENx86", "Android", "Linux ARM",
    "macOS x86-32bit", "Android x86", "PogoPlug ARM", "Android", "Linux Poky x86-32bit",
    "macOS x86-64bit", "ChromeOS", "Linux Poky x86-64bit", "Linux NoKVM x86-32bit",
    "Linux NoKVM x86-64bit", "Windows MinCore console", "Windows MinCore service", "NodeJS",
    "ARM-Linaro", "ARMv6l / ARMv7l", "ARMv8 64bit", "ARMv6l / ARMv7l / NoKVM", "MIPS24KC (OpenWRT)",
    "Apple Silicon", "FreeBSD x86-64", "Unknown", "Linux ARM 64 bit", "Alpine Linux x86 64 Bit (MUSL)",
    "Assistant (Windows)", "Armada370 - ARM32/HF (libc/2.26)", "OpenWRT x86-64", "OpenBSD x86-64",
    "Unknown", "Unknown", "MIPSEL24KC (OpenWRT)", "ARMADA/CORTEX-A53/MUSL (OpenWRT)",
    "Windows ARM 64bit console", "Windows ARM 64bit service", "ARMVIRT32 (OpenWRT)", "RISC-V x86-64")

/** poweraction actiontype values (general_actions.POWER). */
private val POWER = listOf(Triple("Wake up", 100, false), Triple("Sleep", 4, true), Triple("Restart", 3, true),
    Triple("Power off", 2, true))

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun DeviceScreen(app: McdApp, session: Session, id: String, onBack: () -> Unit, onOpen: (String) -> Unit) {
    val node = session.node(id)
    val ctx = LocalContext.current
    var tab by rememberSaveable { mutableStateOf(0) }
    var powerMenu by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<Pair<String, Int>?>(null) }
    var runOpen by remember { mutableStateOf(false) }
    var manageOpen by remember { mutableStateOf(false) }

    Scaffold(topBar = {
        TopAppBar(
            title = { },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { if (node != null) IconButton({ manageOpen = true }) { Icon(Icons.Filled.MoreVert, "Device actions") } })
    }) { pad ->
        if (node == null) {
            Text("This device is not in the list any more (removed, or the agent is offline).",
                Modifier.padding(pad).padding(24.dp))
            return@Scaffold
        }
        val caps = session.caps(node)
        val live = node.online && node.hasAgent
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            // header: icon, name, OS, status, group
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                OsAvatar(node, 60.dp)
                Column(Modifier.weight(1f).padding(start = 16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(node.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold,
                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                    if (node.os.isNotEmpty()) Text(node.os, style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        StatusPill(node.online)
                        session.meshes[node.meshId]?.name?.let {
                            Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
            // actions: like the desktop app's action bar (offered by rights, enabled while the agent is online)
            data class Act(val label: String, val icon: ImageVector, val enabled: Boolean, val tint: Color?, val run: () -> Unit)
            val acts = buildList {
                if (node.hasAgent) {
                    if (caps.desktop) add(Act("Desktop", Icons.Filled.DesktopWindows, live, null) { onOpen("desktop") })
                    if (caps.terminal) add(Act("Terminal", Icons.Filled.Terminal, live, null) { onOpen("terminal") })
                    if (caps.files) add(Act("Files", Icons.Filled.Folder, live, null) { onOpen("files") })
                    if (caps.chat) add(Act("Chat", Icons.AutoMirrored.Filled.Chat, live, null) { onOpen("chat") })
                    if (caps.runCommands) add(Act("Run", Icons.Filled.PlayArrow, live, null) { runOpen = true })
                }
                if (caps.wake || caps.power) add(Act("Power", Icons.Filled.PowerSettingsNew, true, Color(0xFFD9534F)) { powerMenu = true })
            }
            if (!node.hasAgent && acts.isEmpty()) Text("This device has no agent: only its details are shown.",
                Modifier.padding(horizontal = 20.dp, vertical = 8.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                acts.chunked(3).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        row.forEach { a ->
                            Box(Modifier.weight(1f)) {
                                if (a.tint != null) ActionTile(a.label, a.icon, a.enabled, tint = a.tint, onClick = a.run)
                                else ActionTile(a.label, a.icon, a.enabled, onClick = a.run)
                                if (a.label == "Power") DropdownMenu(powerMenu, { powerMenu = false }) {
                                    POWER.forEach { (label, type, needsOnline) ->
                                        val ok = if (type == 100) caps.wake else caps.power && live
                                        DropdownMenuItem({ Text(label) }, enabled = ok && (!needsOnline || live), onClick = {
                                            powerMenu = false
                                            if (type != 100) confirm = label to type else {
                                                sendPower(session, node, type)
                                                Toast.makeText(ctx, "$label sent to ${node.name}", Toast.LENGTH_SHORT).show()
                                            }
                                        })
                                    }
                                }
                            }
                        }
                        repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
                if (node.hasAgent && !node.online) Text("The agent is offline: remote tools return when it reconnects.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            // tools: like the desktop app's Overview / Tools pages (offered by rights)
            val tools = buildList {
                add(Act("Events", Icons.Filled.History, true, Color(0xFF52607A)) { onOpen("events") })
                add(Act("Notes", Icons.AutoMirrored.Filled.Notes, true, Color(0xFF52607A)) { onOpen("notes") })
                if (node.hasAgent) {
                    if (caps.tools) add(Act("Processes", Icons.Filled.Memory, live, Color(0xFF00838F)) { onOpen("processes") })
                    if (caps.tools) add(Act("Services", Icons.Filled.Settings, live, Color(0xFF00838F)) { onOpen("services") })
                    if (caps.software) add(Act("Software", Icons.Filled.Apps, live, Color(0xFF00838F)) { onOpen("software") })
                    if (caps.console) add(Act("Console", Icons.Filled.Code, live, Color(0xFF00838F)) { onOpen("console") })
                    if (caps.registry && node.isWindows) add(Act("Registry", Icons.Filled.AccountTree, live, Color(0xFF00838F)) { onOpen("registry") })
                }
            }
            Text("TOOLS", Modifier.padding(start = 20.dp, top = 8.dp), style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
            Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                tools.chunked(3).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        row.forEach { a -> ActionTile(a.label, a.icon, a.enabled, Modifier.weight(1f), tint = a.tint!!, onClick = a.run) }
                        repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
            val tabs = if (node.hasAgent) listOf("General", "Hardware", "Network") else listOf("General")
            if (tabs.size > 1) SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                tabs.forEachIndexed { i, t ->
                    SegmentedButton(tab == i, { tab = i }, SegmentedButtonDefaults.itemShape(i, tabs.size)) { Text(t) }
                }
            }
            when (tab.coerceAtMost(tabs.size - 1)) {
                0 -> GeneralTab(session, node)
                1 -> AgentInfoTab(session, node, "getsysinfo") { m -> m.optJSONObject("hardware") }
                2 -> AgentInfoTab(session, node, "getnetworkinfo") { m -> m.optJSONObject("netif2") }
            }
        }
        confirm?.let { (label, type) ->
            AlertDialog(onDismissRequest = { confirm = null }, title = { Text("$label ${node.name}?") },
                text = { Text("Unsaved work on the device may be lost.") },
                confirmButton = { TextButton({
                    confirm = null
                    sendPower(session, node, type)
                    Toast.makeText(ctx, "$label sent to ${node.name}", Toast.LENGTH_SHORT).show()
                }) { Text(label, color = MaterialTheme.colorScheme.error) } },
                dismissButton = { TextButton({ confirm = null }) { Text("Cancel") } })
        }
        if (runOpen) RunCommandDialog(session, node) { runOpen = false }
        if (manageOpen) DeviceManageSheet(app, session, node, onDismiss = { manageOpen = false }, onDeleted = { manageOpen = false; onBack() })
    }
}

private fun sendPower(session: Session, node: Node, type: Int) =
    session.ctrl.send("action" to "poweraction", "nodeids" to JSONArray().put(node.id), "actiontype" to type)

@Composable
private fun InfoRows(rows: List<Pair<String, String>>) {
    SectionCard(title = "Details") {
        SelectionContainer {
            Column { rows.forEachIndexed { i, (k, v) -> InfoLine(k, v, last = i == rows.size - 1) } }
        }
    }
}

@Composable
private fun GeneralTab(session: Session, node: Node) {
    val j = node.json
    val agent = j.optJSONObject("agent")
    val rows = buildList {
        if (node.host.isNotEmpty()) add("Host" to node.host)
        if (node.description.isNotEmpty()) add("Description" to node.description)
        if (node.os.isNotEmpty()) add("Operating system" to node.os)
        if (node.mtype == 3) add("Agent" to "Local device (no agent)")
        else if (agent != null) {
            val t = agent.optInt("id")
            var name = AGENT_TYPES.getOrNull(t) ?: AGENT_TYPES[0]
            if (agent.optInt("ver") != 0) name += " v" + agent.optInt("ver")
            if (agent.has("root") && !agent.optBoolean("root") && node.online) name += ", Restricted"
            add("Agent" to name)
        }
        j.optString("ip").takeIf { it.isNotEmpty() }?.let { add("IP address" to it) }
        j.optJSONArray("users")?.let { a -> if (a.length() > 0) add("Logged in users" to (0 until a.length()).joinToString(", ") { a.optString(it) }) }
        if (node.tags.isNotEmpty()) add("Tags" to node.tags.joinToString(", "))
        j.optLong("lastconnect").takeIf { it > 0 }?.let {
            add("Last agent connection" to DateFormat.getDateTimeInstance().format(Date(it)))
        }
    }
    InfoRows(rows)
}

/** Hardware (getsysinfo -> hardware) or Network (getnetworkinfo -> netif2) as an expandable tree. */
@Composable
private fun AgentInfoTab(session: Session, node: Node, action: String, extract: (JSONObject) -> JSONObject?) {
    var data by remember(node.id, action) { mutableStateOf<JSONObject?>(null) }
    var loading by remember(node.id, action) { mutableStateOf(true) }
    fun request() {
        loading = true
        if (action == "getsysinfo") session.ctrl.send("action" to action, "nodeid" to node.id, "cache" to true, "nodeinfo" to true)
        else session.ctrl.send("action" to action, "nodeid" to node.id)
    }
    DisposableEffect(node.id, action) {
        // broadcast-style reply without our responseid: listen for the action, filter by device
        val cb: (JSONObject) -> Unit = { m ->
            if (m.optString("nodeid", node.id) == node.id) { data = extract(m); loading = false }
        }
        session.ctrl.on(action, cb)
        request()
        onDispose { session.ctrl.off(action, cb) }
    }
    SectionCard(title = if (action == "getsysinfo") "Hardware" else "Network") {
        Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (loading) "Loading…" else if (data == null || data!!.length() == 0) "No information reported by the agent." else "Tap a section to open it",
                Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (loading) CircularProgressIndicator(Modifier.padding(12.dp).width(20.dp), strokeWidth = 2.dp)
            else IconButton({ request() }) { Icon(Icons.Filled.Refresh, "Refresh") }
        }
        data?.let { d ->
            SelectionContainer {
                Column { d.keys().forEach { k -> JsonNode(label(k), d.opt(k), 0) } }
            }
        }
    }
}

private fun label(k: String) = k.replace('_', ' ').replaceFirstChar { it.uppercase() }

@Composable
private fun JsonNode(name: String, v: Any?, depth: Int, startOpen: Boolean = false) {
    val indent = (16 + depth * 16).dp
    when (v) {
        is JSONObject, is JSONArray -> {
            var open by rememberSaveable(name, depth) { mutableStateOf(startOpen) }
            Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(start = indent, end = 16.dp, top = 10.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text(name, Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                if (v is JSONArray) Text("${v.length()}", color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall)
                Icon(if (open) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null, Modifier.padding(start = 8.dp))
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
            if (open) {
                if (v is JSONObject) v.keys().forEach { k -> JsonNode(label(k), v.opt(k), depth + 1) }
                else if (v is JSONArray) for (i in 0 until v.length()) {
                    val item = v.opt(i)
                    // name array items by their most telling field
                    val n = (item as? JSONObject)?.let { o ->
                        listOf("address", "Product", "mount_point", "name", "Name", "caption", "Caption")
                            .firstNotNullOfOrNull { k -> o.optString(k).takeIf { it.isNotEmpty() } }
                    } ?: "${i + 1}"
                    JsonNode(n, item, depth + 1)
                }
            }
        }
        else -> {
            Row(Modifier.fillMaxWidth().padding(start = indent, end = 16.dp, top = 8.dp, bottom = 8.dp)) {
                Text(name, Modifier.width(140.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(v?.toString() ?: "", Modifier.weight(1f))
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
        }
    }
}
