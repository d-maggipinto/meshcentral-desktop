// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.data

import android.content.Context
import android.os.SystemClock
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

/**
 * App lock (Settings): the app asks for the phone's fingerprint, face unlock or screen lock (PIN, pattern,
 * password) when it starts and when it comes back after being in the background for longer than the chosen time.
 * The lock is drawn OVER the app, so open sessions (remote desktop, terminal, file transfers) keep running behind
 * it. Settings keys: app_lock (bool), app_lock_after (seconds in the background: 0, 60, 300).
 */
object AppLock {
    var locked by mutableStateOf(false)
        private set
    private var backgroundSince = 0L
    private lateinit var settings: Settings

    private const val AUTH = BIOMETRIC_WEAK or DEVICE_CREDENTIAL

    val enabled get() = settings.getBool("app_lock", false)
    val after get() = settings.getString("app_lock_after").toIntOrNull() ?: 0

    fun init(s: Settings) { settings = s; locked = enabled }

    /** Whether this phone has a screen lock or biometrics set up (otherwise the lock cannot be switched on). */
    fun available(ctx: Context) = BiometricManager.from(ctx).canAuthenticate(AUTH) == BiometricManager.BIOMETRIC_SUCCESS

    fun onBackground() { backgroundSince = SystemClock.elapsedRealtime() }

    fun onForeground() {
        // the shortest choice is 10 s (shown as such): the app's own system screens (photo / file picker, share
        // sheet, the screen-lock prompt) put it in the background for a moment and must not lock it each time
        val limit = maxOf(after, 10) * 1000L
        if (enabled && !locked && backgroundSince > 0 && SystemClock.elapsedRealtime() - backgroundSince >= limit) locked = true
        backgroundSince = 0
    }

    /** The system unlock prompt; ok() after a successful unlock. */
    fun prompt(activity: FragmentActivity, title: String, ok: () -> Unit, failed: (String) -> Unit = {}) {
        val p = BiometricPrompt(activity, ContextCompat.getMainExecutor(activity), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = ok()
            override fun onAuthenticationError(code: Int, msg: CharSequence) = failed(msg.toString())
        })
        p.authenticate(BiometricPrompt.PromptInfo.Builder()
            .setTitle(title)
            .setSubtitle("Use your fingerprint, face or screen lock")
            .setAllowedAuthenticators(AUTH)
            .build())
    }

    fun unlock(activity: FragmentActivity, failed: (String) -> Unit = {}) =
        prompt(activity, "Unlock MeshCentral Desktop", { locked = false }, failed)

    fun setEnabled(on: Boolean) { settings.putBool("app_lock", on); if (!on) locked = false }
    fun setAfter(seconds: Int) = settings.putString("app_lock_after", seconds.toString())
}
