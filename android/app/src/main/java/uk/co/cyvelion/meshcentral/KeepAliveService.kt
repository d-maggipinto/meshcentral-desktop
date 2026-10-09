// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * "Stay connected in the background" (Settings, on by default): while signed in, a foreground service with a quiet
 * notification keeps the app's process running, so Android does not freeze it in the background and the server
 * connection, remote desktop, terminal and file sessions and notifications keep going. Stopped on sign-out.
 */
class KeepAliveService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Connection", NotificationManager.IMPORTANCE_MIN)
            .apply { description = "Shown while the app stays connected in the background (Settings)"; setShowBadge(false) })
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val host = McdApp.instance.session?.ctrl?.server?.host ?: ""
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle("Connected to $host")
            .setContentText("Stays connected in the background. Switch this off in Settings.")
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build()
        ServiceCompat.startForeground(this, ID, n,
            if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0)
        return START_NOT_STICKY            // after the process is gone there is no session to keep
    }

    companion object {
        private const val CHANNEL = "connection"
        private const val ID = 7
        fun start(ctx: Context) {
            try { ContextCompat.startForegroundService(ctx, Intent(ctx, KeepAliveService::class.java)) } catch (e: Exception) { }
        }
        fun stop(ctx: Context) { ctx.stopService(Intent(ctx, KeepAliveService::class.java)) }
    }
}
