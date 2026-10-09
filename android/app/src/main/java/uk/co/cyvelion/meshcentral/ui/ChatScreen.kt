// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.CTRL_CHANNEL
import uk.co.cyvelion.meshcentral.net.ControlConnection
import uk.co.cyvelion.meshcentral.net.USER_AGENT
import uk.co.cyvelion.meshcentral.net.enc
import uk.co.cyvelion.meshcentral.net.http
import uk.co.cyvelion.meshcentral.net.openChatPage

fun messengerId(ctrl: ControlConnection, node: Node) =
    "meshmessenger/" + enc(node.id) + "/" + enc(ctrl.userinfo?.optString("_id") ?: "")

/** The chat page for the remote user, like the server's own (meshuser.js meshmessenger), no login cookie. */
fun remotePageUrl(ctrl: ControlConnection, node: Node): String {
    val suffix = ctrl.serverinfo.optString("domainsuffix")
    return ctrl.server.url + (if (suffix.isNotEmpty()) "/$suffix" else "") + "/messenger?id=" + messengerId(ctrl, node)
}

/**
 * Our end of the meshmessenger relay (chat.py ChatSession). States 0 closed, 1 connecting, 2 waiting for the remote
 * user, 3 connected. Reconnects by itself (like the web page) until stop(). Files both ways like the page (see
 * below); incoming files one at a time, at most 100 MB each, kept in memory until saved.
 */
class ChatSession(private val ctrl: ControlConnection, private val node: Node) {
    var state by mutableIntStateOf(0)
        private set
    var typing by mutableStateOf(false)
        private set
    var recorded = false
        private set
    var onChat: ((String) -> Unit)? = null
    var onNote: ((String) -> Unit)? = null
    /** id key, name, size of a file the remote user offers / progress / done (data, or null when cancelled). */
    var onFileIn: ((String, String, Long) -> Unit)? = null
    var onFileProgress: ((String, Long, Long) -> Unit)? = null
    var onFileDone: ((String, ByteArray?) -> Unit)? = null
    private class Up(val id: Long, val name: String, val data: ByteArray) { var ptr = 0; var started = false }
    private class Down(val id: Any, val name: String, val size: Long) { val buf = java.io.ByteArrayOutputStream(); var got = 0L }
    private val uploads = ArrayList<Up>()
    private val downloads = HashMap<String, Down>()
    private var ws: WebSocket? = null
    private var stopped = true
    private var gen = 0
    private val queue = ArrayList<String>()
    private val main = Handler(Looper.getMainLooper())

    // keep-alive while the remote user is there: proxies (Cloudflare) close a WebSocket without data for ~100 s
    private val pinger = object : Runnable {
        override fun run() {
            if (stopped) return
            if (state == 3) send(JSONObject().put("ctrlChannel", CTRL_CHANNEL).put("type", "ping"))
            main.postDelayed(this, 25_000)
        }
    }

    fun start() { if (stopped) { stopped = false; connect(); main.postDelayed(pinger, 25_000) } }

    fun stop() {
        stopped = true
        main.removeCallbacks(pinger)
        gen++
        ws?.close(1000, null)
        ws = null
        state = 0
        cancelAll()
    }

    private fun connect() {
        val g = ++gen
        state = 1
        ctrl.authCookie { cookie, _ ->
            if (g != gen || stopped) return@authCookie
            val url = ctrl.server.ws("meshrelay.ashx") + "?id=" + messengerId(ctrl, node) + "&auth=" + enc(cookie ?: "")
            ws = http.newWebSocket(Request.Builder().url(url).header("User-Agent", USER_AGENT).build(), object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) { main.post { if (g == gen) state = 2 } }
                override fun onMessage(webSocket: WebSocket, text: String) { main.post { if (g == gen) message(text) } }
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { main.post { closed(g) } }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { main.post { closed(g) } }
            })
        }
    }

    private fun closed(g: Int) {
        if (g != gen || stopped) return
        val was = state
        ws = null
        state = 1
        typing = false
        cancelAll()
        if (was == 3) onNote?.invoke("The remote user left the chat. Waiting for them to come back…")
        main.postDelayed({ if (g == gen && !stopped) connect() }, if (was == 3) 1500L else 4000L)
    }

    private fun message(data: String) {
        if (state < 3 && (data == "c" || data == "cr")) {
            recorded = data == "cr"
            state = 3
            send(JSONObject().put("action", "random").put("random", 1))      // keep everything on the relay (no WebRTC)
            onNote?.invoke("The remote user joined the chat" + if (recorded) ". The server records this chat." else ".")
            queue.forEach { send(JSONObject().put("action", "chat").put("msg", it)) }
            queue.clear()
            return
        }
        if (!data.startsWith("{")) return
        val j = try { JSONObject(data) } catch (e: Exception) { return }
        if (j.optString("ctrlChannel") == CTRL_CHANNEL) {
            if (j.optString("type") == "ping") send(JSONObject().put("ctrlChannel", CTRL_CHANNEL).put("type", "pong"))
            return
        }
        when (j.optString("action")) {
            "chat" -> { typing = false; onChat?.invoke(j.optString("msg")) }
            "outtext" -> typing = j.optBoolean("value")
            "file", "fileUploadStart", "fileData", "fileUploadEnd", "fileUploadAck", "fileUploadCancel" -> fileMessage(j.optString("action"), j)
        }
    }

    // ---- files ----
    /** Queue a file for the remote user (only while connected); returns its id key. */
    fun sendFile(name: String, data: ByteArray): String? {
        if (state != 3) return null
        val id = (java.security.SecureRandom().nextLong() ushr 16)
        uploads.add(Up(id, name, data))
        send(JSONObject().put("action", "file").put("size", data.size).put("id", id).put("type", "").put("name", name))
        if (uploads.size == 1) nextUpload()
        return key(id)
    }

    fun cancelFile(k: String) {
        val u = uploads.firstOrNull { key(it.id) == k }
        if (u != null) {
            uploads.remove(u)
            send(JSONObject().put("action", "fileUploadCancel").put("id", u.id))
            if (uploads.isNotEmpty() && !uploads[0].started) nextUpload()
        } else {
            val d = downloads.remove(k) ?: return
            send(JSONObject().put("action", "fileUploadCancel").put("id", d.id))
        }
        onFileDone?.invoke(k, null)
    }

    private fun cancelAll() {
        uploads.forEach { onFileDone?.invoke(key(it.id), null) }
        downloads.keys.forEach { onFileDone?.invoke(it, null) }
        uploads.clear(); downloads.clear()
    }

    private fun key(id: Any?) = id.toString()

    private fun nextUpload() {
        val u = uploads.firstOrNull() ?: return
        val head = { a: String -> JSONObject().put("action", a).put("size", u.data.size).put("id", u.id).put("type", "").put("name", u.name) }
        when {
            !u.started -> { u.started = true; send(head("fileUploadStart")) }
            u.ptr >= u.data.size -> {
                send(head("fileUploadEnd"))
                uploads.removeAt(0)
                onFileDone?.invoke(key(u.id), ByteArray(0))
                nextUpload()
            }
            else -> {
                val n = minOf(BLOCK, u.data.size - u.ptr)
                send(JSONObject().put("action", "fileData").put("id", u.id).put("data", String(u.data, u.ptr, n, Charsets.ISO_8859_1)))
                u.ptr += n
                onFileProgress?.invoke(key(u.id), u.ptr.toLong(), u.data.size.toLong())
            }
        }
    }

    private fun fileMessage(a: String, j: JSONObject) {
        val id = j.opt("id")
        val k = key(id)
        when (a) {
            "fileUploadAck" -> {
                // our current file, or the ack of the previous file's end
                if (uploads.isNotEmpty() && (key(uploads[0].id) == k || !uploads[0].started)) nextUpload()
                return
            }
            "fileUploadCancel" -> {
                val u = uploads.firstOrNull { key(it.id) == k }
                if (u != null) { uploads.remove(u); if (uploads.isNotEmpty() && !uploads[0].started) nextUpload() }
                else if (downloads.remove(k) == null) return
                onFileDone?.invoke(k, null)
                onNote?.invoke("The file transfer was cancelled by the remote user.")
                return
            }
            "file" -> {
                val name = j.optString("name").ifEmpty { "file" }.take(200)
                val size = j.optLong("size", -1)
                if (downloads.isNotEmpty()) {
                    // one incoming file at a time: a remote peer must not be able to fill the phone's memory
                    send(JSONObject().put("action", "fileUploadCancel").put("id", id))
                    onNote?.invoke("The remote user sent another file (${name.take(80)}) while one is still arriving. Ask them to send it again afterwards.")
                    return
                }
                if (size < 0 || size > MAX_IN) {
                    send(JSONObject().put("action", "fileUploadCancel").put("id", id))
                    onNote?.invoke("The remote user sent a file that is too large for the chat (${name.take(80)}). Use Files.")
                    return
                }
                downloads[k] = Down(id ?: k, name, size)
                onFileIn?.invoke(k, name, size)
                return
            }
        }
        val d = downloads[k] ?: return
        when (a) {
            "fileUploadStart" -> repeat(2) { send(JSONObject().put("action", "fileUploadAck").put("id", id)) }   // two blocks in flight, like the page
            "fileData" -> {
                val text = j.optString("data")
                if (text.length > 65536) { cancelFile(k); return }        // the page sends 4000-byte blocks
                val part = text.toByteArray(Charsets.ISO_8859_1)
                d.buf.write(part); d.got += part.size
                if (d.got > d.size) { cancelFile(k); return }
                send(JSONObject().put("action", "fileUploadAck").put("id", id))
                onFileProgress?.invoke(k, d.got, d.size)
            }
            "fileUploadEnd" -> {
                downloads.remove(k)
                send(JSONObject().put("action", "fileUploadAck").put("id", id))
                onFileDone?.invoke(k, d.buf.toByteArray())
            }
        }
    }

    companion object {
        const val BLOCK = 4000
        const val MAX_IN = 100L * 1024 * 1024            // the page keeps a whole file in memory too
    }

    private fun send(o: JSONObject) { ws?.send(o.toString()) }

    /** A chat line; kept until the remote user joins. */
    fun say(text: String) { if (state == 3) send(JSONObject().put("action", "chat").put("msg", text)) else queue.add(text) }
    fun sendTyping(on: Boolean) { if (state == 3) send(JSONObject().put("action", "outtext").put("value", on)) }
}

private data class Line(val text: String, val kind: Int, val file: String? = null)   // 0 note, 1 mine, 2 theirs; file = id key

/** A file in the conversation: progress, then the data to save (incoming) or done / cancelled. */
private class ChatFile(val name: String, val size: Long, val mine: Boolean) {
    var done by mutableStateOf(0L)
    var state by mutableIntStateOf(0)           // 0 moving, 1 finished, 2 cancelled, 3 saved
    var data: ByteArray? = null
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    if (node == null) { Text("This device is not in the list any more.", Modifier.padding(24.dp)); return }
    val ctx = LocalContext.current
    val chat = remember(node.id) { ChatSession(session.ctrl, node) }
    val lines = remember { mutableStateListOf<Line>() }
    val files = remember { mutableStateMapOf<String, ChatFile>() }
    var text by remember { mutableStateOf("") }
    var typingSent by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf<String?>(null) }
    val list = rememberLazyListState()

    fun openRemote() = openChatPage(session.ctrl, node, session.caps(node), remotePageUrl(session.ctrl, node)) { lines.add(Line(it, 0)) }

    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        uris.forEach { uri ->
            val name = (queryName(ctx, uri) ?: "file").substringAfterLast('/').substringAfterLast('\\')
                .takeIf { it.isNotBlank() && it != "." && it != ".." } ?: "file"
            val size = querySize(ctx, uri)
            if (size > ChatSession.MAX_IN) { lines.add(Line("$name is too large for the chat (100 MB at most). Use Files.", 0)); return@forEach }
            val data = try { ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } } catch (e: Exception) { null }
            if (data == null) { lines.add(Line("Could not read $name.", 0)); return@forEach }
            val k = chat.sendFile(name, data) ?: run { lines.add(Line("Files can be sent once the remote user has joined the chat.", 0)); return@forEach }
            files[k] = ChatFile(name, data.size.toLong(), true)
            lines.add(Line(name, 1, k))
        }
    }
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val k = saving ?: return@rememberLauncherForActivityResult
        saving = null
        val f = files[k] ?: return@rememberLauncherForActivityResult
        if (uri == null) return@rememberLauncherForActivityResult
        try {
            ctx.contentResolver.openOutputStream(uri)?.use { it.write(f.data) }
            f.state = 3
        } catch (e: Exception) { lines.add(Line("Could not save ${f.name}: ${e.message}", 0)) }
    }

    DisposableEffect(node.id) {
        chat.onChat = { lines.add(Line(it, 2)) }
        chat.onNote = { lines.add(Line(it, 0)) }
        chat.onFileIn = { k, name, size -> files[k] = ChatFile(name, size, false); lines.add(Line(name, 2, k)) }
        chat.onFileProgress = { k, done, _ -> files[k]?.done = done }
        chat.onFileDone = { k, data ->
            files[k]?.let { f ->
                if (data == null) f.state = 2 else { f.done = f.size; if (!f.mine) f.data = data; f.state = 1 }
            }
            // received files wait in memory until saved: keep at most 200 MB, the oldest are let go first
            var held = files.values.sumOf { (it.data?.size ?: 0).toLong() }
            for (f in files.values) {
                if (held <= 200L * 1024 * 1024) break
                val d = f.data ?: continue
                if (f === files[k]) continue
                held -= d.size; f.data = null; f.state = 2
            }
        }
        lines.add(Line("Chat with the user of ${node.name}", 0))
        chat.start()
        openRemote()
        onDispose { chat.stop() }
    }
    LaunchedEffect(lines.size) { if (lines.isNotEmpty()) list.animateScrollToItem(lines.size - 1) }

    fun send() {
        val t = text.trim()
        if (t.isEmpty()) return
        text = ""
        typingSent = false
        chat.say(t)
        lines.add(Line(if (chat.state == 3) t else "$t  (sent when the remote user joins)", 1))
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text(node.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).background(if (chat.state == 3) OnlineGreen else OfflineGray, CircleShape))
                        Text(when (chat.state) { 0 -> "Not connected"; 1 -> "Connecting…"; 2 -> "Waiting for the remote user"
                            else -> "Connected" + if (chat.recorded) " (recorded)" else "" },
                            Modifier.padding(start = 6.dp), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { IconButton({ openRemote() }) { Icon(Icons.AutoMirrored.Filled.OpenInNew, "Open the chat again on the remote computer") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding()) {
            LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = list, contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(lines) { _, l ->
                    when {
                        l.kind == 0 -> Text(l.text, Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 4.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
                        else -> Box(Modifier.fillMaxWidth(), contentAlignment = if (l.kind == 1) Alignment.CenterEnd else Alignment.CenterStart) {
                            val mine = l.kind == 1
                            val shape = RoundedCornerShape(18.dp, 18.dp, if (mine) 4.dp else 18.dp, if (mine) 18.dp else 4.dp)
                            val bg = if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh
                            val fg = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface
                            val f = l.file?.let { files[it] }
                            if (f != null) FileBubble(f, shape, bg, fg,
                                onCancel = { chat.cancelFile(l.file) },
                                onSave = { saving = l.file; save.launch(f.name) })
                            else SelectionContainer {
                                Text(l.text, Modifier.widthIn(max = 300.dp).background(bg, shape)
                                    .padding(horizontal = 14.dp, vertical = 9.dp), color = fg)
                            }
                        }
                    }
                }
            }
            if (chat.typing) Text("The remote user is typing…", Modifier.padding(start = 16.dp, bottom = 2.dp),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainer).padding(horizontal = 6.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                IconButton({ if (chat.state == 3) pick.launch(arrayOf("*/*")) else lines.add(Line("Files can be sent once the remote user has joined the chat.", 0)) }) {
                    Icon(Icons.Filled.AttachFile, "Send a file")
                }
                TextField(text, {
                    text = it.take(4096)
                    val on = text.isNotEmpty()
                    if (on != typingSent && chat.state == 3) { typingSent = on; chat.sendTyping(on) }
                }, Modifier.weight(1f), placeholder = { Text("Message") }, maxLines = 4, shape = RoundedCornerShape(24.dp),
                    colors = TextFieldDefaults.colors(focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                        focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerLowest,
                        unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerLowest),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send), keyboardActions = KeyboardActions(onSend = { send() }))
                FilledIconButton({ send() }, Modifier.padding(start = 6.dp), enabled = text.isNotBlank()) {
                    Icon(Icons.AutoMirrored.Filled.Send, "Send")
                }
            }
        }
    }
}

@Composable
private fun FileBubble(f: ChatFile, shape: androidx.compose.ui.graphics.Shape, bg: Color, fg: Color, onCancel: () -> Unit, onSave: () -> Unit) {
    Column(Modifier.widthIn(min = 220.dp, max = 300.dp).background(bg, shape).padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.AutoMirrored.Filled.InsertDriveFile, null, tint = fg)
            Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                Text(f.name, color = fg, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                Text(when (f.state) {
                    0 -> "${fmtSize(f.done)} of ${fmtSize(f.size)}"
                    2 -> "Cancelled"
                    3 -> "Saved · ${fmtSize(f.size)}"
                    else -> if (f.mine) "Sent · ${fmtSize(f.size)}" else "${fmtSize(f.size)} · tap to save"
                }, color = fg.copy(alpha = 0.75f), style = MaterialTheme.typography.bodySmall)
            }
            when {
                f.state == 0 -> IconButton(onCancel) { Icon(Icons.Filled.Close, "Cancel", tint = fg) }
                !f.mine && (f.state == 1 || f.state == 3) -> IconButton(onSave) { Icon(Icons.Filled.Download, "Save", tint = fg) }
            }
        }
        if (f.state == 0) LinearProgressIndicator({ if (f.size > 0) f.done.toFloat() / f.size else 0f },
            Modifier.fillMaxWidth().padding(top = 6.dp, end = 8.dp), color = fg, trackColor = fg.copy(alpha = 0.25f))
    }
}

private fun queryName(ctx: android.content.Context, uri: android.net.Uri): String? =
    ctx.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) c.getString(0) else null
    }

private fun querySize(ctx: android.content.Context, uri: android.net.Uri): Long =
    ctx.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.SIZE), null, null, null)?.use { c ->
        if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else 0L
    } ?: 0L
