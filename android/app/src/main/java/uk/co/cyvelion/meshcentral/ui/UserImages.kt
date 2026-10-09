// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.util.Base64
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import okhttp3.Request
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.McdApp
import uk.co.cyvelion.meshcentral.data.Session
import uk.co.cyvelion.meshcentral.net.USER_AGENT
import uk.co.cyvelion.meshcentral.net.bytesAtMost
import uk.co.cyvelion.meshcentral.net.http
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest

/**
 * Account pictures (web UI account image; desktop app account_panel / user_panel). The server serves them only to a
 * WEB session (GET userimage.ashx[?id=<name>]), so they come through the app's private web sign-in, or, for accounts
 * with two-factor sign-in where that is refused, the remote desktop's web session when there is one. Every picture
 * is cached on the phone (app cache folder, per server and user) and shown at once from there; it is fetched again
 * once per sign-in and whenever the server reports a new picture (event accountchange with accountImageChange).
 * A user's flags bit 1 says whether they have a picture at all.
 */
object UserImages {
    private val mem = mutableStateMapOf<String, ImageBitmap>()          // key -> picture
    private val tried = HashSet<String>()                              // fetched (or failed) during this sign-in
    private var web: ServerWebSession? = null
    private var webFor: Session? = null
    private var listening: Session? = null
    private val main = Handler(Looper.getMainLooper())

    private fun key(session: Session, userId: String) = session.ctrl.server.url + "|" + userId
    private fun file(k: String): File {
        val d = File(McdApp.instance.cacheDir, "avatars").apply { mkdirs() }
        val h = MessageDigest.getInstance("SHA-256").digest(k.toByteArray()).joinToString("") { "%02x".format(it) }.take(32)
        return File(d, h)
    }

    /** The picture of a user for a screen: null = none or not loaded yet (loading starts in an effect, not while drawing). */
    @androidx.compose.runtime.Composable
    fun image(session: Session, userId: String, flags: Int): ImageBitmap? {
        val k = key(session, userId)
        androidx.compose.runtime.LaunchedEffect(k, flags) { ensure(session, userId, flags) }
        return if (flags and 1 == 0) null else mem[k]
    }

    /** Load from the phone's cache, then from the server once per sign-in. */
    private fun ensure(session: Session, userId: String, flags: Int) {
        if (userId.isEmpty()) return
        listen(session)
        val k = key(session, userId)
        if (flags and 1 == 0) {                                         // no picture on the server
            mem.remove(k); file(k).delete()
            return
        }
        if (mem[k] == null) file(k).takeIf { it.exists() }?.readBytes()?.let { decode(it) }?.let { mem[k] = it }
        if (tried.add(k)) fetch(session, userId, k)
    }

    private fun listen(session: Session) {
        if (listening === session) return
        listening = session
        tried.clear()
        session.ctrl.on("event") { m ->
            val ev = m.optJSONObject("event") ?: return@on
            if (ev.optString("action") == "accountchange" && ev.optInt("accountImageChange") == 1) {
                val uid = ev.optString("userid").ifEmpty { ev.optJSONObject("account")?.optString("_id") ?: "" }
                val k = key(session, uid)
                tried.remove(k)
                val f = ev.optJSONObject("account")?.optInt("flags") ?: 1
                if (f and 1 == 0) { mem.remove(k); file(k).delete() } else { tried.add(k); fetch(session, uid, k) }
            }
        }
    }

    private fun fetch(session: Session, userId: String, k: String) {
        val ctrl = session.ctrl
        if (webFor !== session) { web = ServerWebSession(ctrl); webFor = session }
        val own = userId == ctrl.userinfo?.optString("_id")
        val path = "/userimage.ashx" + (if (own) "" else "?id=" + java.net.URLEncoder.encode(userId.substringAfterLast('/'), "UTF-8").replace("+", "%20"))
        val out = object : ByteArrayOutputStream() {           // at most 1 MB, like the decoder accepts
            override fun write(b: ByteArray, off: Int, len: Int) {
                if (size() + len > 1_000_000) throw java.io.IOException("picture too large")
                super.write(b, off, len)
            }
        }
        web!!.fetch(path, out, { _, _ -> }) { err ->
            if (err == null) store(k, out.toByteArray())
            else Thread {
                // two-factor accounts: the remote desktop page's web session, if the user opened one
                val c = android.webkit.CookieManager.getInstance().getCookie(ctrl.server.url)
                val bytes = if (c.isNullOrEmpty()) null else try {
                    http.newBuilder().callTimeout(30, java.util.concurrent.TimeUnit.SECONDS).build()
                        .newCall(Request.Builder().url(ctrl.server.url + path).header("Cookie", c).header("User-Agent", USER_AGENT).build())
                        .execute().use { r -> if (r.isSuccessful) r.body.bytesAtMost(1_000_000) else null }
                } catch (e: Exception) { null }
                if (bytes != null) main.post { store(k, bytes) }
            }.start()
        }
    }

    private fun store(k: String, bytes: ByteArray) {
        val img = decode(bytes) ?: return
        mem[k] = img
        try { file(k).writeBytes(bytes) } catch (e: Exception) { }
    }

    /** PNG or JPEG of at most 1 MB and 4096 px (like ui.load_image), else null. */
    private fun decode(bytes: ByteArray): ImageBitmap? {
        if (bytes.size > 1_000_000) return null
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
        if (o.outWidth <= 0 || o.outWidth > 4096 || o.outHeight > 4096 || o.outMimeType !in listOf("image/png", "image/jpeg")) return null
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
    }

    /** A picked photo as the server wants it: square (centre crop), 256 px, JPEG, as a data: URL (< 600000 chars). */
    fun toDataUrl(src: Bitmap): String {
        val s = minOf(src.width, src.height)
        val sq = Bitmap.createBitmap(src, (src.width - s) / 2, (src.height - s) / 2, s, s)
        val small = Bitmap.createScaledBitmap(sq, 256, 256, true)
        val out = ByteArrayOutputStream()
        small.compress(Bitmap.CompressFormat.JPEG, 88, out)
        return "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }

    /** Our own new picture (or null = removed): shown and cached at once, without waiting for the server. */
    fun setOwn(session: Session, dataUrl: String?) {
        val uid = session.ctrl.userinfo?.optString("_id") ?: return
        val k = key(session, uid)
        tried.add(k)
        if (dataUrl == null) { mem.remove(k); file(k).delete(); return }
        store(k, Base64.decode(dataUrl.substringAfter(","), Base64.DEFAULT))
    }

    /** Sign-out: forget the web session (never reused by the next account); the disk cache stays (per server + user). */
    fun signOut() { web = null; webFor = null; listening = null; tried.clear(); mem.clear() }

    internal fun flags(user: JSONObject?) = user?.optInt("flags") ?: 0
}
