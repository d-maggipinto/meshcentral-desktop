// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Mesh
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.ControlConnection

// serverinfo.features bits (device_list.FEAT_*)
private const val FEAT_LANONLY = 0x2L
private const val FEAT_NOPROXY = 0x2000L
private const val FEAT_UNTRUSTED_CERT = 0x80000000L
private val HOST_RE = Regex("^[A-Za-z0-9.-]{1,253}$")
private val DOMAIN_RE = Regex("^[A-Za-z0-9_-]{1,64}$")

private val OSES = listOf("Windows", "Linux", "macOS", "Mobile", "Invite link")
private val INSTALL = listOf("Background & interactive" to 0, "Background only" to 2, "Interactive only" to 1)
private val EXPIRE = listOf("1 hour" to 1, "8 hours" to 8, "1 day" to 24, "1 week" to 168, "1 month" to 5040, "Unlimited" to 0)
private val AGENTS = listOf("All" to 0, "Windows" to 1, "Linux" to 2, "macOS" to 4, "MeshCentral Assistant" to 8, "Android" to 16)

/**
 * The server's public base like the web UI (addAgentToMesh, device_list.server_base): its name when it has a dot (else
 * the address we connected to), its port unless 443, and the domain path. These end up in shell commands people paste
 * (often with sudo): only a plain host name, a numeric port and a simple domain path are taken from the server.
 */
private fun serverBase(ctrl: ControlConnection): Pair<String, String> {
    val si = ctrl.serverinfo
    val feats = si.optLong("features")
    var name = si.optString("name")
    val host = ctrl.server.host.substringBefore(':')
    if (!name.contains('.') || feats and FEAT_LANONLY != 0L || !HOST_RE.matches(name)) name = host
    val port = si.optInt("port", 443).let { if (it in 1..65535) it else 443 }
    val p = if (port == 443) "" else ":$port"
    val suffix = si.optString("domainsuffix")
    val d = "/" + (if (suffix.isNotEmpty() && DOMAIN_RE.matches(suffix)) "$suffix/" else "")
    return "https://$name$p" to d
}

/** device_list.linux_install_command: the web UI's one-line installer (meshinstall.sh). */
private fun linuxCommand(ctrl: ControlConnection, meshId: String, uninstall: Boolean): String {
    val feats = ctrl.serverinfo.optLong("features")
    val (base, d) = serverBase(ctrl)
    val nc = if (feats and FEAT_UNTRUSTED_CERT != 0L) " --no-check-certificate" else ""
    val m = "'" + meshId.split("/").getOrElse(2) { "" }.replace("'", "'\\''") + "'"     // quoted for the shell whatever it contains
    val arg = if (uninstall) "uninstall " else ""
    val url = base + d.trimEnd('/')
    val run = "sudo -E ./meshinstall.sh $arg$url $m || ./meshinstall.sh $arg$url $m"
    return if (feats and FEAT_NOPROXY != 0L) "wget \"$base${d}meshagents?script=1\" --no-proxy$nc -O ./meshinstall.sh && chmod 755 ./meshinstall.sh && $run"
    else "(wget \"$base${d}meshagents?script=1\"$nc -O ./meshinstall.sh || wget \"$base${d}meshagents?script=1\" --no-proxy$nc -O ./meshinstall.sh) && chmod 755 ./meshinstall.sh && $run"
}

/** Install commands and invite links let anyone add devices to the group: marked sensitive like other secrets. */
private fun copyText(ctx: Context, text: String) {
    (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("MeshCentral", text).apply {
        description.extras = android.os.PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
    })
    Toast.makeText(ctx, "Copied", Toast.LENGTH_SHORT).show()
}

private fun shareText(ctx: Context, subject: String, text: String) {
    ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
        .putExtra(Intent.EXTRA_SUBJECT, subject).putExtra(Intent.EXTRA_TEXT, text), "Share"))
}

/**
 * Add a device to a group (web UI "Add Agent" and "Invite", device_list.AddAgentDialog / InviteDialog): download links
 * and the Linux install command (built here, no server message), or an invitation link from {action:'createInviteLink'}.
 * Everything can be copied or sent with the Android share sheet, so the link reaches the computer to add.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddDeviceSheet(app: McdApp, session: Session, meshId: String?, onDismiss: () -> Unit) {
    val ctrl = session.ctrl
    val ctx = LocalContext.current
    // only agent groups (mtype 2) take agents
    val groups = session.meshes.values.filter { it.type == 2 }.sortedBy { it.name.lowercase() }
    var mesh by remember { mutableStateOf(groups.firstOrNull { it.id == meshId } ?: groups.firstOrNull()) }
    var os by rememberSaveable { mutableIntStateOf(0) }
    var install by rememberSaveable { mutableIntStateOf(0) }
    var expire by rememberSaveable { mutableIntStateOf(2) }
    var agents by rememberSaveable { mutableIntStateOf(0) }
    var groupMenu by remember { mutableStateOf(false) }
    val lanOnly = ctrl.serverinfo.optLong("features") and FEAT_LANONLY != 0L

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 16.dp)) {
            Text("Add a device", Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            val m = mesh
            if (m == null) {
                Text("There is no device group for agents yet. Create one in My account first.", Modifier.padding(20.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                return@Column
            }
            Box(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                OutlinedButton({ groupMenu = true }, Modifier.fillMaxWidth()) {
                    Text("Device group: ${m.name}", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                DropdownMenu(groupMenu, { groupMenu = false }) {
                    groups.forEach { g -> DropdownMenuItem({ Text(g.name) }, onClick = { mesh = g; groupMenu = false }) }
                }
            }
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OSES.forEachIndexed { i, label -> if (!(i == 3 && lanOnly)) FilterChip(os == i, { os = i }, { Text(label) }) }
            }
            val (base, d) = serverBase(ctrl)
            val short = m.id.split("/").getOrElse(2) { "" }
            when (os) {
                0 -> {
                    Explain("Download the agent on the computer to add and run it. It already knows this server and the group \"${m.name}\".")
                    Choice(INSTALL.map { it.first }, install) { install = it }
                    val f = INSTALL[install].second
                    listOf("Windows 64-bit" to 4, "Windows 32-bit" to 3, "Windows ARM 64-bit" to 43).forEach { (label, id) ->
                        LinkRow(ctx, label, "$base${d}meshagents?id=$id&meshid=$short&installflags=$f")
                    }
                }
                1 -> {
                    Explain("Run this command on the Linux or BSD computer (root rights needed). For BSD run \"pkg install wget sudo bash\" first.")
                    CommandBox(ctx, linuxCommand(ctrl, m.id, false))
                    Explain("To remove the agent again:")
                    CommandBox(ctx, linuxCommand(ctrl, m.id, true))
                }
                2 -> {
                    Explain("Download and install the macOS agent on the Mac.")
                    listOf("macOS (Universal)" to 10005, "macOS Apple silicon" to 29, "macOS Intel" to 16).forEach { (label, id) ->
                        LinkRow(ctx, label, "$base${d}meshosxagent?id=$id&meshid=$short")
                    }
                }
                3 -> {
                    val si = ctrl.serverinfo
                    Explain("Install the MeshCentral agent app on the phone or tablet, then paste this code into it:")
                    CommandBox(ctx, "${si.optString("magenturl")},${si.optString("agentCertHash")},$short")
                    LinkRow(ctx, "Android agent (APK)", "$base${d}meshagents?id=14&meshid=$short")
                    LinkRow(ctx, "Google Play", "https://play.google.com/store/apps/details?id=com.meshcentral.agent2")
                }
                4 -> InviteLink(ctrl, m, expire, agents, install, { expire = it }, { agents = it }, { install = it })
            }
        }
    }
}

@Composable
private fun Explain(text: String) {
    Text(text, Modifier.padding(horizontal = 20.dp, vertical = 8.dp), style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun Choice(labels: List<String>, selected: Int, onSelect: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        labels.forEachIndexed { i, l -> FilterChip(selected == i, { onSelect(i) }, { Text(l) }) }
    }
}

@Composable
private fun LinkRow(ctx: Context, label: String, url: String) {
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 2.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Text(url, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
        }
        IconButton({ copyText(ctx, url) }) { Icon(Icons.Filled.ContentCopy, "Copy the link") }
        IconButton({ shareText(ctx, label, url) }) { Icon(Icons.Filled.Share, "Share the link") }
    }
}

@Composable
private fun CommandBox(ctx: Context, text: String) {
    Surface(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceContainerHigh) {
        Column(Modifier.padding(12.dp)) {
            SelectionContainer { Text(text, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall) }
            Row(Modifier.align(Alignment.End)) {
                IconButton({ copyText(ctx, text) }) { Icon(Icons.Filled.ContentCopy, "Copy") }
                IconButton({ shareText(ctx, "Install command", text) }) { Icon(Icons.Filled.Share, "Share") }
            }
        }
    }
}

@Composable
private fun InviteLink(ctrl: ControlConnection, mesh: Mesh, expire: Int, agents: Int, install: Int,
                       setExpire: (Int) -> Unit, setAgents: (Int) -> Unit, setInstall: (Int) -> Unit) {
    val ctx = LocalContext.current
    var url by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf("") }
    DisposableEffect(mesh.id) {
        val cb: (JSONObject) -> Unit = { m ->
            if (m.optString("meshid") == mesh.id || m.optString("meshid") == mesh.id.substringAfterLast('/')) {
                val cookie = m.optString("cookie")
                if (cookie.isNotEmpty()) {
                    val (base, d) = serverBase(ctrl)                 // the web UI rebuilds the URL the same way
                    url = "${base}${d}agentinvite?c=$cookie"
                } else if (m.has("result")) error = m.optString("result")
            }
        }
        ctrl.on("createInviteLink", cb)
        onDispose { ctrl.off("createInviteLink", cb) }
    }
    LaunchedEffect(mesh.id, expire, agents, install) {
        url = null
        error = ""
        ctrl.send("action" to "createInviteLink", "meshid" to mesh.id, "expire" to EXPIRE[expire].second,
            "flags" to INSTALL[install].second, "agents" to AGENTS[agents].second)
    }
    Explain("Send this link to the person whose computer should join \"${mesh.name}\". Opening it shows the right agent to install.")
    Text("Link expires", Modifier.padding(start = 20.dp, top = 4.dp), style = MaterialTheme.typography.labelLarge)
    Choice(EXPIRE.map { it.first }, expire, setExpire)
    Text("Agents", Modifier.padding(start = 20.dp, top = 4.dp), style = MaterialTheme.typography.labelLarge)
    Choice(AGENTS.map { it.first }, agents, setAgents)
    if (AGENTS[agents].second in listOf(0, 1, 2, 4)) {
        Text("Installation", Modifier.padding(start = 20.dp, top = 4.dp), style = MaterialTheme.typography.labelLarge)
        Choice(INSTALL.map { it.first }, install, setInstall)
    }
    when {
        error.isNotEmpty() -> Text(error, Modifier.padding(20.dp), color = MaterialTheme.colorScheme.error)
        url == null -> CircularProgressIndicator(Modifier.padding(20.dp).size(24.dp))
        else -> CommandBox(ctx, url!!)
    }
}
