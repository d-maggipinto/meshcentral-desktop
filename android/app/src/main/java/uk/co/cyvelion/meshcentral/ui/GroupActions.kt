// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DriveFileMove
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.LocalOffer
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.randomHex

/** Group actions on the selected devices (device_list.GroupActions): op, label, icon, rights bit. */
private data class Op(val id: String, val label: String, val icon: ImageVector, val bit: Long)
private val OPS = listOf(
    Op("wake", "Wake up", Icons.Filled.WbSunny, 64), Op("sleep", "Sleep", Icons.Filled.Bedtime, 0x40000),
    Op("reset", "Restart", Icons.Filled.RestartAlt, 0x40000), Op("off", "Power off", Icons.Filled.PowerSettingsNew, 0x40000),
    Op("run", "Run commands", Icons.Filled.PlayArrow, 0x20000), Op("notify", "Device notification", Icons.Filled.Notifications, 0x4000),
    Op("tags", "Edit tags", Icons.Filled.LocalOffer, 4), Op("move", "Move to device group", Icons.AutoMirrored.Filled.DriveFileMove, 1),
    Op("uninstall", "Uninstall agent", Icons.Filled.DeleteForever, 0x8000), Op("delete", "Delete devices", Icons.Filled.Delete, 0x8000),
)

private fun rights(session: Session, n: Node) =
    Rights.node(session.ctrl.serverinfo, session.ctrl.userinfo, session.meshes[n.meshId]?.json, n.json)

private fun allowed(session: Session, op: Op, n: Node): Boolean {
    val r = rights(session, n)
    if (op.id == "uninstall") return n.online && (r == Rights.FULL || r and 0x8000L != 0L)
    return r == Rights.FULL || r and op.bit != 0L
}

/**
 * The action sheet for several devices. Every action goes only to the devices the account has the right for; the
 * rest are counted as skipped (the server would refuse them anyway).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GroupActionsSheet(session: Session, nodes: List<Node>, onDismiss: () -> Unit, onDone: () -> Unit) {
    val ctx = LocalContext.current
    var dialog by remember { mutableStateOf<Op?>(null) }
    val ops = OPS.filter { op -> nodes.any { allowed(session, op, it) } }
    val me = session.ctrl.userinfo
    val need2fa = session.ctrl.serverinfo.optLong("features") and 0x40000L != 0L &&
        listOf("otpsecret", "otphkeys", "otpekey", "otpduo").none { me?.has(it) == true && me.opt(it) != false }

    ModalBottomSheet(onDismiss) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 12.dp)) {
            Text("${nodes.size} device(s) selected", Modifier.padding(horizontal = 24.dp, vertical = 4.dp),
                style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text("Actions go only to the devices your account has the right for.", Modifier.padding(horizontal = 24.dp),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            HorizontalDivider(Modifier.padding(top = 8.dp))
            if (need2fa) Text("This server requires two-factor authentication before using group actions.",
                Modifier.padding(24.dp), color = MaterialTheme.colorScheme.error)
            else if (ops.isEmpty()) Text("No action is allowed on these devices.", Modifier.padding(24.dp))
            else ops.forEach { op ->
                val n = nodes.count { allowed(session, op, it) }
                ListItem(headlineContent = { Text(op.label) },
                    supportingContent = if (n < nodes.size) ({ Text("$n of ${nodes.size} device(s)") }) else null,
                    leadingContent = { Icon(op.icon, null, tint = if (op.id in listOf("delete", "uninstall", "off"))
                        MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary) },
                    modifier = Modifier.clickable {
                        if (op.id != "wake") dialog = op else {
                            // nothing to confirm: sent straight away
                            val ok = nodes.filter { allowed(session, op, it) }
                            session.ctrl.send("action" to "wakedevices", "nodeids" to JSONArray().apply { ok.forEach { put(it.id) } })
                            Toast.makeText(ctx, "Wake-up sent to ${ok.size} device(s)", Toast.LENGTH_SHORT).show()
                            onDone()
                        }
                    })
            }
        }
    }

    val op = dialog ?: return
    val ok = nodes.filter { allowed(session, op, it) }
    val skipped = nodes.size - ok.size
    val ids = JSONArray().apply { ok.forEach { put(it.id) } }
    fun finish(msg: String) {
        Toast.makeText(ctx, msg + if (skipped > 0) " ($skipped skipped: no permission)" else "", Toast.LENGTH_SHORT).show()
        dialog = null
        onDone()
    }
    val close = { dialog = null }
    when (op.id) {
        "sleep", "reset", "off" -> ConfirmDialog("${op.label} ${ok.size} device(s)?", "Unsaved work on the devices may be lost.",
            op.label, close) {
            session.ctrl.send("action" to "poweraction", "nodeids" to ids,
                "actiontype" to mapOf("sleep" to 4, "reset" to 3, "off" to 2)[op.id])
            finish("${op.label} sent to ${ok.size} device(s)")
        }
        "delete" -> TypedConfirmDialog("Delete ${ok.size} device(s)?",
            "${ok.count { it.online }} online, ${ok.count { !it.online }} offline. The devices and their history are removed from the server.",
            "Delete", close) {
            session.ctrl.send("action" to "removedevices", "nodeids" to ids); finish("Removed ${ok.size} device(s)")
        }
        "uninstall" -> TypedConfirmDialog("Uninstall the agent from ${ok.size} device(s)?",
            "They can only be managed again after installing a new agent. The device records stay on the server.",
            "Uninstall", close) {
            session.ctrl.send("action" to "uninstallagent", "nodeids" to ids); finish("Uninstall sent to ${ok.size} device(s)")
        }
        "notify" -> NotifyDialog(close) { type, title, msg, minutes ->
            if (type == 2) session.ctrl.send("action" to "toast", "nodeids" to ids, "title" to title, "msg" to msg)
            else ok.forEach { n ->
                val m = JSONObject().put("action", "msg").put("type", if (type == 1) "messagebox" else "alertbox")
                    .put("nodeid", n.id).put("title", title).put("msg", msg)
                if (type == 1) m.put("timeout", minutes * 60000)
                session.ctrl.send(m)
            }
            finish("Notification sent to ${ok.size} device(s)")
        }
        "tags" -> TagsDialog(session, close) { mode, want ->
            ok.forEach { n ->
                val new = when (mode) { 2 -> want; 1 -> n.tags + want.filter { it !in n.tags }; else -> n.tags.filter { it !in want } }
                if (new != n.tags) session.ctrl.send("action" to "changedevice", "nodeid" to n.id, "tags" to new.joinToString(","))
            }
            finish("Tags changed")
        }
        "move" -> MoveDialog(session, ok, close) { meshId ->
            session.ctrl.send("action" to "changeDeviceMesh", "nodeids" to ids, "meshid" to meshId); finish("Moved ${ok.size} device(s)")
        }
        "run" -> GroupRunDialog(session, ok) { dialog = null; onDone() }
    }
}

@Composable
private fun ConfirmDialog(title: String, text: String, action: String, onClose: () -> Unit, onOk: () -> Unit) =
    AlertDialog(onDismissRequest = onClose, title = { Text(title) }, text = { Text(text) },
        confirmButton = { TextButton(onOk) { Text(action, color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })

/** Like the desktop's "Confirm" check box: the action stays disabled until it is ticked. */
@Composable
private fun TypedConfirmDialog(title: String, text: String, action: String, onClose: () -> Unit, onOk: () -> Unit) {
    var sure by remember { mutableStateOf(false) }
    AlertDialog(onDismissRequest = onClose, title = { Text(title) },
        text = {
            Column {
                Text(text)
                Row(Modifier.clickable { sure = !sure }.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(sure, { sure = it }); Text("Confirm")
                }
            }
        },
        confirmButton = { TextButton(onOk, enabled = sure) { Text(action, color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun NotifyDialog(onClose: () -> Unit, onSend: (Int, String, String, Int) -> Unit) {
    var type by remember { mutableStateOf(2) }
    var title by remember { mutableStateOf("") }
    var msg by remember { mutableStateOf("") }
    var minutes by remember { mutableStateOf(2) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Device notification") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(2 to "Toast", 1 to "Message box", 3 to "Alert box").forEach { (v, l) -> FilterChip(type == v, { type = v }, { Text(l) }) }
                }
                OutlinedTextField(title, { title = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("Title") },
                    placeholder = { Text("MeshCentral") }, singleLine = true)
                OutlinedTextField(msg, { msg = it }, Modifier.fillMaxWidth().heightIn(min = 96.dp), label = { Text("Message") })
                if (type == 1) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(2, 10, 30, 60, 0).forEach { m -> FilterChip(minutes == m, { minutes = m }, { Text(if (m == 0) "Until dismissed" else "$m min") }) }
                }
            }
        },
        confirmButton = { TextButton({ onSend(type, title.trim().ifEmpty { "MeshCentral" }, msg, minutes) }, enabled = msg.isNotBlank()) { Text("Send") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun TagsDialog(session: Session, onClose: () -> Unit, onOk: (Int, List<String>) -> Unit) {
    var mode by remember { mutableStateOf(1) }
    var text by remember { mutableStateOf("") }
    val inUse = session.nodes.flatMap { it.tags }.distinct().sortedBy { it.lowercase() }
    AlertDialog(onDismissRequest = onClose, title = { Text("Edit tags") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(1 to "Add", 2 to "Set", 3 to "Remove").forEach { (v, l) -> FilterChip(mode == v, { mode = v }, { Text(l) }) }
                }
                OutlinedTextField(text, { text = it.take(4096) }, Modifier.fillMaxWidth(), label = { Text("Tags") },
                    placeholder = { Text("Tag1, Tag2") }, singleLine = true)
                if (inUse.isNotEmpty()) Text("In use: " + inUse.joinToString(", "), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        },
        confirmButton = { TextButton({
            onOk(mode, text.split(",").map { it.trim() }.filter { it.isNotEmpty() && it.length < 64 }.distinct())
        }) { Text("OK") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun MoveDialog(session: Session, nodes: List<Node>, onClose: () -> Unit, onOk: (String) -> Unit) {
    val cur = nodes.map { it.meshId }.toSet()
    val types = cur.mapNotNull { session.meshes[it]?.type }.toSet()
    // groups of the same type where the account may add devices (rights 1 = edit group, 4 = manage devices)
    val targets = session.meshes.values.filter { m ->
        val r = Rights.mesh(session.ctrl.serverinfo, session.ctrl.userinfo, m.json)
        (r == Rights.FULL || (r and 1L != 0L && r and 4L != 0L)) && m.type in types && !(nodes.size == 1 && m.id in cur)
    }.sortedBy { it.name.lowercase() }
    var pick by remember { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Move to device group") },
        text = {
            if (targets.isEmpty()) Text("No other device group of the same type where you may add devices.")
            else Column(Modifier.verticalScroll(rememberScrollState())) {
                targets.forEach { m ->
                    ListItem(headlineContent = { Text(m.name) }, modifier = Modifier.clickable { pick = m.id },
                        leadingContent = { androidx.compose.material3.RadioButton(pick == m.id, { pick = m.id }) })
                }
            }
        },
        confirmButton = { TextButton({ pick?.let(onOk) }, enabled = pick != null) { Text("Move") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

/**
 * Run commands on several devices (device_list.GroupRunDialog): one request per device with its own responseid
 * (the output carries only the responseid), outputs listed per device.
 */
@Composable
private fun GroupRunDialog(session: Session, nodes: List<Node>, onClose: () -> Unit) {
    val types = buildList {
        if (nodes.any { it.isWindows }) { add(1 to "Command"); add(2 to "PowerShell") }
        if (nodes.any { it.hasAgent && !it.isWindows }) add(3 to "Shell")
        if (nodes.any { rights(session, it).let { r -> r == Rights.FULL || r and 24L == 24L } }) add(4 to "Agent console")
    }
    var type by remember { mutableStateOf(types.firstOrNull()?.first ?: 3) }
    var runAs by remember { mutableStateOf(0) }
    var cmds by remember { mutableStateOf("") }
    val out = remember { mutableStateMapOf<String, String>() }      // node id -> output / status
    val rids = remember { HashMap<String, String>() }               // responseid -> node id
    var started by remember { mutableStateOf(false) }
    val main = remember { Handler(Looper.getMainLooper()) }

    DisposableEffect(Unit) {
        val onAck: (JSONObject) -> Unit = { m ->
            rids[m.optString("responseid")]?.let { nid ->
                val r = m.optString("result")
                if (r.isNotEmpty() && r != "OK") out[nid] = "Not run: $r" else if (out[nid] == "Sending…") out[nid] = "Running…"
            }
        }
        val onMsg: (JSONObject) -> Unit = { m ->
            if (m.optString("type") == "runcommands") rids[m.optString("responseid")]?.let { nid ->
                out[nid] = m.optString("result").ifEmpty { "(no output)" }
            }
        }
        session.ctrl.on("runcommands", onAck)
        session.ctrl.on("msg", onMsg)
        onDispose { main.removeCallbacksAndMessages(null); session.ctrl.off("runcommands", onAck); session.ctrl.off("msg", onMsg) }
    }

    fun run() {
        started = true
        val base = "mcdgrun" + randomHex()
        nodes.forEachIndexed { i, n ->
            val rid = "$base-$i"
            rids[rid] = n.id
            out[n.id] = "Sending…"
            val req = JSONObject().put("action", "runcommands").put("nodeids", JSONArray().put(n.id)).put("type", type)
                .put("cmds", cmds).put("reply", true).put("responseid", rid)
            if (type != 4) req.put("runAsUser", runAs)
            session.ctrl.send(req)
        }
        main.postDelayed({ nodes.forEach { n -> if (out[n.id] == "Sending…" || out[n.id] == "Running…") out[n.id] = "No output after 120 s." } }, 120_000)
    }

    AlertDialog(onDismissRequest = onClose, title = { Text("Run commands on ${nodes.size} device(s)") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!started) {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        types.forEach { (v, l) -> FilterChip(type == v, { type = v }, { Text(l) }) }
                    }
                    if (type != 4) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(0 to "As agent", 1 to "As user, else agent", 2 to "Must run as user").forEach { (v, l) ->
                            FilterChip(runAs == v, { runAs = v }, { Text(l) }) }
                    }
                    OutlinedTextField(cmds, { cmds = it }, Modifier.fillMaxWidth().heightIn(min = 96.dp), label = { Text("Commands") },
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace))
                } else nodes.forEach { n ->
                    Text(n.name, fontWeight = FontWeight.SemiBold)
                    SelectionContainer {
                        Text(out[n.id] ?: "", Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                            style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                    }
                    HorizontalDivider()
                }
            }
        },
        confirmButton = { if (!started) TextButton({ run() }, enabled = cmds.isNotBlank() && types.isNotEmpty()) { Text("Run") } },
        dismissButton = { TextButton(onClose) { Text("Close") } })
}
