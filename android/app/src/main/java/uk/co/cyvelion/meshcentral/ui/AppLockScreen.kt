// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import uk.co.cyvelion.meshcentral.R
import uk.co.cyvelion.meshcentral.data.AppLock

/**
 * Covers the whole app while it is locked (AppLock); the system unlock prompt opens by itself. It is its own
 * full-screen window, newer than any dialog, sheet or menu that was open when the app went to the background, so
 * those stay underneath and cannot be read or tapped; it also takes the window focus, so keys from a hardware or soft
 * keyboard cannot reach a remote terminal or desktop behind it. Back leaves the app; it never gets past the lock.
 */
@Composable
fun AppLockScreen(activity: FragmentActivity) {
    if (!AppLock.locked) return
    var error by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        (activity.getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager)
            .hideSoftInputFromWindow(activity.window.decorView.windowToken, 0)
        AppLock.unlock(activity) { error = it }
    }
    androidx.compose.ui.window.Dialog(onDismissRequest = { activity.moveTaskToBack(true) },
        properties = androidx.compose.ui.window.DialogProperties(dismissOnBackPress = true, dismissOnClickOutside = false,
            usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
        .clickable(remember { MutableInteractionSource() }, null) { }       // nothing behind is reachable
        .padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Image(painterResource(R.mipmap.ic_launcher), null, Modifier.size(72.dp))
        Spacer(Modifier.height(16.dp))
        Text("MeshCentral Desktop is locked", style = MaterialTheme.typography.titleLarge)
        Text("Unlock with your fingerprint, face or screen lock.", Modifier.padding(top = 6.dp),
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        Spacer(Modifier.height(24.dp))
        Button({ error = ""; AppLock.unlock(activity) { error = it } }) {
            Icon(Icons.Filled.Fingerprint, null, Modifier.padding(end = 8.dp)); Text("Unlock")
        }
        if (error.isNotEmpty()) Text(error, Modifier.padding(top = 12.dp), color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
    }
    }
}
