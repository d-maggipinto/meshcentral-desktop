// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DriveFileMove
import androidx.compose.material.icons.automirrored.filled.Message
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.NodeCaps
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.ControlConnection
import uk.co.cyvelion.meshcentral.net.agentEval
import uk.co.cyvelion.meshcentral.net.b64
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/*
 * Device actions of the desktop app's General page and action bar (device_general.py, general_actions.py,
 * desktop_tools.py, remote_session.notify): edit, user consent, notifications, message, web address, log event,
 * share link, change group, user authorizations, delete. Offered by the account's rights like the desktop app; the
 * server enforces them.
 */

// Linux session scripts, generated from remote_session.py (keep them identical). URL_JS: %s = base64 URL.
// NOTIFY_JS: @T@ / @M@ base64 title / message, @K@ toast | msg | alert, @W@ message box time limit in seconds.
private const val URL_JS = "(function(){try{var fs=require('fs'),NL=String.fromCharCode(10),uid=require('user-sessions').consoleUid();function senv(){var ps=fs.readdirSync('/proc'),fb=null;for(var i=0;i<ps.length;i++){var p=ps[i];if(!(parseInt(p)>0))continue;try{var ls=fs.readFileSync('/proc/'+p+'/status').toString().split(NL);var u=-1;for(var j=0;j<ls.length;j++){if(ls[j].indexOf('Uid:')==0){u=parseInt(ls[j].substring(4).trim());break;}}if(u!=uid)continue;var b=fs.readFileSync('/proc/'+p+'/environ'),e={},st=0;for(var k=0;k<=b.length;k++){if(k==b.length||b[k]==0){if(k>st){var kv=b.slice(st,k).toString();var q=kv.indexOf('=');if(q>0){e[kv.substring(0,q)]=kv.substring(q+1);}}st=k+1;}}if(!e.DISPLAY&&!e.WAYLAND_DISPLAY)continue;var r={},K=['DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','HOME','USER','LOGNAME','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','PATH','LANG','XDG_CURRENT_DESKTOP','XDG_SESSION_TYPE','XDG_DATA_DIRS','XDG_CONFIG_DIRS','XDG_SESSION_DESKTOP','DESKTOP_SESSION'];for(var m=0;m<K.length;m++){if(e[K[m]]){r[K[m]]=e[K[m]];}}if(r.DBUS_SESSION_BUS_ADDRESS){return r;}if(!fb){fb=r;}}catch(x){}}return fb;}var E=senv(),root=false;try{root=require('user-sessions').isRoot();}catch(x){}var O=root?{uid:uid,env:E}:{env:E};var RU=null,UN=null;if(root){var RP=['/usr/sbin/runuser','/sbin/runuser','/usr/bin/runuser'];for(var i=0;i<RP.length;i++){if(fs.existsSync(RP[i])){RU=RP[i];break;}}try{UN=require('user-sessions').getUsername(uid);}catch(x){}}function X(p,a){var cp=require('child_process');if(RU&&UN){var ev=[];for(var k in E){ev.push(k+'='+E[k]);}return cp.execFile(RU,['runuser','-u',UN,'--','/usr/bin/env'].concat(ev).concat([p]).concat(a.slice(1)),{env:{PATH:'/usr/sbin:/usr/bin:/sbin:/bin'}});}return cp.execFile(p,a,O);}if(!E){return 'MCDURL:nodisplay';}var url=Buffer.from('%s','base64').toString();if(url.indexOf('http://')!=0&&url.indexOf('https://')!=0){return 'MCDURL:bad';}var x='/usr/bin/xdg-open';if(!fs.existsSync(x)){return 'MCDURL:noxdg';}var c=X(x,['xdg-open',url]);c.stdout.on('data',function(){});c.stderr.on('data',function(){});return 'MCDURL:ok';}catch(z){return 'MCDURL:err';}})()"
private const val NOTIFY_JS = "(function(){try{var fs=require('fs'),NL=String.fromCharCode(10),uid=require('user-sessions').consoleUid();function senv(){var ps=fs.readdirSync('/proc'),fb=null;for(var i=0;i<ps.length;i++){var p=ps[i];if(!(parseInt(p)>0))continue;try{var ls=fs.readFileSync('/proc/'+p+'/status').toString().split(NL);var u=-1;for(var j=0;j<ls.length;j++){if(ls[j].indexOf('Uid:')==0){u=parseInt(ls[j].substring(4).trim());break;}}if(u!=uid)continue;var b=fs.readFileSync('/proc/'+p+'/environ'),e={},st=0;for(var k=0;k<=b.length;k++){if(k==b.length||b[k]==0){if(k>st){var kv=b.slice(st,k).toString();var q=kv.indexOf('=');if(q>0){e[kv.substring(0,q)]=kv.substring(q+1);}}st=k+1;}}if(!e.DISPLAY&&!e.WAYLAND_DISPLAY)continue;var r={},K=['DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','HOME','USER','LOGNAME','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','PATH','LANG','XDG_CURRENT_DESKTOP','XDG_SESSION_TYPE','XDG_DATA_DIRS','XDG_CONFIG_DIRS','XDG_SESSION_DESKTOP','DESKTOP_SESSION'];for(var m=0;m<K.length;m++){if(e[K[m]]){r[K[m]]=e[K[m]];}}if(r.DBUS_SESSION_BUS_ADDRESS){return r;}if(!fb){fb=r;}}catch(x){}}return fb;}var E=senv(),root=false;try{root=require('user-sessions').isRoot();}catch(x){}var O=root?{uid:uid,env:E}:{env:E};var RU=null,UN=null;if(root){var RP=['/usr/sbin/runuser','/sbin/runuser','/usr/bin/runuser'];for(var i=0;i<RP.length;i++){if(fs.existsSync(RP[i])){RU=RP[i];break;}}try{UN=require('user-sessions').getUsername(uid);}catch(x){}}function X(p,a){var cp=require('child_process');if(RU&&UN){var ev=[];for(var k in E){ev.push(k+'='+E[k]);}return cp.execFile(RU,['runuser','-u',UN,'--','/usr/bin/env'].concat(ev).concat([p]).concat(a.slice(1)),{env:{PATH:'/usr/sbin:/usr/bin:/sbin:/bin'}});}return cp.execFile(p,a,O);}if(!E){return 'MCDNOTE:nodisplay';}var t=Buffer.from('@T@','base64').toString(),m=Buffer.from('@M@','base64').toString(),k='@K@',w=@W@;function esc(s){return s.split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;');}function f(n){var D=['/usr/bin/','/bin/','/usr/local/bin/'];for(var i=0;i<D.length;i++){if(fs.existsSync(D[i]+n)){return D[i]+n;}}return null;}var p=null,a=null;if(k=='toast'&&E.DBUS_SESSION_BUS_ADDRESS&&(p=f('notify-send'))){a=['notify-send','-a','MeshCentral',t,esc(m)];}else if(p=f('zenity')){a=(k=='toast')?['zenity','--notification','--text='+esc(t)+NL+esc(m)]:['zenity',(k=='alert')?'--warning':'--info','--title='+t,'--text='+esc(m),'--width=360'];if(k=='msg'&&w>0){a.push('--timeout='+w);}}else if(p=f('kdialog')){a=(k=='toast')?['kdialog','--title',t,'--passivepopup',m,'10']:['kdialog','--title',t,'--msgbox',m];}else if(p=f('xmessage')){a=['xmessage','-center','-title',t,m];if(k=='msg'&&w>0){a.push('-timeout',String(w));}}if(!a){return 'MCDNOTE:notool';}var c=X(p,a);c.stdout.on('data',function(){});c.stderr.on('data',function(){});return 'MCDNOTE:ok';}catch(z){return 'MCDNOTE:err';}})()"

// consent bits (web UI p20editmeshconsent): bit, section, label
private val CONSENT_FLAGS = listOf(Triple(0x0001, "Desktop", "Notify user"), Triple(0x0008, "Desktop", "Prompt for user consent"),
    Triple(0x0040, "Desktop", "Show connection toolbar"),
    Triple(0x0002, "Terminal", "Notify user"), Triple(0x0010, "Terminal", "Prompt for user consent"),
    Triple(0x0004, "Files", "Notify user"), Triple(0x0020, "Files", "Prompt for user consent"),
    Triple(0x0080, "Registry", "Notify user"), Triple(0x0100, "Registry", "Prompt for user consent"))

private val SHARE_EXPIRE = listOf(1 to "1 minute", 5 to "5 minutes", 10 to "10 minutes", 15 to "15 minutes", 30 to "30 minutes",
    45 to "45 minutes", 60 to "60 minutes", 120 to "2 hours", 240 to "4 hours", 480 to "8 hours", 720 to "12 hours",
    960 to "16 hours", 1440 to "24 hours", 2880 to "2 days", 5760 to "4 days", 0 to "Unlimited")
private val SHARE_TYPES = mapOf(1 to "Terminal", 2 to "Desktop", 3 to "Desktop, View only", 4 to "Files", 5 to "Desktop + Files",
    6 to "Terminal + Files", 7 to "Desktop + Terminal + Files")
private val SHARE_LINK_NAMES = listOf("", "Remote Terminal Link", "Remote Desktop Link", "Remote Desktop + Terminal Link",
    "Remote Files Link", "Remote Terminal + Files Link", "Remote Desktop + Files Link", "Remote Desktop + Terminal + Files Link")

/** Device permission bits (user_panel.DEVICE_RIGHTS, device level): bit, label, indented under remote control. */
private val DEVICE_RIGHTS = listOf(Triple(8, "Remote Control & Relay", false), Triple(256, "Remote View Only", true),
    Triple(4096, "Limited Input Only", true), Triple(524288, "Guest Sharing", true), Triple(65536, "No Desktop Access", true),
    Triple(512, "No Terminal Access", true), Triple(1024, "No File Access", true), Triple(4194304, "No Registry Access", true),
    Triple(8388608, "No Software", true), Triple(2048, "No Intel® AMT", true), Triple(16, "Mesh Agent Console", false),
    Triple(32, "Server Files", false), Triple(64, "Wake Devices", false), Triple(128, "Edit Device Notes", false),
    Triple(8192, "Show Only Own Events", false), Triple(16384, "Chat & Notify", false),
    Triple(32768, "Uninstall Agent / Delete Device", false), Triple(131072, "Remote Commands", false),
    Triple(262144, "Reset / Power Off", false), Triple(1048576, "Device Details", false), Triple(2097152, "Use as Relay", false))

/** web UI makeUserDeviceRightsString (user_panel.device_rights_text) */
private fun deviceRightsText(r: Long): String {
    if (r == 57592L) return "Full Device Rights"
    val out = ArrayList<String>()
    if (r and 8L != 0L) {
        val p = listOf(256L to "No Input", 512L to "No Terminal", 1024L to "No Files", 4194304L to "No Registry",
            8388608L to "No Software", 2048L to "No AMT", 4096L to "Limited Input", 65536L to "No Desktop", 524288L to "Guest Share")
            .filter { r and it.first != 0L }.map { it.second }
        out.add(if (p.isEmpty()) "Control" else "Control (" + p.joinToString(", ") + ")")
    }
    out += listOf(16L to "Console", 32L to "Server Files", 64L to "Wake", 128L to "Notes", 8192L to "Limit Events",
        16384L to "Chat", 32768L to "Uninstall", 131072L to "Commands", 262144L to "Reset/Off", 524288L to "Sharing",
        1048576L to "Details", 2097152L to "Relay").filter { r and it.first != 0L }.map { it.second }
    return out.joinToString(", ").ifEmpty { "No Rights" }
}

/** encodeURIComponent, which the server's setDeviceEvent decodes */
private fun uriComponent(s: String): String = java.net.URLEncoder.encode(s, "UTF-8").replace("+", "%20")
    .replace("%21", "!").replace("%27", "'").replace("%28", "(").replace("%29", ")").replace("%7E", "~")

private fun toast(ctx: Context, text: String) = Toast.makeText(ctx, text, Toast.LENGTH_SHORT).show()

/** Share links grant access to whoever holds them: marked sensitive (Android 13+ hides them in the clipboard preview). */
private fun copyText(ctx: Context, label: String, text: String) {
    (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText(label, text).apply {
        description.extras = android.os.PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
    })
}

private fun shareText(ctx: Context, subject: String, text: String) {
    ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
        .putExtra(Intent.EXTRA_SUBJECT, subject).putExtra(Intent.EXTRA_TEXT, text), subject))
}

/** The Linux session tools apply: a Linux agent and the right to use its console (remote_session.linux_session). */
private fun linuxSession(node: Node, caps: NodeCaps) = node.hasAgent && !node.isWindows && caps.console

/** web UI valid web address: http:// or https:// followed by something (desktop_tools.valid_url) */
internal fun validUrl(text: String): Boolean {
    val x = text.trim().lowercase()
    return (x.startsWith("http://") && x.length > 7) || (x.startsWith("https://") && x.length > 8)
}

/**
 * Open a web address on the remote computer: in the Linux user's session with console rights (URL_JS), else the
 * agent's own openUrl, whose {type:'openUrl', success} answer is reported. report() runs on the main thread.
 */
internal fun openRemoteUrl(ctrl: ControlConnection, node: Node, caps: NodeCaps, url: String, report: (String) -> Unit) {
    fun stock() {
        val main = Handler(Looper.getMainLooper())
        var done = false
        lateinit var reply: (JSONObject) -> Unit
        val timeout = Runnable { if (!done) { done = true; ctrl.off("msg", reply); report("No answer from the agent about the web address") } }
        reply = { m ->
            if (!done && m.optString("type") == "openUrl" && m.optString("nodeid", node.id) == node.id) {
                done = true
                ctrl.off("msg", reply)
                main.removeCallbacks(timeout)
                report(if (m.optBoolean("success")) "The web address was opened on the remote computer"
                    else "The remote computer could not open the web address" +
                        if (node.isWindows) "" else " (the agent's xdg-open must reach the user's desktop session)")
            }
        }
        ctrl.on("msg", reply)
        ctrl.nodeMsg(node.id, "openUrl", "url" to url)
        main.postDelayed(timeout, 20_000)
    }
    if (!linuxSession(node, caps)) { stock(); return }
    agentEval(ctrl, node.id, URL_JS.replace("%s", b64(url)), "MCDURL") { r ->
        when (r) {
            "ok" -> report("The web address was opened on the remote computer")
            "bad" -> report("Only http:// and https:// addresses can be opened")
            else -> stock()
        }
    }
}

/** The web UI's messages (remote_session.send_stock_notification): toast / message box (time limit) / alert box. */
private fun stockNotification(ctrl: ControlConnection, node: Node, kind: String, title: String, msg: String, minutes: Int) {
    when (kind) {
        "toast" -> ctrl.send("action" to "toast", "nodeids" to JSONArray().put(node.id), "title" to title, "msg" to msg)
        "msg" -> ctrl.send("action" to "msg", "type" to "messagebox", "nodeid" to node.id, "title" to title, "msg" to msg,
            "timeout" to minutes * 60000)
        else -> ctrl.send("action" to "msg", "type" to "alertbox", "nodeid" to node.id, "title" to title, "msg" to msg)
    }
}

/**
 * remote_session.notify: kind toast | msg | alert. Linux devices with console rights: shown directly in the user's
 * session (the stock message when the session or a tool is missing); others: the stock message.
 */
private fun notifyRemote(ctrl: ControlConnection, node: Node, caps: NodeCaps, kind: String, title: String, msg: String,
                         minutes: Int, report: (String) -> Unit) {
    if (!linuxSession(node, caps)) { stockNotification(ctrl, node, kind, title, msg, minutes); report("Message sent"); return }
    val js = NOTIFY_JS.replace("@T@", b64(title)).replace("@M@", b64(msg)).replace("@K@", kind)
        .replace("@W@", (if (kind == "msg") minutes * 60 else 0).toString())
    agentEval(ctrl, node.id, js, "MCDNOTE") { r ->
        if (r == "ok") report("Shown on the remote computer")
        else {
            stockNotification(ctrl, node, kind, title, msg, minutes)
            report(if (r == "nodisplay" || r == "notool") "Sent through the agent (no desktop session tool found)" else "Sent through the agent")
        }
    }
}

private data class SheetItem(val key: String, val label: String, val detail: String, val icon: ImageVector, val enabled: Boolean = true)

/**
 * The device's management actions as a bottom sheet; each action opens its own dialog. onDeleted() after the
 * device was removed (the caller leaves the device page).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeviceManageSheet(app: McdApp, session: Session, node: Node, onDismiss: () -> Unit, onDeleted: () -> Unit) {
    val ctx = LocalContext.current
    val ctrl = session.ctrl
    val caps = session.caps(node)
    val r = caps.rights
    val full = r == Rights.FULL
    val mesh = session.meshes[node.meshId]
    val meshRights = Rights.mesh(ctrl.serverinfo, ctrl.userinfo, mesh?.json)
    val mtype = mesh?.type ?: 2
    val si = ctrl.serverinfo
    val f2 = si.optLong("features2")
    val agent = node.json.optJSONObject("agent")
    val agentId = agent?.optInt("id") ?: 0
    val online = node.online
    var dialog by remember { mutableStateOf<String?>(null) }
    val close = { dialog = null; onDismiss() }

    val push = node.json.optInt("pmt") == 1 && f2 and 2L != 0L
    val items = buildList {
        if (full || r and 4L != 0L) add(SheetItem("edit", "Edit device", "Name, hostname, description, tags", Icons.Filled.Edit))
        if (agent != null && agentId != 14 && mtype != 3 && (full || meshRights and 1L != 0L))
            add(SheetItem("consent", "User consent", "Ask or notify the remote user before a session", Icons.Filled.VerifiedUser))
        add(SheetItem("notify", "Notifications", "Get notified when this device connects or disconnects", Icons.Filled.Notifications))
        if (mtype != 4 && ((r and 8L != 0L && online && r and 16384L != 0L) || push))
            add(SheetItem("message", "Send a message", "Toast, message box or alert box on the remote screen", Icons.AutoMirrored.Filled.Message))
        if (caps.desktopInput && node.hasAgent)
            add(SheetItem("url", "Open a web address", "Opens the page on the remote computer", Icons.AutoMirrored.Filled.OpenInNew, online))
        add(SheetItem("event", "Log an event", "Write an entry into this device's event log", Icons.Filled.EditNote))
        if (mtype != 4 && si.opt("guestdevicesharing") != false && (agent?.optInt("caps") ?: 0) and 3 != 0 &&
            (r and 0x80008L) == 0x80008L && (full || r and 0x1000L == 0L))
            add(SheetItem("share", "Share device", "A link for a guest without an account", Icons.Filled.Share, online))
        add(SheetItem("users", "User authorizations", "Users with their own rights on this device", Icons.Filled.Group))
        if (r and 1L != 0L && mtype != 4) add(SheetItem("group", "Change group", "Move this device to another device group",
            Icons.AutoMirrored.Filled.DriveFileMove))
        if (r and 0x8000L != 0L) add(SheetItem("delete", "Delete device", "Remove this device from the server", Icons.Filled.Delete))
    }

    if (dialog == null) {
        val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet) {
            Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 8.dp)) {
                Text(node.name, Modifier.padding(horizontal = 24.dp, vertical = 4.dp), style = MaterialTheme.typography.titleMedium,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                items.forEach {
                    val danger = it.key == "delete"
                    ListItem(
                        headlineContent = { Text(it.label, color = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface) },
                        supportingContent = { Text(it.detail) },
                        leadingContent = { Icon(it.icon, null, tint = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary) },
                        modifier = Modifier.clickable(enabled = it.enabled) { dialog = it.key }.alpha(if (it.enabled) 1f else 0.4f),
                    )
                }
            }
        }
    }
    when (dialog) {
        "edit" -> EditDeviceDialog(ctrl, node, session, close)
        "consent" -> ConsentDialog(ctrl, node, close)
        "notify" -> NotifySettingsDialog(ctrl, node, close)
        "message" -> MessageDialog(ctrl, node, caps, push, close)
        "url" -> OpenUrlDialog(ctrl, node, caps, close)
        "event" -> LogEventDialog(ctrl, node, close)
        "share" -> ShareDialog(ctrl, node, r, close)
        "users" -> DeviceUsersDialog(ctrl, node, r, close)
        "group" -> ChangeGroupDialog(session, node, mtype, close)
        "delete" -> DeleteDeviceDialog(ctrl, node, close) { dialog = null; onDismiss(); onDeleted() }
    }
}

@Composable
private fun EditDeviceDialog(ctrl: ControlConnection, node: Node, session: Session, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val j = node.json
    var name by remember { mutableStateOf(j.optString("name")) }
    var host by remember { mutableStateOf(j.optString("host")) }
    var desc by remember { mutableStateOf(j.optString("desc")) }
    var tags by remember { mutableStateOf(node.tags.joinToString(", ")) }
    val local = session.meshes[node.meshId]?.type == 3
    // hostname is unused in WAN-only mode (features & 1), like the desktop app
    val showHost = (ctrl.serverinfo.optLong("features") and 1L == 0L && (session.meshes[node.meshId]?.type ?: 2) != 4) || local
    val existing = remember { session.nodes.flatMap { it.tags }.distinct().sortedBy { it.lowercase() } }
    AlertDialog(onDismissRequest = onClose, title = { Text("Edit device") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it.take(64) }, Modifier.fillMaxWidth(), label = { Text("Name") }, singleLine = true)
                if (showHost) OutlinedTextField(host, { host = it.take(64) }, Modifier.fillMaxWidth(), label = { Text("Hostname") }, singleLine = true)
                OutlinedTextField(desc, { desc = it.take(1024) }, Modifier.fillMaxWidth(), label = { Text("Description") }, maxLines = 4)
                OutlinedTextField(tags, { tags = it.take(4096) }, Modifier.fillMaxWidth(), label = { Text("Tags") },
                    placeholder = { Text("Tag1, Tag2, Tag3") })
                if (existing.isNotEmpty()) TagChips(existing) { t ->
                    val cur = tags.split(",").map { it.trim() }.filter { it.isNotEmpty() }
                    if (t !in cur) tags = (cur + t).joinToString(", ")
                }
            }
        },
        confirmButton = {
            TextButton({
                val m = JSONObject().put("action", "changedevice").put("nodeid", node.id)
                if (name.trim().isNotEmpty() && name != j.optString("name")) m.put("name", name.trim())
                if (showHost && host.isNotEmpty() && host != j.optString("host")) m.put("host", host)
                if (desc != j.optString("desc")) m.put("desc", desc)
                val newTags = tags.split(",").map { it.trim() }.filter { it.isNotEmpty() && it.length < 64 }.distinct()
                if (newTags != node.tags) m.put("tags", newTags.joinToString(","))
                if (m.length() > 2) { ctrl.send(m); toast(ctx, "Device updated") }
                onClose()
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TagChips(tags: List<String>, onPick: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        tags.forEach { t -> FilterChip(false, { onPick(t) }, { Text(t) }) }
    }
}

@Composable
private fun CheckRow(label: String, checked: Boolean, enabled: Boolean = true, indent: Boolean = false, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled) { onChange(!checked) }.padding(start = if (indent) 24.dp else 0.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked, onChange, enabled = enabled)
        Text(label, color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ConsentDialog(ctrl: ControlConnection, node: Node, onClose: () -> Unit) {
    val cur = node.json.optInt("consent")
    val forced = ctrl.serverinfo.optInt("consent")
    var value by remember { mutableStateOf(cur or forced) }
    AlertDialog(onDismissRequest = onClose, title = { Text("User consent") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                var section = ""
                CONSENT_FLAGS.forEach { (bit, sec, label) ->
                    if (sec != section) {
                        section = sec
                        Text(sec, Modifier.padding(top = 8.dp), fontWeight = FontWeight.SemiBold)
                    }
                    // a bit forced by the server's configuration cannot be switched off
                    CheckRow(label, value and bit != 0, enabled = forced and bit == 0) { on -> value = if (on) value or bit else value and bit.inv() }
                }
            }
        },
        confirmButton = {
            TextButton({
                if (value != cur) ctrl.send("action" to "changedevice", "nodeid" to node.id, "consent" to value)
                onClose()
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun NotifySettingsDialog(ctrl: ControlConnection, node: Node, onClose: () -> Unit) {
    val me = ctrl.userinfo ?: JSONObject()
    val f2 = ctrl.serverinfo.optLong("features2")
    val cur = me.optJSONObject("notify")?.optInt(node.id) ?: 0
    var value by remember { mutableStateOf(cur) }
    val sections = buildList {
        add("Web page notifications" to (listOf(2 to "Device connections", 4 to "Device disconnections") +
            if (node.json.has("intelamt")) listOf(8 to "Intel® AMT desktop and serial events") else emptyList()))
        if (f2 and 0x4000L != 0L && me.optBoolean("emailVerified"))
            add("Email notifications" to listOf(16 to "Device connections", 32 to "Device disconnections", 64 to "Help requests"))
        if (me.has("msghandle") && f2 and 0x02000000L != 0L)
            add("Messaging notifications" to listOf(128 to "Device connections", 256 to "Device disconnections", 512 to "Help requests"))
    }
    AlertDialog(onDismissRequest = onClose, title = { Text("Notification settings") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("Server notifications for this device, for your account (the web page and this app's own " +
                    "connect / disconnect notifications are set separately in Settings).",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                sections.forEach { (title, flags) ->
                    Text(title, Modifier.padding(top = 8.dp), fontWeight = FontWeight.SemiBold)
                    flags.forEach { (bit, label) -> CheckRow(label, value and bit != 0) { on -> value = if (on) value or bit else value and bit.inv() } }
                }
            }
        },
        confirmButton = {
            TextButton({
                // bits of sections not shown are dropped, like the web UI
                val shown = sections.flatMap { s -> s.second.map { it.first } }.sum()
                val v = value and shown
                if (v != cur) {
                    ctrl.send("action" to "changeusernotify", "nodeid" to node.id, "notify" to v)
                    ctrl.userinfo?.let { u -> (u.optJSONObject("notify") ?: JSONObject().also { u.put("notify", it) }).put(node.id, v) }
                }
                onClose()
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

/** A labelled choice: the current value on a button, the options in a menu. */
@Composable
private fun <T> Choice(label: String, options: List<Pair<T, String>>, value: T, enabled: Boolean = true, onChange: (T) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Box {
            OutlinedButton({ open = true }, Modifier.fillMaxWidth(), enabled = enabled) {
                Text(options.firstOrNull { it.first == value }?.second ?: "", Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Icon(Icons.Filled.ArrowDropDown, null)
            }
            DropdownMenu(open, { open = false }) {
                options.forEach { (v, l) -> DropdownMenuItem({ Text(l) }, onClick = { open = false; onChange(v) }) }
            }
        }
    }
}

@Composable
private fun MessageDialog(ctrl: ControlConnection, node: Node, caps: NodeCaps, push: Boolean, onClose: () -> Unit) {
    val ctx = LocalContext.current
    var kind by remember { mutableStateOf("toast") }
    var title by remember { mutableStateOf("") }
    var text by remember { mutableStateOf("") }
    var minutes by remember { mutableStateOf(2) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Send a message") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (push) Text("This device gets a push notification.", style = MaterialTheme.typography.bodySmall)
                else Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("toast" to "Toast", "msg" to "Message box", "alert" to "Alert box").forEach { (k, l) ->
                        FilterChip(kind == k, { kind = k }, { Text(l) })
                    }
                }
                OutlinedTextField(title, { title = it.take(256) }, Modifier.fillMaxWidth(), label = { Text("Title") },
                    placeholder = { Text("MeshCentral") }, singleLine = true)
                OutlinedTextField(text, { text = it.take(4096) }, Modifier.fillMaxWidth().heightIn(min = 100.dp), label = { Text("Message") })
                if (!push && kind == "msg") Choice("Time limit", listOf(2 to "Show for 2 minutes (default)", 10 to "Show for 10 minutes",
                    30 to "Show for 30 minutes", 60 to "Show for 60 minutes", 0 to "Show until dismissed by the user"), minutes) { minutes = it }
            }
        },
        confirmButton = {
            TextButton({
                val t = title.trim().ifEmpty { "MeshCentral" }
                if (push) {
                    ctrl.send("action" to "pushmessage", "nodeid" to node.id, "title" to t, "msg" to text)
                    toast(ctx, "Message sent")
                } else notifyRemote(ctrl, node, caps, kind, t, text, minutes) { toast(ctx, it) }
                onClose()
            }, enabled = text.isNotBlank()) { Text("Send") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun OpenUrlDialog(ctrl: ControlConnection, node: Node, caps: NodeCaps, onClose: () -> Unit) {
    val ctx = LocalContext.current
    var url by remember { mutableStateOf("https://") }
    AlertDialog(onDismissRequest = onClose, title = { Text("Open a web address") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("The page opens in the remote user's web browser.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(url, { url = it.take(2048) }, Modifier.fillMaxWidth(), singleLine = true,
                    placeholder = { Text("https://example.com") })
            }
        },
        confirmButton = {
            TextButton({ openRemoteUrl(ctrl, node, caps, url.trim()) { toast(ctx, it) }; onClose() }, enabled = validUrl(url)) { Text("Open") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun LogEventDialog(ctrl: ControlConnection, node: Node, onClose: () -> Unit) {
    val ctx = LocalContext.current
    var text by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onClose, title = { Text("Log an event") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(text, { text = it.take(4096) }, Modifier.fillMaxWidth().heightIn(min = 120.dp), label = { Text("Event") })
                Text("This adds an entry to this device's event log.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        },
        confirmButton = {
            TextButton({
                ctrl.send("action" to "setDeviceEvent", "nodeid" to node.id, "msg" to uriComponent(text))
                toast(ctx, "Event added to ${node.name}")
                onClose()
            }, enabled = text.isNotEmpty()) { Text("Add") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

private val DT = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US)
private fun parseDt(s: String): Long? = try { DT.isLenient = false; DT.parse(s.trim())?.time } catch (e: Exception) { null }
private fun fmtDt(ms: Long): String = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT).format(Date(ms))

/** Web UI "Share Device": a guest link for desktop / terminal / files, plus the device's existing links. */
@Composable
private fun ShareDialog(ctrl: ControlConnection, node: Node, r: Long, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val full = r == Rights.FULL
    val acaps = node.json.optJSONObject("agent")?.optInt("caps") ?: 0
    val types = buildList {
        if (acaps and 1 != 0) { if (full || r and 0x100L == 0L) add(2); add(3) }
        if (acaps and 2 != 0 && (full || r and 0x200L == 0L)) add(1)
        if (acaps and 4 != 0 && (full || r and 0x400L == 0L)) add(4)
        if (acaps and 5 == 5 && (full || r and 0x500L == 0L)) add(5)
        if (acaps and 6 == 6 && (full || r and 0x600L == 0L)) add(6)
        if (acaps and 7 == 7 && (full || r and 0x700L == 0L)) add(7)
    }
    val maxt = if (ctrl.serverinfo.has("guestdevicesharingmaxtime")) ctrl.serverinfo.optInt("guestdevicesharingmaxtime") else null
    val expire = SHARE_EXPIRE.filter { maxt == null || (it.first in 1..maxt) }
    val duration = SHARE_EXPIRE.filter { it.first in 1..720 && (maxt == null || it.first <= maxt) }
    var guest by remember { mutableStateOf("") }
    var type by remember { mutableStateOf(types.firstOrNull() ?: 0) }
    var mode by remember { mutableStateOf(0) }
    var exp by remember { mutableStateOf(expire.firstOrNull { it.first == 60 }?.first ?: expire.firstOrNull()?.first ?: 0) }
    var dur by remember { mutableStateOf(duration.firstOrNull { it.first == 60 }?.first ?: duration.firstOrNull()?.first ?: 60) }
    var start by remember { mutableStateOf(DT.format(Date())) }
    var end by remember { mutableStateOf(DT.format(Date(System.currentTimeMillis() + 86_400_000))) }
    var consentMode by remember { mutableStateOf(0) }
    var result by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf("") }
    var shares by remember { mutableStateOf<List<JSONObject>?>(null) }

    DisposableEffect(node.id) {
        val onShares: (JSONObject) -> Unit = { m ->
            if (m.optString("nodeid") == node.id) {
                val a = m.optJSONArray("deviceShares")
                shares = if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it) }
            }
        }
        // the server sends the new list as an event after a link is created or removed
        val onEvent: (JSONObject) -> Unit = { m ->
            val ev = m.optJSONObject("event")
            if (ev?.optString("action") == "deviceShareUpdate" && ev.optString("nodeid") == node.id) {
                val a = ev.optJSONArray("deviceShares")
                shares = if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it) }
            }
        }
        ctrl.on("deviceShares", onShares)
        ctrl.on("event", onEvent)
        ctrl.send("action" to "deviceShares", "nodeid" to node.id)
        onDispose { ctrl.off("deviceShares", onShares); ctrl.off("event", onEvent) }
    }

    val res = result
    if (res != null) {
        val url = res.optString("url")
        AlertDialog(onDismissRequest = onClose, title = { Text("Share device") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    val rows = buildList {
                        add("Device" to node.name); add("Guest" to res.optString("guestname"))
                        add("User input" to if (res.optBoolean("viewOnly")) "Not allowed, view only" else "Allowed")
                        if (res.optLong("start") > 0 && res.optLong("expire") > 0) {
                            add("Start" to fmtDt(res.optLong("start")))
                            if (res.optInt("recurring") > 0) add("Duration" to "${res.optLong("expire")} minutes")
                            else add("Expires" to fmtDt(res.optLong("expire")))
                        }
                        if (res.optInt("recurring") in 1..2) add("Recurring" to if (res.optInt("recurring") == 1) "Daily" else "Weekly")
                        val c = res.optInt("consent")
                        add("User consent" to (listOf(0x07 to "Notify", 0x38 to "Prompt", 0x40 to "Privacy bar")
                            .filter { c and it.first != 0 }.map { it.second }.ifEmpty { listOf("None") }.joinToString(", ")))
                        val p = res.optInt("p")
                        add("Type" to (SHARE_LINK_NAMES.getOrNull(p)?.takeIf { p > 0 } ?: p.toString()))
                    }
                    rows.forEach { (k, v) ->
                        Row { Text(k, Modifier.weight(0.4f), color = MaterialTheme.colorScheme.onSurfaceVariant); Text(v, Modifier.weight(0.6f)) }
                    }
                    Text(url, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall, maxLines = 4, overflow = TextOverflow.Ellipsis)
                }
            },
            confirmButton = { TextButton({ shareText(ctx, "Remote access to ${node.name}", url) }) { Text("Share") } },
            dismissButton = {
                Row {
                    TextButton({ copyText(ctx, "Share link", url); toast(ctx, "Link copied") }) { Text("Copy") }
                    TextButton(onClose) { Text("Close") }
                }
            })
        return
    }

    val s0 = parseDt(start); val e0 = parseDt(end)
    val valid = guest.isNotBlank() && types.isNotEmpty() && when (mode) { 0 -> true; 1 -> s0 != null && e0 != null && e0 > s0; else -> s0 != null }
    AlertDialog(onDismissRequest = onClose, title = { Text("Share device") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (types.isEmpty()) Text("This device cannot be shared with your rights.")
                else {
                    Text("Creates a link that lets a guest without an account control this device for a limited time.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    OutlinedTextField(guest, { guest = it.take(128) }, Modifier.fillMaxWidth(), label = { Text("Guest name") }, singleLine = true)
                    Choice("Type", types.map { it to SHARE_TYPES.getValue(it) }, type) { type = it }
                    Choice("Validity", listOf(0 to "Starting now", 1 to "Time range", 2 to "Recurring daily", 3 to "Recurring weekly"), mode) { mode = it }
                    if (mode == 0) Choice("Expires after", expire, exp) { exp = it }
                    if (mode >= 1) OutlinedTextField(start, { start = it }, Modifier.fillMaxWidth(), label = { Text("Start (YYYY-MM-DD HH:MM)") },
                        singleLine = true, isError = s0 == null)
                    if (mode == 1) OutlinedTextField(end, { end = it }, Modifier.fillMaxWidth(), label = { Text("End (YYYY-MM-DD HH:MM)") },
                        singleLine = true, isError = e0 == null || (s0 != null && e0 <= s0))
                    if (mode >= 2) Choice("Duration", duration, dur) { dur = it }
                    if (acaps and 1 != 0) Choice("User consent", listOf(0 to "Notify only", 1 to "Prompt for consent", 2 to "No consent"), consentMode) { consentMode = it }
                    if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
                }
                val list = shares
                if (!list.isNullOrEmpty()) {
                    HorizontalDivider(Modifier.padding(vertical = 4.dp))
                    Text("Existing links", fontWeight = FontWeight.SemiBold)
                    list.forEach { d ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(d.optString("guestName"), maxLines = 1, overflow = TextOverflow.Ellipsis)
                                val p = d.optInt("p")
                                Text((SHARE_LINK_NAMES.getOrNull(p)?.takeIf { p > 0 } ?: "") +
                                    (if (d.optLong("expireTime") > 0) " · until " + fmtDt(d.optLong("expireTime")) else ""),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            val u = d.optString("url")
                            if (u.isNotEmpty()) IconButton({ copyText(ctx, "Share link", u); toast(ctx, "Link copied") }) { Icon(Icons.Filled.ContentCopy, "Copy link") }
                            IconButton({ ctrl.send("action" to "removeDeviceShare", "nodeid" to node.id, "publicid" to d.optString("publicid")) }) {
                                Icon(Icons.Filled.Delete, "Remove link", tint = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton({
                val q = listOf(0, 1, 2, 2, 4, 6, 5, 7)[type]           // 1 terminal, 2 desktop, 4 files
                val cv = if (acaps and 1 != 0) consentMode else 0
                var consent = 0
                if (q and 1 != 0) consent = consent or 0x0002
                if (q and 2 != 0) consent = consent or 0x0041
                if (q and 4 != 0) consent = consent or 0x0004
                if (cv == 1) consent = consent or (if (q and 1 != 0) 0x0010 else 0) or (if (q and 2 != 0) 0x0008 else 0) or (if (q and 4 != 0) 0x0020 else 0)
                else if (cv == 2) consent = 0
                val m = JSONObject().put("action", "createDeviceShareLink").put("nodeid", node.id).put("guestname", guest.trim())
                    .put("p", q).put("consent", consent).put("viewOnly", type == 3)
                when (mode) {
                    0 -> m.put("expire", exp)
                    1 -> m.put("start", s0!! / 1000).put("end", e0!! / 1000)
                    else -> m.put("start", s0!! / 1000).put("expire", dur).put("recurring", mode - 1)
                }
                error = ""
                ctrl.send(m) { reply ->
                    if (reply.optString("result", "OK") != "OK" || reply.optString("url").isEmpty())
                        error = "The link was not created: " + reply.optString("result").ifEmpty { "no answer" }
                    else result = reply
                }
            }, enabled = valid) { Text("Create link") }
        },
        dismissButton = { TextButton(onClose) { Text("Close") } })
}

/** Device permission checkboxes (user_panel.RightsDialog, device level) with the web UI's dependencies. */
@Composable
private fun DeviceRightsChecks(value: Long, guestSharing: Boolean, onChange: (Long) -> Unit) {
    fun on(b: Int) = value and b.toLong() != 0L
    Column {
        DEVICE_RIGHTS.forEach { (bit, label, under) ->
            if (bit == 524288 && !guestSharing) return@forEach
            val rc = on(8)
            val enabled = when (bit) {
                256 -> rc
                4096 -> rc && !on(256)
                524288 -> rc && (on(256) || !on(4096))
                else -> !under || rc
            }
            CheckRow(label, on(bit), enabled, indent = under) { c -> onChange(if (c) value or bit.toLong() else value and bit.toLong().inv()) }
        }
    }
}

@Composable
private fun DeviceUsersDialog(ctrl: ControlConnection, node: Node, r: Long, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val dom = node.id.split("/").getOrElse(1) { "" }
    val guest = ctrl.serverinfo.opt("guestdevicesharing") != false
    var ugroups by remember { mutableStateOf<JSONObject?>(null) }
    var edit by remember { mutableStateOf<Pair<String?, Long>?>(null) }      // (uid or null = add user, rights)
    var addGroup by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<String?>(null) }
    DisposableEffect(node.id) {
        val cb: (JSONObject) -> Unit = { m -> ugroups = m.optJSONObject("ugroups") ?: JSONObject() }
        ctrl.on("usergroups", cb)
        ctrl.send("action" to "usergroups")
        onDispose { ctrl.off("usergroups", cb) }
    }
    val links = node.json.optJSONObject("links") ?: JSONObject()
    val ids = links.keys().asSequence().filter { it.startsWith("user/") || it.startsWith("ugrp/") }.sorted().toList()
    fun linkName(uid: String): String = ugroups?.optJSONObject(uid)?.optString("name")?.takeIf { it.isNotEmpty() }
        ?: (if (uid == ctrl.userinfo?.optString("_id")) ctrl.userinfo?.optString("name") else null)
        ?: links.optJSONObject(uid)?.optString("name")?.takeIf { it.isNotEmpty() } ?: uid.substringAfterLast('/')
    fun add(extra: JSONObject, names: List<String>? = null, title: String = "Device permissions") {
        val m = JSONObject().put("action", "adddeviceuser").put("nodeid", node.id).put("nodename", node.name)
        extra.keys().forEach { m.put(it, extra.get(it)) }
        ctrl.send(m) { reply ->
            val res = reply.optString("result")
            if (res.isNotEmpty() && res != "ok") toast(ctx, "$title: $res")
            else if (names != null) {
                // the server answers ok even for unknown names: look for them once the device list refreshed
                Handler(Looper.getMainLooper()).postDelayed({
                    toast(ctx, "Added. A name that has no account on the server is ignored.")
                }, 300)
            }
        }
    }
    val freeGroups = ugroups?.let { g -> g.keys().asSequence().filter { k ->
        g.optJSONObject(k)?.has("membershipType") != true && k.split("/").getOrNull(1) == dom && !links.has(k) }.toList() } ?: emptyList()

    AlertDialog(onDismissRequest = onClose, title = { Text("User authorizations") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (ids.isEmpty()) Text("No users with special device permissions.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                ids.forEach { uid ->
                    val grp = uid.startsWith("ugrp/")
                    val rights = links.optJSONObject(uid)?.optLong("rights") ?: 0L
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f).clickable(enabled = r and 2L != 0L) { edit = uid to rights }.padding(vertical = 6.dp)) {
                            Text((if (grp) "Group: " else "") + linkName(uid), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(deviceRightsText(rights), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (r and 2L != 0L) IconButton({ removing = uid }) { Icon(Icons.Filled.Delete, "Remove", tint = MaterialTheme.colorScheme.error) }
                    }
                }
                if (r and 7L != 0L) Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton({ edit = null to 0L }) { Text("Add user") }
                    if (freeGroups.isNotEmpty()) OutlinedButton({ addGroup = true }) { Text("Add user group") }
                }
            }
        },
        confirmButton = { TextButton(onClose) { Text("Close") } })

    edit?.let { (uid, cur) ->
        var value by remember(uid) { mutableStateOf(cur) }
        var names by remember(uid) { mutableStateOf("") }
        AlertDialog(onDismissRequest = { edit = null },
            title = { Text(if (uid == null) "Add user" else if (uid.startsWith("ugrp/")) "Group rights" else "User rights") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (uid == null) OutlinedTextField(names, { names = it.take(256) }, Modifier.fillMaxWidth(), singleLine = true,
                        label = { Text("User names") }, placeholder = { Text("user1, user2") })
                    else Text(linkName(uid), fontWeight = FontWeight.SemiBold)
                    DeviceRightsChecks(value, guest) { value = it }
                }
            },
            confirmButton = {
                TextButton({
                    if (uid == null) {
                        val list = names.split(",").map { it.trim() }.filter { it.isNotEmpty() }
                        if (list.isNotEmpty()) add(JSONObject().put("usernames", JSONArray(list)).put("rights", value), list, "Add user")
                    } else add(JSONObject().put("userids", JSONArray().put(uid)).put("rights", value))
                    edit = null
                }, enabled = uid != null || names.isNotBlank()) { Text("Save") }
            },
            dismissButton = { TextButton({ edit = null }) { Text("Cancel") } })
    }
    if (addGroup) {
        var gid by remember { mutableStateOf(freeGroups.firstOrNull() ?: "") }
        var value by remember { mutableStateOf(0L) }
        AlertDialog(onDismissRequest = { addGroup = false }, title = { Text("Add user group") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Choice("User group", freeGroups.map { it to linkName(it) }.sortedBy { it.second.lowercase() }, gid) { gid = it }
                    DeviceRightsChecks(value, guest) { value = it }
                }
            },
            confirmButton = {
                TextButton({
                    add(JSONObject().put("userids", JSONArray().put(gid)).put("rights", value), title = "Add user group")
                    addGroup = false
                }, enabled = gid.isNotEmpty()) { Text("Add") }
            },
            dismissButton = { TextButton({ addGroup = false }) { Text("Cancel") } })
    }
    removing?.let { uid ->
        AlertDialog(onDismissRequest = { removing = null }, title = { Text("Remove permissions") },
            text = { Text("Remove the access rights of ${if (uid.startsWith("ugrp/")) "user group" else "user"} \"${linkName(uid)}\" to this device?") },
            confirmButton = {
                TextButton({ add(JSONObject().put("userids", JSONArray().put(uid)).put("rights", 0).put("remove", true)); removing = null }) {
                    Text("Remove", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton({ removing = null }) { Text("Cancel") } })
    }
}

@Composable
private fun ChangeGroupDialog(session: Session, node: Node, mtype: Int, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val ctrl = session.ctrl
    val targets = session.meshes.values.filter {
        it.id != node.meshId && it.type == mtype && Rights.mesh(ctrl.serverinfo, ctrl.userinfo, it.json) and 4L != 0L
    }.sortedBy { it.name.lowercase() }
    var pick by remember { mutableStateOf(targets.firstOrNull()?.id) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Change group") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (targets.isEmpty()) Text("No other device group of the same type exists.")
                else {
                    Text("Select a new group for this device.", style = MaterialTheme.typography.bodySmall)
                    targets.forEach { m ->
                        Row(Modifier.fillMaxWidth().clickable { pick = m.id }, verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(pick == m.id, { pick = m.id })
                            Text(m.name)
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton({
                pick?.let {
                    ctrl.send("action" to "changeDeviceMesh", "nodeids" to JSONArray().put(node.id), "meshid" to it)
                    toast(ctx, "Moving ${node.name}")
                }
                onClose()
            }, enabled = pick != null) { Text("Move") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

@Composable
private fun DeleteDeviceDialog(ctrl: ControlConnection, node: Node, onClose: () -> Unit, onDeleted: () -> Unit) {
    val ctx = LocalContext.current
    var typed by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onClose, title = { Text("Delete ${node.name}?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("The device is removed from the server with its events and notes. An installed agent connects " +
                    "again only after it is reinstalled.")
                Text("Type the device name to confirm.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(typed, { typed = it }, Modifier.fillMaxWidth(), singleLine = true, placeholder = { Text(node.name) })
            }
        },
        confirmButton = {
            TextButton({
                ctrl.send("action" to "removedevices", "nodeids" to JSONArray().put(node.id))
                toast(ctx, "${node.name} deleted")
                onDeleted()
            }, enabled = typed.trim() == node.name.trim()) { Text("Delete", color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}
