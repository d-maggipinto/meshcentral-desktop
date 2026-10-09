// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Session

/**
 * Device notes (info_panel.NotesPanel): getNotes -> {action:'getNotes', id, notes}; setNotes has no reply, so the
 * notes are read back to confirm. Editable only with the notes right (128).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotesScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val canEdit = node != null && session.caps(node).notesEdit
    var text by remember { mutableStateOf("") }
    var saved by remember { mutableStateOf<String?>(null) }    // the notes as the server has them; null while loading
    var status by remember { mutableStateOf("") }
    var savePending by remember { mutableStateOf(false) }
    val main = remember { Handler(Looper.getMainLooper()) }

    fun request() = session.ctrl.send("action" to "getNotes", "id" to id)
    DisposableEffect(id) {
        val cb: (JSONObject) -> Unit = { m ->
            if (m.optString("id", id) == id) {
                val n = if (m.isNull("notes")) "" else m.optString("notes")
                text = n
                saved = n
                status = if (savePending) "Saved" else ""
                savePending = false
            }
        }
        session.ctrl.on("getNotes", cb)
        request()
        onDispose { session.ctrl.off("getNotes", cb); main.removeCallbacksAndMessages(null) }
    }

    fun save() {
        session.ctrl.send("action" to "setNotes", "id" to id, "notes" to text)
        status = "Saving…"
        savePending = true
        main.postDelayed({ request() }, 400)
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Notes", maxLines = 1)
                    Text(node?.name ?: "", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                IconButton({ request() }) { Icon(Icons.Filled.Refresh, "Reload") }
                if (canEdit) Button({ save() }, Modifier.padding(end = 8.dp), enabled = saved != null && text != saved) { Text("Save") }
            })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding().padding(16.dp)) {
            Text(when {
                saved == null -> "Loading…"
                !canEdit -> "Read only: your account may not edit notes on this device."
                status.isNotEmpty() -> status
                else -> "Notes for this device, visible to other administrators."
            }, Modifier.padding(bottom = 8.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().weight(1f), readOnly = !canEdit,
                enabled = saved != null, placeholder = { Text(if (canEdit) "Write notes here" else "No notes") })
        }
    }
}
