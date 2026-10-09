// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import android.util.Base64
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.NO_PERMISSION
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Session

private const val SW_TIMEOUT_MS = 120_000L

/** One installed application (desktop or Microsoft Store). */
private class App(val o: JSONObject, val store: Boolean) {
    val name = o.optString("name").ifEmpty { "-" }
    val version = o.optString("version").ifEmpty { "-" }
    val publisher = o.optString("publisher")
    val date = o.optString("date")
    val location = o.optString("location").let { l -> if (o.optString("arch").isNotEmpty()) "$l (${o.optString("arch")})" else l }
    val uninstall = o.optString("uninstall")
    val scope = o.optString("scope").let { s -> listOf("User", "System", "Prov").filter { s.contains(it) }.joinToString(", ") }
    val packageFullName = o.optString("packageFullName")
    /** Store apps are removed by name, desktop apps by their uninstall command line */
    val removable get() = uninstall.isNotEmpty()
}

/**
 * Software (software_panel.py, web UI p18): {action:'software', nodeid, type:'installedapps'|'installedstoreapps'} -> the
 * agent answers {action:'software', nodeid, value:<JSON>}: an array, or {error} / {success}. NO responseid: the server
 * first answers {result:'Denied'} to any request carrying one. Uninstall only with full device rights, like the web UI.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SoftwareScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val caps = node?.let { session.caps(it) }
    val full = node != null && caps?.rights == Rights.FULL
    var desktop by remember { mutableStateOf<List<App>>(emptyList()) }
    var storeApps by remember { mutableStateOf<List<App>>(emptyList()) }
    var loading by remember { mutableStateOf<String?>(null) }    // 'installedapps' | 'installedstoreapps' | null
    var status by remember { mutableStateOf("") }
    var showStore by rememberSaveable { mutableStateOf(false) }
    var query by rememberSaveable { mutableStateOf("") }
    var selected by remember { mutableStateOf<App?>(null) }
    var confirm by remember { mutableStateOf<App?>(null) }
    var warnOps by remember { mutableStateOf<App?>(null) }
    val main = remember { Handler(Looper.getMainLooper()) }
    val timeout = remember { Runnable { if (loading != null) { loading = null; status = "No answer from the agent after ${SW_TIMEOUT_MS / 1000} s" } } }

    fun ask(type: String, text: String) {
        loading = type
        status = text
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, SW_TIMEOUT_MS)
        session.ctrl.send(JSONObject().put("action", "software").put("nodeid", id).put("type", type))
    }
    fun load() {
        if (loading != null || node == null) return
        if (!node.online) { status = "The device is offline."; return }
        desktop = emptyList(); storeApps = emptyList()
        ask("installedapps", "Loading installed software… (can take a minute)")
    }

    DisposableEffect(id) {
        val cb: (JSONObject) -> Unit = cb@{ m ->
            if (m.optString("nodeid", id) != id || m.optString("result") == "Denied") return@cb
            val v = m.opt("value")
            val data: Any? = if (v is String) (try { if (v.trim().startsWith("[")) JSONArray(v) else JSONObject(v) } catch (e: Exception) { null }) else v
            when {
                data is JSONArray -> {
                    val list = (0 until data.length()).mapNotNull { data.optJSONObject(it) }
                    main.removeCallbacks(timeout)
                    if (loading == "installedstoreapps") {
                        storeApps = list.map { App(it, true) }; loading = null; status = ""
                    } else {
                        desktop = list.map { App(it, false) }; loading = null; status = ""
                        if (showStore && node?.isWindows == true) ask("installedstoreapps", "Loading store apps…")
                    }
                }
                data is JSONObject && data.optString("error").isNotEmpty() -> {
                    main.removeCallbacks(timeout); loading = null; status = "Error: ${data.optString("error")}"
                }
                data is JSONObject && data.optBoolean("success") -> status = "Done. Refresh to update the list."
            }
        }
        session.ctrl.on("software", cb)
        load()                                       // the web UI also loads when the page opens
        onDispose { session.ctrl.off("software", cb); main.removeCallbacksAndMessages(null) }
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Software", maxLines = 1)
                    Text(node?.name ?: "", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { IconButton({ load() }, enabled = loading == null) { Icon(Icons.Filled.Refresh, "Refresh") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            if (node == null || caps?.software != true) {
                Text(if (node == null) "This device is not in the list any more." else NO_PERMISSION, Modifier.padding(24.dp))
                return@Column
            }
            TextField(query, { query = it }, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), singleLine = true,
                placeholder = { Text("Search software") }, shape = CircleShape,
                leadingIcon = { Icon(Icons.Filled.Search, null) },
                trailingIcon = { if (query.isNotEmpty()) IconButton({ query = "" }) { Icon(Icons.Filled.Close, "Clear") } },
                colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh))
            val q = query.trim().lowercase()
            fun match(a: App) = q.isEmpty() || a.name.lowercase().contains(q) || a.publisher.lowercase().contains(q)
            val desk = desktop.filter(::match).sortedBy { it.name.lowercase() }
            val store = if (showStore) storeApps.filter(::match).sortedBy { it.name.lowercase() } else emptyList()
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // the agent only lists Store apps on Windows
                if (node.isWindows) FilterChip(showStore, {
                    showStore = !showStore
                    if (showStore && storeApps.isEmpty() && loading == null && node.online) ask("installedstoreapps", "Loading store apps…")
                }, { Text("Store apps") })
                if (loading != null) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                Text(status.ifEmpty { if (desktop.isEmpty() && storeApps.isEmpty()) "" else
                    "Desktop ${desk.size}/${desktop.size}" + if (showStore) " · Store ${store.size}/${storeApps.size}" else "" },
                    Modifier.weight(1f), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                if (showStore) item { SwHeader("Desktop applications (${desk.size})") }
                items(desk) { a -> SwRow(a) { selected = a } }
                if (showStore) {
                    item { SwHeader("Microsoft Store apps (${store.size})") }
                    items(store) { a -> SwRow(a) { selected = a } }
                }
            }
        }
    }

    selected?.let { a ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(a.name) },
            text = {
                SelectionContainer {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        listOfNotNull("Version" to a.version, a.publisher.takeIf { it.isNotEmpty() }?.let { "Publisher" to it },
                            a.date.takeIf { it.isNotEmpty() }?.let { "Install date" to it },
                            a.location.takeIf { it.isNotEmpty() }?.let { "Location" to it },
                            a.scope.takeIf { it.isNotEmpty() }?.let { "Scope" to it },
                            a.packageFullName.takeIf { it.isNotEmpty() }?.let { "Package" to it }).forEach { (k, v) ->
                            Column {
                                Text(k, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(v, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                        if (a.removable && !full) Text("Uninstalling needs full rights on this device.", Modifier.padding(top = 6.dp),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            },
            confirmButton = { TextButton({ selected = null }) { Text("Close") } },
            dismissButton = { if (a.removable) TextButton({ selected = null; confirm = a }, enabled = full && node?.online == true) {
                Text(if (a.store) "Remove" else "Uninstall", color = MaterialTheme.colorScheme.error) } })
    }

    fun uninstall(a: App) {
        if (a.store) {
            session.ctrl.send(JSONObject().put("action", "software").put("nodeid", id).put("type", "uninstallstoreapp")
                .put("value", "\"" + a.name.replace("\"", "\\\"") + "\""))
            status = "Remove command sent. Refresh to update."
        } else {
            val v = Base64.encodeToString(a.uninstall.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
            session.ctrl.send(JSONObject().put("action", "software").put("nodeid", id).put("type", "uninstallapp").put("value", v))
            status = "Uninstall started. Refresh to update."
        }
    }
    confirm?.let { a ->
        AlertDialog(onDismissRequest = { confirm = null },
            title = { Text(if (a.store) "Remove this Store app?" else "Uninstall this software?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(a.name)
                    if (a.store) {
                        // the agent removes every package whose name CONTAINS this one (Get-AppxPackage -Name "*name*"),
                        // for all users: say how many that is before the user confirms
                        val others = storeApps.filter { it !== a && it.name.contains(a.name, ignoreCase = true) }
                        if (others.isNotEmpty()) Text("This also removes ${others.size} other package(s) whose name contains " +
                            "\"${a.name}\": " + others.take(5).joinToString(", ") { it.name } + if (others.size > 5) ", …" else "",
                            color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }
                    if (!a.store) {
                        Text(a.uninstall, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                        Text("A silent uninstall will be performed.")
                    }
                }
            },
            confirmButton = { TextButton({
                confirm = null
                // the command line comes from the device (a user there may have written it) and the agent runs it with
                // cmd.exe as SYSTEM: chained commands get a second, explicit warning
                if (!a.store && Regex("[&|<>^]").containsMatchIn(a.uninstall)) warnOps = a else uninstall(a)
            }) { Text(if (a.store) "Remove" else "Uninstall", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ confirm = null }) { Text("Cancel") } })
    }
    warnOps?.let { a ->
        AlertDialog(onDismissRequest = { warnOps = null }, title = { Text("This uninstall command runs more than one program") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(a.uninstall, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                    Text("Shell operators (& | < > ^) in an uninstall command are unusual and could run extra commands as SYSTEM " +
                        "on the device. Run it only if you trust it.")
                }
            },
            confirmButton = { TextButton({ warnOps = null; uninstall(a) }) { Text("Run anyway", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ warnOps = null }) { Text("Cancel") } })
    }
}

@Composable
private fun SwHeader(text: String) {
    Text(text.uppercase(), Modifier.padding(start = 20.dp, top = 14.dp, bottom = 6.dp), style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary)
}

@Composable
private fun SwRow(a: App, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 20.dp, vertical = 10.dp)) {
        Row {
            Text(a.name, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(a.version, Modifier.padding(start = 8.dp), style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        val sub = listOf(a.publisher, a.date).filter { it.isNotEmpty() }.joinToString(" · ")
        if (sub.isNotEmpty()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
    HorizontalDivider(Modifier.padding(start = 20.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}
