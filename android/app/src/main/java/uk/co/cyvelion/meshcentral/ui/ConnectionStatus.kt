// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Session

/**
 * Over every screen: a small "Reconnecting" pill while the connection to the server is re-established, and the
 * "Sign in again" dialog only when the server refused the automatic sign-in (e.g. a new two-factor code is needed).
 */
@Composable
fun BoxScope.ConnectionStatus(app: McdApp, session: Session) {
    AnimatedVisibility(session.reconnecting, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 88.dp),
        enter = slideInVertically { it }, exit = slideOutVertically { it }) {
        Row(Modifier.background(Color(0xEE2B2F36), RoundedCornerShape(20.dp)).padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CircularProgressIndicator(Modifier.size(16.dp), color = Color.White, strokeWidth = 2.dp)
            Text("Connection lost. Reconnecting…", color = Color.White, style = MaterialTheme.typography.bodyMedium)
        }
    }
    session.lost?.let { r ->
        AlertDialog(onDismissRequest = {}, title = { Text("Signed out") },
            text = {
                Text(when {
                    r.msg == "tokenrequired" || r.cause == "tokenrequired" ->
                        "The connection to the server was lost and signing in again needs a new two-factor code."
                    r.cause == "noauth" -> "The connection to the server was lost and the server did not accept the sign-in again."
                    else -> "The connection to the server was lost" + (r.msg?.let { ": $it" } ?: ".")
                })
            },
            confirmButton = { TextButton({ app.signOut() }) { Text("Sign in again") } })
    }
}
