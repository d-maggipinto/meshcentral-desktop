// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Password
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Pin
import androidx.compose.material.icons.filled.Token
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Rights
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.data.Site
import uk.co.cyvelion.meshcentral.net.ControlConnection

private val TOKEN_EXPIRY = listOf("Unlimited" to 0, "1 hour" to 60, "8 hours" to 480, "1 day" to 1440, "2 days" to 2880,
    "4 days" to 5760, "15 minutes" to 15, "30 minutes" to 30)
private val OTP_ERRORS = mapOf(1 to "Two-factor settings are locked by the server administrator.",
    3 to "Not allowed when signed in with a login token.", 4 to "Authenticator apps are disabled on this server.",
    5 to "Your account settings are locked.", 6 to "The server cannot generate authenticator secrets.")
/** changepassword answers only with a notify message: 20 = changed, 17-19 / 21 = refused. */
private val PASSWORD_MSGS = mapOf(17 to "The new password does not meet the server's requirements.",
    18 to "The new password was used before.", 19 to "The password cannot be changed yet.",
    21 to "The current password is not correct.")

/** Listen for one reply of a broadcast-style action (no responseid); gives up after secs. */
private fun once(ctrl: ControlConnection, action: String, secs: Long = 15, onTimeout: (() -> Unit)? = null, cb: (JSONObject) -> Unit) {
    var done = false
    var h: ((JSONObject) -> Unit)? = null
    h = { m -> if (!done) { done = true; ctrl.off(action, h!!); cb(m) } }
    ctrl.on(action, h)
    Handler(Looper.getMainLooper()).postDelayed({ if (!done) { done = true; ctrl.off(action, h); onTimeout?.invoke() } }, secs * 1000)
}

private fun copy(ctx: Context, label: String, text: String) {
    (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText(label, text).apply {
        // Android 13+: keep secrets out of the clipboard preview
        description.extras = android.os.PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
    })
    Toast.makeText(ctx, "Copied", Toast.LENGTH_SHORT).show()
}

private sealed interface AccDialog {
    data object Password : AccDialog
    data object RemoveOtp : AccDialog
    data class Authenticator(val secret: String, val url: String) : AccDialog
    data class Codes(val codes: List<String>) : AccDialog
    data class Keys(val keys: List<JSONObject>) : AccDialog
    data class Logins(val events: List<JSONObject>) : AccDialog
    data object Tokens : AccDialog
    data class TokenCreated(val user: String, val pass: String, val expire: Any?) : AccDialog
    data object Language : AccDialog
    data object NewGroup : AccDialog
    data class Message(val title: String, val text: String) : AccDialog
}

/**
 * My Account (account_panel.py): the account's two-factor sign-in (authenticator app, backup codes, security keys),
 * previous logins, password, login tokens, language and device groups. Accounts with locked settings (site right
 * 0x400, not full administrators) cannot change their security settings.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountScreen(app: McdApp, session: Session, onBack: () -> Unit) {
    val ctrl = session.ctrl
    val ctx = LocalContext.current
    var user by remember { mutableStateOf(ctrl.userinfo ?: JSONObject()) }
    var dialog by remember { mutableStateOf<AccDialog?>(null) }
    var busy by remember { mutableStateOf(false) }
    val locked = !Site.full(ctrl.userinfo) && (Site.rights(ctrl.userinfo) and Site.LOCKSETTINGS) != 0L
    // account picture (account_panel change_image / remove_image): updateUserImage {image: data URL | 0}
    var picMenu by remember { mutableStateOf(false) }
    val pickPhoto = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val bmp = try {
            if (android.os.Build.VERSION.SDK_INT < 28) ctx.contentResolver.openInputStream(uri)?.use {
                android.graphics.BitmapFactory.decodeStream(it, null, android.graphics.BitmapFactory.Options().apply { inSampleSize = 2 })
            } else {
            val src = android.graphics.ImageDecoder.createSource(ctx.contentResolver, uri)
            android.graphics.ImageDecoder.decodeBitmap(src) { d, info, _ ->
                d.allocator = android.graphics.ImageDecoder.ALLOCATOR_SOFTWARE
                val m = maxOf(info.size.width, info.size.height)
                if (m > 1024) d.setTargetSampleSize(m / 1024)             // enough for a 256 px picture
            }
            }
        } catch (e: Exception) { null }
        if (bmp == null) { android.widget.Toast.makeText(ctx, "Could not read this picture.", android.widget.Toast.LENGTH_SHORT).show(); return@rememberLauncherForActivityResult }
        val url = UserImages.toDataUrl(bmp)
        ctrl.send("action" to "updateUserImage", "image" to url)
        UserImages.setOwn(session, url)
        user = JSONObject(user.toString()).put("flags", user.optInt("flags") or 1)
    }

    DisposableEffect(Unit) {
        // our own changes come back as event accountchange (ControlConnection already updated userinfo)
        val cb: (JSONObject) -> Unit = { m ->
            val ev = m.optJSONObject("event")
            if (ev?.optString("action") == "accountchange" && ev.optJSONObject("account")?.optString("_id") == user.optString("_id"))
                user = ctrl.userinfo ?: user
        }
        ctrl.on("event", cb)
        onDispose { ctrl.off("event", cb) }
    }
    fun msg(title: String, text: String) { busy = false; dialog = AccDialog.Message(title, text) }

    fun authenticator() {
        if (user.optInt("otpsecret") != 0 || user.optBoolean("otpsecret")) { dialog = AccDialog.RemoveOtp; return }
        busy = true
        once(ctrl, "otpauth-request", onTimeout = { msg("No answer from the server", "Two-step sign-in may be disabled on this server (it needs a DNS host name).") }) { m ->
            busy = false
            if (m.has("err") || m.optString("secret").isEmpty())
                msg("Cannot set up an authenticator app", OTP_ERRORS[m.optInt("err")] ?: "Server error ${m.opt("err")}")
            else dialog = AccDialog.Authenticator(m.optString("secret"), m.optString("url"))
        }
        ctrl.send("action" to "otpauth-request")
    }
    fun backupCodes(sub: Int? = null) {
        if (!has2fa(user)) { msg("Backup codes need two-step sign-in", "Set up an authenticator app or a security key first."); return }
        busy = true
        once(ctrl, "otpauth-getpasswords", onTimeout = { msg("No answer from the server", "Backup codes may be disabled on this server.") }) { m ->
            busy = false
            val a = m.optJSONArray("passwords")
            dialog = AccDialog.Codes(if (a == null) emptyList() else (0 until a.length()).map { a.opt(it).toString() })
        }
        if (sub == null) ctrl.send("action" to "otpauth-getpasswords") else ctrl.send("action" to "otpauth-getpasswords", "subaction" to sub)
    }
    fun securityKeys() {
        busy = true
        once(ctrl, "otp-hkey-get", onTimeout = { msg("No answer from the server", "Security keys may be disabled on this server.") }) { m ->
            busy = false
            val a = m.optJSONArray("keys")
            dialog = AccDialog.Keys(if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it) })
        }
        ctrl.send("action" to "otp-hkey-get")
    }
    fun previousLogins() {
        busy = true
        once(ctrl, "previousLogins", onTimeout = { msg("No answer from the server", "") }) { m ->
            busy = false
            val a = m.optJSONArray("events")
            dialog = AccDialog.Logins(if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it) }
                .sortedByDescending { it.optString("t") })
        }
        ctrl.send("action" to "previousLogins")
    }

    val siteRights = Site.rights(ctrl.userinfo)
    Scaffold(topBar = {
        TopAppBar(title = { Text("Account") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = { if (busy) CircularProgressIndicator(Modifier.padding(end = 16.dp).size(22.dp), strokeWidth = 2.dp) })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                // tap the picture to change or remove it (not with locked settings: the web UI hides it too)
                Box {
                    Box(Modifier.clickable(enabled = !locked) { picMenu = true }) {
                        AdmAvatar(user.optString("name"), size = 64, image = UserImages.image(session, user.optString("_id"), UserImages.flags(user)))
                        if (!locked) Box(Modifier.align(Alignment.BottomEnd).size(24.dp)
                            .background(MaterialTheme.colorScheme.primary, CircleShape), contentAlignment = Alignment.Center) {
                            Icon(Icons.Filled.PhotoCamera, "Change picture", Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onPrimary)
                        }
                    }
                    androidx.compose.material3.DropdownMenu(picMenu, { picMenu = false }) {
                        androidx.compose.material3.DropdownMenuItem({ Text("Change picture") }, onClick = {
                            picMenu = false
                            pickPhoto.launch(androidx.activity.result.PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        }, leadingIcon = { Icon(Icons.Filled.PhotoCamera, null) })
                        if (UserImages.flags(user) and 1 != 0) androidx.compose.material3.DropdownMenuItem({ Text("Remove picture") }, onClick = {
                            picMenu = false
                            ctrl.send("action" to "updateUserImage", "image" to 0)
                            UserImages.setOwn(session, null)
                            user = JSONObject(user.toString()).put("flags", user.optInt("flags") and 1.inv())
                        }, leadingIcon = { Icon(Icons.Filled.Delete, null) })
                    }
                }
                Column(Modifier.weight(1f).padding(start = 16.dp)) {
                    Text(user.optString("name"), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    if (user.optString("email").isNotEmpty()) Text(user.optString("email"), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(when { siteRights == Rights.FULL -> "Full administrator"; siteRights != 0L -> "Administrator"; else -> "User" } +
                        "  ·  " + ctrl.server.host, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (locked) Text("Your account settings are locked by an administrator.", Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)

            SectionCard(title = "Two-step sign-in") {
                val otp = user.optInt("otpsecret") != 0 || user.optBoolean("otpsecret")
                AccRow(Icons.Filled.PhoneAndroid, "Authenticator app", if (otp) "Enabled" else "Not set up", !locked) { authenticator() }
                AccRow(Icons.Filled.Pin, "Backup codes", if (user.optInt("otpkeys") > 0) "${user.optInt("otpkeys")} unused" else "None", !locked) { backupCodes() }
                AccRow(Icons.Filled.Key, "Security keys", if (user.optInt("otphkeys") > 0) "${user.optInt("otphkeys")} registered" else "None",
                    !locked, last = true) { securityKeys() }
            }
            SectionCard(title = "Account") {
                AccRow(Icons.Filled.History, "Previous logins", "Web sign-ins to this account", true) { previousLogins() }
                AccRow(Icons.Filled.Password, "Change password", "", !locked) { dialog = AccDialog.Password }
                AccRow(Icons.Filled.Token, "Login tokens", "Temporary credentials for tools and scripts", true) { dialog = AccDialog.Tokens }
                AccRow(Icons.Filled.Language, "Language", user.optString("lang").ifEmpty { "Browser default" }, true, last = true) { dialog = AccDialog.Language }
            }
            val canNew = Site.full(ctrl.userinfo) || (siteRights and Site.NONEWGROUPS) == 0L
            SectionCard(title = "Device groups") {
                val groups = session.meshes.values.map { it to Rights.mesh(ctrl.serverinfo, ctrl.userinfo, it.json) }
                    .filter { it.second != 0L }.sortedBy { it.first.name.lowercase() }
                if (groups.isEmpty()) Text("No device groups", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                groups.forEachIndexed { i, (m, r) ->
                    AccRow(Icons.Filled.Group, m.name, if (r == Rights.FULL) "Full administrator" else "Partial rights", true,
                        last = i == groups.size - 1 && !canNew, chevron = false) {}
                }
                if (canNew) AccRow(Icons.Filled.Add, "New device group", "", true, last = true) { dialog = AccDialog.NewGroup }
            }
        }
    }

    when (val d = dialog) {
        null -> {}
        AccDialog.RemoveOtp -> AlertDialog(onDismissRequest = { dialog = null },
            title = { Text("Remove the authenticator app?") },
            text = { Text("Two-step sign-in with the app will no longer be required. Backup codes and security keys are not affected.") },
            confirmButton = { TextButton({
                dialog = null
                once(ctrl, "otpauth-clear") { m -> msg(if (m.optBoolean("success")) "Authenticator app removed" else "Could not remove it", "") }
                ctrl.send("action" to "otpauth-clear")
            }) { Text("Remove", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } })
        is AccDialog.Message -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text(d.title) },
            text = { if (d.text.isNotEmpty()) Text(d.text) }, confirmButton = { TextButton({ dialog = null }) { Text("OK") } })
        is AccDialog.Authenticator -> AuthenticatorDialog(ctrl, d.secret, d.url, { dialog = null }) {
            msg("Authenticator app enabled", "Two-step sign-in is now on. Consider creating backup codes in case you lose the phone.")
        }
        is AccDialog.Codes -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Backup codes") },
            text = {
                Column {
                    if (d.codes.isEmpty()) Text("You have no backup codes.")
                    else {
                        Text("Each code can be used once instead of the authenticator app. Keep them somewhere safe.",
                            style = MaterialTheme.typography.bodySmall)
                        SelectionContainer {
                            Column(Modifier.padding(top = 10.dp)) {
                                d.codes.chunked(2).forEach { row ->
                                    Row { row.forEach { Text(it, Modifier.width(120.dp).padding(vertical = 2.dp), fontFamily = FontFamily.Monospace,
                                        style = MaterialTheme.typography.titleMedium) } }
                                }
                            }
                        }
                        TextButton({ copy(ctx, "Backup codes", d.codes.joinToString("\n")) }) { Text("Copy") }
                    }
                }
            },
            confirmButton = { TextButton({ dialog = null; backupCodes(1) }) { Text("Generate new codes") } },
            dismissButton = {
                Row {
                    if (d.codes.isNotEmpty()) TextButton({ dialog = null; backupCodes(2) }) { Text("Clear", color = MaterialTheme.colorScheme.error) }
                    TextButton({ dialog = null }) { Text("Close") }
                }
            })
        is AccDialog.Keys -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Security keys") },
            text = {
                Column {
                    if (d.keys.isEmpty()) Text("No security keys registered.")
                    d.keys.forEach { k ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(k.optString("name").ifEmpty { "Key" })
                                Text(when (k.optInt("type")) { 1 -> "YubiKey OTP"; 2 -> "WebAuthn / FIDO2"; else -> "Key" },
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            IconButton({
                                ctrl.send("action" to "otp-hkey-remove", "index" to k.optInt("i"))
                                dialog = AccDialog.Keys(d.keys - k)
                            }) { Icon(Icons.Filled.Delete, "Remove", tint = MaterialTheme.colorScheme.error) }
                        }
                    }
                    Text("Registering a new key needs a web browser: open your MeshCentral web interface.", Modifier.padding(top = 10.dp),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            },
            confirmButton = { TextButton({ dialog = null }) { Text("Close") } },
            dismissButton = { TextButton({
                runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(ctrl.server.url + "/"))) }
            }) { Text("Open web interface") } })
        is AccDialog.Logins -> AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Previous logins") },
            text = {
                Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState())) {
                    if (d.events.isEmpty()) Text("No logins recorded yet. The server records web sign-ins (not app sign-ins) for this list.")
                    d.events.forEach { e ->
                        val a = e.optJSONArray("a")?.let { arr -> (0 until arr.length()).map { arr.optString(it) } } ?: emptyList()
                        val what = when (e.optInt("m")) { 107 -> "Login"; 108 -> "Wrong second factor"; 109 -> "Locked account"; 110 -> "Invalid login"
                            else -> "Event ${e.optInt("m")}" }
                        Column(Modifier.padding(vertical = 6.dp)) {
                            Text("$what  ·  ${srvTime(e.opt("t"))}", style = MaterialTheme.typography.bodyMedium,
                                color = if (e.optInt("m") == 107) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.error)
                            Text(a.joinToString("  ·  ") + (e.optString("tn").takeIf { it.isNotEmpty() }?.let { "  (token: $it)" } ?: ""),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        HorizontalDivider()
                    }
                }
            },
            confirmButton = { TextButton({ dialog = null }) { Text("Close") } })
        AccDialog.Password -> PasswordDialog(app, ctrl, { dialog = null }) { t, m -> msg(t, m) }
        AccDialog.Tokens -> TokensDialog(ctrl, ctx, { dialog = null }) { u, p, e -> dialog = AccDialog.TokenCreated(u, p, e) }
        is AccDialog.TokenCreated -> AlertDialog(onDismissRequest = {}, title = { Text("Login token created") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Copy the password now. It is shown only once.", style = MaterialTheme.typography.bodySmall)
                    listOf("Username" to d.user, "Password" to d.pass).forEach { (label, v) ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                SelectionContainer { Text(v, fontFamily = FontFamily.Monospace) }
                            }
                            IconButton({ copy(ctx, label, v) }) { Icon(Icons.Filled.ContentCopy, "Copy $label") }
                        }
                    }
                    Text("Expires: " + (if (d.expire == null || d.expire == 0 || d.expire == 0L) "never" else srvTime(d.expire)),
                        style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton({ dialog = AccDialog.Tokens }) { Text("Done") } })
        AccDialog.Language -> {
            val langs = listOf("") + (ctrl.serverinfo.optJSONArray("languages")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList())
            AlertDialog(onDismissRequest = { dialog = null }, title = { Text("Language") },
                text = {
                    Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) {
                        Text("The language of the server's web pages and emails for this account.", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        langs.forEach { l ->
                            Text((if (user.optString("lang") == l) "✓ " else "    ") + l.ifEmpty { "Browser default" },
                                Modifier.fillMaxWidth().clickable { dialog = null; ctrl.send("action" to "changelang", "lang" to l) }.padding(vertical = 10.dp))
                        }
                    }
                },
                confirmButton = { TextButton({ dialog = null }) { Text("Close") } })
        }
        AccDialog.NewGroup -> TextDialog("New device group", "", "Create", { dialog = null }) { n ->
            dialog = null
            if (n.isNotBlank()) {
                ctrl.send("action" to "createmesh", "meshname" to n.trim(), "meshtype" to 2, "desc" to "")
                Handler(Looper.getMainLooper()).postDelayed({ session.load() }, 800)
            }
        }
    }
}

private fun has2fa(u: JSONObject) = u.optInt("otpsecret") != 0 || u.optBoolean("otpsecret") || u.optInt("otphkeys") > 0

@Composable
private fun AccRow(icon: ImageVector, title: String, sub: String, enabled: Boolean, last: Boolean = false, chevron: Boolean = true, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick).alpha(if (enabled) 1f else 0.45f)
        .padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
        Column(Modifier.weight(1f).padding(start = 16.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (sub.isNotEmpty()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (chevron) Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.outline)
    }
    if (!last) HorizontalDivider(Modifier.padding(start = 56.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}

@Composable
private fun AuthenticatorDialog(ctrl: ControlConnection, secret: String, url: String, onDismiss: () -> Unit, onEnabled: () -> Unit) {
    val ctx = LocalContext.current
    var code by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    var checking by remember { mutableStateOf(false) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Add authenticator app") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Add this account to Google Authenticator, Microsoft Authenticator, Aegis or any TOTP app, then enter the 6-digit code it shows.",
                    style = MaterialTheme.typography.bodyMedium)
                if (url.startsWith("otpauth://")) OutlinedButton({
                    try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
                    catch (e: Exception) { Toast.makeText(ctx, "No authenticator app found on this phone: enter the secret by hand.", Toast.LENGTH_LONG).show() }
                }, Modifier.fillMaxWidth()) { Text("Open in authenticator app") }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Secret", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        SelectionContainer { Text(secret.chunked(4).joinToString(" "), fontFamily = FontFamily.Monospace) }
                    }
                    IconButton({ copy(ctx, "Secret", secret) }) { Icon(Icons.Filled.ContentCopy, "Copy secret") }
                }
                OutlinedTextField(code, { code = it.filter { c -> c.isDigit() }.take(6) }, Modifier.fillMaxWidth(), label = { Text("6-digit code") },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword))
                if (status.isNotEmpty()) Text(status, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { TextButton({
            checking = true
            status = ""
            once(ctrl, "otpauth-setup", onTimeout = { checking = false; status = "No answer from the server." }) { m ->
                checking = false
                if (m.optBoolean("success")) { onDismiss(); onEnabled() }
                else { status = "Wrong code. Check the phone's time and try again."; code = "" }
            }
            ctrl.send("action" to "otpauth-setup", "secret" to secret, "token" to code)
        }, enabled = code.length == 6 && !checking) { Text("Enable") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}

@Composable
private fun PasswordDialog(app: McdApp, ctrl: ControlConnection, onDismiss: () -> Unit, onResult: (String, String) -> Unit) {
    var old by remember { mutableStateOf("") }
    var new1 by remember { mutableStateOf("") }
    var new2 by remember { mutableStateOf("") }
    val problem = when {
        new2.isNotEmpty() && new1 != new2 -> "The new passwords do not match."
        new1.isNotEmpty() && new1 == old -> "The new password must differ from the current one."
        else -> ""
    }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Change password") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(Triple("Current password", old) { v: String -> old = v }, Triple("New password", new1) { v: String -> new1 = v },
                    Triple("Repeat new password", new2) { v: String -> new2 = v }).forEach { (label, v, set) ->
                    OutlinedTextField(v, set, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = true,
                        visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
                }
                if (problem.isNotEmpty()) Text(problem, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { TextButton({
            val newPass = new1
            onDismiss()
            var watch: ((JSONObject) -> Unit)? = null
            val main = Handler(Looper.getMainLooper())
            watch = { m ->
                val id = m.optInt("msgid")
                if (m.optString("type") == "notify" && id in listOf(17, 18, 19, 20, 21)) {
                    ctrl.off("msg", watch!!)
                    if (id == 20) {
                        // keep the saved password current (the remembered one would fail at the next sign-in)
                        if (app.settings.remember) app.credentials.store(app.settings.server, app.settings.username, newPass)
                        ctrl.password = newPass                  // the remote desktop's web sign-in uses it
                        onResult("Password changed", "Use the new password the next time you sign in.")
                    } else onResult("Password not changed", PASSWORD_MSGS[id] ?: m.optString("value"))
                }
            }
            ctrl.on("msg", watch)
            main.postDelayed({ ctrl.off("msg", watch) }, 20_000)
            ctrl.send("action" to "changepassword", "oldpass" to old, "newpass" to newPass)
        }, enabled = old.isNotEmpty() && new1.isNotEmpty() && problem.isEmpty() && new2 == new1) { Text("Change password") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}

@Composable
private fun TokensDialog(ctrl: ControlConnection, ctx: Context, onDismiss: () -> Unit, onCreated: (String, String, Any?) -> Unit) {
    var tokens by remember { mutableStateOf<List<JSONObject>?>(null) }
    var creating by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var expiry by remember { mutableIntStateOf(0) }
    var expMenu by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<JSONObject?>(null) }
    DisposableEffect(Unit) {
        val cb: (JSONObject) -> Unit = { m ->
            val a = m.optJSONArray("loginTokens")
            tokens = if (a == null) emptyList() else (0 until a.length()).mapNotNull { a.optJSONObject(it) }
        }
        ctrl.on("loginTokens", cb)
        ctrl.send("action" to "loginTokens")
        onDispose { ctrl.off("loginTokens", cb) }
    }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(if (creating) "Create login token" else "Login tokens") },
        text = {
            Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (creating) {
                    OutlinedTextField(name, { name = it.take(100) }, Modifier.fillMaxWidth(), label = { Text("Token name") }, singleLine = true)
                    Box {
                        OutlinedButton({ expMenu = true }, Modifier.fillMaxWidth()) { Text("Expires: " + TOKEN_EXPIRY[expiry].first) }
                        DropdownMenu(expMenu, { expMenu = false }) {
                            TOKEN_EXPIRY.forEachIndexed { i, (label, _) -> DropdownMenuItem({ Text(label) }, onClick = { expiry = i; expMenu = false }) }
                        }
                    }
                } else {
                    Text("A login token is a temporary user name and password that can sign in to your account instead of your real credentials.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    when {
                        tokens == null -> CircularProgressIndicator(Modifier.size(24.dp))
                        tokens!!.isEmpty() -> Text("No login tokens.")
                    }
                    tokens?.forEach { t ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(t.optString("name"))
                                Text(t.optString("tokenUser") + "  ·  expires " + (if (t.optLong("expire") == 0L) "never" else srvTime(t.opt("expire"))),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            IconButton({ removing = t }) { Icon(Icons.Filled.Delete, "Remove", tint = MaterialTheme.colorScheme.error) }
                        }
                    }
                }
            }
        },
        confirmButton = {
            if (creating) TextButton({
                once(ctrl, "createLoginToken") { m ->
                    if (m.optString("tokenUser").isEmpty())
                        Toast.makeText(ctx, "Cannot create a login token: " + m.optString("result", "refused by the server"), Toast.LENGTH_LONG).show()
                    else { ctrl.send("action" to "loginTokens"); onCreated(m.optString("tokenUser"), m.optString("tokenPass"), m.opt("expire")) }
                }
                ctrl.send("action" to "createLoginToken", "name" to name.trim(), "expire" to TOKEN_EXPIRY[expiry].second)
            }, enabled = name.isNotBlank()) { Text("Create") }
            else TextButton({ creating = true }) { Text("Create") }
        },
        dismissButton = { TextButton({ if (creating) creating = false else onDismiss() }) { Text(if (creating) "Back" else "Close") } })
    removing?.let { t ->
        AlertDialog(onDismissRequest = { removing = null }, title = { Text("Remove login token ${t.optString("name")}?") },
            text = { Text("Anything using it will no longer be able to sign in.") },
            confirmButton = { TextButton({
                removing = null
                ctrl.send("action" to "loginTokens", "remove" to JSONArray(listOf(t.optString("tokenUser"))))
            }) { Text("Remove", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ removing = null }) { Text("Cancel") } })
    }
}
