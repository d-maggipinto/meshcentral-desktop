// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.net.Uri
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.CreateNewFolder
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.PROTO_FILES
import uk.co.cyvelion.meshcentral.net.Tunnel
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer

private const val CHUNK = 65536

/** t: 1 drive, 2 folder, 3 file (files_panel). */
private data class Entry(val name: String, val type: Int, val size: Long, val date: String) {
    val isDir get() = type < 3
}

private class Download(val id: Double, val name: String, val out: OutputStream, var got: Long = 0)
private class Upload(val queue: ArrayDeque<Uri>, var input: InputStream? = null, var name: String = "", var size: Long = 0, var sent: Long = 0)

fun fmtSize(n: Long): String = when {
    n < 1024 -> "$n B"
    n < 1024L * 1024 -> "%.1f KB".format(n / 1024.0)
    n < 1024L * 1024 * 1024 -> "%.1f MB".format(n / 1048576.0)
    else -> "%.2f GB".format(n / 1073741824.0)
}

/** Compare paths the agent's way (files_panel._same_path): separators and their repetition do not matter. */
private fun samePath(a: String) = a.replace('\\', '/').replace(Regex("/+"), "/").trim('/')

/** Device file manager over relay protocol 5 (files_panel.py). Connects only on the Connect button. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun FilesScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val ctx = LocalContext.current
    val holder = remember { arrayOfNulls<Tunnel>(1) }
    var state by remember { mutableIntStateOf(0) }
    var location by remember { mutableStateOf(listOf<String>()) }
    var entries by remember { mutableStateOf<List<Entry>?>(null) }
    var note by remember { mutableStateOf("") }
    var progress by remember { mutableStateOf<Pair<String, Float?>?>(null) }
    var download by remember { mutableStateOf<Download?>(null) }
    var upload by remember { mutableStateOf<Upload?>(null) }
    var pendingDownload by remember { mutableStateOf<Entry?>(null) }
    var menuFor by remember { mutableStateOf<Entry?>(null) }
    var renameOf by remember { mutableStateOf<Entry?>(null) }
    var deleteOf by remember { mutableStateOf<Entry?>(null) }
    var newFolder by remember { mutableStateOf(false) }
    // read through the state on every call: callbacks made in an earlier composition must see the current folder
    fun cur() = location.joinToString("/")
    val curPath = cur()

    fun tunnel() = holder[0]?.takeIf { it.state == 3 }
    fun list() { entries = null; tunnel()?.sendJson(JSONObject().put("action", "ls").put("reqid", 1).put("path", cur())) }
    fun goTo(loc: List<String>) {
        location = loc
        entries = null
        tunnel()?.sendJson(JSONObject().put("action", "ls").put("reqid", 1).put("path", loc.joinToString("/")))
    }

    fun finishDownload(ok: Boolean) {
        val d = download ?: return
        download = null
        progress = null
        runCatching { d.out.close() }
        Toast.makeText(ctx, if (ok) "Downloaded ${d.name}" else "Download of ${d.name} stopped", Toast.LENGTH_SHORT).show()
    }

    fun uploadNext() {
        val u = upload ?: return
        runCatching { u.input?.close() }
        u.input = null
        val uri = u.queue.removeFirstOrNull()
        if (uri == null) {
            upload = null
            progress = null
            Toast.makeText(ctx, "Upload complete", Toast.LENGTH_SHORT).show()
            list()
            return
        }
        var name = "file"
        var size = 0L
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) { name = c.getString(0) ?: name; size = c.getLong(1) }
        }
        // the agent joins path + name without resolving "..": a name from another app's file provider such as
        // "../../etc/cron.d/x" must not write outside the current folder (files_panel uses os.path.basename too)
        name = name.substringAfterLast('/').substringAfterLast('\\').takeIf { it.isNotBlank() && it != "." && it != ".." } ?: "file"
        u.input = ctx.contentResolver.openInputStream(uri)
        u.name = name; u.size = size; u.sent = 0
        progress = "Uploading $name" to 0f
        tunnel()?.sendJson(JSONObject().put("action", "upload").put("reqid", 1).put("path", cur()).put("name", name).put("size", size))
    }

    fun uploadChunk() {
        val u = upload ?: return
        val input = u.input ?: return
        val buf = ByteArray(CHUNK)
        val n = input.read(buf)
        if (n <= 0) { tunnel()?.sendJson(JSONObject().put("action", "uploaddone").put("reqid", 1)); return }
        val data = buf.copyOf(n)
        // a zero byte first if the data could pass for JSON ('{' or NUL), like the web client
        tunnel()?.send(if (data[0].toInt() == 0 || data[0].toInt() == 123) byteArrayOf(0) + data else data)
        u.sent += n
        progress = "Uploading ${u.name}" to (if (u.size > 0) (u.sent.toFloat() / u.size).coerceAtMost(1f) else null)
    }

    fun handleJson(m: JSONObject) {
        val action = m.optString("action")
        when {
            action == "ls" || (m.has("path") && m.has("dir")) -> {
                if (samePath(m.optString("path")) != samePath(cur())) return
                val dir = m.optJSONArray("dir") ?: JSONArray()
                entries = (0 until dir.length()).mapNotNull { dir.optJSONObject(it) }
                    .map { Entry(it.optString("n"), it.optInt("t", 3), it.optLong("s"), it.optString("d")) }
                    .sortedWith(compareBy<Entry> { !it.isDir }.thenBy { it.name.lowercase() })
            }
            action == "download" -> {
                val d = download ?: return
                if (m.optDouble("id") != d.id) return
                when (m.optString("sub")) {
                    "start" -> tunnel()?.sendJson(JSONObject().put("action", "download").put("sub", "startack").put("id", d.id))
                    "cancel" -> finishDownload(false)
                }
            }
            action == "uploadstart" || action == "uploadack" -> uploadChunk()
            action == "uploaddone" -> uploadNext()
            action == "uploaderror" -> {
                note = "Upload failed" + m.optString("msg").let { if (it.isNotEmpty()) ": $it" else "" }
                runCatching { upload?.input?.close() }
                upload = null; progress = null
            }
            action == "refresh" -> list()
        }
    }

    fun onBinary(b: ByteArray) {
        // JSON control frames arrive as binary frames beginning with '{'; payload frames start with 4 flag bytes
        if (b.isNotEmpty() && b[0] == '{'.code.toByte()) {
            runCatching { JSONObject(String(b, Charsets.UTF_8)) }.getOrNull()?.let { handleJson(it) }
            return
        }
        val d = download ?: return
        if (b.size < 4) return
        val flags = ByteBuffer.wrap(b, 0, 4).int
        if (b.size > 4) {
            try { d.out.write(b, 4, b.size - 4) } catch (e: Exception) { finishDownload(false); return }
            d.got += b.size - 4
            progress = "Downloading ${d.name} (${fmtSize(d.got)})" to null
        }
        if (flags and 1 != 0) finishDownload(true)
        else tunnel()?.sendJson(JSONObject().put("action", "download").put("sub", "ack").put("id", d.id))
    }

    fun disconnect() {
        holder[0]?.let { holder[0] = null; it.stop() }
        state = 0
        entries = null
        if (download != null) finishDownload(false)
        runCatching { upload?.input?.close() }
        upload = null
        progress = null
    }

    fun connect() {
        val n = node ?: return
        disconnect()
        note = ""
        val t = Tunnel(session.ctrl, n.id, PROTO_FILES)
        t.onState = { s -> if (holder[0] === t) { state = s; if (s == 3) goTo(location) } }
        t.onText = { txt -> runCatching { JSONObject(txt) }.getOrNull()?.let { handleJson(it) } }
        t.onBinary = { onBinary(it) }
        t.onConsole = { if (it.isNotEmpty()) note = it }
        holder[0] = t
        t.start()
    }

    val saveAs = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val e = pendingDownload
        pendingDownload = null
        if (uri == null || e == null) return@rememberLauncherForActivityResult
        val out = ctx.contentResolver.openOutputStream(uri) ?: return@rememberLauncherForActivityResult
        val d = Download(Math.random(), e.name, out)
        download = d
        progress = "Downloading ${e.name}" to null
        tunnel()?.sendJson(JSONObject().put("action", "download").put("sub", "start").put("id", d.id)
            .put("path", (cur() + "/" + e.name).trim('/')))
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty() && tunnel() != null) { upload = Upload(ArrayDeque(uris)); uploadNext() }
    }

    DisposableEffect(Unit) { onDispose { disconnect() } }
    BackHandler(enabled = state == 3 && location.isNotEmpty()) { goTo(location.dropLast(1)) }
    val busy = download != null || upload != null

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text(node?.name ?: "Files", maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(if (state == 3) "/" + curPath else listOf("Disconnected", "Connecting…", "Waiting for agent…", "")[state],
                        style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.StartEllipsis,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (state == 3) {
                    IconButton({ goTo(location.dropLast(1)) }, enabled = location.isNotEmpty()) { Icon(Icons.Filled.ArrowUpward, "Up") }
                    IconButton({ list() }) { Icon(Icons.Filled.Refresh, "Refresh") }
                    IconButton({ newFolder = true }, enabled = location.isNotEmpty()) { Icon(Icons.Filled.CreateNewFolder, "New folder") }
                    IconButton({ pick.launch(arrayOf("*/*")) }, enabled = location.isNotEmpty() && !busy) { Icon(Icons.Filled.Upload, "Upload") }
                } else if (state == 0) Button({ connect() }, enabled = node?.online == true) { Text("Connect") }
                else OutlinedButton({ disconnect() }) { Text("Cancel") }
            })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            progress?.let { (text, frac) ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(text, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        TextButton({ disconnect(); connect() }) { Text("Stop") }
                    }
                    if (frac == null) LinearProgressIndicator(Modifier.fillMaxWidth()) else LinearProgressIndicator({ frac }, Modifier.fillMaxWidth())
                }
            }
            if (note.isNotEmpty()) Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.tertiaryContainer).padding(start = 16.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text(note, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onTertiaryContainer)
                TextButton({ note = "" }) { Text("OK") }
            }
            val shown = entries          // the lazy list reads it later: never through the state, it may be null by then
            when {
                state == 0 -> Text(if (node?.online == true) "Tap Connect to browse the files on this device." else "The device is offline.",
                    Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                state < 3 || shown == null -> LinearProgressIndicator(Modifier.fillMaxWidth().padding(16.dp))
                shown.isEmpty() -> Text("This folder is empty.", Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(shown, key = { it.name }) { e ->
                        Box {
                            ListItem(
                                modifier = Modifier.combinedClickable(
                                    onClick = { if (e.isDir) goTo(location + e.name) else menuFor = e },
                                    onLongClick = { if (location.isNotEmpty() || !e.isDir) menuFor = e }),
                                leadingContent = {
                                    Icon(when (e.type) { 1 -> Icons.Filled.Storage; 2 -> Icons.Filled.Folder; else -> Icons.AutoMirrored.Filled.InsertDriveFile },
                                        null, tint = if (e.isDir) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                                },
                                headlineContent = { Text(e.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                supportingContent = {
                                    val parts = listOfNotNull(if (e.isDir) null else fmtSize(e.size), e.date.take(19).replace('T', ' ').ifEmpty { null })
                                    if (parts.isNotEmpty()) Text(parts.joinToString(" · "))
                                },
                                trailingContent = if (location.isNotEmpty() || !e.isDir) ({
                                    IconButton({ menuFor = e }) { Icon(Icons.Filled.MoreVert, "Actions") }
                                }) else null)
                            DropdownMenu(menuFor == e, { menuFor = null }) {
                                if (!e.isDir) DropdownMenuItem({ Text("Download") }, enabled = !busy, onClick = {
                                    menuFor = null; pendingDownload = e; saveAs.launch(e.name)
                                })
                                DropdownMenuItem({ Text("Rename") }, onClick = { menuFor = null; renameOf = e })
                                DropdownMenuItem({ Text("Delete", color = MaterialTheme.colorScheme.error) }, onClick = { menuFor = null; deleteOf = e })
                            }
                        }
                    }
                }
            }
        }
    }

    renameOf?.let { e ->
        TextDialog("Rename", e.name, "Rename", onDismiss = { renameOf = null }) { name ->
            renameOf = null
            if (name != e.name) {
                tunnel()?.sendJson(JSONObject().put("action", "rename").put("reqid", 1).put("path", cur()).put("oldname", e.name).put("newname", name))
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ list() }, 400)
            }
        }
    }
    if (newFolder) TextDialog("New folder", "", "Create", onDismiss = { newFolder = false }) { name ->
        newFolder = false
        tunnel()?.sendJson(JSONObject().put("action", "mkdir").put("reqid", 1).put("path", (cur() + "/" + name).trim('/')))
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ list() }, 400)
    }
    deleteOf?.let { e ->
        AlertDialog(onDismissRequest = { deleteOf = null }, title = { Text("Delete ${e.name}?") },
            text = { Text(if (e.isDir) "The folder and everything in it will be deleted on the device." else "The file will be deleted on the device.") },
            confirmButton = { TextButton({
                deleteOf = null
                tunnel()?.sendJson(JSONObject().put("action", "rm").put("reqid", 1).put("path", cur())
                    .put("delfiles", JSONArray().put(e.name)).put("rec", true))
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ list() }, 400)
            }) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ deleteOf = null }) { Text("Cancel") } })
    }
}

@Composable
fun TextDialog(title: String, initial: String, action: String, onDismiss: () -> Unit, onOk: (String) -> Unit) {
    // the name without its extension is selected, ready to type over
    val end = initial.lastIndexOf('.').takeIf { it > 0 } ?: initial.length
    var text by remember { mutableStateOf(TextFieldValue(initial, TextRange(0, end))) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) },
        text = { OutlinedTextField(text, { text = it }, Modifier.focusRequester(focus), singleLine = true) },
        confirmButton = { TextButton({ onOk(text.text.trim()) }, enabled = text.text.isNotBlank()) { Text(action) } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}
