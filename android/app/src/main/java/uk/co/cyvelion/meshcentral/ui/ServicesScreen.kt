// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.NO_PERMISSION
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.randomHex

/** display name, type, state, service name (for control) */
private class Svc(val display: String, val type: String, val state: String, val name: String)

// Linux: the agent's own "services" enumeration is slow (3+ s locally, far more over a tunnel) and returns every
// unit twice. systemctl answers in milliseconds, so with the Run commands right we ask it through runcommands
// (output as a separate {action:'msg', type:'runcommands', result, responseid}) and fall back to the agent's list.
private const val SYSTEMCTL = "systemctl list-units --type=service --all --no-legend --no-pager --plain 2>/dev/null; " +
    "echo ===MCD===; systemctl list-unit-files --type=service --no-legend --no-pager 2>/dev/null"

/** systemctl output -> services, or null when it is not systemd output (tools_panel._handle_systemctl). */
private fun parseSystemctl(text: String): List<Svc>? {
    if (!text.contains("===MCD===")) return null
    val (units, files) = text.split("===MCD===", limit = 2)
    data class U(val sub: String, val active: String, val desc: String)
    val info = HashMap<String, U>()
    units.lines().forEach { line ->
        val p = line.trim().split(Regex("\\s+"), limit = 5)              // unit load active sub description
        if (p.size >= 4 && p[0].endsWith(".service")) info[p[0].dropLast(8)] = U(p[3], p[2], p.getOrElse(4) { "" })
    }
    val startup = HashMap<String, String>()
    files.lines().forEach { line ->
        val p = line.trim().split(Regex("\\s+"))                         // unit state [preset]
        if (p.size >= 2 && p[0].endsWith(".service") && !p[0].contains("@.")) startup[p[0].dropLast(8)] = p[1]
    }
    if (info.isEmpty() && startup.isEmpty()) return null
    return (info.keys + startup.keys).map { name ->
        val u = info[name]
        val sub = u?.sub ?: "dead"
        var state = when (sub) { "running" -> "Running"; "exited" -> "Exited"; "dead" -> "Inactive"; "failed" -> "Failed"
            else -> sub.replaceFirstChar { it.uppercase() } }
        if (u?.active == "failed") state = "Failed"
        Svc(u?.desc?.ifEmpty { null } ?: name, "systemd" + (startup[name]?.let { " · $it" } ?: ""), state, name)
    }
}

/** The agent's "services" list: every Linux unit twice (keep the copy with a state); Windows entries carry status. */
private fun parseAgentServices(value: String): List<Svc> {
    val a = try { JSONArray(value) } catch (e: Exception) { return emptyList() }
    fun raw(s: JSONObject) = s.optString("state").ifEmpty { s.optJSONObject("status")?.optString("state") ?: "" }
    val byName = LinkedHashMap<String, JSONObject>()
    for (i in 0 until a.length()) {
        val s = a.optJSONObject(i) ?: continue
        val key = s.optString("name").ifEmpty { s.optString("displayName").ifEmpty { s.optString("description") } }
        if (key.isEmpty()) continue
        val prev = byName[key]
        if (prev == null || (raw(prev).isEmpty() && raw(s).isNotEmpty())) byName[key] = s
    }
    return byName.values.map { s ->
        val status = s.optJSONObject("status")
        if (status != null) {                                                // Windows: live SCM state
            val st = status.optString("state").lowercase().replaceFirstChar { it.uppercase() }.ifEmpty { "Unknown" }
            Svc(s.optString("displayName").ifEmpty { s.optString("name") }, "service", st, s.optString("name"))
        } else {                                                             // Linux / systemd
            val display = s.optString("description").ifEmpty { s.optString("name") }
            Svc(display, s.optString("serviceType").ifEmpty { "service" }, if (raw(s).isNotEmpty()) "Running" else "Inactive",
                s.optString("name").ifEmpty { display })
        }
    }
}

/**
 * Services (tools_panel.ServicesPanel): list, search, start / stop / restart (agent msg serviceStart|Stop|Restart with
 * serviceName). They only work when the agent runs as root (Linux) or SYSTEM (Windows).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServicesScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val caps = node?.let { session.caps(it) }
    var services by remember { mutableStateOf<List<Svc>?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var runningOnly by rememberSaveable { mutableStateOf(false) }
    var selected by remember { mutableStateOf<Svc?>(null) }
    var confirm by remember { mutableStateOf<Pair<Svc, Pair<String, String>>?>(null) }   // service, (label, action)
    val rid = remember { arrayOfNulls<String>(1) }
    val main = remember { Handler(Looper.getMainLooper()) }

    fun agentList() = session.ctrl.nodeMsg(id, "services")
    fun request() {
        services = null
        if (node == null) return
        if (node.isWindows || caps?.runCommands != true) { agentList(); return }
        val r = "mcdsvc" + randomHex()
        rid[0] = r
        session.ctrl.send(JSONObject().put("action", "runcommands").put("nodeids", JSONArray().put(id)).put("type", 3)
            .put("cmds", SYSTEMCTL).put("runAsUser", 0).put("reply", true).put("responseid", r))
        main.postDelayed({ if (rid[0] == r) { rid[0] = null; agentList() } }, 10_000)   // never answered: the agent's list
    }

    DisposableEffect(id) {
        val cb: (JSONObject) -> Unit = cb@{ m ->
            if (m.optString("nodeid", id) != id) return@cb
            when (m.optString("type")) {
                "runcommands" -> {
                    if (m.optString("responseid") != rid[0] || rid[0] == null) return@cb
                    val result = m.optString("result")
                    if (result == "OK") return@cb
                    rid[0] = null
                    val list = parseSystemctl(result)
                    if (list != null) services = list else agentList()          // not systemd / no output
                }
                "services" -> services = parseAgentServices(m.optString("value", "[]"))
            }
        }
        session.ctrl.on("msg", cb)
        request()
        onDispose { session.ctrl.off("msg", cb); main.removeCallbacksAndMessages(null) }
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Services", maxLines = 1)
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
                placeholder = { Text("Search services") }, shape = CircleShape,
                leadingIcon = { Icon(Icons.Filled.Search, null) },
                trailingIcon = { if (query.isNotEmpty()) IconButton({ query = "" }) { Icon(Icons.Filled.Close, "Clear") } },
                colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh))
            val q = query.trim().lowercase()
            val shown = services?.filter { (!runningOnly || it.state == "Running") &&
                (q.isEmpty() || it.display.lowercase().contains(q) || it.name.lowercase().contains(q)) }?.sortedBy { it.display.lowercase() }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                FilterChip(runningOnly, { runningOnly = !runningOnly }, { Text("Running") })
                Text(services?.let { l -> "${shown!!.size} shown · ${l.count { it.state == "Running" }} of ${l.size} running" } ?: "",
                    Modifier.weight(1f), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = androidx.compose.ui.text.style.TextAlign.End)
            }
            Text("Start, stop and restart need the agent to run as root (Linux) or SYSTEM (Windows); otherwise they have no effect.",
                Modifier.padding(horizontal = 20.dp, vertical = 2.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            PullToRefreshBox(isRefreshing = services == null && node.online, onRefresh = { request() }, modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                    if (!node.online) item { Text("The device is offline.", Modifier.padding(24.dp)) }
                    items(shown ?: emptyList(), key = { it.name + "|" + it.display }) { s ->
                        Row(Modifier.fillMaxWidth().clickable { selected = s }.padding(horizontal = 20.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(s.display, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(if (s.name != s.display) "${s.name} · ${s.type}" else s.type, style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                            StateBadge(s.state)
                        }
                        HorizontalDivider(Modifier.padding(start = 20.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                    }
                }
            }
        }
    }

    selected?.let { s ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(s.display) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Service: ${s.name}", style = MaterialTheme.typography.bodyMedium)
                    Text("Type: ${s.type}", style = MaterialTheme.typography.bodyMedium)
                    Text("State: ${s.state}", style = MaterialTheme.typography.bodyMedium)
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        listOf("Start" to "serviceStart", "Stop" to "serviceStop", "Restart" to "serviceRestart").forEach { a ->
                            TextButton({ selected = null; confirm = s to a }, enabled = node?.online == true) { Text(a.first) }
                        }
                    }
                }
            },
            confirmButton = { TextButton({ selected = null }) { Text("Close") } })
    }
    confirm?.let { (s, a) ->
        AlertDialog(onDismissRequest = { confirm = null }, title = { Text("${a.first} service?") },
            text = { Text(s.display) },
            confirmButton = { TextButton({
                confirm = null
                session.ctrl.nodeMsg(id, a.second, "serviceName" to s.name)
                main.postDelayed({ request() }, 800)
            }) { Text(a.first) } },
            dismissButton = { TextButton({ confirm = null }) { Text("Cancel") } })
    }
}

@Composable
private fun StateBadge(state: String) {
    val c = when (state) { "Running" -> OnlineGreen; "Failed" -> MaterialTheme.colorScheme.error; else -> OfflineGray }
    Text(state, Modifier.padding(start = 8.dp).background(c.copy(alpha = 0.13f), CircleShape).padding(horizontal = 10.dp, vertical = 3.dp),
        style = MaterialTheme.typography.labelMedium, color = if (state == "Running" || state == "Failed") c else MaterialTheme.colorScheme.onSurfaceVariant)
}
