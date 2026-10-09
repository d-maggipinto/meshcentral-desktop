// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.randomHex

/**
 * Run commands with output (general_actions.RunOutputDialog). With reply:true the server first answers
 * {action:'runcommands', result:'OK', responseid} (only an ACK); the output comes later as
 * {action:'msg', type:'runcommands', result, responseid, nodeid}.
 */
@Composable
fun RunCommandDialog(session: Session, node: Node, onClose: () -> Unit) {
    val shells = if (node.isWindows) listOf("Command" to 0, "PowerShell" to 2) else listOf("Shell" to 3)
    var shell by rememberSaveable { mutableStateOf(0) }
    var cmd by rememberSaveable { mutableStateOf("") }
    var rid by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }

    val main = remember { Handler(Looper.getMainLooper()) }
    val timeout = remember { Runnable {
        if (running) { running = false; status = "No output after 120 s. The agent may be offline or the command is still running. Use the Terminal for long-running commands." }
    } }

    DisposableEffect(Unit) {
        val onAck: (JSONObject) -> Unit = { m ->
            if (m.optString("responseid") == rid && running) {
                val r = m.optString("result")
                if (r == "OK") status = "Running… waiting for the output"
                else if (r.isNotEmpty()) { running = false; status = "Not run: $r" }
            }
        }
        val onMsg: (JSONObject) -> Unit = { m ->
            if (m.optString("type") == "runcommands" && m.optString("responseid") == rid && running) {
                running = false
                main.removeCallbacks(timeout)
                val out = m.optString("result")
                output = out
                status = if (out.isEmpty()) "Done. The command produced no output." else "Done."
            }
        }
        session.ctrl.on("runcommands", onAck)
        session.ctrl.on("msg", onMsg)
        onDispose {
            main.removeCallbacks(timeout)
            session.ctrl.off("runcommands", onAck)
            session.ctrl.off("msg", onMsg)
        }
    }

    fun run() {
        val id = "mcdrun" + randomHex()
        rid = id
        output = ""
        running = true
        status = "Sending…"
        session.ctrl.send(JSONObject().put("action", "runcommands").put("nodeids", JSONArray().put(node.id))
            .put("type", shells[shell].second).put("cmds", cmd).put("runAsUser", 0).put("reply", true).put("responseid", id))
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, 120_000)
    }

    AlertDialog(onDismissRequest = onClose, title = { Text("Run command") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (shells.size > 1) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    shells.forEachIndexed { i, (l, _) -> FilterChip(shell == i, { shell = i }, { Text(l) }, enabled = !running) }
                }
                OutlinedTextField(cmd, { cmd = it }, Modifier.fillMaxWidth().heightIn(min = 96.dp),
                    label = { Text("Commands") }, enabled = !running,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace))
                if (status.isNotEmpty()) Row(verticalAlignment = Alignment.CenterVertically) {
                    if (running) CircularProgressIndicator(Modifier.padding(end = 8.dp).size(16.dp), strokeWidth = 2.dp)
                    Text(status, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (output.isNotEmpty()) SelectionContainer {
                    Text(output, Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                }
            }
        },
        confirmButton = { TextButton({ run() }, enabled = !running && cmd.isNotBlank()) { Text("Run") } },
        dismissButton = { TextButton(onClose) { Text("Close") } })
}
