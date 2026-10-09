// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.NO_PERMISSION
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.Tunnel

private const val PROTO_REGISTRY = 4          // Windows registry (agents/meshcore.js + win-registry-remote)
private val HIVES = mapOf("HKLM" to "HKEY_LOCAL_MACHINE", "HKCU" to "HKEY_CURRENT_USER", "HKU" to "HKEY_USERS",
    "HKCR" to "HKEY_CLASSES_ROOT", "HKCC" to "HKEY_CURRENT_CONFIG")
private val WRITABLE = listOf("REG_SZ", "REG_EXPAND_SZ", "REG_DWORD", "REG_QWORD")
private val NUMERIC = setOf("REG_DWORD", "REG_QWORD")

/** kind: hive | key | value; raw = the name the agent uses ("" = the default value) */
private class RegItem(val kind: String, val name: String, val type: String, val data: String, val raw: String)

/** 'HKLM\Software/Foo' -> (HKEY_LOCAL_MACHINE, Software\Foo); "" or "Root" -> (null, ""); null for an unknown hive. */
private fun normalizeRegPath(text: String): Pair<String?, String>? {
    val t = text.trim()
    if (t.isEmpty() || t.equals("root", true)) return null to ""
    val parts = t.replace('/', '\\').split('\\').filter { it.isNotEmpty() }
    if (parts.isEmpty()) return null to ""
    val hive = parts[0].uppercase().let { HIVES[it] ?: it }
    if (hive !in HIVES.values) return null
    return hive to parts.drop(1).joinToString("\\")
}

private fun regDisplay(hive: String?, path: String) = if (hive == null) "Root" else hive + (if (path.isNotEmpty()) "\\" + path else "")

private fun validNumber(text: String): Boolean {
    val t = text.trim()
    return if (t.lowercase().startsWith("0x")) t.length > 2 && t.drop(2).all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }
    else t.isNotEmpty() && t.all { it.isDigit() }
}

private sealed class RegDialog {
    class NewKey : RegDialog()
    class Value(val item: RegItem?) : RegDialog()            // null = new value
    class Rename(val item: RegItem) : RegDialog()
    class Delete(val item: RegItem) : RegDialog()
    class Details(val item: RegItem) : RegDialog()
    class GoTo : RegDialog()
}

/**
 * Registry of a Windows device (registry_panel.py, web UI p9): relay protocol 4 with JSON requests listroots / list /
 * createkey / setvalue / delete / rename / export. Every reply echoes action and reqid; a failure carries error.
 * Like Desktop / Terminal / Files, opening the page does not connect: the user presses Connect.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun RegistryScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val ctx = LocalContext.current
    val allowed = node != null && node.isWindows && session.caps(node).registry
    val holder = remember { arrayOfNulls<Tunnel>(1) }
    val seq = remember { intArrayOf(0) }
    var state by remember { mutableIntStateOf(0) }
    var hive by remember { mutableStateOf<String?>(null) }
    var path by remember { mutableStateOf("") }
    var rows by remember { mutableStateOf<List<RegItem>?>(null) }
    var listReq by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("Connect to browse the registry of this device.") }
    var error by remember { mutableStateOf<String?>(null) }
    var doneMsg by remember { mutableStateOf<String?>(null) }
    var dialog by remember { mutableStateOf<RegDialog?>(null) }
    var menuFor by remember { mutableStateOf<RegItem?>(null) }
    var topMenu by remember { mutableStateOf(false) }
    var exportName by remember { mutableStateOf("") }
    var exportReq by remember { mutableStateOf("") }          // only the answer to OUR export opens the save dialog
    var exportText by remember { mutableStateOf<String?>(null) }

    fun tunnel() = holder[0]?.takeIf { it.state == 3 }
    fun send(o: JSONObject): String {
        seq[0]++
        val r = o.optString("action") + "-" + seq[0]
        o.put("reqid", r)
        tunnel()?.sendJson(o)
        return r
    }
    fun goTo(h: String?, p: String) {
        hive = h; path = p; rows = null
        if (tunnel() == null) return
        status = if (h == null) "Loading root hives…" else "Loading registry key…"
        listReq = send(if (h == null) JSONObject().put("action", "listroots")
            else JSONObject().put("action", "list").put("hive", h).put("path", p))
    }
    fun refresh() = goTo(hive, path)
    fun child(name: String) = if (path.isNotEmpty()) "$path\\$name" else name
    fun goUp() { if (hive != null) { if (path.isEmpty()) goTo(null, "") else goTo(hive, path.substringBeforeLast('\\', "")) } }

    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val text = exportText
        exportText = null
        if (uri == null || text == null) return@rememberLauncherForActivityResult
        try {
            // reg.exe writes .reg files as UTF-16LE with a BOM; keep that so regedit imports them as they are
            val body = "\uFEFF" + text.replace("\r\n", "\n").replace("\n", "\r\n")
            ctx.contentResolver.openOutputStream(uri)?.use { it.write(body.toByteArray(Charsets.UTF_16LE)) }
            status = "Registry key exported."
        } catch (e: Exception) { error = "Cannot save the file: ${e.message}" }
    }

    fun handle(m: JSONObject) {
        val action = m.optString("action")
        val err = m.optString("error").takeIf { m.has("error") && it.isNotEmpty() && it != "null" }
        if (action == "listroots" || action == "list") {
            if (m.optString("reqid") != listReq) return                    // an older listing, the user moved on
            if (err != null) { rows = emptyList(); status = err; error = err; return }
            error = null
            val out = ArrayList<RegItem>()
            if (action == "listroots") {
                val a = m.optJSONArray("roots") ?: JSONArray()
                for (i in 0 until a.length()) out.add(RegItem("hive", a.optString(i), "Hive", "", a.optString(i)))
                status = if (out.isEmpty()) "No registry roots were returned." else "${out.size} hives"
            } else {
                val sk = m.optJSONArray("subkeys") ?: JSONArray()
                val keys = (0 until sk.length()).map { sk.optString(it) }.sortedBy { it.lowercase() }
                keys.forEach { out.add(RegItem("key", it, "Key", "", it)) }
                val va = m.optJSONArray("values") ?: JSONArray()
                val vals = (0 until va.length()).mapNotNull { va.optJSONObject(it) }
                    .sortedWith(compareBy({ it.optString("rawname") != "" }, { it.optString("name").lowercase() }))
                vals.forEach { v ->
                    val raw = if (v.isNull("rawname")) "" else v.optString("rawname")
                    val data = if (v.isNull("value")) "" else v.opt("value").toString()
                    out.add(RegItem("value", v.optString("name").ifEmpty { if (raw.isEmpty()) "(Default)" else raw },
                        v.optString("type"), data, raw))
                }
                status = if (keys.isEmpty() && vals.isEmpty()) "Registry key is empty." else "${keys.size} keys, ${vals.size} values"
            }
            rows = out
            doneMsg?.let { status = it; doneMsg = null }
            return
        }
        if (err != null) {
            error = (mapOf("createkey" to "Create key", "setvalue" to "Set value", "delete" to "Delete", "rename" to "Rename",
                "export" to "Export")[action] ?: "Request") + " failed: $err"
            if (action != "export") refresh()
            return
        }
        when (action) {
            "createkey", "setvalue", "delete", "rename" -> {
                doneMsg = mapOf("createkey" to "Registry key created.", "setvalue" to "Registry value updated.",
                    "delete" to "Registry item deleted.", "rename" to "Registry item renamed.")[action]
                refresh()
            }
            "export" -> if (exportReq.isNotEmpty() && m.optString("reqid") == exportReq) { exportReq = ""; exportText = m.optString("content"); save.launch(exportName.ifEmpty { "registry-export" }.replace(Regex("[\\\\/:*?\"<>|]"), "_") + ".reg") }
        }
    }

    fun disconnect() { holder[0]?.let { holder[0] = null; it.onState = null; it.stop() }; state = 0 }
    fun connect() {
        disconnect()
        error = null
        val t = Tunnel(session.ctrl, id, PROTO_REGISTRY)
        holder[0] = t
        t.onState = { s ->
            state = s
            status = when (s) { 1 -> "Connecting…"; 2 -> "Waiting for the agent…"; 3 -> ""; else -> "Disconnected" }
            if (s == 0) { rows = null; hive = null; path = ""; listReq = null }
            if (s == 3) goTo(null, "")
        }
        // like the file relay, the agent's JSON may arrive as a binary or a text frame
        t.onText = { txt -> (try { JSONObject(txt) } catch (e: Exception) { null })?.let { handle(it) } }
        t.onBinary = { b -> (try { JSONObject(String(b, Charsets.UTF_8)) } catch (e: Exception) { null })?.let { handle(it) } }
        t.onConsole = { msg -> if (msg.isNotEmpty()) status = msg }       // e.g. waiting for the user to grant access
        t.start()
    }
    DisposableEffect(id) { onDispose { disconnect() } }
    BackHandler(enabled = state == 3 && hive != null) { goUp() }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Registry", maxLines = 1)
                    Text(node?.name ?: "", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (allowed) {
                    if (state != 0) OutlinedButton({ disconnect() }) { Text(if (state == 3) "Disconnect" else "Cancel") }
                    else Button({ connect() }, enabled = node?.online == true) { Text("Connect") }
                }
                if (state == 3) {
                    IconButton({ refresh() }) { Icon(Icons.Filled.Refresh, "Refresh") }
                    Box {
                        IconButton({ topMenu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                        DropdownMenu(topMenu, { topMenu = false }) {
                            DropdownMenuItem({ Text("Go to key…") }, onClick = { topMenu = false; dialog = RegDialog.GoTo() })
                            DropdownMenuItem({ Text("New key…") }, enabled = hive != null, onClick = { topMenu = false; dialog = RegDialog.NewKey() })
                            DropdownMenuItem({ Text("New value…") }, enabled = hive != null, onClick = { topMenu = false; dialog = RegDialog.Value(null) })
                        }
                    }
                }
            })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            if (!allowed) {
                Text(when { node == null -> "This device is not in the list any more."; !node.isWindows -> "The registry is only available on Windows devices."
                    else -> NO_PERMISSION }, Modifier.padding(24.dp))
                return@Column
            }
            // breadcrumb: Root > hive > key > ...
            if (state == 3) Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                FilterChip(hive == null, { goTo(null, "") }, { Text("Root") })
                hive?.let { h ->
                    FilterChip(path.isEmpty(), { goTo(h, "") }, { Text(HIVES.entries.firstOrNull { it.value == h }?.key ?: h) })
                    val parts = if (path.isEmpty()) emptyList() else path.split('\\')
                    parts.forEachIndexed { i, p ->
                        FilterChip(i == parts.size - 1, { goTo(h, parts.take(i + 1).joinToString("\\")) },
                            { Text(p, maxLines = 1, overflow = TextOverflow.Ellipsis) })
                    }
                }
            }
            error?.let {
                Text(it, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall)
            }
            if (status.isNotEmpty()) Text(status, Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                items(rows ?: emptyList()) {
                    Box {
                        Row(Modifier.fillMaxWidth().combinedClickable(
                            onClick = {
                                when (it.kind) {
                                    "hive" -> goTo(it.raw, "")
                                    "key" -> goTo(hive, child(it.raw))
                                    else -> dialog = if (it.type in WRITABLE) RegDialog.Value(it) else RegDialog.Details(it)
                                }
                            },
                            onLongClick = { if (it.kind != "hive") menuFor = it })
                            .padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(when (it.kind) { "hive" -> Icons.Filled.Storage; "key" -> Icons.Filled.Folder
                                else -> Icons.AutoMirrored.Filled.InsertDriveFile }, null,
                                tint = if (it.kind == "value") MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary)
                            Column(Modifier.weight(1f).padding(start = 14.dp)) {
                                Text(it.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                if (it.kind == "value") Text(it.type + if (it.data.isNotEmpty()) "  " + it.data.replace('\n', ' ') else "",
                                    style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                            if (it.kind != "hive") IconButton({ menuFor = it }) { Icon(Icons.Filled.MoreVert, "Actions") }
                        }
                        DropdownMenu(menuFor === it, { menuFor = null }) {
                            if (it.kind == "value" && it.type in WRITABLE) DropdownMenuItem({ Text("Edit…") }, onClick = { menuFor = null; dialog = RegDialog.Value(it) })
                            if (!(it.kind == "value" && it.raw.isEmpty()))
                                DropdownMenuItem({ Text("Rename…") }, onClick = { menuFor = null; dialog = RegDialog.Rename(it) })
                            if (it.kind == "key") DropdownMenuItem({ Text("Export as .reg…") }, onClick = {
                                menuFor = null
                                exportName = it.raw
                                status = "Exporting ${it.name}…"
                                exportReq = send(JSONObject().put("action", "export").put("hive", hive).put("path", child(it.raw)))
                            })
                            DropdownMenuItem({ Text("Details") }, onClick = { menuFor = null; dialog = RegDialog.Details(it) })
                            DropdownMenuItem({ Text("Delete…", color = MaterialTheme.colorScheme.error) },
                                onClick = { menuFor = null; dialog = RegDialog.Delete(it) })
                        }
                    }
                    HorizontalDivider(Modifier.padding(start = 54.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                }
            }
        }
    }

    when (val d = dialog) {
        null -> {}
        is RegDialog.GoTo -> RegNameDialog("Go to key", "Path, e.g. HKLM\\SOFTWARE\\Microsoft", regDisplay(hive, path), "Go",
            onDismiss = { dialog = null }) { text ->
            val target = normalizeRegPath(text)
            if (target == null) "Invalid registry path. Use a full hive path such as HKEY_LOCAL_MACHINE\\SOFTWARE."
            else { dialog = null; goTo(target.first, target.second); null }
        }
        is RegDialog.NewKey -> RegNameDialog("New key in ${regDisplay(hive, path)}", "Key name", "", "Create",
            onDismiss = { dialog = null }) { name ->
            if (name.isBlank() || name.contains('\\')) "A registry name cannot be empty or contain a backslash."
            else { dialog = null; send(JSONObject().put("action", "createkey").put("hive", hive).put("path", path).put("name", name.trim())); null }
        }
        is RegDialog.Rename -> RegNameDialog("Rename ${d.item.name}", "New name", d.item.raw, "Rename",
            onDismiss = { dialog = null }) { name ->
            when {
                name.isBlank() || name.contains('\\') -> "A registry name cannot be empty or contain a backslash."
                name.trim() == d.item.raw -> { dialog = null; null }
                else -> {
                    dialog = null
                    send(JSONObject().put("action", "rename").put("newName", name.trim()).put("item", JSONObject()
                        .put("kind", d.item.kind).put("hive", hive).put("path", path).put("name", d.item.raw)))
                    null
                }
            }
        }
        is RegDialog.Value -> RegValueDialog(d.item, regDisplay(hive, path), onDismiss = { dialog = null }) { name, type, data ->
            dialog = null
            send(JSONObject().put("action", "setvalue").put("hive", hive).put("path", path).put("name", name).put("type", type).put("value", data))
        }
        is RegDialog.Delete -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Delete ${d.item.name}?") },
            text = { Text(if (d.item.kind == "key") "The key is deleted with all its subkeys and values." else "The value is deleted.") },
            confirmButton = { TextButton({
                dialog = null
                send(JSONObject().put("action", "delete").put("items", JSONArray().put(JSONObject().put("kind", d.item.kind)
                    .put("hive", hive).put("path", path).put("name", d.item.raw))))
            }) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } })
        is RegDialog.Details -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text(d.item.name) },
            text = {
                SelectionContainer {
                    Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        val itemPath = when (d.item.kind) { "hive" -> d.item.raw; "key" -> regDisplay(hive, child(d.item.raw)); else -> regDisplay(hive, path) }
                        listOf("Kind" to d.item.kind, "Path" to itemPath, "Type" to d.item.type).forEach { (k, v) ->
                            Column {
                                Text(k, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(v, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                        if (d.item.kind == "value") Column {
                            Text("Data", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(d.item.data, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                        }
                    }
                }
            },
            confirmButton = { TextButton({ dialog = null }) { Text("Close") } })
    }
}

/** One text field; onOk returns an error text to show, or null when done. */
@Composable
private fun RegNameDialog(title: String, label: String, initial: String, ok: String, onDismiss: () -> Unit, onOk: (String) -> String?) {
    var text by remember { mutableStateOf(initial) }
    var err by remember { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) },
        text = {
            Column {
                OutlinedTextField(text, { text = it; err = null }, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = true,
                    isError = err != null)
                err?.let { Text(it, Modifier.padding(top = 6.dp), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = { TextButton({ err = onOk(text) }) { Text(ok) } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}

/** New value (item == null: name editable) or edit a value: type and data, DWORD / QWORD must be numbers. */
@Composable
private fun RegValueDialog(item: RegItem?, where: String, onDismiss: () -> Unit, onOk: (String, String, String) -> Unit) {
    var name by remember { mutableStateOf(item?.raw ?: "") }
    var type by remember { mutableStateOf(item?.type?.takeIf { it in WRITABLE } ?: "REG_SZ") }
    var data by remember { mutableStateOf(item?.data ?: "") }
    var err by remember { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(if (item == null) "New value" else "Edit ${item.name}") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(where, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (item == null) OutlinedTextField(name, { name = it; err = null }, Modifier.fillMaxWidth(), label = { Text("Name") }, singleLine = true)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    WRITABLE.forEach { t -> FilterChip(type == t, { type = t; err = null }, { Text(t.removePrefix("REG_")) }) }
                }
                OutlinedTextField(data, { data = it; err = null }, Modifier.fillMaxWidth().heightIn(min = 96.dp), label = { Text("Data") },
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), singleLine = type in NUMERIC)
                err?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = { TextButton({
            when {
                item == null && name.isBlank() -> err = "Enter a name for the value."
                type in NUMERIC && !validNumber(data) -> err = "$type data must be a decimal number or 0x followed by hex digits."
                else -> onOk(if (item == null) name.trim() else item.raw, type, if (type in NUMERIC) data.trim() else data)
            }
        }) { Text(if (item == null) "Create" else "Save") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}
