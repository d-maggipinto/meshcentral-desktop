// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.data

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.MainActivity
import uk.co.cyvelion.meshcentral.R

/**
 * Android notifications for what the desktop app shows as cards (mainwindow.show_notification): user broadcasts,
 * server notices and, if switched on, devices connecting / disconnecting. Delivered while the app is running.
 */
class Notifier(private val ctx: Context, private val settings: Settings) {
    private var nextId = 1000

    init {
        run {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CH_MESSAGES, "Messages", NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Broadcasts and notices from the MeshCentral server" })
            nm.createNotificationChannel(NotificationChannel(CH_DEVICES, "Device connections", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "A device connected or disconnected (switch on in Settings)" })
        }
    }

    /** Listen on a session; returns the function that stops listening. */
    fun attach(session: Session): () -> Unit {
        val ctrl = session.ctrl
        val onMsg: (JSONObject) -> Unit = { m ->
            if (m.optString("type") == "notify")
                message(m.optString("title"), m.optString("value"), m.optString("tag"), m.optInt("msgid"),
                    fromUser = m.has("userid") || m.has("username"))
        }
        val onEvent: (JSONObject) -> Unit = { m ->
            val ev = m.optJSONObject("event") ?: JSONObject()
            when (ev.optString("action")) {
                "notify" -> message(ev.optString("title"), ev.optString("value"), ev.optString("tag"), m.optInt("msgid"), false)
                "nodeconnect" -> connection(session, ev)
            }
        }
        ctrl.on("msg", onMsg)
        ctrl.on("event", onEvent)
        return { ctrl.off("msg", onMsg); ctrl.off("event", onEvent) }
    }

    private fun message(title: String, text: String, tag: String, msgid: Int, fromUser: Boolean) {
        val body = text.ifEmpty { MSGIDS[msgid] ?: "" }
        if (body.isEmpty()) return
        val t = title.split(Regex("\\s+")).joinToString(" ").trim().take(80)
        // a user chooses the title: always say who sent it, so nobody can pose as a server notice
        val head = when {
            tag == "broadcast" && t.isNotEmpty() -> "Broadcast from $t"
            fromUser -> "Message from ${t.ifEmpty { "a user" }}"
            else -> t.ifEmpty { "MeshCentral" }
        }
        post(CH_MESSAGES, head, body)
    }

    private fun connection(session: Session, ev: JSONObject) {
        if (!ev.has("conn")) return
        val node = session.node(ev.optString("nodeid")) ?: return
        val now = ev.optInt("conn") and 1 != 0
        if (node.online == now || !settings.getBool(if (now) "notify_connect" else "notify_disconnect", false)) return
        var name = node.name
        if (settings.getBool("notify_groupname", true)) session.meshes[node.meshId]?.name?.let { name += " ($it)" }
        post(CH_DEVICES, name, if (now) "Device connected" else "Device disconnected")
    }

    private fun post(channel: String, title: String, text: String) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val open = PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(ctx, channel)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .apply {
                // with the app lock on, the phone's lock screen shows only that something arrived
                if (AppLock.enabled) setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(
                    NotificationCompat.Builder(ctx, channel).setSmallIcon(R.drawable.ic_notify)
                        .setContentTitle("MeshCentral").setContentText("New notification").build())
            }
            .build()
        try { NotificationManagerCompat.from(ctx).notify(nextId++, n) } catch (e: SecurityException) { }
    }

    companion object {
        const val CH_MESSAGES = "messages"
        const val CH_DEVICES = "devices"
        private val MSGIDS = mapOf(1 to "Permission denied", 14 to "Email sent.", 10 to "Account limit reached.")
    }
}
