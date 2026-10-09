// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import uk.co.cyvelion.meshcentral.data.CredentialStore
import uk.co.cyvelion.meshcentral.data.Notifier
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.data.Settings

class McdApp : Application() {
    lateinit var settings: Settings
        private set
    lateinit var credentials: CredentialStore
        private set

    lateinit var notifier: Notifier
        private set
    private var detachNotifier: (() -> Unit)? = null

    /** The signed-in session, or null on the sign-in screen. */
    var session by mutableStateOf<Session?>(null)
        private set

    fun startSession(s: Session) {
        detachNotifier?.invoke()
        detachNotifier = notifier.attach(s)
        session = s
        uk.co.cyvelion.meshcentral.data.ServerIcons.load(s.ctrl.server.url)
        if (settings.getBool("keep_alive", true)) KeepAliveService.start(this)
    }

    /** Settings switch "Stay connected in the background". */
    fun setKeepAlive(on: Boolean) {
        settings.putBool("keep_alive", on)
        if (on && session != null) KeepAliveService.start(this) else KeepAliveService.stop(this)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        if (BuildConfig.DEBUG) android.webkit.WebView.setWebContentsDebuggingEnabled(true)
        settings = Settings(this)
        credentials = CredentialStore(this)
        notifier = Notifier(this, settings)
        uk.co.cyvelion.meshcentral.data.AppLock.init(settings)
        // reconnect at once when the network comes back or the app returns to the screen (instead of waiting for the
        // next retry): ControlConnection retries by itself, this only shortens the wait
        getSystemService(android.net.ConnectivityManager::class.java).registerDefaultNetworkCallback(
            object : android.net.ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: android.net.Network) { main.post { session?.ctrl?.reconnectNow() } }
            })
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityResumed(a: android.app.Activity) { session?.ctrl?.reconnectNow() }
            override fun onActivityCreated(a: android.app.Activity, b: android.os.Bundle?) {}
            override fun onActivityStarted(a: android.app.Activity) { uk.co.cyvelion.meshcentral.data.AppLock.onForeground() }
            override fun onActivityPaused(a: android.app.Activity) {}
            override fun onActivityStopped(a: android.app.Activity) {
                if (!a.isChangingConfigurations) uk.co.cyvelion.meshcentral.data.AppLock.onBackground()
            }
            override fun onActivitySaveInstanceState(a: android.app.Activity, b: android.os.Bundle) {}
            override fun onActivityDestroyed(a: android.app.Activity) {}
        })
    }
    private val main = android.os.Handler(android.os.Looper.getMainLooper())

    fun signOut() {
        KeepAliveService.stop(this)
        detachNotifier?.invoke()
        detachNotifier = null
        session?.close()
        session = null
        uk.co.cyvelion.meshcentral.data.ServerIcons.clear()
        uk.co.cyvelion.meshcentral.ui.UserImages.signOut()
        // the remote desktop's web sign-in must not carry over to the next account
        android.webkit.CookieManager.getInstance().removeAllCookies(null)
        android.webkit.WebStorage.getInstance().deleteAllData()
    }

    companion object {
        lateinit var instance: McdApp
            private set
    }
}
