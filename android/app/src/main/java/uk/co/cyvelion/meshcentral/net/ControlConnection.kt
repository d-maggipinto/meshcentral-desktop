// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.net

import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.net.URI
import java.security.SecureRandom
import java.util.concurrent.TimeUnit

const val USER_AGENT = "MeshCentralDesktop-Android/1.0"
const val CTRL_CHANNEL = "102938"

/** A MeshCentral server address. HTTPS only: the password travels in the x-meshauth header. */
class ServerAddress(input: String) {
    val url: String
    val host: String
    val path: String

    init {
        var u = input.trim().trimEnd('/')
        if (!u.contains("://")) u = "https://$u"
        val uri = URI(u)
        require(uri.scheme.equals("https", ignoreCase = true)) { "Only https:// servers are supported" }
        require(!uri.host.isNullOrEmpty()) { "Enter the server address" }
        host = if (uri.port > 0) "${uri.host}:${uri.port}" else uri.host
        path = (uri.rawPath ?: "").trimEnd('/')
        url = "https://$host$path"
    }

    fun ws(endpoint: String) = "wss://$host$path/$endpoint"
}

/** Why the control connection closed: the server's "close" message (cause / msg) or a network error. */
data class CloseReason(val cause: String?, val msg: String?)

internal fun b64(s: String): String = Base64.encodeToString(s.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)

private val random = SecureRandom()
internal fun randomHex(bytes: Int = 6): String =
    ByteArray(bytes).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }

/** A response body of at most max bytes (null if larger): a server must not be able to fill the phone's memory. */
internal fun okhttp3.ResponseBody.bytesAtMost(max: Long): ByteArray? {
    if (contentLength() > max) return null
    source().use { src ->
        src.request(max + 1)
        return if (src.buffer.size > max) null else src.buffer.readByteArray()
    }
}

/**
 * Shared HTTP client (system + user-installed certificates, see network_security_config.xml). Redirects are followed
 * only within the same host: OkHttp keeps custom headers on a redirect (only Authorization is dropped), so a
 * redirect to another host would carry x-meshauth (user name, password, two-factor code) or a Cookie header there.
 */
val http: OkHttpClient by lazy {
    OkHttpClient.Builder()
        .addNetworkInterceptor { chain ->
            val req = chain.request()
            val res = chain.proceed(req)
            val to = res.header("Location")?.let { req.url.resolve(it) }
            // no Location = OkHttp hands the 3xx back as the final answer instead of following it
            if (res.isRedirect && to != null && (to.host != req.url.host || to.port != req.url.port || !to.isHttps))
                res.newBuilder().removeHeader("Location").build() else res
        }
        .pingInterval(30, TimeUnit.SECONDS)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
}

/**
 * The user's session (wss://server/control.ashx). Every server message is delivered on the MAIN thread to
 * the listeners of its action, to a responseid callback, and to the "any" listeners, like client.py.
 *
 * Staying connected: once signed in, the connection sends the server's own {action:'ping'} every 25 s (data, so
 * proxies such as Cloudflare that close idle WebSockets after ~100 s see traffic), keeps a fresh login cookie, and
 * when the connection drops for any reason except a refused sign-in it reconnects by itself (backoff 1 s .. 30 s):
 * first with the cookie (control.ashx?auth=, valid 1 hour, bound to the IP address, so no two-factor code is
 * needed again), with the user name and password as the fallback. Listeners stay registered across reconnects.
 * onClose is called only when it gives up (the server refused the sign-in).
 */
class ControlConnection(server: String, val username: String, password: String,
                        private val token: String? = null) {
    val server = ServerAddress(server)
    /** Kept for the remote desktop's web sign-in; updated after a password change (My Account). */
    internal var password: String = password
    private val main = Handler(Looper.getMainLooper())
    private var ws: WebSocket? = null
    @Volatile var connected = false
        private set
    private val listeners = HashMap<String, MutableList<(JSONObject) -> Unit>>()
    private val anyListeners = mutableListOf<(JSONObject) -> Unit>()
    private val pending = HashMap<String, (JSONObject) -> Unit>()
    private val cookieWaiters = mutableListOf<(String?, String?) -> Unit>()
    var serverinfo = JSONObject()
        private set
    var userinfo: JSONObject? = null
        private set
    var onOpen: (() -> Unit)? = null
    var onClose: ((CloseReason?) -> Unit)? = null
    /** true while the connection is lost and being re-established; false once signed in again. */
    var onReconnecting: ((Boolean) -> Unit)? = null
    private var closeReason: CloseReason? = null
    private var signedIn = false                     // the first sign-in succeeded: reconnect from now on
    private var userClosed = false
    private var cookie: String? = null               // control.ashx?auth= login cookie, refreshed every 20 min
    private var attempt = 0
    private var gen = 0                              // ignores callbacks of a socket we replaced
    private val pinger = object : Runnable {
        override fun run() { if (connected) ws?.send("{\"action\":\"ping\"}"); main.postDelayed(this, 25_000) }
    }
    private val cookieRefresh = object : Runnable {
        override fun run() { if (connected) authCookie { c, _ -> if (c != null) cookie = c }; main.postDelayed(this, 20 * 60_000L) }
    }
    private val retry = Runnable { if (!userClosed && !connected) open() }

    fun connect() { userClosed = false; open() }

    private fun open() {
        val g = ++gen
        var auth = b64(username) + "," + b64(password)
        // the two-factor code is good for one sign-in only; reconnects use the cookie instead
        if (!signedIn && !token.isNullOrEmpty()) auth += "," + b64(token)
        val url = server.ws("control.ashx") + (cookie?.let { "?auth=" + java.net.URLEncoder.encode(it, "UTF-8") } ?: "")
        val req = Request.Builder().url(url)
            .header("x-meshauth", auth)
            .header("User-Agent", USER_AGENT)
            .build()
        closeReason = null
        ws = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (g != gen) return
                connected = true
                main.post { if (g == gen) onOpen?.invoke() }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (g != gen) return
                val msg = try { JSONObject(text) } catch (e: Exception) { return }
                main.post { if (g == gen) dispatch(msg) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { main.post { closed(g) } }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w("McdControl", "control connection failed (HTTP ${response?.code})", t)
                main.post {
                    if (g == gen && closeReason == null) closeReason = CloseReason("error", t.message ?: t.javaClass.simpleName)
                    closed(g)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }
        })
    }

    private fun closed(g: Int) {
        if (g != gen) return
        val was = connected || ws != null
        connected = false
        ws = null
        main.removeCallbacks(pinger); main.removeCallbacks(cookieRefresh)
        if (!was || userClosed) return
        val r = closeReason
        // a refused sign-in is final (the server tries the cookie, then the password, so both were refused, e.g.
        // a new two-factor code is needed); anything else (network, server restart, proxy time-out) is retried
        val refused = r?.cause == "noauth" || r?.cause == "tokenrequired" || r?.msg == "tokenrequired"
        if (signedIn && !refused) {
            attempt++
            onReconnecting?.invoke(true)
            main.postDelayed(retry, listOf(1L, 2, 4, 8, 15, 30)[minOf(attempt - 1, 5)] * 1000)
            return
        }
        onClose?.invoke(r)
    }

    /** Reconnect at once if the connection is down (the network came back, the app returned to the screen). */
    fun reconnectNow() {
        if (userClosed || !signedIn || connected) return
        main.removeCallbacks(retry)
        open()
    }

    fun close() {
        userClosed = true
        onClose = null
        onReconnecting = null
        main.removeCallbacks(retry); main.removeCallbacks(pinger); main.removeCallbacks(cookieRefresh)
        gen++
        ws?.close(1000, null)
        ws = null
        connected = false
    }

    private fun dispatch(msg: JSONObject) {
        val action = msg.optString("action")
        when (action) {
            "close" -> { closeReason = CloseReason(msg.optString("cause", null), msg.optString("msg", null)); return }
            "serverinfo" -> serverinfo = msg.optJSONObject("serverinfo") ?: JSONObject()
            "userinfo" -> {
                userinfo = msg.optJSONObject("userinfo")
                // signed in (first time or again): keep the connection alive from now on
                val again = signedIn && attempt > 0
                signedIn = true
                attempt = 0
                main.removeCallbacks(pinger); main.postDelayed(pinger, 25_000)
                main.removeCallbacks(cookieRefresh); main.post(cookieRefresh)
                if (again) onReconnecting?.invoke(false)
            }
            "authcookie" -> {
                val waiters = cookieWaiters.toList()
                cookieWaiters.clear()
                waiters.forEach { it(msg.optString("cookie", null), msg.optString("rcookie", null)) }
            }
            "event" -> {
                val ev = msg.optJSONObject("event")
                if (ev?.optString("action") == "accountchange") {
                    val acc = ev.optJSONObject("account")
                    if (acc != null && acc.optString("_id") == userinfo?.optString("_id")) userinfo = acc
                }
            }
        }
        val rid = msg.optString("responseid", "")
        if (rid.isNotEmpty()) pending.remove(rid)?.invoke(msg)
        listeners[action]?.toList()?.forEach { it(msg) }
        anyListeners.toList().forEach { it(msg) }
    }

    /** Send a message; with a callback a responseid is added (replies that echo it go to the callback). */
    fun send(obj: JSONObject, callback: ((JSONObject) -> Unit)? = null) {
        if (callback != null) {
            val rid = "mcd" + randomHex()
            obj.put("responseid", rid)
            pending[rid] = callback
        }
        ws?.send(obj.toString())
    }

    fun send(vararg pairs: Pair<String, Any?>, callback: ((JSONObject) -> Unit)? = null) =
        send(JSONObject().apply { pairs.forEach { (k, v) -> put(k, v) } }, callback)

    fun on(action: String, cb: (JSONObject) -> Unit) {
        listeners.getOrPut(action) { mutableListOf() }.add(cb)
    }

    fun off(action: String, cb: (JSONObject) -> Unit) {
        listeners[action]?.remove(cb)
    }

    fun onAny(cb: (JSONObject) -> Unit) = anyListeners.add(cb)
    fun offAny(cb: (JSONObject) -> Unit) = anyListeners.remove(cb)

    /** A one-time relay cookie (cookie, rcookie) for meshrelay.ashx. */
    fun authCookie(cb: (String?, String?) -> Unit) {
        cookieWaiters.add(cb)
        send("action" to "authcookie")
    }

    fun nodeMsg(nodeid: String, type: String, vararg extra: Pair<String, Any?>) =
        send(JSONObject().apply {
            put("action", "msg"); put("type", type); put("nodeid", nodeid)
            extra.forEach { (k, v) -> put(k, v) }
        })

    /** Raw message from a background thread (tunnels): posted to the main thread. */
    internal fun post(fn: () -> Unit) = main.post(fn)
}
