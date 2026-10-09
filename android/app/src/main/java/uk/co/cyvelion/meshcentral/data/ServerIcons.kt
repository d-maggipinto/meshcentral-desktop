// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.data

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import okhttp3.Request
import uk.co.cyvelion.meshcentral.net.USER_AGENT
import uk.co.cyvelion.meshcentral.net.bytesAtMost
import uk.co.cyvelion.meshcentral.net.http

/**
 * The device-type icons of the signed-in server (servericons.py): the web UI's sprite /images/icons64.png, eight
 * 64 x 64 cells for node.icon 1..8 (desktop, laptop, phone, server, storage, network device, embedded board,
 * virtual machine). Public, no sign-in needed; a server with its own icon set shows its own icons, like the web UI
 * and the desktop app. Until it loads (or if it cannot) the app draws built-in icons of the same types.
 */
object ServerIcons {
    var cells by mutableStateOf<List<ImageBitmap>>(emptyList())
        private set
    private var loadedFor: String? = null

    fun load(serverUrl: String) {
        if (loadedFor == serverUrl) return
        loadedFor = serverUrl
        cells = emptyList()
        val main = Handler(Looper.getMainLooper())
        Thread {
            val out = try {
                http.newBuilder().callTimeout(30, java.util.concurrent.TimeUnit.SECONDS).build().newCall(Request.Builder().url("$serverUrl/images/icons64.png").header("User-Agent", USER_AGENT).build())
                    .execute().use { r ->
                        val bytes = if (r.isSuccessful) r.body.bytesAtMost(1_000_000) else null
                        // a PNG of at most 1 MB that is 8 square cells side by side
                        if (bytes == null || bytes.size > 1_000_000 || bytes.size < 8 ||
                            bytes[1] != 'P'.code.toByte() || bytes[2] != 'N'.code.toByte()) null
                        else BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    }?.let { b -> slice(b) }
            } catch (e: Exception) { null }
            main.post { if (loadedFor == serverUrl && out != null) cells = out }
        }.start()
    }

    private fun slice(b: Bitmap): List<ImageBitmap>? {
        val h = b.height
        if (h < 8 || h > 512 || b.width < h * 8) return null
        return (0 until 8).map { Bitmap.createBitmap(b, it * h, 0, h, h).asImageBitmap() }
    }

    /** The server's icon for node.icon (1..8), or null. */
    fun of(icon: Int): ImageBitmap? = cells.getOrNull(icon - 1)

    fun clear() { loadedFor = null; cells = emptyList() }
}
