// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Backup
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.data.Site
import uk.co.cyvelion.meshcentral.net.ControlConnection
import java.text.SimpleDateFormat
import java.time.Instant
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

private const val STATS_INTERVAL_MS = 10_000
private val STATE_NAMES = listOf("UserAccounts" to "User accounts", "DeviceGroups" to "Device groups",
    "AgentSessions" to "Agent sessions", "ConnectedUsers" to "Connected users", "UsersSessions" to "User sessions",
    "RelaySessions" to "Relay sessions", "RelayCount" to "Relay count", "ConnectedIntelAMT" to "Connected Intel AMT",
    "ConnectedIntelAMTCira" to "Connected Intel AMT CIRA", "RelayErrors" to "Relay errors")
/** Server warning texts by id (same table as the web UI; {0}, {1} = args). */
private val WARNINGS = mapOf(
    2 to "Missing WebDAV parameters.", 3 to "Unrecognized configuration option \"{0}\".",
    4 to "WebSocket compression is disabled, this feature is broken in NodeJS v11.11 to v12.15 and v13.2",
    5 to "Unable to load Intel AMT TLS root certificate for default domain.",
    6 to "Unable to load Intel AMT TLS root certificate for domain {0}.",
    7 to "CIRA local FQDN's ignored when server in LAN-only or WAN-only mode.",
    8 to "Can't have more than 4 CIRA local FQDN's. Ignoring value.",
    9 to "Agent hash checking is being skipped, this is unsafe.", 10 to "Missing Let's Encrypt email address.",
    11 to "Invalid Let's Encrypt host names.", 12 to "Invalid Let's Encrypt names, can't contain a *.",
    13 to "Unable to setup Let's Encrypt module.", 14 to "Invalid Let's Encrypt names, unable to resolve: {0}",
    15 to "Invalid Let's Encrypt email address, unable to resolve: {0}",
    16 to "Unable to load CloudFlare trusted proxy IPv6 address list.",
    17 to "SendGrid server has limited use in LAN mode.", 18 to "SMTP server has limited use in LAN mode.",
    19 to "SMS gateway has limited use in LAN mode.", 20 to "Invalid \"LoginCookieEncryptionKey\" in config.json.",
    21 to "Backup path can't be set within meshcentral-data folder, backup settings ignored.",
    22 to "Failed to sign agent {0}: {1}", 23 to "Unable to load agent icon file: {0}.",
    24 to "Unable to load agent logo file: {0}.", 25 to "This NodeJS version does not support OpenID.",
    26 to "This NodeJS version does not support Discord.js.",
    27 to "Firebase now requires a service account JSON file, Firebase disabled.")
private val WARNING_HINTS = mapOf(22 to "MeshCentral re-signs its Windows agent installers and timestamps the signature " +
    "through an online timestamp server. This usually means the server could not reach it (outbound HTTP, DNS or IPv6). " +
    "Linux agents and existing agents are not affected.")

private fun warningText(w: Any?): Pair<String, String?> {
    if (w !is JSONObject) return (w?.toString() ?: "") to null
    var t = WARNINGS[w.optInt("id", -1)] ?: return w.optString("msg").ifEmpty { w.toString() } to null
    w.optJSONArray("args")?.let { a -> for (i in 0 until a.length()) t = t.replace("{$i}", a.opt(i).toString()) }
    return t to WARNING_HINTS[w.optInt("id")]
}

// ---- Stats: same series, colours and ranges as the web UI (server_panel.build_series) ----
private val RANGES = listOf("3 h" to 3, "8 h" to 8, "Day" to 24, "Week" to 168, "30 days" to 720)
private val CHART_KINDS = listOf("connections" to "Connections", "memory" to "Memory", "cpu" to "CPU",
    "in" to "Traffic in", "out" to "Traffic out")
private fun rgb(r: Int, g: Int, b: Int) = Color(r, g, b)
private val CONN_SERIES = listOf(Triple("Agents", "ca", rgb(158, 151, 16)), Triple("Users", "cu", rgb(16, 84, 158)),
    Triple("User sessions", "us", rgb(255, 99, 132)), Triple("Relay sessions", "rs", rgb(39, 158, 16)),
    Triple("Intel AMT", "am", rgb(134, 16, 158)), Triple("Intel AMT CIRA", "amc", rgb(255, 155, 0)))
private val MEM_SERIES = listOf(Triple("External", "external", rgb(158, 151, 16)), Triple("Heap used", "heapUsed", rgb(16, 84, 158)),
    Triple("Heap total", "heapTotal", rgb(255, 99, 132)), Triple("RSS", "rss", rgb(39, 158, 16)))
private val TRAFFIC_NAMES = listOf("Agent", "CIRA", "AMT-OS", "HTTP", "Relay", "Terminal", "Desktop", "Files", "WebRDP",
    "WebSSH", "WebVNC", "Desktop multiplex")
private val TRAFFIC_COLORS = listOf(rgb(158, 151, 16), rgb(16, 84, 158), rgb(255, 99, 132), rgb(39, 158, 16), rgb(134, 16, 158),
    rgb(0, 148, 255), rgb(255, 216, 0), rgb(255, 127, 237), rgb(109, 213, 255), rgb(89, 94, 255), rgb(179, 104, 255), rgb(179, 104, 255))
private val Y_TITLES = mapOf("connections" to "Connections", "memory" to "MB", "cpu" to "Load (1 min)", "in" to "MB", "out" to "MB")
private const val MB = 1024.0 * 1024.0

private class Series(val name: String, val color: Color, val pts: List<Pair<Double, Double?>>)   // (epoch s, value or null = gap)

private fun epoch(t: Any?): Double? = when (t) {
    is Number -> t.toDouble().let { if (it > 1e11) it / 1000 else it }
    is String -> try { Instant.parse(t).toEpochMilli() / 1000.0 } catch (e: Exception) { null }
    else -> null
}

/** 1-minute load from a sample's cpu: a list, or an object keyed "0" (depends on the server's database). */
private fun cpu1(cpu: Any?): Double? = when (cpu) {
    is JSONArray -> if (cpu.length() > 0) (cpu.opt(0) as? Number)?.toDouble() else null
    is JSONObject -> (cpu.opt("0") as? Number)?.toDouble()
    else -> null
}

private fun trafficValues(tr: JSONObject, inbound: Boolean): List<Double> {
    val d = if (inbound) "In" else "Out"
    val relay = tr.opt("relay$d")
    fun rel(i: Int): Double = when (relay) {
        is JSONArray -> (relay.opt(i) as? Number)?.toDouble() ?: 0.0
        is JSONObject -> (relay.opt(i.toString()) as? Number)?.toDouble() ?: 0.0
        else -> 0.0
    }
    val v = mutableListOf(tr.optDouble("AgentCtrl$d", 0.0), tr.optDouble("CIRA$d", 0.0), tr.optDouble("LMS$d", 0.0), tr.optDouble("http$d", 0.0))
    listOf(0, 1, 2, 5, 10, 11, 12).forEach { v.add(rel(it)) }
    v.add(tr.optJSONObject("desktopMultiplex")?.optDouble(if (inbound) "in" else "out", 0.0) ?: 0.0)
    return v.map { (if (it.isNaN()) 0.0 else it) / MB }
}

private fun buildSeries(all: List<JSONObject>, kind: String): List<Series> {
    var samples = all.filter { epoch(it.opt("time")) != null }
    val first = samples.firstOrNull { it.has("s") }?.opt("s")
    if (first != null) samples = samples.filter { it.opt("s") == first }        // peering: the first server, like the web UI
    samples = samples.sortedBy { epoch(it.opt("time")) }
    fun from(spec: List<Triple<String, String, Color>>, get: (JSONObject, String) -> Double?): List<Series> = spec.mapNotNull { (name, key, col) ->
        val pts = ArrayList<Pair<Double, Double?>>()
        samples.forEach { s ->
            val t = epoch(s.opt("time"))!!
            if (s.optBoolean("first")) pts.add(t - 0.001 to null)          // server restarted: a gap
            get(s, key)?.let { pts.add(t to it) }
        }
        if (key == "amc" && pts.none { it.second != null }) null else Series(name, col, pts)
    }
    return when (kind) {
        "connections" -> from(CONN_SERIES) { s, k -> s.optJSONObject("conn")?.opt(k)?.let { (it as? Number)?.toDouble() } }
        "memory" -> from(MEM_SERIES) { s, k -> s.optJSONObject("mem")?.let { it.optDouble(k, 0.0) / MB } }
        "cpu" -> from(listOf(Triple("CPU", "0", rgb(158, 151, 16)))) { s, _ -> cpu1(s.opt("cpu")) }
        else -> {
            val inbound = kind == "in"
            val rows = samples.filter { it.has("traffic") }.map { it to trafficValues(it.optJSONObject("traffic") ?: JSONObject(), inbound) }
            TRAFFIC_NAMES.indices.filter { i -> rows.any { it.second[i] > 0 } }.map { i ->
                val pts = ArrayList<Pair<Double, Double?>>()
                rows.forEach { (s, v) ->
                    val t = epoch(s.opt("time"))!!
                    if (s.optBoolean("first")) pts.add(t - 0.001 to null)
                    pts.add(t to v[i])
                }
                Series(TRAFFIC_NAMES[i], TRAFFIC_COLORS[i], pts)
            }
        }
    }
}

private fun fmtNum(v: Double): String = if (abs(v) >= 100 || v == Math.floor(v)) "%.0f".format(v) else if (abs(v) >= 10) "%.1f".format(v) else "%.2f".format(v)

/** Listen for one reply of a broadcast-style action (no responseid). */
private fun onceReply(ctrl: ControlConnection, action: String, secs: Long, onTimeout: () -> Unit, cb: (JSONObject) -> Unit) {
    var done = false
    var h: ((JSONObject) -> Unit)? = null
    h = { m -> if (!done) { done = true; ctrl.off(action, h!!); cb(m) } }
    ctrl.on(action, h)
    Handler(Looper.getMainLooper()).postDelayed({ if (!done) { done = true; ctrl.off(action, h); onTimeout() } }, secs * 1000)
}

private val TRACE_GROUPS = listOf(
    "Core server" to listOf("cookie" to "Cookie encoder", "dispatch" to "Message dispatcher", "main" to "Main server messages",
        "peer" to "MeshCentral server peering", "agent" to "MeshAgent traffic", "agentupdate" to "MeshAgent update",
        "cert" to "Server certificate", "db" to "Server database", "email" to "Email / SMS / push traffic"),
    "Web server" to listOf("web" to "Web server", "webrequest" to "Web server requests", "relay" to "Web socket relay",
        "httpheaders" to "Web server HTTP headers", "authlog" to "User authentication log"),
    "Intel AMT" to listOf("amt" to "Intel AMT manager", "webrelay" to "Connection relay", "mps" to "CIRA server",
        "mpscmd" to "CIRA server commands"))
private val TRACE_NAMES = TRACE_GROUPS.flatMap { it.second }.toMap()
private const val TRACE_LIMIT = 500

private sealed interface SrvDialog {
    data class Text(val title: String, val text: String, val warning: String? = null, val clearLog: Boolean = false) : SrvDialog
    data class Version(val current: String, val stable: String, val latest: String) : SrvDialog
    data class ConfirmUpdate(val version: String) : SrvDialog
    data object ConfigWarning : SrvDialog
    data object Trace : SrvDialog
    data class TraceItem(val e: JSONObject) : SrvDialog
}

/**
 * My Server (server_panel.py, web UI "My Server"): live server statistics, the stats history chart, the server
 * console and tracing. Site rights: the page needs backup 1, restore 4 or update 16; backup download needs 1; version,
 * error log and configuration need 16; console and trace are for full administrators only.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ServerScreen(app: McdApp, session: Session, onBack: () -> Unit) {
    val ctrl = session.ctrl
    val ctx = LocalContext.current
    val ui = ctrl.userinfo
    val full = Site.full(ui)
    val allowed = Site.has(ui, Site.BACKUP) || Site.has(ui, Site.RESTORE) || Site.has(ui, Site.UPDATE)
    val canBackup = Site.has(ui, Site.BACKUP)
    val canUpdate = Site.has(ui, Site.UPDATE)
    val tabs = if (full) listOf("General", "Stats", "Console", "Trace") else listOf("General", "Stats")
    var tab by rememberSaveable { mutableIntStateOf(0) }

    var stats by remember { mutableStateOf<JSONObject?>(null) }
    var updatedAt by remember { mutableStateOf("") }
    val timeline = remember { mutableStateListOf<JSONObject>() }
    var timelineLoaded by remember { mutableStateOf(false) }
    var range by rememberSaveable { mutableIntStateOf(0) }
    var kind by rememberSaveable { mutableIntStateOf(0) }
    val console = remember { mutableStateListOf<String>() }
    val trace = remember { mutableStateListOf<JSONObject>() }
    var traceSources by remember { mutableStateOf(ServerSignInInfo.traceSources(ctrl)) }
    var dialog by remember { mutableStateOf<SrvDialog?>(null) }
    var clearLogAsk by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf<String?>(null) }
    var backupProgress by remember { mutableStateOf<Float?>(null) }
    val web = remember { ServerWebSession(ctrl) }

    fun requestTimeline() { timelineLoaded = false; ctrl.send("action" to "servertimelinestats", "hours" to RANGES[range].second) }

    DisposableEffect(allowed) {
        if (!allowed) return@DisposableEffect onDispose {}
        val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
        val onStats: (JSONObject) -> Unit = { m -> stats = m; updatedAt = fmt.format(Date()) }
        val onTimeline: (JSONObject) -> Unit = { m ->
            timeline.clear()
            m.optJSONArray("events")?.let { a -> for (i in 0 until a.length()) a.optJSONObject(i)?.let { timeline.add(it) } }
            timelineLoaded = true
        }
        val onConsole: (JSONObject) -> Unit = { m -> if (m.has("value")) { console.add(m.optString("value").trimEnd('\n')); while (console.size > 2000) console.removeAt(0) } }
        val onEvent: (JSONObject) -> Unit = { m ->
            val ev = m.optJSONObject("event")
            when (ev?.optString("action")) {
                "servertimelinestats" -> ev.optJSONObject("data")?.let { timeline.add(it) }      // a new 5-minute sample
                "traceinfo" -> traceSources = ev.optJSONArray("traceSources")
            }
        }
        val onTrace: (JSONObject) -> Unit = { m -> trace.add(0, m); while (trace.size > TRACE_LIMIT) trace.removeAt(trace.size - 1) }
        val onTraceInfo: (JSONObject) -> Unit = { m -> traceSources = m.optJSONArray("traceSources") }
        ctrl.on("serverstats", onStats)
        ctrl.on("servertimelinestats", onTimeline)
        ctrl.on("serverconsole", onConsole)
        ctrl.on("event", onEvent)
        ctrl.on("trace", onTrace)
        ctrl.on("traceinfo", onTraceInfo)
        ctrl.send("action" to "serverstats", "interval" to STATS_INTERVAL_MS)
        onDispose {
            ctrl.send("action" to "serverstats")                  // no interval: the server stops the timer
            ctrl.off("serverstats", onStats); ctrl.off("servertimelinestats", onTimeline); ctrl.off("serverconsole", onConsole)
            ctrl.off("event", onEvent); ctrl.off("trace", onTrace); ctrl.off("traceinfo", onTraceInfo)
        }
    }
    LaunchedEffect(tab, range) { if (allowed && tab == 1) requestTimeline() }

    val saveBackup = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val out = try { ctx.contentResolver.openOutputStream(uri) } catch (e: Exception) { null }
            ?: run { Toast.makeText(ctx, "Cannot write the file.", Toast.LENGTH_SHORT).show(); return@rememberLauncherForActivityResult }
        busy = "Creating the backup on the server (can take up to 2 minutes)…"
        backupProgress = null
        web.fetch("/backup.zip", out, { d, t -> busy = "Downloading backup (${fmtSize(d)})"; backupProgress = if (t > 0) d.toFloat() / t else null }) { err ->
            busy = null
            val hint = when {
                err == null -> ""
                err.contains("403") -> "\n\nBackups are disabled in the server configuration (settings.autobackup)."
                err.contains("401") -> "\n\nDownloading backups is not allowed for this account or domain (myserver.backup)."
                else -> ""
            }
            dialog = SrvDialog.Text(if (err == null) "Server backup saved" else "Backup failed", (err ?: "The backup was saved.") + hint)
        }
    }

    fun checkVersion() {
        busy = "Checking the server version (the server asks the npm registry)…"
        onceReply(ctrl, "serverversion", 30, {
            busy = null
            dialog = SrvDialog.Text("No answer from the server", "The server did not report its version within 30 seconds. It may be unable to reach " +
                "the npm registry, or version checks are disabled for this domain (myserver.upgrade).")
        }) { m ->
            busy = null
            val tags = m.optJSONObject("tags")
            val cur = tags?.optString("current").orEmpty()
            dialog = if (m.has("result") && m.optString("result") != "OK") SrvDialog.Text("Cannot check the server version", m.optString("result"))
            else if (cur.isEmpty()) SrvDialog.Text("Cannot check the server version", "The server could not determine the available versions (npm registry unreachable?).")
            else SrvDialog.Version(cur, tags?.optString("stable").orEmpty(), tags?.optString("latest").orEmpty())
        }
        ctrl.send("action" to "serverversion")
    }
    fun errorLog() {
        busy = "Reading the error log…"
        onceReply(ctrl, "servererrors", 15, { busy = null; dialog = SrvDialog.Text("No answer from the server", "The error log may be disabled for this domain (myserver.errorlog).") }) { m ->
            busy = null
            val data = m.optString("data")
            dialog = SrvDialog.Text("Server error log", data.ifEmpty { "The server error log is empty." }, clearLog = data.isNotEmpty())
        }
        ctrl.send("action" to "servererrors")
    }
    fun config() {
        busy = "Reading the configuration…"
        onceReply(ctrl, "serverconfig", 15, { busy = null; dialog = SrvDialog.Text("No answer from the server", "Viewing the configuration may be disabled (myserver.config).") }) { m ->
            busy = null
            dialog = SrvDialog.Text("Server configuration (config.json)", m.optString("data"), warning = "This file can contain secrets (passwords, keys). Do not share it.")
        }
        ctrl.send("action" to "serverconfig")
    }

    Scaffold(topBar = {
        Column {
            TopAppBar(title = {
                Column {
                    Text("Server")
                    Text(ctrl.server.host, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }, navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
            if (allowed) PrimaryScrollableTabRow(selectedTabIndex = tab.coerceAtMost(tabs.size - 1), edgePadding = 8.dp) {
                tabs.forEachIndexed { i, t -> Tab(tab == i, { tab = i }, text = { Text(t) }) }
            }
        }
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding()) {
            if (!allowed) {
                Text("My Server needs the server backup, restore or update permission. An administrator can grant it.",
                    Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                return@Column
            }
            busy?.let { b ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
                    Text(b, style = MaterialTheme.typography.bodySmall)
                    val p = backupProgress
                    if (p == null) LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 4.dp))
                    else LinearProgressIndicator({ p.coerceIn(0f, 1f) }, Modifier.fillMaxWidth().padding(top = 4.dp))
                }
            }
            when (tabs.getOrNull(tab) ?: "General") {
                "General" -> GeneralTab(ctrl, stats, updatedAt, canBackup, canUpdate, busy == null,
                    onBackup = { saveBackup.launch("meshcentral-backup-" + SimpleDateFormat("yyyyMMdd-HHmm", Locale.US).format(Date()) + ".zip") },
                    onVersion = { checkVersion() }, onErrors = { errorLog() }, onConfig = { dialog = SrvDialog.ConfigWarning })
                "Stats" -> StatsTab(timeline, timelineLoaded, range, kind, { range = it }, { kind = it }) { requestTimeline() }
                "Console" -> ConsoleTab(ctrl, console)
                "Trace" -> TraceTab(traceSources, trace, onChoose = { dialog = SrvDialog.Trace },
                    onOff = { ctrl.send("action" to "traceinfo", "traceSources" to JSONArray()) },
                    onClear = { trace.clear() }, onShow = { dialog = SrvDialog.TraceItem(it) })
            }
        }
    }

    // the error log can be evidence of a problem: clearing it is confirmed (it cannot be undone)
    if (clearLogAsk) AlertDialog(onDismissRequest = { clearLogAsk = false }, title = { Text("Clear the server error log?") },
        text = { Text("The log is deleted on the server for good.") },
        confirmButton = { TextButton({ clearLogAsk = false; dialog = null; ctrl.send("action" to "serverclearerrorlog") }) {
            Text("Clear log", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton({ clearLogAsk = false }) { Text("Cancel") } })
    when (val d = dialog) {
        null -> {}
        is SrvDialog.Text -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text(d.title) },
            text = {
                Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) {
                    d.warning?.let { Text(it, Modifier.padding(bottom = 8.dp), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    SelectionContainer {
                        Text(d.text, fontFamily = if (d.text.contains('\n')) FontFamily.Monospace else null, style = MaterialTheme.typography.bodySmall)
                    }
                }
            },
            confirmButton = { TextButton({ dialog = null }) { Text("Close") } },
            dismissButton = { if (d.clearLog) TextButton({ clearLogAsk = true }) {
                Text("Clear log", color = MaterialTheme.colorScheme.error) } })
        SrvDialog.ConfigWarning -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Show the server configuration?") },
            text = { Text("config.json can contain secrets such as passwords and keys. Make sure nobody else can see your screen.") },
            confirmButton = { TextButton({ dialog = null; config() }) { Text("Show") } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } })
        is SrvDialog.Version -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("MeshCentral ${d.current}") },
            text = {
                Column {
                    InfoLine("Current", d.current)
                    InfoLine("Stable", d.stable.ifEmpty { "unknown" })
                    InfoLine("Latest", d.latest.ifEmpty { "unknown" }, last = true)
                    val offers = listOfNotNull(d.latest.takeIf { it.isNotEmpty() && it != d.current },
                        d.stable.takeIf { it.isNotEmpty() && it != d.current && it != d.latest })
                    if (offers.isEmpty()) Text("The server is up to date.", Modifier.padding(top = 8.dp))
                    offers.forEach { v ->
                        OutlinedButton({ dialog = SrvDialog.ConfirmUpdate(v) }, Modifier.fillMaxWidth().padding(top = 6.dp)) {
                            Text(if (v == d.stable) "Install $v (stable)" else "Update to $v")
                        }
                    }
                }
            },
            confirmButton = { TextButton({ dialog = null }) { Text("Close") } })
        is SrvDialog.ConfirmUpdate -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Install MeshCentral ${d.version}?") },
            text = { Text("The server downloads the new version and RESTARTS. All users and agents are disconnected for a short time.") },
            confirmButton = { TextButton({
                dialog = null
                ctrl.send("action" to "serverupdate", "version" to d.version)
                Toast.makeText(ctx, "Server update to ${d.version} started", Toast.LENGTH_LONG).show()
            }) { Text("Install and restart", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } })
        SrvDialog.Trace -> TraceDialog(traceSources, { dialog = null }) { chosen ->
            dialog = null
            ctrl.send("action" to "traceinfo", "traceSources" to JSONArray(chosen))
        }
        is SrvDialog.TraceItem -> AlertDialog(onDismissRequest = { dialog = null },
            title = { Text("Trace: " + d.e.optString("source").uppercase()) },
            text = {
                Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) {
                    Text(srvTime(d.e.opt("time")), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    SelectionContainer {
                        Text(d.e.optJSONArray("args")?.let { a -> (0 until a.length()).joinToString("\n\n") { srvPretty(a.opt(it)) } } ?: "",
                            fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                    }
                }
            },
            confirmButton = { TextButton({ dialog = null }) { Text("Close") } })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GeneralTab(ctrl: ControlConnection, stats: JSONObject?, updatedAt: String, canBackup: Boolean, canUpdate: Boolean, idle: Boolean,
                       onBackup: () -> Unit, onVersion: () -> Unit, onErrors: () -> Unit, onConfig: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        val warnings = ServerSignInInfo.warnings(ctrl)
        if (warnings.length() > 0) SectionCard(title = "Server warnings") {
            for (i in 0 until warnings.length()) {
                val (text, hint) = warningText(warnings.opt(i))
                Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
                    Icon(Icons.Filled.Warning, null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.error)
                    Column(Modifier.padding(start = 10.dp)) {
                        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                        hint?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                }
            }
        }
        SectionCard(title = "Server") {
            val cpu = stats?.optJSONArray("cpuavg")
            val total = stats?.optLong("totalmem") ?: 0L
            val avail = stats?.let { if (it.has("availablemem")) it.optLong("availablemem") else it.optLong("freemem") } ?: 0L
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                // like the web UI: ring = min(1-minute load, 1); a load average depends on the core count, so no alarm colour
                Gauge(Modifier.weight(1f), "CPU load", if (cpu != null && cpu.length() > 0) cpu.optDouble(0).toFloat() else null, false,
                    cpu?.let { a -> (0 until a.length()).joinToString(", ") { fmtNum(a.optDouble(it)) } } ?: "…")
                Gauge(Modifier.weight(1f), "Memory used", if (total > 0) 1f - avail.toFloat() / total else null, true,
                    if (total > 0) "${fmtSize(avail)} free of ${fmtSize(total)}" else "…")
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
            InfoLine("Name", ctrl.serverinfo.optString("name").ifEmpty { ctrl.server.host })
            InfoLine("Address", ctrl.server.url, last = updatedAt.isEmpty())
            if (updatedAt.isNotEmpty()) InfoLine("Updated", "$updatedAt  (every ${STATS_INTERVAL_MS / 1000} s)", last = true)
        }
        val state = stats?.optJSONObject("values")?.optJSONObject("ServerState")
        val errs = stats?.optJSONObject("values")?.optJSONObject("AgentErrorCounters")
        if (state != null) SectionCard(title = "Server state") {
            FlowRow(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
                maxItemsInEachRow = 2) {
                STATE_NAMES.filter { state.has(it.first) }.forEach { (k, name) -> StateTile(Modifier.weight(1f), name, state.opt(k).toString(), k == "RelayErrors") }
                errs?.keys()?.forEach { k -> StateTile(Modifier.weight(1f), "Agent errors: $k", errs.opt(k).toString(), true) }
            }
        }
        SectionCard(title = "Server actions") {
            SrvAction(Icons.Filled.Backup, "Download server backup", if (canBackup) "Saved where you choose" else "Needs the server backup permission",
                canBackup && idle, onBackup)
            SrvAction(Icons.Filled.SystemUpdate, "Check server version", if (canUpdate) "Current, stable and latest MeshCentral" else "Needs the server update permission",
                canUpdate && idle, onVersion)
            SrvAction(Icons.Filled.ErrorOutline, "Server error log", if (canUpdate) "" else "Needs the server update permission", canUpdate && idle, onErrors)
            SrvAction(Icons.Filled.Settings, "Server configuration", if (canUpdate) "config.json (can contain secrets)" else "Needs the server update permission",
                canUpdate && idle, onConfig, last = true)
        }
    }
}

@Composable
private fun SrvAction(icon: ImageVector, title: String, sub: String, enabled: Boolean, onClick: () -> Unit, last: Boolean = false) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).alpha(if (enabled) 1f else 0.45f)
        .padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
        Column(Modifier.weight(1f).padding(start = 16.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (sub.isNotEmpty()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.outline)
    }
    if (!last) HorizontalDivider(Modifier.padding(start = 56.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}

@Composable
private fun StateTile(modifier: Modifier, name: String, value: String, alert: Boolean) {
    Surface(modifier, shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surfaceContainer) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold,
                color = if (alert && value != "0") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
            Text(name, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Ring gauge like the web UI's CPU / memory indicators; levels = colour by usage. */
@Composable
private fun Gauge(modifier: Modifier, title: String, fraction: Float?, levels: Boolean, text: String) {
    val f = (fraction ?: 0f).coerceIn(0f, 1f)
    val track = MaterialTheme.colorScheme.surfaceContainerHighest
    val col = when {
        !levels || f < 0.7f -> OnlineGreen
        f < 0.9f -> Color(0xFFF39C12)
        else -> MaterialTheme.colorScheme.error
    }
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Canvas(Modifier.size(52.dp)) {
            val stroke = 7.dp.toPx()
            val inset = stroke / 2
            val sz = Size(size.width - stroke, size.height - stroke)
            drawArc(track, 0f, 360f, false, Offset(inset, inset), sz, style = Stroke(stroke))
            if (fraction != null) drawArc(col, -90f, 360f * max(f, 0.01f), false, Offset(inset, inset), sz, style = Stroke(stroke, cap = StrokeCap.Round))
        }
        Column(Modifier.padding(start = 10.dp)) {
            Text(title, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(text, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StatsTab(timeline: List<JSONObject>, loaded: Boolean, range: Int, kind: Int, setRange: (Int) -> Unit, setKind: (Int) -> Unit, refresh: () -> Unit) {
    val k = CHART_KINDS[kind].first
    val series = remember(timeline.size, kind, loaded) { buildSeries(timeline.toList(), k) }
    val now = System.currentTimeMillis() / 1000.0
    val t0 = now - RANGES[range].second * 3600.0
    // the window ends at the newest sample if the server clock is ahead of ours
    val newest = series.flatMap { s -> s.pts.filter { it.second != null }.map { it.first } }.maxOrNull() ?: now
    val t1 = max(now, newest)
    var hover by remember(kind, range) { mutableStateOf<Double?>(null) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            CHART_KINDS.forEachIndexed { i, (_, label) -> FilterChip(kind == i, { setKind(i) }, { Text(label) }) }
        }
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically) {
            RANGES.forEachIndexed { i, (label, _) -> FilterChip(range == i, { setRange(i) }, { Text(label) }) }
            IconButton(refresh) { Icon(Icons.Filled.Refresh, "Refresh") }
        }
        SectionCard {
            if (!loaded) Box(Modifier.fillMaxWidth().height(260.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            else TimeChart(series, t0, t1, Y_TITLES[k] ?: "", hover) { hover = it }
            val samples = timeline.count { (epoch(it.opt("time")) ?: 0.0) >= t0 }
            val note = when {
                !loaded -> ""
                k == "cpu" && series.all { s -> s.pts.none { it.second != null } } ->
                    "This server does not keep CPU load in its history (NeDB / MongoDB). New 5-minute samples appear while this page is open."
                series.isEmpty() || samples == 0 -> "No samples in this range. The server records one every 5 minutes."
                else -> "$samples samples. Touch the chart for values."
            }
            if (note.isNotEmpty()) Text(note, Modifier.padding(horizontal = 16.dp, vertical = 8.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            // values at the touched time, else the legend
            val h = hover
            FlowRow(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (h != null) Text(SimpleDateFormat(if (RANGES[range].second > 24) "d MMM HH:mm" else "HH:mm", androidx.compose.ui.platform.LocalConfiguration.current.locales[0]).format(Date((h * 1000).toLong())),
                    style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                series.forEach { s ->
                    val v = h?.let { t -> s.pts.filter { it.second != null && it.first in t0..t1 }.minByOrNull { abs(it.first - t) }?.second }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(10.dp).background(s.color, CircleShape))
                        Text(s.name + (v?.let { "  " + fmtNum(it) } ?: ""), Modifier.padding(start = 4.dp), style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
        }
    }
}

@Composable
private fun TimeChart(series: List<Series>, t0: Double, t1: Double, yTitle: String, hover: Double?, onHover: (Double?) -> Unit) {
    val grid = MaterialTheme.colorScheme.outlineVariant
    val label = MaterialTheme.colorScheme.onSurfaceVariant.toArgb()
    val cross = MaterialTheme.colorScheme.primary
    val density = LocalDensity.current
    val textPx = with(density) { 11.dp.toPx() }
    val left = with(density) { 44.dp.toPx() }
    val bottom = with(density) { 22.dp.toPx() }
    val top = with(density) { 14.dp.toPx() }
    val right = with(density) { 10.dp.toPx() }
    val visible = series.map { s -> s.pts.filter { it.first in t0..t1 } }
    val vmax = visible.flatten().mapNotNull { it.second }.maxOrNull() ?: 0.0
    val yMax = if (vmax <= 0) 1.0 else niceCeil(vmax)
    var width by remember { mutableStateOf(1f) }
    fun timeAt(x: Float) = t0 + ((x - left) / (width - left - right)).coerceIn(0f, 1f) * (t1 - t0)
    Canvas(Modifier.fillMaxWidth().height(260.dp)
        .pointerInput(t0, t1) { detectTapGestures { onHover(timeAt(it.x)) } }
        .pointerInput(t0, t1) { detectDragGestures(onDragEnd = {}) { change, _ -> onHover(timeAt(change.position.x)) } }) {
        width = size.width
        val w = size.width - left - right
        val h = size.height - top - bottom
        fun x(t: Double) = (left + (t - t0) / (t1 - t0) * w).toFloat()
        fun y(v: Double) = (top + h - v / yMax * h).toFloat()
        val paint = android.graphics.Paint().apply { color = label; textSize = textPx; isAntiAlias = true }
        // value grid and labels
        for (i in 0..4) {
            val v = yMax * i / 4
            val yy = y(v)
            drawLine(grid, Offset(left, yy), Offset(size.width - right, yy), strokeWidth = 1f)
            paint.textAlign = android.graphics.Paint.Align.RIGHT
            drawContext.canvas.nativeCanvas.drawText(fmtNum(v), left - 6f, yy + textPx / 3, paint)
        }
        paint.textAlign = android.graphics.Paint.Align.LEFT
        drawContext.canvas.nativeCanvas.drawText(yTitle, left, top - 3f, paint)
        // time labels: start, middle, end
        val span = t1 - t0
        val tf = SimpleDateFormat(if (span > 86400 * 1.5) "d MMM" else "HH:mm", Locale.getDefault())
        listOf(0.0, 0.5, 1.0).forEach { p ->
            val t = t0 + span * p
            paint.textAlign = when (p) { 0.0 -> android.graphics.Paint.Align.LEFT; 1.0 -> android.graphics.Paint.Align.RIGHT; else -> android.graphics.Paint.Align.CENTER }
            drawContext.canvas.nativeCanvas.drawText(tf.format(Date((t * 1000).toLong())), x(t), size.height - 4f, paint)
        }
        // series: lines with breaks at gaps (server restarts)
        series.forEachIndexed { i, s ->
            val path = Path()
            var pen = false
            visible[i].forEach { (t, v) ->
                if (v == null) { pen = false; return@forEach }
                if (!pen) path.moveTo(x(t), y(v)) else path.lineTo(x(t), y(v))
                pen = true
            }
            drawPath(path, s.color, style = Stroke(2.dp.toPx(), cap = StrokeCap.Round))
            if (visible[i].count { it.second != null } <= 160) visible[i].forEach { (t, v) -> if (v != null) drawCircle(s.color, 2.dp.toPx(), Offset(x(t), y(v))) }
        }
        hover?.let { t -> if (t in t0..t1) drawLine(cross, Offset(x(t), top), Offset(x(t), top + h), strokeWidth = 1.5f) }
    }
}

private fun niceCeil(v: Double): Double {
    val mag = Math.pow(10.0, Math.floor(Math.log10(v)))
    for (m in listOf(1.0, 2.0, 2.5, 5.0, 10.0)) if (v <= m * mag) return m * mag
    return 10 * mag
}

@Composable
private fun ConsoleTab(ctrl: ControlConnection, lines: List<String>) {
    var cmd by remember { mutableStateOf("") }
    val list = rememberLazyListState()
    LaunchedEffect(lines.size) { if (lines.isNotEmpty()) list.scrollToItem(lines.size - 1) }
    fun send() {
        val c = cmd.trim()
        if (c.isEmpty()) return
        cmd = ""
        (lines as? MutableList<String>)?.add("> $c")
        ctrl.send("action" to "serverconsole", "value" to c)
    }
    Column(Modifier.fillMaxSize()) {
        Surface(Modifier.weight(1f).fillMaxWidth().padding(12.dp), shape = MaterialTheme.shapes.large, color = Color(0xFF14171C)) {
            if (lines.isEmpty()) Text("MeshCentral server console: type \"help\" for the list of commands.", Modifier.padding(14.dp),
                color = Color(0xFFA9B1BE), style = MaterialTheme.typography.bodySmall)
            SelectionContainer {
                LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = PaddingValues(12.dp)) {
                    itemsIndexed(lines) { _, l ->
                        Text(l, color = if (l.startsWith("> ")) Color(0xFF9DBEFF) else Color(0xFFE1E5EC), fontFamily = FontFamily.Monospace,
                            style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainer).padding(6.dp), verticalAlignment = Alignment.CenterVertically) {
            TextField(cmd, { cmd = it }, Modifier.weight(1f), singleLine = true, placeholder = { Text("Command (help, info, …)") },
                shape = RoundedCornerShape(24.dp), textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerLowest, unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerLowest),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send), keyboardActions = KeyboardActions(onSend = { send() }))
            FilledIconButton({ send() }, Modifier.padding(start = 6.dp), enabled = cmd.isNotBlank()) { Icon(Icons.AutoMirrored.Filled.Send, "Send") }
        }
    }
}

@Composable
private fun TraceTab(sources: JSONArray?, trace: List<JSONObject>, onChoose: () -> Unit, onOff: () -> Unit, onClear: () -> Unit, onShow: (JSONObject) -> Unit) {
    val active = sources?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
    Column(Modifier.fillMaxSize()) {
        SectionCard {
            Column(Modifier.padding(16.dp)) {
                Text(if (active.isEmpty()) "Tracing is off" else "Active: " + active.joinToString(", ") { TRACE_NAMES[it] ?: it },
                    style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                Text(if (active.isEmpty()) "Choose server components to trace." else
                    "Tracing is server-wide: every full administrator receives these messages until it is switched off.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onChoose) { Text("Choose…") }
                    if (active.isNotEmpty()) OutlinedButton(onOff) { Text("Turn off", color = MaterialTheme.colorScheme.error) }
                    if (trace.isNotEmpty()) TextButton(onClear) { Text("Clear") }
                }
            }
        }
        if (trace.isEmpty()) Text("No trace messages yet.", Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        else LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
            itemsIndexed(trace) { _, e ->
                val t = e.optLong("time")
                val text = e.optJSONArray("args")?.let { a -> (0 until a.length()).joinToString(", ") { a.opt(it).toString() } } ?: ""
                Column(Modifier.fillMaxWidth().clickable { onShow(e) }.padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Text((if (t > 0) SimpleDateFormat("HH:mm:ss", androidx.compose.ui.platform.LocalConfiguration.current.locales[0]).format(Date(t)) + "  " else "") + e.optString("source").uppercase(),
                        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    Text(text.replace('\n', ' '), style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace, maxLines = 3,
                        overflow = TextOverflow.Ellipsis)
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
            }
        }
    }
}

@Composable
private fun TraceDialog(sources: JSONArray?, onDismiss: () -> Unit, onOk: (List<String>) -> Unit) {
    val chosen = remember { mutableStateListOf<String>().apply { sources?.let { a -> for (i in 0 until a.length()) add(a.optString(i)) } } }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Server tracing") },
        text = {
            Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) {
                TRACE_GROUPS.forEach { (group, items) ->
                    Text(group, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                    items.forEach { (key, name) ->
                        Row(Modifier.fillMaxWidth().clickable { if (key in chosen) chosen.remove(key) else chosen.add(key) },
                            verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(key in chosen, { if (it) chosen.add(key) else chosen.remove(key) })
                            Column {
                                Text(name, style = MaterialTheme.typography.bodyMedium)
                                if (key == "httpheaders" || key == "authlog") Text("May include sensitive data (headers, cookies, user names)",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton({ onOk(chosen.toList()) }) { Text("OK") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}
