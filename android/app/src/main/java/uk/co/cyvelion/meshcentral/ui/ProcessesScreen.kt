// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.NO_PERMISSION
import uk.co.cyvelion.meshcentral.data.Session

private class Proc(val pid: Int, val user: String, val cmd: String) {
    /** the program's name: last path part of the first word, for sorting and the headline */
    val name: String = cmd.trim().split(' ').firstOrNull()?.substringAfterLast('/')?.substringAfterLast('\\')?.ifEmpty { cmd } ?: cmd
}

// psinfo fields the web UI shows, in its order (tools_panel._PSINFO): key, label, kind (b = bytes, s = seconds, bool)
private val PSINFO = listOf(
    Triple("processName", "Process name", ""), Triple("machineName", "Machine name", ""), Triple("cmd", "Command line", ""),
    Triple("mainWindowTitle", "Window title", ""), Triple("processUser", "User", ""), Triple("processDomain", "Domain", ""),
    Triple("startTime", "Start time", ""), Triple("priorityBoostEnabled", "Priority boost", "bool"),
    Triple("sessionId", "Session ID", ""), Triple("handleCount", "Handle count", ""),
    Triple("privilegedProcessorTime", "Privileged processor time", "s"), Triple("totalProcessorTime", "Total processor time", "s"),
    Triple("userProcessorTime", "User processor time", "s"), Triple("nonpagedSystemMemorySize", "Non-paged memory", "b"),
    Triple("pagedMemorySize", "Paged memory", "b"), Triple("privateMemorySize", "Private memory", "b"),
    Triple("virtualMemorySize", "Virtual memory", "b"), Triple("workingSet", "Working set", "b"),
    Triple("peakWorkingSet", "Peak working set", "b"), Triple("peakPagedMemorySize", "Peak paged memory", "b"),
    Triple("peakVirtualMemorySize", "Peak virtual memory", "b"))
// Windows agents send PowerShell Get-Process fields: the ones the web UI does not show, in plain words
private val PSINFO_WINDOWS = listOf(
    Triple("description", "Description", ""), Triple("company", "Company", ""), Triple("product", "Product", ""),
    Triple("fileversion", "File version", ""), Triple("cpu", "Processor time", "s"), Triple("si", "Session ID", ""),
    Triple("basepriority", "Base priority", ""), Triple("ws", "Working set", "b"), Triple("pm", "Private memory", "b"),
    Triple("npm", "Non-paged memory", "b"), Triple("vm", "Virtual memory", "b"))
// Linux agents send /proc/<pid>/status as is: the useful lines first, in plain words, then the rest
private val PSINFO_LINUX = listOf("Name" to "Process name", "State" to "State", "Pid" to "Process ID",
    "PPid" to "Parent process ID", "Uid" to "User ID (real, effective, saved, fs)", "Gid" to "Group ID (real, effective, saved, fs)",
    "Threads" to "Threads", "VmRSS" to "Memory in use (RSS)", "VmSize" to "Virtual memory", "VmPeak" to "Peak virtual memory",
    "VmHWM" to "Peak memory in use", "VmSwap" to "Swapped out")

private fun empty(v: Any?) = v == null || v == JSONObject.NULL || v.toString().isEmpty() || v.toString() == "[]" || v.toString() == "{}"

private fun psValue(v: Any?, kind: String): String = when (kind) {
    "bool" -> if (v == true || v.toString() == "true") "Enabled" else "Disabled"
    "s" -> "$v seconds"
    "b" -> v.toString().toDoubleOrNull()?.let { fmtSize(it.toLong()) } ?: v.toString()
    else -> v.toString()
}

/** psinfo value -> label / text rows like the web UI's Process Details dialog (tools_panel.process_details). */
private fun processDetails(value: JSONObject?): List<Pair<String, String>> {
    if (value == null || value.length() == 0) return emptyList()
    val keys = value.keys().asSequence().toList()
    if (keys.any { it in setOf("PPid", "State", "Tgid", "VmRSS") }) {
        val raw = keys.associateWith { value.opt(it) }.toMutableMap()
        val out = ArrayList<Pair<String, String>>()
        PSINFO_LINUX.forEach { (k, label) -> raw.remove(k)?.takeIf { !empty(it) }?.let { out.add(label to it.toString().replace("\t", "  ")) } }
        raw.toSortedMap().forEach { (k, v) -> out.add(k to v.toString().replace("\t", "  ")) }
        return out
    }
    val low = HashMap<String, Any?>()          // web UI: jsonToCamel, compared without case
    keys.forEach { low[it.replace("_", "").lowercase()] = value.opt(it) }
    if (empty(low["cmd"]) && !empty(low["path"])) low["cmd"] = low["path"]
    val user = low["username"]?.toString() ?: ""
    if (empty(low["processuser"]) && user.contains('\\')) {
        low["processdomain"] = user.substringBefore('\\'); low["processuser"] = user.substringAfter('\\')
    }
    val out = ArrayList<Pair<String, String>>()
    PSINFO.forEach { (k, label, kind) -> low[k.lowercase()]?.takeIf { !empty(it) }?.let { out.add(label to psValue(it, kind)) } }
    val shown = out.map { it.first }.toMutableSet()
    PSINFO_WINDOWS.forEach { (k, label, kind) ->
        low[k]?.takeIf { !empty(it) && label !in shown }?.let { out.add(label to psValue(it, kind)); shown.add(label) }
    }
    if (!empty(low["name"]) && "Process name" !in shown) out.add(0, "Process name" to low["name"].toString())
    return out
}

/**
 * Processes (tools_panel.ProcessesPanel): agent msg `ps` -> value = JSON {pid: {cmd, user}}; `psinfo` for details
 * (a busy Windows agent can answer {}: asked again twice); `pskill` with value = pid.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProcessesScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val caps = node?.let { session.caps(it) }
    var procs by remember { mutableStateOf<List<Proc>?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var sort by rememberSaveable { mutableStateOf(0) }          // 0 name, 1 pid, 2 user
    var detail by remember { mutableStateOf<Proc?>(null) }
    var info by remember { mutableStateOf<List<Pair<String, String>>?>(null) }
    var infoState by remember { mutableStateOf(0) }              // 0 loading, 1 done, 2 no answer
    var kill by remember { mutableStateOf<Proc?>(null) }
    val main = remember { Handler(Looper.getMainLooper()) }
    val retries = remember { intArrayOf(0) }

    fun request() { procs = null; session.ctrl.nodeMsg(id, "ps") }
    fun askInfo(p: Proc) { session.ctrl.nodeMsg(id, "psinfo", "pid" to p.pid) }

    DisposableEffect(id) {
        val cb: (JSONObject) -> Unit = cb@{ m ->
            if (m.optString("nodeid", id) != id) return@cb
            when (m.optString("type")) {
                "ps" -> {
                    val v = try { JSONObject(m.optString("value", "{}")) } catch (e: Exception) { return@cb }
                    procs = v.keys().asSequence().mapNotNull { k ->
                        val pid = k.toIntOrNull() ?: return@mapNotNull null
                        if (pid == 0) return@mapNotNull null
                        val o = v.optJSONObject(k)
                        Proc(pid, o?.optString("user") ?: "", o?.optString("cmd") ?: "")
                    }.toList()
                }
                "psinfo" -> {
                    val d = detail ?: return@cb
                    if (m.optString("pid").toIntOrNull() != d.pid) return@cb
                    val v = m.optJSONObject("value")
                    if ((v == null || v.length() == 0) && retries[0] > 0) {
                        retries[0]--
                        main.postDelayed({ if (detail?.pid == d.pid) askInfo(d) }, 2000)
                        return@cb
                    }
                    info = processDetails(v); infoState = 1
                }
            }
        }
        session.ctrl.on("msg", cb)
        request()
        onDispose { session.ctrl.off("msg", cb); main.removeCallbacksAndMessages(null) }
    }

    fun openDetail(p: Proc) {
        detail = p; info = null; infoState = 0; retries[0] = 2
        askInfo(p)
        // Windows agents run PowerShell for this: it can take a while on a busy machine
        main.postDelayed({ if (detail?.pid == p.pid && infoState == 0) infoState = 2 }, 45_000)
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Processes", maxLines = 1)
                    Text(node?.name ?: "", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { IconButton({ request() }) { Icon(Icons.Filled.Refresh, "Refresh") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            if (node == null || caps?.tools != true) {
                Text(if (node == null) "This device is not in the list any more." else NO_PERMISSION, Modifier.padding(24.dp))
                return@Column
            }
            TextField(query, { query = it }, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), singleLine = true,
                placeholder = { Text("Search processes") }, shape = CircleShape,
                leadingIcon = { Icon(Icons.Filled.Search, null) },
                trailingIcon = { if (query.isNotEmpty()) IconButton({ query = "" }) { Icon(Icons.Filled.Close, "Clear") } },
                colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh))
            val q = query.trim().lowercase()
            val shown = procs?.filter { q.isEmpty() || it.cmd.lowercase().contains(q) || it.user.lowercase().contains(q) || it.pid.toString() == q }
                ?.let { l -> when (sort) { 1 -> l.sortedBy { it.pid }; 2 -> l.sortedWith(compareBy({ it.user.lowercase() }, { it.name.lowercase() }))
                    else -> l.sortedWith(compareBy({ it.name.lowercase() }, { it.pid })) } }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("Name", "PID", "User").forEachIndexed { i, l -> FilterChip(sort == i, { sort = i }, { Text(l) }) }
                Text(shown?.let { "${it.size} processes" } ?: "", Modifier.weight(1f).padding(top = 14.dp),
                    style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = androidx.compose.ui.text.style.TextAlign.End)
            }
            PullToRefreshBox(isRefreshing = procs == null && node.online, onRefresh = { request() }, modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                    if (!node.online) item { Text("The device is offline.", Modifier.padding(24.dp)) }
                    items(shown ?: emptyList(), key = { it.pid }) { p ->
                        Column(Modifier.fillMaxWidth().clickable { openDetail(p) }.padding(horizontal = 20.dp, vertical = 10.dp)) {
                            Row {
                                Text(p.name, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text("${p.pid}", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(p.cmd, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            if (p.user.isNotEmpty()) Text(p.user, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
                        }
                        HorizontalDivider(Modifier.padding(start = 20.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                    }
                }
            }
        }
    }

    detail?.let { p ->
        AlertDialog(onDismissRequest = { detail = null }, title = { Text("Process ${p.pid}") },
            text = {
                Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) {
                    when {
                        infoState == 0 && info == null -> Row {
                            CircularProgressIndicator(Modifier.padding(end = 12.dp).width(18.dp), strokeWidth = 2.dp)
                            Text("Requesting process details…")
                        }
                        info.isNullOrEmpty() -> {
                            Text(if (infoState == 2) "No answer from the agent." else "No information provided by the agent.")
                            Text(p.cmd, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                        }
                        else -> SelectionContainer {
                            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                info!!.forEach { (k, v) ->
                                    Column {
                                        Text(k, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        Text(v, style = MaterialTheme.typography.bodyMedium)
                                    }
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = { TextButton({ detail = null }) { Text("Close") } },
            dismissButton = { TextButton({ kill = p; detail = null }, enabled = node?.online == true) {
                Text("Kill process", color = MaterialTheme.colorScheme.error) } })
    }
    kill?.let { p ->
        AlertDialog(onDismissRequest = { kill = null }, title = { Text("Kill process ${p.pid}?") },
            text = { Text(p.cmd, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace)) },
            confirmButton = { TextButton({
                kill = null
                session.ctrl.nodeMsg(id, "pskill", "value" to p.pid)
                main.postDelayed({ request() }, 400)
            }) { Text("Kill process", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ kill = null }) { Text("Cancel") } })
    }
}
