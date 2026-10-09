// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import uk.co.cyvelion.meshcentral.BuildConfig
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.R
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.ControlConnection

@Composable
fun LoginScreen(app: McdApp) {
    val s = app.settings
    var server by rememberSaveable { mutableStateOf(s.server) }
    var user by rememberSaveable { mutableStateOf(s.username) }
    var password by rememberSaveable { mutableStateOf(
        if (s.remember && s.server.isNotEmpty()) app.credentials.load(s.server, s.username) ?: "" else "") }
    var token by rememberSaveable { mutableStateOf("") }
    var remember by rememberSaveable { mutableStateOf(s.remember) }
    var showPw by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("") }
    var needToken by rememberSaveable { mutableStateOf(false) }
    val tokenFocus = remember { FocusRequester() }

    fun signIn() {
        val conn = try {
            ControlConnection(server, user.trim(), password, token.trim().ifEmpty { null })
        } catch (e: IllegalArgumentException) {
            status = e.message ?: "Invalid server address"
            return
        }
        busy = true
        status = "Connecting…"
        val main = Handler(Looper.getMainLooper())
        var done = false
        val timeout = Runnable {
            if (!done) {
                done = true
                busy = false
                status = "No response from server. Check the address."
                conn.close()
            }
        }
        // signed in once the server sends our account (userinfo)
        conn.on("userinfo") {
            if (done) return@on
            done = true
            main.removeCallbacks(timeout)
            s.server = server.trim()
            s.username = user.trim()
            s.remember = remember
            if (remember) app.credentials.store(s.server, s.username, password) else app.credentials.clear(s.server, s.username)
            val session = Session(conn)
            session.load()
            busy = false
            status = ""
            token = ""
            app.startSession(session)
        }
        conn.onOpen = { status = "Authenticating…"; main.postDelayed(timeout, 8000) }
        conn.onClose = { r ->
            if (!done) {
                done = true
                main.removeCallbacks(timeout)
                busy = false
                status = when {
                    r?.msg == "tokenrequired" -> { needToken = true; "Two-factor code required. Enter your code and sign in again." }
                    r?.cause == "noauth" -> "Invalid username, password or two-factor code."
                    r?.cause == "error" -> "Cannot reach server: ${r.msg ?: "connection failed"}"
                    else -> "Sign-in failed. Check your details and try again."
                }
            }
        }
        // the server sends its warnings and trace sources only once, right after sign-in (My Server shows them)
        ServerSignInInfo.attach(conn)
        conn.connect()
    }

    val canSignIn = !busy && server.isNotBlank() && user.isNotBlank() && password.isNotEmpty()
    val done = KeyboardActions(onDone = { if (canSignIn) signIn() })

    LaunchedEffect(needToken) { if (needToken) runCatching { tokenFocus.requestFocus() } }

    Scaffold { pad ->
        Column(
            Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Spacer(Modifier.height(24.dp))
            Image(painterResource(R.mipmap.ic_launcher), null, Modifier.size(72.dp))
            Text("MeshCentral Desktop", style = MaterialTheme.typography.headlineSmall)
            Text("v" + BuildConfig.VERSION_NAME, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            val field = Modifier.fillMaxWidth().widthIn(max = 480.dp)
            OutlinedTextField(server, { server = it }, field, label = { Text("Server") },
                placeholder = { Text("https://mesh.example.com") }, singleLine = true, enabled = !busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next))
            OutlinedTextField(user, { user = it }, field, label = { Text("Username") }, singleLine = true,
                enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next))
            OutlinedTextField(password, { password = it }, field, label = { Text("Password") }, singleLine = true,
                enabled = !busy,
                visualTransformation = if (showPw) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = done,
                trailingIcon = {
                    IconButton({ showPw = !showPw }) {
                        Icon(if (showPw) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                            if (showPw) "Hide password" else "Show password")
                    }
                })
            OutlinedTextField(token, { token = it.filter { c -> c.isLetterOrDigit() } }, field.focusRequester(tokenFocus),
                label = { Text("Two-factor code (if enabled)") }, singleLine = true, enabled = !busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                keyboardActions = done)
            Row(field, verticalAlignment = Alignment.CenterVertically) {
                Checkbox(remember, { remember = it }, enabled = !busy)
                Text("Remember password on this device")
            }
            Button({ signIn() }, field.height(48.dp), enabled = canSignIn) {
                if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Text("Sign in")
            }
            if (status.isNotEmpty()) Text(status, color = if (busy) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.error)
        }
    }
}
