// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Base64
import android.view.inputmethod.InputMethodManager
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.TextDecrease
import androidx.compose.material.icons.filled.TextIncrease
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.PROTO_POWERSHELL
import uk.co.cyvelion.meshcentral.net.PROTO_TERMINAL
import uk.co.cyvelion.meshcentral.net.PROTO_USER_POWERSHELL
import uk.co.cyvelion.meshcentral.net.PROTO_USER_SHELL
import uk.co.cyvelion.meshcentral.net.Tunnel

private data class Shell(val label: String, val protocol: Int, val login: Boolean = false)

/** The web UI's terminal choices (terminal_panel.shell_options); serverinfo.linuxshell forces one type. */
private fun shellOptions(node: Node, linuxshell: String?): List<Shell> {
    if (node.isWindows) return listOf(Shell("Admin Shell", PROTO_TERMINAL), Shell("Admin PowerShell", PROTO_POWERSHELL),
        Shell("User Shell", PROTO_USER_SHELL), Shell("User PowerShell", PROTO_USER_POWERSHELL))
    val opts = mapOf("root" to Shell("Root Shell", PROTO_TERMINAL), "user" to Shell("User Shell", PROTO_USER_SHELL),
        "login" to Shell("Login Shell", PROTO_TERMINAL, true))
    opts[linuxshell]?.let { return listOf(it) }
    return opts.values.toList()
}

private val STATE_TEXT = mapOf(0 to "Disconnected", 1 to "Connecting…", 2 to "Waiting for agent…", 3 to "Connected")

/** Keys a phone keyboard lacks: label to the bytes sent (Ctrl / Alt are sticky modifiers for the next key). */
private val KEYS = listOf("Esc" to "\u001b", "Tab" to "\t", "↑" to "\u001b[A", "↓" to "\u001b[B", "←" to "\u001b[D",
    "→" to "\u001b[C", "Home" to "\u001b[H", "End" to "\u001b[F", "PgUp" to "\u001b[5~", "PgDn" to "\u001b[6~",
    "|" to "|", "~" to "~", "/" to "/", "-" to "-")

@OptIn(ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun TerminalScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    val ctx = LocalContext.current
    val shells = remember(node?.id) { node?.let { shellOptions(it, session.ctrl.serverinfo.optString("linuxshell", "")) } ?: emptyList() }
    var shell by rememberSaveable { mutableIntStateOf(0) }
    var state by remember { mutableIntStateOf(0) }
    var note by remember { mutableStateOf("") }
    var ctrlOn by remember { mutableStateOf(false) }
    var altOn by remember { mutableStateOf(false) }
    var font by rememberSaveable { mutableIntStateOf(14) }
    var menu by remember { mutableStateOf(false) }
    val holder = remember { arrayOfNulls<Tunnel>(1) }
    val size = remember { intArrayOf(80, 24) }
    var everConnected by remember { mutableStateOf(false) }

    lateinit var page: AssetPage
    fun out(bytes: ByteArray) = page.post(JSONObject().put("t", "out").put("b", Base64.encodeToString(bytes, Base64.NO_WRAP)).toString())
    fun out(text: String) = out(text.toByteArray(Charsets.UTF_8))
    fun sendKeys(s: String) { holder[0]?.takeIf { it.state == 3 }?.send(s) }

    page = remember {
        AssetPage(ctx, "term/term.html", rawKeyboard = true) { raw ->
            val m = try { JSONObject(raw) } catch (e: Exception) { return@AssetPage }
            when (m.optString("t")) {
                "ready" -> { page.ready(); out("Choose a shell and tap Connect.\r\n") }
                "in" -> sendKeys(m.optString("d"))
                "size" -> {
                    size[0] = m.optInt("c", 80); size[1] = m.optInt("r", 24)
                    holder[0]?.takeIf { it.state == 3 }?.sendCtrl(JSONObject().put("type", "termsize").put("cols", size[0]).put("rows", size[1]))
                }
                "modused" -> { ctrlOn = false; altOn = false }
                // a tap on the terminal (not a scroll): open the keyboard on purpose
                "kb" -> {
                    page.view.requestFocus()
                    (ctx.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(page.view, 0)
                }
                "copy" -> m.optString("d").trimEnd('\r', '\n').takeIf { it.isNotEmpty() }?.let {
                    (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Terminal", it))
                }
            }
        }
    }

    fun disconnect() {
        holder[0]?.let { t -> holder[0] = null; t.stop() }
        state = 0
    }

    fun connect() {
        val n = node ?: return
        disconnect()
        val sh = shells.getOrNull(shell) ?: return
        page.post("""{"t":"reset"}""")
        note = ""
        val opts = JSONObject().put("cols", size[0]).put("rows", size[1]).put("xterm", true)
        if (sh.login) opts.put("requireLogin", true)        // the agent runs `login` instead of the shell
        val t = Tunnel(session.ctrl, n.id, sh.protocol, opts)
        t.onState = { s ->
            if (holder[0] === t) {
                state = s
                if (s == 3) { everConnected = true; page.view.requestFocus(); page.post("""{"t":"focus"}""") }
                if (s == 0 && everConnected) out("\r\n\u001b[41;97m  Disconnected. Tap Connect to start a new session.  \u001b[0m\r\n")
            }
        }
        t.onText = { out(it) }
        t.onBinary = { out(it) }
        t.onConsole = { if (it.isNotEmpty()) note = it }
        holder[0] = t
        t.start()
    }

    fun setMods() = page.post(JSONObject().put("t", "mod").put("ctrl", ctrlOn).put("alt", altOn).toString())

    DisposableEffect(Unit) { onDispose { disconnect(); page.destroy() } }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text(node?.name ?: "Terminal", maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(STATE_TEXT[state] ?: "", style = MaterialTheme.typography.bodySmall,
                        color = if (state == 3) OnlineGreen else MaterialTheme.colorScheme.onSurfaceVariant)
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (state == 0) Button({ connect() }, enabled = node?.online == true) { Text("Connect") }
                else OutlinedButton({ disconnect() }) { Text("Disconnect") }
                Box {
                    IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem({ Text("Copy selection") }, leadingIcon = { Icon(Icons.Filled.ContentCopy, null) },
                            onClick = { menu = false; page.post("""{"t":"copy"}""") })
                        DropdownMenuItem({ Text("Paste") }, leadingIcon = { Icon(Icons.Filled.ContentPaste, null) },
                            enabled = state == 3, onClick = {
                                menu = false
                                val clip = (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip
                                val text = clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(ctx)?.toString()
                                if (!text.isNullOrEmpty()) page.post(JSONObject().put("t", "paste").put("d", text).toString())
                            })
                        DropdownMenuItem({ Text("Smaller text") }, leadingIcon = { Icon(Icons.Filled.TextDecrease, null) },
                            onClick = { font = (font - 1).coerceAtLeast(8); page.post("""{"t":"font","s":$font}""") })
                        DropdownMenuItem({ Text("Bigger text") }, leadingIcon = { Icon(Icons.Filled.TextIncrease, null) },
                            onClick = { font = (font + 1).coerceAtMost(28); page.post("""{"t":"font","s":$font}""") })
                    }
                }
            })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding()) {
            if (state == 0 && shells.size > 1) {
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    shells.forEachIndexed { i, s -> FilterChip(shell == i, { shell = i }, { Text(s.label) }) }
                }
            }
            if (node?.online != true && state == 0) Text("The device is offline.", Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                color = MaterialTheme.colorScheme.error)
            if (note.isNotEmpty()) Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.tertiaryContainer)
                .padding(start = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(note, Modifier.weight(1f), color = MaterialTheme.colorScheme.onTertiaryContainer,
                    style = MaterialTheme.typography.bodySmall)
                TextButton({ note = "" }) { Text("OK") }
            }
            AndroidView({ page.view }, Modifier.weight(1f).fillMaxWidth().background(Color(0xFF1E1E1E)))
            // the page must know whether the keyboard is open: while it is closed a touch must not bring it back
            val imeOpen = WindowInsets.isImeVisible
            LaunchedEffect(imeOpen) { page.post(JSONObject().put("t", "ime").put("v", imeOpen).toString()) }
            // extra keys above the soft keyboard
            Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainer)
                .horizontalScroll(rememberScrollState()).padding(horizontal = 4.dp, vertical = 2.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton({
                    page.view.requestFocus()
                    page.post("""{"t":"ime","v":true}""")
                    page.post("""{"t":"focus"}""")
                    (ctx.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(page.view, 0)
                }) { Icon(Icons.Filled.Keyboard, "Keyboard") }
                KeyButton("Ctrl", ctrlOn) { ctrlOn = !ctrlOn; setMods() }
                KeyButton("Alt", altOn) { altOn = !altOn; setMods() }
                KEYS.forEach { (label, seq) ->
                    KeyButton(label, false) {
                        if (altOn) sendKeys("\u001b")
                        sendKeys(seq)
                        if (ctrlOn || altOn) { ctrlOn = false; altOn = false; setMods() }
                    }
                }
            }
        }
    }
}

@Composable
private fun KeyButton(label: String, on: Boolean, onClick: () -> Unit) {
    if (on) Button(onClick, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp)) { Text(label) }
    else FilledTonalButton(onClick, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp)) { Text(label) }
}
