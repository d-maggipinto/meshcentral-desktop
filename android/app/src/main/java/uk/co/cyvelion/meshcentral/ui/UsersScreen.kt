// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Campaign
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.data.Site
import uk.co.cyvelion.meshcentral.net.ControlConnection
import java.text.DateFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/*
 * Users (admin_panel.py UsersPanel + user_panel.py UserPage): the web UI's "My Users" list and "General - <user>"
 * page, with the same control-channel actions:
 *   users / wssessioncount (+ event wssessioncount)   adduser (with responseid: {result:'ok' | error})
 *   edituser {id, email|realname|phone|flags+removeRights|siteadmin(+quota)|consent|groups}
 *   changeuserpass {userid, pass, removeMultiFactor, resetNextLogin[, hint]}   (no reply: event accountchange msgid 75)
 *   deleteuser {userid, username}   notifyuser {userid, msg}   userbroadcast {msg, target?, maxtime}
 *   addmeshuser / removemeshuser / adddeviceuser   addusertousergroup / removeuserfromusergroup
 *   getNotes / setNotes {id: user id}   previousLogins {userid}   events {userid, limit[, filter]}
 * Changes come back as event accountchange / accountcreate / accountremove: the list is read again.
 *
 * The Adm* helpers (internal, prefixed) are shared with UserGroupsScreen.kt.
 */

internal const val ADM_FULL = 0xFFFFFFFFL
private const val FEAT_NOUSERS = 0x4L
private const val FEAT_PASSWORD_HINT = 0x10000L
private const val FEAT_LDAP_SSPI = 0x80000L
private const val FEAT_USERNAME_IS_EMAIL = 0x200000L
private const val FEAT_SMS = 0x02000000L
private const val BROADCAST_MAX = 512

/** Same regex as the server's common.validateEmail (needs a TLD). */
private val EMAIL_RE = Regex("""^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$""")

// ---- shared helpers (users + user groups) ------------------------------------------------------

internal fun admFeatures(ctrl: ControlConnection) = ctrl.serverinfo.optLong("features", 0L)
internal fun admSiteRights(ctrl: ControlConnection) = Site.rights(ctrl.userinfo)
internal fun admDomain(id: String) = id.split("/").getOrNull(1) ?: ""
internal fun admShortId(id: String) = id.split("/").getOrNull(2) ?: id
internal fun admGuest(ctrl: ControlConnection) = ctrl.serverinfo.opt("guestdevicesharing") != false
internal fun admLinks(o: JSONObject?): JSONObject = o?.optJSONObject("links") ?: JSONObject()
internal fun admLinkRights(links: JSONObject, id: String) = links.optJSONObject(id)?.optLong("rights", 0L) ?: 0L

/** Epoch seconds, epoch ms or an ISO-8601 string as epoch ms (0 if unknown). */
internal fun admMillis(v: Any?): Long = when (v) {
    is Number -> v.toLong().let { if (it < 100_000_000_000L) it * 1000 else it }
    is String -> try { java.time.Instant.parse(v).toEpochMilli() } catch (e: Exception) { 0L }
    else -> 0L
}

/** Epoch seconds, epoch ms or an ISO-8601 string, as local date and time. */
internal fun admTime(v: Any?): String {
    val ms = admMillis(v)
    if (ms <= 0) return if (v is String) v else ""
    return DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(ms))
}

/** (bit, label, indent, group only): web UI p20showAddMeshUserDialog */
private val DEVICE_RIGHTS = listOf(
    Triple(1L, "Edit Device Group", 0) to true, Triple(2L, "Manage Device Group Users", 0) to true,
    Triple(4L, "Manage Device Group Computers", 0) to true,
    Triple(8L, "Remote Control & Relay", 0) to false, Triple(256L, "Remote View Only", 1) to false,
    Triple(4096L, "Limited Input Only", 1) to false, Triple(524288L, "Guest Sharing", 1) to false,
    Triple(65536L, "No Desktop Access", 1) to false, Triple(512L, "No Terminal Access", 1) to false,
    Triple(1024L, "No File Access", 1) to false, Triple(4194304L, "No Registry Access", 1) to false,
    Triple(8388608L, "No Software", 1) to false, Triple(2048L, "No Intel AMT", 1) to false,
    Triple(16L, "Mesh Agent Console", 0) to false, Triple(32L, "Server Files", 0) to false,
    Triple(64L, "Wake Devices", 0) to false, Triple(128L, "Edit Device Notes", 0) to false,
    Triple(8192L, "Show Only Own Events", 0) to false, Triple(16384L, "Chat & Notify", 0) to false,
    Triple(32768L, "Uninstall Agent / Delete Device", 0) to false, Triple(131072L, "Remote Commands", 0) to false,
    Triple(262144L, "Reset / Power Off", 0) to false, Triple(1048576L, "Device Details", 0) to false,
    Triple(2097152L, "Use as Relay", 0) to false,
)
private val UNDER_CONTROL = setOf(256L, 4096L, 524288L, 65536L, 512L, 1024L, 4194304L, 8388608L, 2048L)

private fun controlDetail(r: Long, guest: Boolean): String {
    val parts = listOf(256L to "No Input", 512L to "No Terminal", 1024L to "No Files", 4194304L to "No Registry",
        8388608L to "No Software", 2048L to "No AMT", 4096L to "Limited Input", 65536L to "No Desktop")
        .filter { r and it.first != 0L }.map { it.second }.toMutableList()
    if (guest && r and 524288L != 0L) parts.add("Guest Share")
    return if (parts.isEmpty()) "Control" else "Control (${parts.joinToString(", ")})"
}

private fun rightsTail(r: Long) = listOf(16L to "Console", 32L to "Server Files", 64L to "Wake", 128L to "Notes",
    8192L to "Limit Events", 16384L to "Chat", 32768L to "Uninstall", 131072L to "Commands", 262144L to "Reset/Off",
    524288L to "Sharing", 1048576L to "Details", 2097152L to "Relay").filter { r and it.first != 0L }.map { it.second }

/** web UI makeDeviceGroupRightsString */
internal fun admGroupRightsText(r: Long, guest: Boolean): String {
    if (r == ADM_FULL) return "Full Rights"
    val s = listOf(1L to "Edit Group", 2L to "Manage Users", 4L to "Manage Devices").filter { r and it.first != 0L }
        .map { it.second }.toMutableList()
    if (r and 8L != 0L) s.add(controlDetail(r, guest))
    s += rightsTail(r)
    return s.joinToString(", ").ifEmpty { "No Rights" }
}

/** web UI makeUserDeviceRightsString */
internal fun admDeviceRightsText(r: Long, guest: Boolean): String {
    if (r == 57592L) return "Full Device Rights"
    val s = (if (r and 8L != 0L) listOf(controlDetail(r, guest)) else emptyList()) + rightsTail(r)
    return s.joinToString(", ").ifEmpty { "No Rights" }
}

/** web UI user consent string; bits of the user / group or forced by the server */
internal fun admConsentText(o: JSONObject, serverinfo: JSONObject): String {
    val c = o.optLong("consent", 0L) or serverinfo.optLong("consent", 0L)
    var f = mutableListOf<String>()
    when {
        c and 0x40 != 0L && c and 0x8 != 0L -> f.add("Desktop Prompt+Toolbar")
        c and 0x40 != 0L -> f.add("Desktop Toolbar")
        c and 0x8 != 0L -> f.add("Desktop Prompt")
        c and 0x1 != 0L -> f.add("Desktop Notify")
    }
    for ((prompt, notify, name) in listOf(Triple(0x10L, 0x2L, "Terminal"), Triple(0x20L, 0x4L, "Files"), Triple(0x100L, 0x80L, "Registry"))) {
        if (c and prompt != 0L) f.add("$name Prompt") else if (c and notify != 0L) f.add("$name Notify")
    }
    if (c == 0x87L) f = mutableListOf("Always Notify")
    if (c and 0x138L == 0x138L) f = mutableListOf("Always Prompt")
    return f.joinToString(", ").ifEmpty { "None" }
}

/** An error / information dialog. */
@Composable
internal fun AdmMessage(title: String, text: String, onClose: () -> Unit) =
    AlertDialog(onDismissRequest = onClose, title = { Text(title) }, text = { Text(text) },
        confirmButton = { TextButton(onClose) { Text("OK") } })

@Composable
internal fun AdmConfirm(title: String, text: String, action: String, onDismiss: () -> Unit, onOk: () -> Unit) =
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) }, text = { Text(text) },
        confirmButton = { TextButton({ onDismiss(); onOk() }) { Text(action, color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })

/** A dialog whose body scrolls (long check-box lists). */
@Composable
internal fun AdmFormDialog(title: String, ok: String = "OK", okEnabled: Boolean = true, onDismiss: () -> Unit,
                           onOk: (() -> Unit)?, content: @Composable () -> Unit) =
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) },
        text = { Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState())) { content() } },
        confirmButton = { if (onOk != null) TextButton(onOk, enabled = okEnabled) { Text(ok) } },
        dismissButton = { TextButton(onDismiss) { Text(if (onOk == null) "Close" else "Cancel") } })

@Composable
internal fun AdmCheck(label: String, checked: Boolean, enabled: Boolean = true, indent: Int = 0, onChange: (Boolean) -> Unit) =
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled) { onChange(!checked) }.padding(start = (indent * 20).dp),
        verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked, onChange, enabled = enabled)
        Text(label, style = MaterialTheme.typography.bodyMedium,
            color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f))
    }

@Composable
internal fun AdmHeading(text: String) =
    Text(text, Modifier.padding(top = 10.dp, bottom = 2.dp), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)

/** A drop-down choice: options (id, label). */
@Composable
internal fun AdmPicker(label: String, options: List<Pair<String, String>>, selected: String?, enabled: Boolean = true,
                       onSelect: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Box {
            OutlinedButton({ open = true }, Modifier.fillMaxWidth(), enabled = enabled && options.isNotEmpty()) {
                Text(options.firstOrNull { it.first == selected }?.second ?: "None", Modifier.weight(1f),
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Icon(Icons.Filled.ArrowDropDown, null)
            }
            DropdownMenu(open, { open = false }) {
                options.forEach { (id, text) -> DropdownMenuItem({ Text(text) }, onClick = { open = false; onSelect(id) }) }
            }
        }
    }
}

/** Device-group (meshLevel) or device permission check boxes (web UI RightsDialog), with its rules. */
internal class AdmRights(private val meshLevel: Boolean, private val guest: Boolean, value: Long) {
    var full by mutableStateOf(meshLevel && value == ADM_FULL)
    var enabled by mutableStateOf(true)
    val checks = mutableStateMapOf<Long, Boolean>().apply {
        DEVICE_RIGHTS.forEach { (r, meshOnly) ->
            if ((meshOnly && !meshLevel) || (r.first == 524288L && !guest)) return@forEach
            put(r.first, value != ADM_FULL && value and r.first != 0L)
        }
    }

    fun set(value: Long) {
        full = meshLevel && value == ADM_FULL
        checks.keys.toList().forEach { checks[it] = value != ADM_FULL && value and it != 0L }
    }

    private fun on(b: Long) = checks[b] == true

    fun sensitive(bit: Long): Boolean {
        val nc = enabled && !(meshLevel && full)
        val rc = on(8L)
        return when {
            bit == 256L -> nc && rc
            bit == 4096L -> nc && rc && !on(256L)
            bit == 524288L -> nc && rc && (on(256L) || !on(4096L))
            bit in UNDER_CONTROL -> nc && rc
            else -> nc
        }
    }

    fun value(): Long {
        if (meshLevel && full) return ADM_FULL
        var v = checks.filter { it.value }.keys.fold(0L) { a, b -> a or b }
        if (v and 256L != 0L && v and 4096L != 0L) v = v and 4096L.inv()          // limited input only without view-only
        if (v and 524288L != 0L && !(v and 256L != 0L || v and 4096L == 0L)) v = v and 524288L.inv()
        if (v and 8L == 0L) UNDER_CONTROL.forEach { v = v and it.inv() }           // no remote control: drop its options
        return v
    }

    @Composable
    fun Editor() {
        if (meshLevel) AdmCheck("Full Administrator", full, enabled) { full = it }
        DEVICE_RIGHTS.forEach { (r, _) ->
            if (r.first in checks) AdmCheck(r.second, checks[r.first] == true, sensitive(r.first), r.third) { checks[r.first] = it }
        }
    }
}

/** Add / edit device-group permissions of a user or user group (web UI types 1 and 3). */
@Composable
internal fun AdmMeshRightsDialog(session: Session, links: JSONObject, domain: String, meshId: String?,
                                 onDismiss: () -> Unit, onOk: (String, Long) -> Unit) {
    val ctrl = session.ctrl
    val ids = if (meshId != null) listOf(meshId) else session.meshes.keys
        .filter { admDomain(it) == domain && !links.has(it) }.sortedBy { session.meshes[it]?.name?.lowercase() }
    var sel by remember { mutableStateOf(ids.firstOrNull()) }
    val rd = remember { AdmRights(true, admGuest(ctrl), if (meshId != null) admLinkRights(links, meshId) else 0L) }
    AdmFormDialog(if (meshId != null) "Edit Device Group Permissions" else "Add Device Group Permissions",
        okEnabled = sel != null, onDismiss = onDismiss, onOk = { sel?.let { onOk(it, rd.value()) } }) {
        AdmPicker("Device group", ids.map { it to (session.meshes[it]?.name ?: it) }, sel, enabled = meshId == null) { sel = it }
        if (ids.isEmpty()) Text("No other device groups.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        rd.Editor()
    }
}

/** Add / edit device permissions (web UI types 4 and 7): pick a device group you manage, then a device. */
@Composable
internal fun AdmDeviceRightsDialog(session: Session, links: JSONObject, nodeId: String?,
                                   onDismiss: () -> Unit, onOk: (String, Long) -> Unit) {
    val ctrl = session.ctrl
    val selMesh = nodeId?.let { session.node(it)?.meshId }
    val meshIds = session.meshes.values.filter {
        Rights.mesh(ctrl.serverinfo, ctrl.userinfo, it.json) and 7L != 0L || it.id == selMesh
    }.sortedBy { it.name.lowercase() }.map { it.id }
    var mesh by remember { mutableStateOf(selMesh ?: meshIds.firstOrNull()) }
    val nodes = session.nodes.filter { it.meshId == mesh }.sortedBy { it.name.lowercase() }
    var node by remember { mutableStateOf(nodeId) }
    val rd = remember { AdmRights(false, admGuest(ctrl), 0L) }
    LaunchedEffect(mesh) { if (nodeId == null) node = nodes.firstOrNull()?.id }
    LaunchedEffect(node) {
        rd.set(node?.let { admLinkRights(links, it) } ?: 0L)
        rd.enabled = node != null
    }
    AdmFormDialog(if (nodeId != null) "Edit Device Permissions" else "Add Device Permissions", okEnabled = node != null,
        onDismiss = onDismiss, onOk = { node?.let { onOk(it, rd.value()) } }) {
        AdmPicker("Device group", meshIds.map { it to (session.meshes[it]?.name ?: it) }, mesh, nodeId == null) { mesh = it }
        AdmPicker("Device", nodes.map { it.id to it.name }, node, nodeId == null) { node = it }
        rd.Editor()
    }
}

/** web UI p20editmeshconsent: bits forced by the server are ticked and fixed. */
@Composable
internal fun AdmConsentDialog(title: String, current: Long, server: Long, onDismiss: () -> Unit, onOk: (Long) -> Unit) {
    val c = remember { mutableStateMapOf<Long, Boolean>() }
    val sections = listOf("Desktop" to listOf(0x1L to "Notify user", 0x8L to "Prompt for user consent", 0x40L to "Show connection toolbar"),
        "Terminal" to listOf(0x2L to "Notify user", 0x10L to "Prompt for user consent"),
        "Files" to listOf(0x4L to "Notify user", 0x20L to "Prompt for user consent"),
        "Registry" to listOf(0x80L to "Notify user", 0x100L to "Prompt for user consent"))
    AdmFormDialog(title, onDismiss = onDismiss, onOk = {
        onOk(sections.flatMap { it.second }.filter { c[it.first] ?: ((current or server) and it.first != 0L) }.fold(0L) { a, b -> a or b.first })
    }) {
        sections.forEach { (name, items) ->
            AdmHeading(name)
            items.forEach { (bit, label) ->
                AdmCheck(label, c[bit] ?: ((current or server) and bit != 0L), server and bit == 0L) { c[bit] = it }
            }
        }
    }
}

/** web UI "Broadcast Message": {action:'userbroadcast', msg, target?, maxtime}. */
@Composable
internal fun AdmBroadcastDialog(ctrl: ControlConnection, target: String?, targetName: String?, onClose: () -> Unit) {
    val durations = listOf("Until dismissed" to 0, "10 seconds" to 10, "1 minute" to 60, "5 minutes" to 300)
    var text by remember { mutableStateOf("") }
    var dur by remember { mutableStateOf("0") }
    var result by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    AdmFormDialog("Broadcast message", ok = "Send", okEnabled = !busy && text.trim().length in 1..BROADCAST_MAX,
        onDismiss = onClose, onOk = {
            busy = true; result = "Sending…"
            val m = JSONObject().put("action", "userbroadcast").put("msg", text.trim()).put("maxtime", dur.toInt())
            if (target != null) m.put("target", target)
            ctrl.send(m) { r ->
                busy = false
                if (r.optString("result") == "ok") onClose() else result = r.optString("result").ifEmpty { "Failed" }
            }
        }) {
        Text(if (target != null) "To all connected members of \"$targetName\"." else "To all connected users.",
            style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(text, { text = it.take(BROADCAST_MAX + 50) }, Modifier.fillMaxWidth().padding(top = 8.dp),
            minLines = 4, label = { Text("Message") }, supportingText = { Text("${text.trim().length}/$BROADCAST_MAX") },
            isError = text.trim().length > BROADCAST_MAX)
        AdmPicker("Show the message", durations.map { it.second.toString() to it.first }, dur) { dur = it }
        if (result.isNotEmpty()) Text(result, color = if (busy) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error)
    }
}

/** One row of a membership section: name, detail, optional edit / remove / open. */
internal class AdmRow(val name: String, val detail: String, val onEdit: (() -> Unit)? = null,
                      val onRemove: (() -> Unit)? = null, val onOpen: (() -> Unit)? = null)

/** Web-UI style membership list in a card, with an optional "Add" button in the heading. */
@Composable
internal fun AdmListSection(title: String, addLabel: String, onAdd: (() -> Unit)?, rows: List<AdmRow>, empty: String) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        Row(Modifier.fillMaxWidth().padding(start = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(title.uppercase(), Modifier.weight(1f), style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
            if (onAdd != null) TextButton(onAdd) { Icon(Icons.Filled.Add, null, Modifier.size(18.dp)); Text(addLabel) }
        }
        Surface(shape = MaterialTheme.shapes.large, color = MaterialTheme.colorScheme.surfaceContainerLow,
            border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)),
            modifier = Modifier.fillMaxWidth()) {
            Column {
                if (rows.isEmpty()) Text(empty, Modifier.padding(16.dp), fontStyle = FontStyle.Italic,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                rows.forEachIndexed { i, r ->
                    Row(Modifier.fillMaxWidth().clickable(enabled = r.onOpen != null) { r.onOpen?.invoke() }
                        .padding(start = 16.dp, end = 4.dp, top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f).padding(vertical = 4.dp)) {
                            Text(r.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis,
                                color = if (r.onOpen != null) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                            if (r.detail.isNotEmpty()) Text(r.detail, style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (r.onEdit != null) IconButton(r.onEdit) { Icon(Icons.Filled.Edit, "Edit permissions") }
                        if (r.onRemove != null) IconButton(r.onRemove) { Icon(Icons.Filled.Delete, "Remove") }
                    }
                    if (i < rows.size - 1) HorizontalDivider(Modifier.padding(start = 16.dp),
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                }
            }
        }
    }
}

/** Label / value line with an optional edit pencil (InfoLine with an action). */
@Composable
internal fun AdmInfoLine(label: String, value: String, italic: Boolean = false, last: Boolean = false, onEdit: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.width(120.dp).padding(vertical = 8.dp), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        SelectionContainer(Modifier.weight(1f)) {
            Text(value, style = MaterialTheme.typography.bodyMedium, fontStyle = if (italic) FontStyle.Italic else FontStyle.Normal,
                color = if (italic) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
        }
        if (onEdit != null) IconButton(onEdit) { Icon(Icons.Filled.Edit, "Change ${label.lowercase()}", tint = MaterialTheme.colorScheme.primary) }
        else Spacer(Modifier.width(12.dp))
    }
    if (!last) HorizontalDivider(Modifier.padding(start = 16.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}

/** A user's account picture (UserImages) or a round initial, for a user or group. */
@Composable
internal fun AdmAvatar(name: String, online: Boolean = false, size: Int = 44, image: androidx.compose.ui.graphics.ImageBitmap? = null) {
    Box(Modifier.size((size + 4).dp)) {
        if (image != null) androidx.compose.foundation.Image(image, name, Modifier.size(size.dp).clip(CircleShape),
            contentScale = androidx.compose.ui.layout.ContentScale.Crop)
        else Box(Modifier.size(size.dp).background(MaterialTheme.colorScheme.primaryContainer, CircleShape), contentAlignment = Alignment.Center) {
            Text(name.trim().take(1).uppercase().ifEmpty { "?" }, color = MaterialTheme.colorScheme.onPrimaryContainer,
                style = if (size > 50) MaterialTheme.typography.headlineSmall else MaterialTheme.typography.titleMedium)
        }
        if (online) Box(Modifier.align(Alignment.BottomEnd).size((size * 0.3f).dp)
            .background(MaterialTheme.colorScheme.surfaceContainerLow, CircleShape).padding(2.dp).background(OnlineGreen, CircleShape))
    }
}

/** Search field in the style of the device list. */
@Composable
internal fun AdmSearch(query: String, placeholder: String, onChange: (String) -> Unit) =
    TextField(query, onChange, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), singleLine = true,
        placeholder = { Text(placeholder) }, shape = CircleShape,
        leadingIcon = { Icon(Icons.Filled.Search, null) },
        trailingIcon = { if (query.isNotEmpty()) IconButton({ onChange("") }) { Icon(Icons.Filled.Close, "Clear") } },
        colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
            focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh))

/** A reply callback that reports failures; ok = result missing / "ok", or addmeshuser's success count. */
internal fun admReplyOk(msg: JSONObject): Boolean = when {
    msg.has("success") -> msg.optInt("success") > 0 && msg.optInt("failed") == 0
    msg.has("added") -> msg.optInt("failed") == 0
    else -> msg.optString("result", "ok").let { it == "ok" || it.isEmpty() }
}

// ---- user texts (admin_panel.py / user_panel.py) ------------------------------------------------

private fun JSONObject.siteadmin(): Long? = if (has("siteadmin")) optLong("siteadmin") else null

/** Users list "Permissions" exactly like the web UI's addUserHtml. */
private fun permissionsLabel(u: JSONObject): String {
    val sa = u.siteadmin()
    val pre = if (sa != null && sa and 32L != 0L && sa != ADM_FULL) "Locked, " else ""
    val ur = if (sa != null) sa and (ADM_FULL - 1248) else 0L
    var label = when {
        sa == null || ur == 0L -> "User"
        ur == 8L -> "User + Files"
        sa == ADM_FULL -> "Administrator"
        ur and 2L != 0L -> "Manager"
        else -> "Partial"
    }
    if (sa != null && sa != ADM_FULL && sa and (64L + 128 + 1024) != 0L) label += "*"
    return pre + label
}

private fun serverRightsText(u: JSONObject): String {
    val sa = u.siteadmin()
    val out = mutableListOf<String>()
    if (sa != null && sa and 32L != 0L && sa != ADM_FULL) out.add("Locked account")
    out.add(when {
        sa == null || sa and (ADM_FULL - 1248) == 0L -> "No server rights"
        sa == 8L -> "Access to server files"
        sa == ADM_FULL -> "Full administrator"
        else -> "Partial rights"
    })
    if (sa != null && sa != ADM_FULL && sa and (64L + 128 + 1024) != 0L) out.add("Restrictions")
    return out.joinToString(", ")
}

private fun featuresText(u: JSONObject, si: JSONObject): String {
    val f = mutableListOf<String>()
    if (si.optInt("usersSessionRecording") == 1 && u.optLong("flags") and 2L != 0L) f.add("Record Sessions")
    val rr = u.optLong("removeRights")
    if (rr != 0L) {
        if (rr and 0x8L != 0L) f.add("No Remote Control") else {
            if (rr and 0x10000L != 0L) f.add("No Desktop") else if (rr and 0x100L != 0L) f.add("Desktop View Only")
            f += listOf(0x200L to "No Terminal", 0x400L to "No Files", 0x400000L to "No Registry", 0x800000L to "No Software")
                .filter { rr and it.first != 0L }.map { it.second }
        }
        f += listOf(0x10L to "No Console", 0x8000L to "No Uninstall", 0x20000L to "No Remote Command", 0x40L to "No Wake",
            0x40000L to "No Reset/Off").filter { rr and it.first != 0L }.map { it.second }
    }
    return f.joinToString(", ").ifEmpty { "None" }
}

private fun secondFactors(u: JSONObject): List<String> {
    val f = listOf("otpsecret" to "Authentication App", "otphkeys" to "Security Key", "otpekey" to "Email", "otpduo" to "Duo")
        .filter { truthy(u.opt(it.first)) }.map { it.second }.toMutableList()
    if (f.isEmpty()) return f
    if (truthy(u.opt("otpkeys"))) f.add("Backup Codes")
    if (truthy(u.opt("otpdev"))) f.add("Device Push")
    return f
}

private fun truthy(v: Any?): Boolean = when (v) {
    null, JSONObject.NULL, false -> false
    is Number -> v.toDouble() != 0.0
    is String -> v.isNotEmpty()
    is JSONArray -> v.length() > 0
    else -> true
}

private fun has2fa(u: JSONObject) = listOf("otphkeys", "otpkeys", "otpsecret", "otpdev").any { truthy(u.opt(it)) }

private fun groupsOf(u: JSONObject): List<String> = u.optJSONArray("groups")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()

// ---- export (web UI "Download user information") -----------------------------------------------

/** Spreadsheets run a cell starting with = + - @ as a formula: user-chosen values get a leading quote. */
private fun noFormula(v: String) = if (v.isNotEmpty() && v[0] in "=+-@\t\r") "'$v" else v

private fun csvQ(v: String) = "\"" + v.replace("\"", "\"\"") + "\""

/** userlist.csv with the web UI's columns; full admins are never reported as locked. */
private fun usersToCsv(users: List<JSONObject>): String {
    val fmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT)
    fun t(s: Long) = if (s > 0) fmt.format(Date(s * 1000)) else ""
    val sb = StringBuilder()
    sb.append(listOf("id", "name", "email", "creation", "lastlogin", "groups", "authfactors", "siteadmin", "useradmin", "locked")
        .joinToString(",") { csvQ(it) }).append("\r\n")
    for (u in users) {
        val sa = u.optLong("siteadmin", 0L)
        val factors = mutableListOf<String>()
        if (truthy(u.opt("otpsecret")) || truthy(u.opt("otphkeys"))) {
            if (truthy(u.opt("otpsecret"))) factors.add("AuthApp")
            if (truthy(u.opt("otphkeys"))) factors.add("SecurityKey")
            if (truthy(u.opt("otpkeys"))) factors.add("BackupCodes")
        }
        sb.append(listOf(csvQ(noFormula(u.optString("_id"))), csvQ(noFormula(u.optString("name"))),
            csvQ(noFormula(u.optString("email"))), csvQ(t(u.optLong("creation"))), csvQ(t(u.optLong("login"))),
            csvQ(noFormula(groupsOf(u).joinToString(","))), csvQ(factors.joinToString(",")),
            if (sa == ADM_FULL) "1" else "0", if (sa and 2L != 0L) "1" else "0",
            if (sa != ADM_FULL && sa and 32L != 0L) "1" else "0").joinToString(",")).append("\r\n")
    }
    return sb.toString()
}

// ---- the screen -------------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UsersScreen(app: McdApp, session: Session, onBack: () -> Unit) {
    val ctrl = session.ctrl
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val manage = Site.has(ctrl.userinfo, Site.MANAGEUSERS)
    var users by remember { mutableStateOf<List<JSONObject>?>(null) }
    var sessions by remember { mutableStateOf<Map<String, Int>>(emptyMap()) }
    var usergroups by remember { mutableStateOf<JSONObject?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var openId by rememberSaveable { mutableStateOf<String?>(null) }
    var menu by remember { mutableStateOf(false) }
    var newAccount by remember { mutableStateOf(false) }
    var broadcast by remember { mutableStateOf(false) }
    var exportText by remember { mutableStateOf<String?>(null) }
    var alert by remember { mutableStateOf<Pair<String, String>?>(null) }
    // a password change has no reply: the accountchange event (msgid 75) for that user confirms it
    var pwWait by remember { mutableStateOf<Pair<String, Job>?>(null) }
    var soon by remember { mutableStateOf<Job?>(null) }

    fun request() {
        ctrl.send("action" to "users")
        ctrl.send("action" to "wssessioncount")
        ctrl.send("action" to "usergroups")
    }
    fun refreshSoon(ms: Long = 1000) { soon?.cancel(); soon = scope.launch { delay(ms); request() } }

    val saveCsv = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        val t = exportText; exportText = null
        if (uri != null && t != null) try { ctx.contentResolver.openOutputStream(uri)?.use { it.write(t.toByteArray()) } }
            catch (e: Exception) { alert = "Export failed" to (e.message ?: "") }
    }
    val saveJson = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        val t = exportText; exportText = null
        if (uri != null && t != null) try { ctx.contentResolver.openOutputStream(uri)?.use { it.write(t.toByteArray()) } }
            catch (e: Exception) { alert = "Export failed" to (e.message ?: "") }
    }

    DisposableEffect(Unit) {
        val onUsers: (JSONObject) -> Unit = { m ->
            val a = m.optJSONArray("users")
            val o = m.optJSONObject("users")
            users = when {
                a != null -> (0 until a.length()).mapNotNull { a.optJSONObject(it) }
                o != null -> o.keys().asSequence().mapNotNull { o.optJSONObject(it) }.toList()
                else -> emptyList()
            }
        }
        val onSessions: (JSONObject) -> Unit = { m ->
            m.optJSONObject("wssessions")?.let { w -> sessions = w.keys().asSequence().associateWith { w.optInt(it) }.filterValues { it > 0 } }
        }
        val onGroups: (JSONObject) -> Unit = { m -> usergroups = m.optJSONObject("ugroups") ?: JSONObject() }
        val onEvent: (JSONObject) -> Unit = { m ->
            val ev = m.optJSONObject("event") ?: JSONObject()
            when (val act = ev.optString("action")) {
                "wssessioncount" -> ev.optString("userid").takeIf { it.isNotEmpty() }?.let { uid ->
                    val c = ev.optInt("count")
                    sessions = if (c > 0) sessions + (uid to c) else sessions - uid
                }
                "accountcreate", "accountchange", "accountremove", "usergroupchange", "meshchange", "changenode", "removenode" -> {
                    val acc = ev.optJSONObject("account")
                    val w = pwWait
                    if (act == "accountchange" && w != null && acc?.optString("_id") == w.first && ev.optInt("msgid") == 75) {
                        w.second.cancel(); pwWait = null
                        alert = "Password changed" to "The new password is set."
                    }
                    refreshSoon()
                }
            }
        }
        ctrl.on("users", onUsers); ctrl.on("wssessioncount", onSessions); ctrl.on("usergroups", onGroups); ctrl.on("event", onEvent)
        request()
        onDispose {
            ctrl.off("users", onUsers); ctrl.off("wssessioncount", onSessions); ctrl.off("usergroups", onGroups); ctrl.off("event", onEvent)
            soon?.cancel(); pwWait?.second?.cancel()
        }
    }

    val open = openId?.let { id -> users?.firstOrNull { it.optString("_id") == id } }
    LaunchedEffect(open, users) { if (openId != null && users != null && open == null) openId = null }   // deleted
    BackHandler(enabled = openId != null) { openId = null }

    if (open != null) {
        UserPage(session, open, sessions[open.optString("_id")] ?: 0, usergroups, onBack = { openId = null },
            refreshSoon = { refreshSoon(700) }, onAlert = { t, m -> alert = t to m },
            onPasswordSent = { uid ->
                pwWait?.second?.cancel()
                pwWait = uid to scope.launch {
                    delay(6000); pwWait = null
                    alert = "The server did not confirm the password change" to
                        "The new password probably does not meet the server's password requirements."
                }
            })
    } else Scaffold(topBar = {
        TopAppBar(title = { Text("Users") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (manage) IconButton({ broadcast = true }) { Icon(Icons.Filled.Campaign, "Broadcast to all users") }
                IconButton({ request() }) { Icon(Icons.Filled.Refresh, "Refresh") }
                Box {
                    IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                    DropdownMenu(menu, { menu = false }) {
                        val list = users.orEmpty().sortedBy { it.optString("name").lowercase() }
                        DropdownMenuItem({ Text("Export as CSV") }, enabled = list.isNotEmpty(), onClick = {
                            menu = false; exportText = usersToCsv(list); saveCsv.launch("userlist.csv")
                        })
                        DropdownMenuItem({ Text("Export as JSON") }, enabled = list.isNotEmpty(), onClick = {
                            menu = false; exportText = JSONArray(list).toString(2); saveJson.launch("userlist.json")
                        })
                    }
                }
            })
    }, floatingActionButton = {
        val feats = admFeatures(ctrl)
        if (manage && feats and FEAT_NOUSERS == 0L && !ctrl.serverinfo.optBoolean("domainauth"))
            ExtendedFloatingActionButton(onClick = { newAccount = true }, icon = { Icon(Icons.Filled.PersonAdd, null) }, text = { Text("New account") })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            AdmSearch(query, "Search users (name, email)") { query = it }
            val list = users
            when {
                list == null -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                list.isEmpty() && !manage -> Text("Your account does not have the right to manage users on this server.",
                    Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> {
                    val q = query.trim().lowercase()
                    fun match(u: JSONObject): Boolean {
                        if (q.isEmpty()) return true
                        val name = u.optString("name").lowercase(); val email = u.optString("email").lowercase()
                        for ((pre, e) in listOf("email:" to true, "e:" to true, "name:" to false, "n:" to false))
                            if (q.startsWith(pre)) { val k = q.removePrefix(pre); return if (e) email.contains(k) else name.contains(k) }
                        return name.contains(q) || email.contains(q)
                    }
                    val shown = list.filter { match(it) }.sortedBy { it.optString("name").lowercase() }
                    val online = shown.filter { (sessions[it.optString("_id")] ?: 0) > 0 }
                    val offline = shown.filter { (sessions[it.optString("_id")] ?: 0) == 0 }
                    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                        for ((title, group) in listOf("Online" to online, "Offline" to offline)) {
                            if (group.isEmpty()) continue
                            item(key = "h:$title") {
                                Text("${title.uppercase()}  ${group.size}", Modifier.padding(start = 20.dp, top = 14.dp, bottom = 6.dp),
                                    style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold,
                                    color = MaterialTheme.colorScheme.primary)
                            }
                            items(group, key = { it.optString("_id") }) { u ->
                                UserRow(u, sessions[u.optString("_id")] ?: 0, UserImages.image(session, u.optString("_id"), UserImages.flags(u))) {
                                    openId = u.optString("_id") }
                            }
                        }
                        if (shown.isEmpty()) item {
                            Text(if (list.isEmpty()) "No users." else "No user matches.", Modifier.padding(24.dp),
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
    if (newAccount) NewAccountDialog(ctrl, onClose = { newAccount = false }, onDone = { newAccount = false; refreshSoon(300) })
    if (broadcast) AdmBroadcastDialog(ctrl, null, null) { broadcast = false }
    alert?.let { (t, m) -> AdmMessage(t, m) { alert = null } }
}

@Composable
private fun UserRow(u: JSONObject, sessions: Int, image: androidx.compose.ui.graphics.ImageBitmap?, onClick: () -> Unit) {
    Surface(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))) {
        Row(Modifier.clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            AdmAvatar(u.optString("name"), sessions > 0, image = image)
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(u.optString("name"), style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val email = u.optString("email")
                if (email.isNotEmpty() && email != u.optString("name")) Text(email, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val groups = admLinks(u).keys().asSequence().count { it.startsWith("mesh/") }
                val access = if (sessions > 0) (if (sessions == 1) "1 session" else "$sessions sessions")
                    else admTime(if (u.has("access")) u.opt("access") else u.opt("login")).let { if (it.isEmpty()) "" else "Last access $it" }
                Text(listOf(permissionsLabel(u), if (groups == 1) "1 group" else "$groups groups", access, if (has2fa(u)) "2FA" else "")
                    .filter { it.isNotEmpty() }.joinToString("  ·  "), style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.outline)
        }
    }
}

/** Web UI "New Account…": {action:'adduser', …}; with a responseid the server answers result 'ok' or an error. */
@Composable
private fun NewAccountDialog(ctrl: ControlConnection, onClose: () -> Unit, onDone: () -> Unit) {
    val si = ctrl.serverinfo
    val emailIsName = admFeatures(ctrl) and FEAT_USERNAME_IS_EMAIL != 0L
    val emailcheck = si.optBoolean("emailcheck")
    val domains = si.optJSONArray("crossDomain")?.let { a -> (0 until a.length()).map { a.optString(it) } }
    var domain by remember { mutableStateOf(domains?.firstOrNull() ?: "") }
    var name by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var p1 by remember { mutableStateOf("") }
    var p2 by remember { mutableStateOf("") }
    var random by remember { mutableStateOf(false) }
    var removeEvents by remember { mutableStateOf(false) }
    var reset by remember { mutableStateOf(false) }
    var verified by remember { mutableStateOf(false) }
    var invite by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    var timer by remember { mutableStateOf<Job?>(null) }
    DisposableEffect(Unit) { onDispose { timer?.cancel() } }

    val emailOk = EMAIL_RE.matches(email)
    val nameOk = emailIsName || (name.isNotEmpty() && name.none { it in " \",/" } && !name.startsWith("~"))
    val passOk = random || (p1.isNotEmpty() && p1 == p2)
    val canInvite = emailOk && reset && verified
    if (!emailOk && verified) verified = false
    if (!canInvite && invite) invite = false
    AdmFormDialog("New account", ok = "Create", okEnabled = !busy && nameOk && emailOk && passOk, onDismiss = onClose, onOk = {
        busy = true; result = "Creating the account…"
        val m = JSONObject().put("action", "adduser").put("username", if (emailIsName) email.trim() else name)
            .put("email", email.trim()).put("pass", if (random) "" else p1).put("resetNextLogin", reset)
            .put("randomPassword", random).put("removeEvents", removeEvents)
        if (emailcheck) m.put("emailVerified", verified).put("emailInvitation", invite)
        if (domains != null) m.put("domain", domain)
        timer = scope.launch { delay(15000); busy = false; result = "No response from the server." }
        ctrl.send(m) { r ->
            timer?.cancel(); busy = false
            when (val res = r.optString("result")) {
                "ok" -> onDone()
                "maxUsersExceed" -> result = "The server's account limit was reached."
                "passwordHashError" -> result = "The server could not store the password."
                "Invalid password" -> result = "Invalid password. It does not meet the server's password requirements."
                else -> result = res.ifEmpty { "Creating the account failed." }
            }
        }
    }) {
        if (domains != null) AdmPicker("Domain", domains.map { it to it.ifEmpty { "Default" } }, domain) { domain = it }
        if (!emailIsName) OutlinedTextField(name, { name = it.take(64) }, Modifier.fillMaxWidth(), label = { Text("User name") },
            singleLine = true, isError = name.isNotEmpty() && !nameOk)
        OutlinedTextField(email, { email = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("Email") }, singleLine = true,
            isError = email.isNotEmpty() && !emailOk, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
        OutlinedTextField(p1, { p1 = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("Password") }, singleLine = true,
            enabled = !random, visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        OutlinedTextField(p2, { p2 = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("Password again") }, singleLine = true,
            enabled = !random, visualTransformation = PasswordVisualTransformation(), isError = p2.isNotEmpty() && p1 != p2,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        AdmCheck("Randomize the password", random) { random = it }
        AdmCheck("Remove all previous events for this user id", removeEvents) { removeEvents = it }
        AdmCheck("Force password reset on next login", reset) { reset = it }
        if (emailcheck) {
            AdmCheck("Email is verified", verified, emailOk) { verified = it }
            AdmCheck("Send invitation email", invite, canInvite) { invite = it }
        }
        val hints = listOfNotNull(if (emailIsName) "This server uses the email address as the user name." else null,
            if (random) "The server generates a password that is not shown to anyone: send an invitation or set a new password later." else null,
            if (!random && p1.isNotEmpty() && p2.isNotEmpty() && p1 != p2) "The passwords do not match." else null)
        if (hints.isNotEmpty()) Text(hints.joinToString(" "), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (result.isNotEmpty()) Text(result, color = if (busy) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error)
    }
}

// ---- one user's page ----------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun UserPage(session: Session, u: JSONObject, sessions: Int, usergroups: JSONObject?, onBack: () -> Unit,
                     refreshSoon: () -> Unit, onAlert: (String, String) -> Unit, onPasswordSent: (String) -> Unit) {
    val ctrl = session.ctrl
    val si = ctrl.serverinfo
    val me = ctrl.userinfo ?: JSONObject()
    val mySa = admSiteRights(ctrl)
    val feats = admFeatures(ctrl)
    val uid = u.optString("_id")
    val name = u.optString("name")
    val isSelf = uid == me.optString("_id")
    val tsa = u.siteadmin()
    // web UI userAdminRights: manage-users right and the target is not a full admin, or we are one
    val userAdmin = (mySa and 2L != 0L && tsa != ADM_FULL) || mySa == ADM_FULL
    val mayEdit = tsa != ADM_FULL || mySa == ADM_FULL
    val guest = admGuest(ctrl)
    val links = admLinks(u)
    var tab by rememberSaveable { mutableStateOf(0) }
    var dialog by remember { mutableStateOf<String?>(null) }
    var editMesh by remember { mutableStateOf<String?>(null) }
    var editNode by remember { mutableStateOf<String?>(null) }
    var confirm by remember { mutableStateOf<Triple<String, String, () -> Unit>?>(null) }

    fun reply(what: String): (JSONObject) -> Unit = { m ->
        if (!admReplyOk(m)) onAlert("$what failed", m.optString("result"))
        refreshSoon()
    }
    fun edituser(what: String, vararg fields: Pair<String, Any?>) {
        val m = JSONObject().put("action", "edituser").put("id", uid)
        fields.forEach { (k, v) -> m.put(k, v) }
        ctrl.send(m, reply(what))
    }

    Scaffold(topBar = {
        TopAppBar(title = { Text(name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                AdmAvatar(name, sessions > 0, 60, UserImages.image(session, u.optString("_id"), UserImages.flags(u)))
                Column(Modifier.weight(1f).padding(start = 16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(permissionsLabel(u), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    StatusPill(sessions > 0, if (sessions == 0) "Offline" else if (sessions == 1) "1 active session" else "$sessions active sessions")
                }
            }
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                listOf("General", "Events").forEachIndexed { i, t ->
                    SegmentedButton(tab == i, { tab = i }, SegmentedButtonDefaults.itemShape(i, 2)) { Text(t) }
                }
            }
            if (tab == 1) { UserEvents(ctrl, uid); return@Column }

            // actions
            val uidShort = admShortId(uid)
            val canPassword = userAdmin && feats and FEAT_LDAP_SSPI == 0L && !uidShort.startsWith("~")
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (mySa and 2L != 0L && !isSelf) Box(Modifier.weight(1f)) {
                    ActionTile("Message", Icons.Filled.Campaign, sessions > 0, Modifier.fillMaxWidth()) { dialog = "notify" }
                }
                if (canPassword) Box(Modifier.weight(1f)) {
                    ActionTile("Password", Icons.Filled.Edit, true, Modifier.fillMaxWidth()) { dialog = "password" }
                }
                Box(Modifier.weight(1f)) { ActionTile("Notes", Icons.Filled.Edit, true, Modifier.fillMaxWidth()) { dialog = "notes" } }
            }

            SectionCard(title = "Details") {
                val dom = admDomain(uid)
                AdmInfoLine("Domain", dom.ifEmpty { "Default" }, italic = dom.isEmpty())
                AdmInfoLine("User ID", uid)
                var email = u.optString("email")
                if (si.optBoolean("emailcheck") && email.isNotEmpty()) email += if (u.optBoolean("emailVerified")) "  (verified)" else "  (not verified)"
                if (feats and FEAT_USERNAME_IS_EMAIL != 0L) AdmInfoLine("Email", email.ifEmpty { "Not set" }, email.isEmpty())
                else AdmInfoLine("Email", email.ifEmpty { "Not set" }, email.isEmpty(), onEdit = if (mayEdit) ({ dialog = "email" }) else null)
                AdmInfoLine("Real name", u.optString("realname").ifEmpty { "Not set" }, u.optString("realname").isEmpty(),
                    onEdit = if (mayEdit) ({ dialog = "realname" }) else null)
                if (feats and FEAT_SMS != 0L || u.has("phone"))
                    AdmInfoLine("Phone", u.optString("phone").ifEmpty { "None" }, u.optString("phone").isEmpty()) { dialog = "phone" }
                val ft = featuresText(u, si)
                AdmInfoLine("Features", ft, ft == "None") { dialog = "features" }
                AdmInfoLine("Server rights", serverRightsText(u)) { dialog = "server" }
                if (u.optLong("quota") > 0) AdmInfoLine("Server quota", "${u.optLong("quota") / 1024} k")
                if (u.optLong("creation") > 0) AdmInfoLine("Created", admTime(u.optLong("creation")))
                if (u.optLong("login") > 0) AdmInfoLine("Last login", admTime(u.optLong("login")))
                when {
                    u.optLong("passchange") == -1L -> AdmInfoLine("Password", "Will be changed on next login.")
                    u.optLong("passchange") > 0 -> AdmInfoLine("Password", "Last changed " + admTime(u.optLong("passchange")))
                }
                if (mySa == ADM_FULL || mySa and 2L != 0L) {
                    val realms = groupsOf(u).joinToString(", ").ifEmpty { "None" }
                    val can = mySa == ADM_FULL || (groupsOf(me).isEmpty() && !isSelf && tsa != ADM_FULL)
                    AdmInfoLine("Admin realms", realms, realms == "None", onEdit = if (can) ({ dialog = "realms" }) else null)
                }
                val ct = admConsentText(u, si)
                val f2 = secondFactors(u)
                AdmInfoLine("User consent", ct, ct == "None", last = f2.isEmpty()) { dialog = "consent" }
                if (f2.isNotEmpty()) AdmInfoLine("Security", "2nd factor: " + f2.joinToString(", "), last = true)
            }

            // memberships
            val meshes = session.meshes
            AdmListSection("Device groups", "Add",
                if (!isSelf && meshes.keys.any { admDomain(it) == admDomain(uid) && !links.has(it) }) ({ editMesh = "" }) else null,
                links.keys().asSequence().filter { it.startsWith("mesh/") && meshes.containsKey(it) }
                    .sortedBy { meshes[it]?.name?.lowercase() }.map { mid ->
                        val can = !isSelf && Rights.mesh(si, ctrl.userinfo, meshes[mid]?.json) and 2L != 0L
                        AdmRow(meshes[mid]?.name ?: mid, admGroupRightsText(admLinkRights(links, mid), guest),
                            onEdit = if (can) ({ editMesh = mid }) else null,
                            onRemove = if (can) ({
                                confirm = Triple("Remove device group permissions", "Remove the access rights of $name to the device group \"${meshes[mid]?.name}\"?") {
                                    ctrl.send(JSONObject().put("action", "removemeshuser").put("meshid", mid).put("userid", uid),
                                        reply("Removing the device group permissions"))
                                }
                            }) else null)
                    }.toList(), "No device groups in common")
            if (usergroups != null) {
                val may = mySa and 256L != 0L
                val avail = usergroups.keys().asSequence().filter { g ->
                    usergroups.optJSONObject(g)?.has("membershipType") == false && admDomain(g) == admDomain(uid) && !links.has(g)
                }.toList()
                AdmListSection("User group memberships", "Add", if (may && avail.isNotEmpty()) ({ dialog = "addgroup" }) else null,
                    links.keys().asSequence().filter { it.startsWith("ugrp/") && usergroups.has(it) }
                        .sortedBy { usergroups.optJSONObject(it)?.optString("name")?.lowercase() }.map { gid ->
                            val g = usergroups.optJSONObject(gid) ?: JSONObject()
                            AdmRow(g.optString("name").ifEmpty { gid }, g.optString("desc"),
                                onRemove = if (may && !g.has("membershipType")) ({
                                    confirm = Triple("Remove user group membership", "Remove $name from the user group \"${g.optString("name")}\"?") {
                                        ctrl.send(JSONObject().put("action", "removeuserfromusergroup").put("ugrpid", gid).put("userid", uid),
                                            reply("Removing the membership"))
                                    }
                                }) else null)
                        }.toList(), "No user group memberships")
            }
            val sameDomain = admDomain(uid) == admDomain(me.optString("_id"))
            AdmListSection("Devices", "Add", if (sameDomain) ({ editNode = "" }) else null,
                links.keys().asSequence().filter { it.startsWith("node/") && session.node(it) != null }
                    .sortedBy { session.node(it)?.name?.lowercase() }.map { nid ->
                        val n = session.node(nid)!!
                        val can = Rights.node(si, ctrl.userinfo, meshes[n.meshId]?.json, n.json) and 2L != 0L
                        AdmRow(n.name, admDeviceRightsText(admLinkRights(links, nid), guest),
                            onEdit = if (can) ({ editNode = nid }) else null,
                            onRemove = if (can) ({
                                confirm = Triple("Remove device permissions", "Remove the access rights of $name to the device \"${n.name}\"?") {
                                    ctrl.send(JSONObject().put("action", "adddeviceuser").put("nodeid", nid).put("nodename", n.name)
                                        .put("userids", JSONArray().put(uid)).put("rights", 0).put("remove", true),
                                        reply("Removing the device permissions"))
                                }
                            }) else null)
                    }.toList(), "No devices in common")

            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (canPassword) FilledTonalButton({ dialog = "logins" }) { Text("Previous logins") }
                Spacer(Modifier.weight(1f))
                if (userAdmin && !isSelf) OutlinedButton({ dialog = "delete" }) { Text("Delete user", color = MaterialTheme.colorScheme.error) }
            }
        }
    }

    when (dialog) {
        "notify" -> NotifyUserDialog(name, onClose = { dialog = null }) { text ->
            dialog = null
            ctrl.send(JSONObject().put("action", "notifyuser").put("userid", uid).put("msg", text))   // no reply
            onAlert("Message sent", "The message was sent to the open sessions of $name.")
        }
        "password" -> ChangePasswordDialog(u, feats, onClose = { dialog = null }) { m ->
            dialog = null
            ctrl.send(m)
            onPasswordSent(uid)
        }
        "notes" -> UserNotesDialog(ctrl, uid, name, mySa and 2L != 0L) { dialog = null }
        "logins" -> PreviousLoginsDialog(ctrl, uid, name) { dialog = null }
        "email" -> EmailDialog(u, si.optBoolean("emailcheck"), onClose = { dialog = null }) { fields ->
            dialog = null; edituser("Changing the email", *fields.toTypedArray())
        }
        "realname" -> TextEditDialog("Real name", u.optString("realname"), 256, { true }, { dialog = null }) {
            dialog = null; edituser("Changing the real name", "realname" to it)
        }
        "phone" -> TextEditDialog("Phone number", u.optString("phone"), 20, { it.isEmpty() || Regex("""^\+?[0-9 ()\-]{4,20}$""").matches(it) },
            { dialog = null }) { dialog = null; edituser("Changing the phone number", "phone" to it) }
        "realms" -> TextEditDialog("Administrative realms (comma separated)", groupsOf(u).joinToString(", "), 256,
            { v -> v.isEmpty() || (v.none { it in "\"/<>'" } && v.split(",").all { it.isNotBlank() }) }, { dialog = null }) { v ->
            dialog = null
            edituser("Changing the realms", "groups" to JSONArray(v.split(",").map { it.trim() }.filter { it.isNotEmpty() }))
        }
        "features" -> FeaturesDialog(u, si, onClose = { dialog = null }) { flags, rr ->
            dialog = null; edituser("Changing the features", "flags" to flags, "removeRights" to rr)
        }
        "consent" -> AdmConsentDialog("User consent", u.optLong("consent"), si.optLong("consent"), { dialog = null }) {
            dialog = null; edituser("Changing the user consent", "consent" to it)
        }
        "server" -> ServerRightsDialog(u, mySa, isSelf, onClose = { dialog = null }) { sa, quota ->
            dialog = null
            if (quota != null) edituser("Changing the server permissions", "siteadmin" to sa, "quota" to quota)
            else edituser("Changing the server permissions", "siteadmin" to sa)
        }
        "addgroup" -> {
            val ug = usergroups ?: JSONObject()
            val opts = ug.keys().asSequence().filter { g ->
                ug.optJSONObject(g)?.has("membershipType") == false && admDomain(g) == admDomain(uid) && !links.has(g)
            }.sortedBy { ug.optJSONObject(it)?.optString("name")?.lowercase() }.map { it to (ug.optJSONObject(it)?.optString("name") ?: it) }.toList()
            var sel by remember { mutableStateOf(opts.firstOrNull()?.first) }
            AdmFormDialog("Add membership", okEnabled = sel != null, onDismiss = { dialog = null }, onOk = {
                dialog = null
                ctrl.send(JSONObject().put("action", "addusertousergroup").put("ugrpid", sel).put("usernames", JSONArray().put(admShortId(uid))),
                    reply("Adding the membership"))
            }) { AdmPicker("User group", opts, sel) { sel = it } }
        }
        "delete" -> TypedDeleteDialog("Delete user", "This removes the account $name. Type the user name to confirm.", name,
            onClose = { dialog = null }) {
            dialog = null
            ctrl.send(JSONObject().put("action", "deleteuser").put("userid", uid).put("username", name)) { m ->
                if (!admReplyOk(m)) onAlert("Deleting the user failed", m.optString("result")) else onBack()
                refreshSoon()
            }
        }
    }
    editMesh?.let { mid ->
        AdmMeshRightsDialog(session, links, admDomain(uid), mid.ifEmpty { null }, { editMesh = null }) { meshId, value ->
            editMesh = null
            ctrl.send(JSONObject().put("action", "addmeshuser").put("meshid", meshId).put("meshname", session.meshes[meshId]?.name)
                .put("userids", JSONArray().put(uid)).put("meshadmin", value), reply("Changing the device group permissions"))
        }
    }
    editNode?.let { nid ->
        AdmDeviceRightsDialog(session, links, nid.ifEmpty { null }, { editNode = null }) { nodeId, value ->
            editNode = null
            ctrl.send(JSONObject().put("action", "adddeviceuser").put("nodeid", nodeId).put("nodename", session.node(nodeId)?.name)
                .put("userids", JSONArray().put(uid)).put("rights", value), reply("Changing the device permissions"))
        }
    }
    confirm?.let { (t, m, f) -> AdmConfirm(t, m, "Remove", { confirm = null }, f) }
}

/** events {userid, limit[, filter]}: the reply carries userid (device and server-wide replies do not). */
@Composable
private fun UserEvents(ctrl: ControlConnection, uid: String) {
    val filters = listOf("" to "All logs", "agentlog" to "Agent logs", "relaylog" to "Relay logs", "manual" to "Manual logs",
        "runcommands" to "Run command logs", "batchupload" to "Batch upload logs", "changenode" to "Change node logs",
        "removenode" to "Remove node logs")
    var filter by rememberSaveable { mutableStateOf("") }
    var events by remember { mutableStateOf<List<JSONObject>?>(null) }
    fun load() {
        events = null
        val m = JSONObject().put("action", "events").put("userid", uid).put("limit", 250)
        if (filter.isNotEmpty()) m.put("filter", filter)
        ctrl.send(m)
    }
    DisposableEffect(uid) {
        val cb: (JSONObject) -> Unit = { m ->
            if (m.optString("userid") == uid) {
                val a = m.optJSONArray("events") ?: JSONArray()
                events = (0 until a.length()).mapNotNull { a.optJSONObject(it) }
            }
        }
        ctrl.on("events", cb)
        onDispose { ctrl.off("events", cb) }
    }
    LaunchedEffect(filter) { load() }
    Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f)) { AdmPicker("Show", filters, filter) { filter = it } }
        IconButton({ load() }) { Icon(Icons.Filled.Refresh, "Refresh") }
    }
    SectionCard(title = events?.let { "${it.size} events (last 250)" } ?: "Loading…") {
        val list = events.orEmpty()
        if (events != null && list.isEmpty()) Text("No events.", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        list.forEachIndexed { i, e ->
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
                Text(listOf(admTime(e.opt("time")), e.optString("username"), e.optString("action")).filter { it.isNotEmpty() }.joinToString("  ·  "),
                    style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                val msg = e.opt("msg")
                if (msg is String && msg.isNotEmpty()) Text(msg, style = MaterialTheme.typography.bodyMedium)
            }
            if (i < list.size - 1) HorizontalDivider(Modifier.padding(start = 16.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
        }
    }
}

@Composable
private fun NotifyUserDialog(name: String, onClose: () -> Unit, onSend: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AdmFormDialog("Message to $name", ok = "Send", okEnabled = text.isNotBlank(), onDismiss = onClose, onOk = { onSend(text.trim()) }) {
        Text("Shown as a notification in the user's open sessions.", style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(text, { text = it.take(4096) }, Modifier.fillMaxWidth().padding(top = 8.dp), minLines = 3, label = { Text("Message") })
    }
}

/** changeuserpass: the server never answers (see onPasswordSent). */
@Composable
private fun ChangePasswordDialog(u: JSONObject, feats: Long, onClose: () -> Unit, onOk: (JSONObject) -> Unit) {
    var p1 by remember { mutableStateOf("") }
    var p2 by remember { mutableStateOf("") }
    var hint by remember { mutableStateOf("") }
    var reset by remember { mutableStateOf(u.optLong("passchange") == -1L) }
    var rm2fa by remember { mutableStateOf(false) }
    val mfa = secondFactors(u).isNotEmpty()
    AdmFormDialog("Change password", okEnabled = p1 == p2, onDismiss = onClose, onOk = {
        val m = JSONObject().put("action", "changeuserpass").put("userid", u.optString("_id")).put("pass", p1)
            .put("removeMultiFactor", mfa && rm2fa).put("resetNextLogin", reset)
        if (feats and FEAT_PASSWORD_HINT != 0L) m.put("hint", hint)
        onOk(m)
    }) {
        OutlinedTextField(p1, { p1 = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("New password") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        OutlinedTextField(p2, { p2 = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("New password again") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), isError = p2.isNotEmpty() && p1 != p2,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        if (feats and FEAT_PASSWORD_HINT != 0L) OutlinedTextField(hint, { hint = it.take(256) }, Modifier.fillMaxWidth(),
            label = { Text("Password hint") }, singleLine = true)
        AdmCheck("Force password reset on next login", reset) { reset = it }
        if (mfa) AdmCheck("Remove all 2nd factor authentication", rm2fa) { rm2fa = it }
        Text("Leave both fields empty to only change the options.", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun EmailDialog(u: JSONObject, emailcheck: Boolean, onClose: () -> Unit, onOk: (List<Pair<String, Any?>>) -> Unit) {
    var email by remember { mutableStateOf(u.optString("email")) }
    var verified by remember { mutableStateOf(u.optBoolean("emailVerified")) }
    val p = email.split("@")
    val ok = email.isEmpty() || (p.size == 2 && p[0].isNotEmpty() && p[1].split(".").size > 1 && p[1].length > 2 && email.length < 1024)
    AdmFormDialog("Change email", okEnabled = ok, onDismiss = onClose, onOk = {
        onOk(listOf("email" to email) + if (emailcheck) listOf("emailVerified" to verified) else emptyList())
    }) {
        OutlinedTextField(email, { email = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("Email") }, singleLine = true,
            isError = !ok, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
        if (emailcheck) AdmCheck("Email is verified", verified) { verified = it }
    }
}

@Composable
private fun TextEditDialog(label: String, value: String, max: Int, valid: (String) -> Boolean, onClose: () -> Unit, onOk: (String) -> Unit) {
    var v by remember { mutableStateOf(value) }
    AdmFormDialog("Change ${label.substringBefore(" (").lowercase()}", okEnabled = valid(v), onDismiss = onClose, onOk = { onOk(v) }) {
        OutlinedTextField(v, { v = it.take(max) }, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = true, isError = !valid(v))
    }
}

/** web UI "Edit User Features": record sessions (flags 2) and removed rights. */
@Composable
private fun FeaturesDialog(u: JSONObject, si: JSONObject, onClose: () -> Unit, onOk: (Long, Long) -> Unit) {
    val flags = u.optLong("flags"); val rr = u.optLong("removeRights")
    var rec by remember { mutableStateOf(flags and 2L != 0L) }
    val c = remember { mutableStateMapOf<Long, Boolean>() }
    fun on(b: Long) = c[b] ?: (rr and b != 0L)
    val items = listOf(Triple(0x8L, "No Remote Control", 0), Triple(0x10000L, "No Desktop Access", 1), Triple(0x100L, "Remote View Only", 2),
        Triple(0x200L, "No Terminal Access", 1), Triple(0x400L, "No File Access", 1), Triple(0x400000L, "No Registry Access", 1),
        Triple(0x800000L, "No Software", 1), Triple(0x10L, "No Agent Console", 0), Triple(0x8000L, "No Uninstall", 0),
        Triple(0x20000L, "No Remote Command", 0), Triple(0x40L, "No Wake", 0), Triple(0x40000L, "No Reset/Off", 0))
    AdmFormDialog("User features", onDismiss = onClose, onOk = {
        val f = (flags and 1L) or (if (si.optInt("usersSessionRecording") == 1 && rec) 2L else 0L)
        var r = 0L
        if (on(0x8L)) r = r or 0x8L else {
            if (on(0x10000L)) r = r or 0x10000L else if (on(0x100L)) r = r or 0x100L
            listOf(0x200L, 0x400L, 0x400000L, 0x800000L).forEach { if (on(it)) r = r or it }
        }
        listOf(0x10L, 0x8000L, 0x20000L, 0x40L, 0x40000L).forEach { if (on(it)) r = r or it }
        onOk(f, r)
    }) {
        if (si.optInt("usersSessionRecording") == 1) AdmCheck("Record sessions", rec) { rec = it }
        val nrc = !on(0x8L)
        items.forEach { (bit, label, ind) ->
            val enabled = when (bit) {
                0x10000L, 0x200L, 0x400L, 0x400000L, 0x800000L -> nrc
                0x100L -> nrc && !on(0x10000L)
                else -> true
            }
            AdmCheck(label, on(bit), enabled, ind) { c[bit] = it }
        }
    }
}

/** web UI "Server Permissions" (edit_server_rights): what we may change depends on our own site rights. */
@Composable
private fun ServerRightsDialog(u: JSONObject, me: Long, isSelf: Boolean, onClose: () -> Unit, onOk: (Long, Long?) -> Unit) {
    val tsa = u.siteadmin() ?: 0L
    var full by remember { mutableStateOf(tsa == ADM_FULL) }
    val c = remember { mutableStateMapOf<Long, Boolean>() }
    var quota by remember { mutableStateOf(if (u.has("quota")) (u.optLong("quota") / 1024).toString() else "") }
    fun on(b: Long) = c[b] ?: (tsa != ADM_FULL && tsa and b != 0L)
    val base = HashMap<Long, Boolean>()
    listOf(8L, 1L, 4L, 16L).forEach { base[it] = !isSelf && me == ADM_FULL }
    listOf(2L, 256L, 512L, 2048L).forEach { base[it] = !isSelf && me and it != 0L }
    listOf(32L, 64L, 4096L, 128L, 1024L).forEach { base[it] = !isSelf && me and 2L != 0L && tsa != ADM_FULL }
    fun enabled(b: Long) = base[b] == true && (!full || me != ADM_FULL)
    AdmFormDialog("Server permissions", onDismiss = onClose, onOk = if (isSelf) null else ({
        val sa = if (full) ADM_FULL else base.keys.filter { on(it) }.fold(0L) { a, b -> a or b }
        onOk(sa, quota.trim().toLongOrNull()?.let { it * 1024 })
    })) {
        if (me == ADM_FULL) {
            AdmCheck("Server files", on(8L), enabled(8L)) { c[8L] = it }
            OutlinedTextField(quota, { quota = it.filter { ch -> ch.isDigit() }.take(12) }, Modifier.fillMaxWidth().padding(start = 40.dp),
                label = { Text("Quota in k (blank: default)") }, singleLine = true, enabled = !isSelf && on(8L) && !full,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            HorizontalDivider(Modifier.padding(vertical = 6.dp))
            AdmCheck("Full administrator", full, !isSelf) { full = it }
            AdmCheck("Server backup", on(1L), enabled(1L)) { c[1L] = it }
            AdmCheck("Server restore", on(4L), enabled(4L)) { c[4L] = it }
            AdmCheck("Server updates", on(16L), enabled(16L)) { c[16L] = it }
        }
        if (me and 2L != 0L) AdmCheck("Manage users", on(2L), enabled(2L)) { c[2L] = it }
        if (me and 256L != 0L) AdmCheck("Manage user groups", on(256L), enabled(256L)) { c[256L] = it }
        if (me and 512L != 0L) AdmCheck("Manage recordings", on(512L), enabled(512L)) { c[512L] = it }
        AdmCheck("View all events", on(2048L), enabled(2048L)) { c[2048L] = it }
        HorizontalDivider(Modifier.padding(vertical = 6.dp))
        listOf(32L to "Lock account", 64L to "No new device groups", 4096L to "No new devices", 128L to "No tools (MeshCmd / Router)",
            1024L to "Lock account settings").forEach { (b, l) -> AdmCheck(l, on(b), enabled(b)) { c[b] = it } }
        if (isSelf) Text("You cannot change your own server permissions.", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Notes about a user: getNotes / setNotes {id: user id}; editing needs the manage-users right. */
@Composable
private fun UserNotesDialog(ctrl: ControlConnection, uid: String, name: String, editable: Boolean, onClose: () -> Unit) {
    var text by remember { mutableStateOf<String?>(null) }
    DisposableEffect(uid) {
        val cb: (JSONObject) -> Unit = { m -> if (m.optString("id") == uid) text = if (m.isNull("notes")) "" else m.optString("notes") }
        ctrl.on("getNotes", cb)
        ctrl.send("action" to "getNotes", "id" to uid)
        onDispose { ctrl.off("getNotes", cb) }
    }
    AdmFormDialog("Notes about $name", ok = "Save", okEnabled = text != null, onDismiss = onClose,
        onOk = if (editable) ({ ctrl.send("action" to "setNotes", "id" to uid, "notes" to (text ?: "")); onClose() }) else null) {
        val t = text
        if (t == null) CircularProgressIndicator(Modifier.padding(16.dp))
        else OutlinedTextField(t, { text = it }, Modifier.fillMaxWidth(), minLines = 6, readOnly = !editable)
    }
}

/** previousLogins {userid} -> {events:[{t, a:[ip, browser, os], tn?}]}: only web sign-ins are recorded. */
@Composable
private fun PreviousLoginsDialog(ctrl: ControlConnection, uid: String, name: String, onClose: () -> Unit) {
    var rows by remember { mutableStateOf<List<JSONObject>?>(null) }
    DisposableEffect(uid) {
        val cb: (JSONObject) -> Unit = { m ->
            val a = m.optJSONArray("events") ?: JSONArray()
            rows = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.sortedByDescending { admMillis(it.opt("t")) }
        }
        ctrl.on("previousLogins", cb)
        ctrl.send("action" to "previousLogins", "userid" to uid)
        onDispose { ctrl.off("previousLogins", cb) }
    }
    AdmFormDialog("Previous logins of $name", onDismiss = onClose, onOk = null) {
        val r = rows
        when {
            r == null -> CircularProgressIndicator(Modifier.padding(16.dp))
            r.isEmpty() -> Text("No web sign-ins recorded (sign-ins from apps are not recorded by the server).")
            else -> r.take(100).forEach { e ->
                val a = e.optJSONArray("a")
                Column(Modifier.padding(vertical = 6.dp)) {
                    Text(admTime(e.opt("t")), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text((0 until (a?.length() ?: 0)).map { a!!.optString(it) }.filter { it.isNotEmpty() }.joinToString("  ·  "),
                        style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

/** Delete confirmation where the name has to be typed. */
@Composable
private fun TypedDeleteDialog(title: String, text: String, expected: String, onClose: () -> Unit, onOk: () -> Unit) {
    var v by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onClose, title = { Text(title) },
        text = {
            Column {
                Text(text)
                OutlinedTextField(v, { v = it }, Modifier.fillMaxWidth().padding(top = 8.dp), singleLine = true, placeholder = { Text(expected) })
            }
        },
        confirmButton = { TextButton(onOk, enabled = v.trim() == expected) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}
