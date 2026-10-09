// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.NO_PERMISSION
import uk.co.cyvelion.meshcentral.data.Session

private val CONSOLE_BG = Color(0xFF16181C)
private val CONSOLE_FG = Color(0xFFD8DADE)

/**
 * Agent console (tools_panel.ConsolePanel): MeshAgent commands, not a shell. Agent msg `console` with value = the
 * command; the answers come back as msg type console. Needs rights 8 + 16; the server logs every command.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConsoleScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val allowed = node != null && session.caps(node).console
    val lines = remember { mutableStateListOf<Pair<String, Boolean>>() }     // text, typed by us
    val history = remember { mutableStateListOf<String>() }
    var histPos by remember { mutableIntStateOf(-1) }
    var cmd by remember { mutableStateOf("") }
    var online by remember { mutableStateOf(node?.online == true) }
    val list = rememberLazyListState()

    DisposableEffect(id) {
        lines.add("Agent console ready. Type 'help' for the list of MeshAgent commands." to false)
        val cb: (JSONObject) -> Unit = cb@{ m ->
            if (m.optString("nodeid", id) != id || m.optString("type") != "console") return@cb
            val v = m.optString("value")
            if (v.contains("MCDCLIP") || v.contains("MCDPATCH")) return@cb       // the desktop app's private traffic
            if (v.isNotEmpty()) lines.add(v.trimEnd() to false)
        }
        session.ctrl.on("msg", cb)
        onDispose { session.ctrl.off("msg", cb) }
    }
    // the agent restarting or updating: say so, like the desktop app
    val nowOnline = session.node(id)?.online == true
    LaunchedEffect(nowOnline) {
        if (nowOnline != online) lines.add((if (nowOnline) "*** Agent is back online ***"
            else "*** Agent went offline (restarting or updating?), waiting for it to reconnect ***") to false)
        online = nowOnline
    }
    LaunchedEffect(lines.size) { if (lines.isNotEmpty()) list.animateScrollToItem(lines.size - 1) }

    fun send() {
        val c = cmd.trim()
        if (c.isEmpty()) return
        cmd = ""
        histPos = -1
        if (history.lastOrNull() != c) history.add(c)
        lines.add("> $c" to true)
        if (!online) { lines.add("(the agent is offline: command not sent)" to false); return }
        session.ctrl.nodeMsg(id, "console", "value" to c)
    }
    fun recall(step: Int) {
        if (history.isEmpty()) return
        histPos = when {
            histPos == -1 && step < 0 -> history.size - 1
            histPos == -1 -> return
            else -> histPos + step
        }
        if (histPos >= history.size) { histPos = -1; cmd = ""; return }
        histPos = histPos.coerceAtLeast(0)
        cmd = history[histPos]
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Agent console", maxLines = 1)
                    Text(node?.name ?: "", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { IconButton({ lines.clear() }) { Icon(Icons.Filled.DeleteSweep, "Clear") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding()) {
            if (!allowed) {
                Text(if (node == null) "This device is not in the list any more." else NO_PERMISSION, Modifier.padding(24.dp))
                return@Column
            }
            Text("Runs MeshAgent commands (help, ls, ps, cpuinfo...), not a shell: use the Terminal for that. " +
                "The server records every console command in its event log.",
                Modifier.padding(horizontal = 16.dp, vertical = 6.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            SelectionContainer(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 8.dp)
                .background(CONSOLE_BG, RoundedCornerShape(12.dp))) {
                LazyColumn(Modifier.fillMaxSize().padding(10.dp), state = list) {
                    itemsIndexed(lines) { _, (t, mine) ->
                        Text(t, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                            color = if (mine) Color(0xFF8AB4F8) else CONSOLE_FG)
                    }
                }
            }
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton({ recall(-1) }, enabled = history.isNotEmpty()) { Icon(Icons.Filled.KeyboardArrowUp, "Previous command") }
                IconButton({ recall(1) }, enabled = histPos != -1) { Icon(Icons.Filled.KeyboardArrowDown, "Next command") }
                TextField(cmd, { cmd = it }, Modifier.weight(1f), singleLine = true, placeholder = { Text("Command (e.g. help)") },
                    shape = RoundedCornerShape(24.dp),
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                    colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                        focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                        unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false,
                        imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { send() }))
                FilledIconButton({ send() }, Modifier.padding(start = 6.dp), enabled = cmd.isNotBlank()) {
                    Icon(Icons.AutoMirrored.Filled.Send, "Send")
                }
            }
        }
    }
}
