// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Description
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import uk.co.cyvelion.meshcentral.BuildConfig
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.MainActivity
import uk.co.cyvelion.meshcentral.data.AppLock

private const val REPO = "https://github.com/d-maggipinto/meshcentral-desktop"

/** The app's own settings (security, connection, notifications) and About, a page like the other drawer entries. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(app: McdApp, onBack: () -> Unit) {
    val s = app.settings
    val ctx = LocalContext.current
    var connect by remember { mutableStateOf(s.getBool("notify_connect", false)) }
    var disconnect by remember { mutableStateOf(s.getBool("notify_disconnect", false)) }
    var group by remember { mutableStateOf(s.getBool("notify_groupname", true)) }
    var keep by remember { mutableStateOf(s.getBool("keep_alive", true)) }
    var lock by remember { mutableStateOf(AppLock.enabled) }
    var lockAfter by remember { mutableStateOf(AppLock.after) }
    var lockMsg by remember { mutableStateOf("") }
    val activity = androidx.activity.compose.LocalActivity.current as? androidx.fragment.app.FragmentActivity
    fun open(url: String) {
        try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
        catch (e: Exception) { android.widget.Toast.makeText(ctx, "No browser found on this phone.", android.widget.Toast.LENGTH_SHORT).show() }
    }

    Scaffold(topBar = {
        TopAppBar(title = { Text("Settings") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            SectionCard(title = "Security") {
                // switching the lock on or off needs an unlock first, so nobody else can change it
                SwitchRow("Lock the app", "Asks for your fingerprint, face or screen lock when the app opens or comes back. " +
                    "Open remote sessions keep running.", lock, last = !lock && lockMsg.isEmpty()) { on ->
                    lockMsg = ""
                    when {
                        activity == null -> {}
                        on && !AppLock.available(activity) -> lockMsg = "Set up a screen lock or fingerprint in the phone's settings first."
                        else -> AppLock.prompt(activity, if (on) "Turn on the app lock" else "Turn off the app lock", {
                            AppLock.setEnabled(on); lock = on; (activity as? MainActivity)?.privacy()
                        }) { lockMsg = it }
                    }
                }
                if (lock) Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
                    Text("Lock again after leaving the app", style = MaterialTheme.typography.bodyMedium)
                    Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(0 to "10 s", 60 to "1 min", 300 to "5 min").forEach { (v, l) ->
                            FilterChip(lockAfter == v, { lockAfter = v; AppLock.setAfter(v) }, { Text(l) })
                        }
                    }
                }
                if (lockMsg.isNotEmpty()) Text(lockMsg, Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
            SectionCard(title = "Connection") {
                SwitchRow("Stay connected in the background", "Keeps the server connection, remote sessions and notifications " +
                    "going while you use other apps (shows a quiet notification). The app reconnects by itself after network " +
                    "drops either way.", keep, last = true) { keep = it; app.setKeepAlive(it) }
            }
            SectionCard(title = "Notifications") {
                Text("Server messages and broadcasts are always shown.", Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp),
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                SwitchRow("A device connects", "", connect) { connect = it; s.putBool("notify_connect", it) }
                SwitchRow("A device disconnects", "", disconnect) { disconnect = it; s.putBool("notify_disconnect", it) }
                SwitchRow("Show the group name", "", group, last = true) { group = it; s.putBool("notify_groupname", it) }
            }
            SectionCard(title = "About") {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(uk.co.cyvelion.meshcentral.R.mipmap.ic_launcher),
                        null, Modifier.size(52.dp))
                    Column(Modifier.padding(start = 16.dp)) {
                        Text("MeshCentral Desktop", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text("Version ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})" + if (BuildConfig.DEBUG) " preview" else "",
                            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                HorizontalDivider(Modifier.padding(start = 16.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Copyright 2026 CYVELION LTD", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                    Text("Author: Denis Maggipinto", style = MaterialTheme.typography.bodyMedium)
                    Text("Licensed under the Apache License, Version 2.0. An independent, unofficial client for MeshCentral, " +
                        "not affiliated with or endorsed by the MeshCentral project. Developed with the assistance of Claude Code.",
                        Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                HorizontalDivider(Modifier.padding(start = 16.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
                LinkRow(Icons.Filled.Code, "Source code", "github.com/d-maggipinto/meshcentral-desktop") { open(REPO) }
                LinkRow(Icons.Filled.Description, "Licence and notices", "Apache-2.0, MeshCentral, xterm.js", last = true) { open("$REPO/blob/main/NOTICE") }
            }
        }
    }
}

@Composable
private fun SwitchRow(title: String, sub: String, on: Boolean, last: Boolean = false, set: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { set(!on) }.padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 12.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (sub.isNotEmpty()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(on, set)
    }
    if (!last) HorizontalDivider(Modifier.padding(start = 16.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}

@Composable
private fun LinkRow(icon: ImageVector, title: String, sub: String, last: Boolean = false, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
        Column(Modifier.weight(1f).padding(start = 16.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.outline)
    }
    if (!last) HorizontalDivider(Modifier.padding(start = 56.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
}
