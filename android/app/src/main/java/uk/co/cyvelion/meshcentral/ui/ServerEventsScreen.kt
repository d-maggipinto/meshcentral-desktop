// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Storage
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Session

/** Kinds of events by their etype, for the filter chips. */
private val KINDS = listOf("All" to "", "Users" to "user", "Devices" to "node", "Groups" to "mesh", "Server" to "server")

private fun eventIcon(e: JSONObject): ImageVector = when (e.optString("etype")) {
    "user" -> Icons.Filled.Person
    "node" -> Icons.Filled.Computer
    "mesh", "ugrp" -> Icons.Filled.Group
    else -> Icons.Filled.Storage
}

/** The event's own text, or its action name in words ("accountremove" stays as the server wrote it). */
private fun eventText(e: JSONObject): String = e.opt("msg").let { if (it is String && it.isNotBlank()) it else e.optString("action") }

/**
 * Server-wide events (admin_panel.ServerEventsPanel, web UI "Events"): {action:'events', limit} answers WITHOUT our
 * responseid and a device's or a user's event list arrives under the same action, so the reply is filtered (no nodeid,
 * no userid = the server-wide list).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerEventsScreen(session: Session, onBack: () -> Unit) {
    val ctrl = session.ctrl
    var events by remember { mutableStateOf<List<JSONObject>?>(null) }
    var timedOut by remember { mutableStateOf(false) }
    var query by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf("") }
    var shown by remember { mutableStateOf<JSONObject?>(null) }
    var gen by remember { mutableStateOf(0) }

    fun request() {
        events = null
        timedOut = false
        gen++
        ctrl.send("action" to "events", "limit" to 500)
    }
    DisposableEffect(Unit) {
        val cb: (JSONObject) -> Unit = { m ->
            if (!m.has("nodeid") && !m.has("userid")) {
                val a = m.optJSONArray("events")
                events = if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it) }
            }
        }
        ctrl.on("events", cb)
        request()
        onDispose { ctrl.off("events", cb) }
    }
    LaunchedEffect(gen) { delay(10_000); if (events == null) timedOut = true }

    val q = query.trim().lowercase()
    val list = (events ?: emptyList()).filter { e ->
        (kind.isEmpty() || e.optString("etype") == kind || (kind == "mesh" && e.optString("etype") == "ugrp")) &&
            (q.isEmpty() || eventText(e).lowercase().contains(q) || e.optString("username").lowercase().contains(q) ||
                e.optString("action").lowercase().contains(q))
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Server events")
                    Text(events?.let { "${list.size} of ${it.size} events" } ?: "Loading…", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
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
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                KINDS.forEach { (label, k) -> FilterChip(kind == k, { kind = k }, { Text(label) }) }
            }
            when {
                events == null && timedOut -> Text("No answer from the server. Your account may not see server events.",
                    Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                events == null -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                list.isEmpty() -> Text(if (events!!.isEmpty()) "No events." else "No event matches.", Modifier.padding(24.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                    itemsIndexed(list) { _, e ->
                        Row(Modifier.fillMaxWidth().clickable { shown = e }.padding(horizontal = 16.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(36.dp).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f), CircleShape),
                                contentAlignment = Alignment.Center) {
                                Icon(eventIcon(e), null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
                            }
                            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                                Text(eventText(e), style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(listOf(e.optString("username"), srvTime(e.opt("time"))).filter { it.isNotEmpty() }.joinToString("  ·  "),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        HorizontalDivider(Modifier.padding(start = 64.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                    }
                }
            }
        }
    }
    shown?.let { e ->
        AlertDialog(onDismissRequest = { shown = null },
            title = { Text(e.optString("action").ifEmpty { "Event" }, fontWeight = FontWeight.SemiBold) },
            text = {
                Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState())) {
                    Text(eventText(e), style = MaterialTheme.typography.bodyMedium)
                    Text(srvTime(e.opt("time")), Modifier.padding(vertical = 6.dp), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    SelectionContainer {
                        Text(srvPretty(e), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                    }
                }
            },
            confirmButton = { TextButton({ shown = null }) { Text("Close") } })
    }
}
