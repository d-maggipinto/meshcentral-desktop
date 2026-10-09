// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

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
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Session
import java.text.DateFormat
import java.time.Instant
import java.util.Date

private class DevEvent(val time: Long, val timeText: String, val action: String, val msg: String, val user: String)

/** Event time: ISO-8601 or epoch ms / s (ui.fmt_time). Returns (sort key ms, text). */
private fun eventTime(v: Any?): Pair<Long, String> {
    val fmt = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.MEDIUM)
    return when (v) {
        is Number -> {
            val ms = v.toLong().let { if (it > 100_000_000_000L) it else it * 1000 }
            ms to fmt.format(Date(ms))
        }
        is String -> try {
            val ms = Instant.parse(v.trim()).toEpochMilli()
            ms to fmt.format(Date(ms))
        } catch (e: Exception) { 0L to v }
        else -> 0L to ""
    }
}

/**
 * Device events (info_panel.EventsPanel): `events` with nodeid. The reply is broadcast-style (no responseid):
 * keep only the one for this device (the server echoes nodeid; server-wide and per-user replies carry none / a userid).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeviceEventsScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    var events by remember { mutableStateOf<List<DevEvent>?>(null) }
    var query by rememberSaveable { mutableStateOf("") }

    fun request() {
        events = null
        session.ctrl.send("action" to "events", "nodeid" to id, "limit" to 500)
    }
    DisposableEffect(id) {
        val cb: (JSONObject) -> Unit = { m ->
            if (m.has("events") && m.optString("nodeid") == id) {
                val a = m.optJSONArray("events")
                events = (0 until (a?.length() ?: 0)).mapNotNull { a!!.optJSONObject(it) }.map { e ->
                    val (t, text) = eventTime(e.opt("time"))
                    DevEvent(t, text, e.optString("action"), (e.opt("msg") as? String) ?: "", e.optString("username"))
                }.sortedByDescending { it.time }
            }
        }
        session.ctrl.on("events", cb)
        request()
        onDispose { session.ctrl.off("events", cb) }
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Events", maxLines = 1)
                    Text(node?.name ?: "", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { IconButton({ request() }) { Icon(Icons.Filled.Refresh, "Refresh") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            TextField(query, { query = it }, Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), singleLine = true,
                placeholder = { Text("Search events") }, shape = CircleShape,
                leadingIcon = { Icon(Icons.Filled.Search, null) },
                trailingIcon = { if (query.isNotEmpty()) IconButton({ query = "" }) { Icon(Icons.Filled.Close, "Clear") } },
                colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh))
            val q = query.trim().lowercase()
            val shown = events?.filter { q.isEmpty() || it.msg.lowercase().contains(q) || it.action.lowercase().contains(q)
                || it.user.lowercase().contains(q) || it.timeText.lowercase().contains(q) }
            PullToRefreshBox(isRefreshing = events == null, onRefresh = { request() }, modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(vertical = 8.dp)) {
                    if (shown != null) item {
                        Text(if (shown.isEmpty()) (if (events!!.isEmpty()) "No events for this device." else "No event matches.")
                            else "${shown.size} events, newest first", Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
                            style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    items(shown ?: emptyList()) { e ->
                        SectionCard {
                            SelectionContainer {
                                Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    Row {
                                        Text(e.timeText, Modifier.weight(1f), style = MaterialTheme.typography.labelMedium,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        if (e.action.isNotEmpty()) Text(e.action, style = MaterialTheme.typography.labelMedium,
                                            fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                                    }
                                    if (e.msg.isNotEmpty()) Text(e.msg, style = MaterialTheme.typography.bodyMedium)
                                    if (e.user.isNotEmpty()) Text(e.user, style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
