// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.os.Handler
import android.os.Looper
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.FormBody
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody
import okio.BufferedSink
import org.json.JSONArray
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.net.ControlConnection
import uk.co.cyvelion.meshcentral.net.USER_AGENT
import uk.co.cyvelion.meshcentral.net.http
import java.io.InputStream
import java.io.OutputStream
import java.text.DateFormat
import java.time.Instant
import java.util.Date
import java.util.WeakHashMap

/**
 * A private web sign-in (client.WebSession): some server pages need a signed-in WEB session, not the control channel
 * (downloadfile.ashx, backup.zip). Its own cookie jar, in memory only, one per screen: never shared between accounts.
 * Accounts with two-factor sign-in cannot get one (the code was used up by the app's own sign-in); callers fall back
 * where they can.
 */
internal class ServerWebSession(private val ctrl: ControlConnection) {
    private val cookies = ArrayList<Cookie>()
    private val jar = object : CookieJar {
        override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
            synchronized(this@ServerWebSession) {
                cookies.forEach { c -> this@ServerWebSession.cookies.removeAll { it.name == c.name }; this@ServerWebSession.cookies.add(c) }
            }
        }
        override fun loadForRequest(url: HttpUrl): List<Cookie> =
            synchronized(this@ServerWebSession) { cookies.filter { it.matches(url) } }
    }
    private val client = http.newBuilder().cookieJar(jar).followRedirects(false).build()
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var loggedIn = false

    private fun login() {
        if (loggedIn) return
        val form = FormBody.Builder().add("action", "login").add("username", ctrl.username).add("password", ctrl.password).build()
        client.newCall(Request.Builder().url(ctrl.server.url + "/login").header("User-Agent", USER_AGENT).post(form).build())
            .execute().close()                                // a redirect is the normal answer
        if (synchronized(this) { cookies.none { it.name.startsWith("xid") } })
            throw IllegalStateException("The server did not accept the web sign-in (accounts with two-factor sign-in need the web interface for this).")
        loggedIn = true
    }

    /** GET <server><path> into out (closed afterwards); progress(done, total) and done(error or null) on the main thread. */
    fun fetch(path: String, out: OutputStream, progress: (Long, Long) -> Unit, done: (String?) -> Unit) {
        Thread {
            val err = try {
                login()
                client.newBuilder().followRedirects(true).build()
                    .newCall(Request.Builder().url(ctrl.server.url + path).header("User-Agent", USER_AGENT).build()).execute().use { r ->
                        if (!r.isSuccessful) throw IllegalStateException("HTTP ${r.code}")
                        val body = r.body
                        val total = body.contentLength()
                        body.byteStream().use { input ->
                            val buf = ByteArray(65536)
                            var got = 0L
                            var last = 0L
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                out.write(buf, 0, n)
                                got += n
                                if (got - last > 131072) { last = got; val g = got; main.post { progress(g, total) } }
                            }
                        }
                    }
                null
            } catch (e: Exception) {
                loggedIn = false
                e.message ?: e.javaClass.simpleName
            } finally {
                runCatching { out.close() }
            }
            main.post { done(err) }
        }.start()
    }

    /** Multipart POST of one file with form fields and the control channel's auth cookie as "auth" (uploadfile.ashx). */
    fun postFile(path: String, fields: Map<String, String>, fileField: String, name: String, size: Long, input: InputStream,
                 progress: (Long, Long) -> Unit, done: (String?) -> Unit) {
        ctrl.authCookie { cookie, _ ->
            Thread {
                val err = try {
                    runCatching { login() }                  // the "auth" field may suffice
                    val file = object : RequestBody() {
                        override fun contentType() = "application/octet-stream".toMediaType()
                        override fun contentLength() = if (size > 0) size else -1L
                        override fun writeTo(sink: BufferedSink) {
                            val buf = ByteArray(65536)
                            var sent = 0L
                            var last = 0L
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                sink.write(buf, 0, n)
                                sent += n
                                if (sent - last > 131072) { last = sent; val s = sent; main.post { progress(s, size) } }
                            }
                        }
                    }
                    val b = MultipartBody.Builder().setType(MultipartBody.FORM)
                    fields.forEach { (k, v) -> b.addFormDataPart(k, v) }
                    b.addFormDataPart("auth", cookie ?: "")
                    b.addFormDataPart(fileField, name.replace("\"", "_"), file)
                    client.newBuilder().followRedirects(true).build().newCall(Request.Builder().url(ctrl.server.url + path)
                        .header("User-Agent", USER_AGENT).post(b.build()).build()).execute().use { r ->
                        if (!r.isSuccessful) throw IllegalStateException("HTTP ${r.code}")
                    }
                    null
                } catch (e: Exception) {
                    e.message ?: e.javaClass.simpleName
                } finally {
                    runCatching { input.close() }
                }
                main.post { done(err) }
            }.start()
        }
    }
}

/** Event / server times: ISO-8601 text or epoch (ms or s), shown in local time. */
internal fun srvTime(v: Any?): String {
    val ms: Long = when (v) {
        null -> return ""
        is Number -> v.toLong().let { if (it in 1..99_999_999_999L) it * 1000 else it }
        is String -> if (v.isBlank()) return "" else try { Instant.parse(v).toEpochMilli() } catch (e: Exception) {
            v.toLongOrNull()?.let { if (it < 100_000_000_000L) it * 1000 else it } ?: return v
        }
        else -> return v.toString()
    }
    if (ms <= 0) return ""
    return DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(ms))
}

/** Pretty JSON for detail dialogs. */
internal fun srvPretty(v: Any?): String = when (v) {
    is JSONObject -> v.toString(2)
    is JSONArray -> v.toString(2)
    null -> ""
    else -> v.toString()
}

/**
 * What the server sends only once, right after sign-in, to full administrators: warnings and the trace sources
 * (meshuser.js). Attach to the control connection as soon as the session starts (McdApp.startSession), before any
 * screen exists; the My Server screen reads it.
 */
object ServerSignInInfo {
    private class Info { var warnings: JSONArray = JSONArray(); var trace: JSONArray? = null }
    private val infos = WeakHashMap<ControlConnection, Info>()

    fun attach(ctrl: ControlConnection) {
        val i = Info()
        infos[ctrl] = i
        ctrl.on("serverwarnings") { m -> i.warnings = m.optJSONArray("warnings") ?: JSONArray() }
        ctrl.on("traceinfo") { m -> i.trace = m.optJSONArray("traceSources") }
        ctrl.on("event") { m ->
            val ev = m.optJSONObject("event")
            if (ev?.optString("action") == "traceinfo") i.trace = ev.optJSONArray("traceSources")
        }
    }

    internal fun warnings(ctrl: ControlConnection): JSONArray = infos[ctrl]?.warnings ?: JSONArray()
    internal fun traceSources(ctrl: ControlConnection): JSONArray? = infos[ctrl]?.trace
}
