// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.net

import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.net.URLEncoder

// Relay protocols (client.py)
const val PROTO_TERMINAL = 1          // admin / root shell
const val PROTO_FILES = 5
const val PROTO_POWERSHELL = 6        // admin PowerShell
const val PROTO_USER_SHELL = 8        // shell as the logged-in user (7 is the plugin channel, not a shell)
const val PROTO_USER_POWERSHELL = 9

internal fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

/**
 * A relay session to one agent (meshrelay.ashx), port of client.py Tunnel.
 * States: 0 closed, 1 connecting, 2 waiting for the agent, 3 connected. Every callback runs on the main thread.
 */
class Tunnel(private val ctrl: ControlConnection, val nodeId: String, val protocol: Int,
             private val options: JSONObject? = null) {
    var state = 0
        private set
    var onState: ((Int) -> Unit)? = null
    var onText: ((String) -> Unit)? = null
    var onBinary: ((ByteArray) -> Unit)? = null
    /** agent / server console messages (consent prompts, errors...) */
    var onConsole: ((String) -> Unit)? = null
    private var ws: WebSocket? = null
    private var stopped = false

    fun start() {
        setState(1)
        ctrl.authCookie { cookie, rcookie -> if (!stopped) open(cookie, rcookie) }
    }

    private fun open(cookie: String?, rcookie: String?) {
        val tid = randomHex()
        val srv = ctrl.server
        val url = srv.ws("meshrelay.ashx") + "?browser=1&p=$protocol&nodeid=${enc(nodeId)}&id=$tid&auth=${enc(cookie ?: "")}"
        val req = Request.Builder().url(url).header("User-Agent", USER_AGENT).build()
        ws = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { ctrl.post { if (!stopped) setState(2) } }
            override fun onMessage(webSocket: WebSocket, text: String) { ctrl.post { if (!stopped) text(text) } }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val b = bytes.toByteArray()
                ctrl.post { if (!stopped) onBinary?.invoke(b) }
            }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { ctrl.post { if (!stopped) setState(0) } }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { ctrl.post { if (!stopped) setState(0) } }
        })
        var rurl = "*${srv.path}/meshrelay.ashx?p=$protocol&nodeid=$nodeId&id=$tid"
        if (!rcookie.isNullOrEmpty()) rurl += "&rauth=$rcookie"
        ctrl.send("action" to "msg", "type" to "tunnel", "nodeid" to nodeId, "value" to rurl, "usage" to protocol)
    }

    private fun text(data: String) {
        if (state < 3 && (data == "c" || data == "cr")) {
            options?.let { o -> sendRawText(JSONObject(o.toString()).put("type", "options").toString()) }
            sendRawText(protocol.toString())
            setState(3)
            return
        }
        if (data.startsWith("{")) {
            val j = try { JSONObject(data) } catch (e: Exception) { null }
            if (j != null && j.optString("ctrlChannel") == CTRL_CHANNEL) {
                when (j.optString("type")) {
                    "ping" -> sendRawText(JSONObject().put("ctrlChannel", CTRL_CHANNEL).put("type", "pong").toString())
                    "console" -> onConsole?.invoke(j.optString("msg"))
                }
                return
            }
        }
        onText?.invoke(data)
    }

    // keep-alive: the server only pings relays when configured (agentPing), and proxies such as Cloudflare close a
    // WebSocket that carries no data for ~100 s (an idle terminal or file list); the agent answers "ping" with "pong"
    private val keepAlive = android.os.Handler(android.os.Looper.getMainLooper())
    private val pinger = object : Runnable {
        override fun run() {
            if (stopped || state < 3) return
            sendRawText("{\"ctrlChannel\":\"$CTRL_CHANNEL\",\"type\":\"ping\"}")
            keepAlive.postDelayed(this, 25_000)
        }
    }

    private fun setState(s: Int) {
        if (s == state) return
        state = s
        keepAlive.removeCallbacks(pinger)
        if (s >= 3) keepAlive.postDelayed(pinger, 25_000)      // only once the agent is on the other end
        onState?.invoke(s)
    }

    fun sendRawText(s: String) { ws?.send(s) }

    /** Binary data; text goes as UTF-8 bytes, like the web client. */
    fun send(data: ByteArray) { ws?.send(data.toByteString()) }
    fun send(text: String) = send(text.toByteArray(Charsets.UTF_8))
    fun sendJson(obj: JSONObject) = send(obj.toString())
    fun sendCtrl(obj: JSONObject) = sendRawText(obj.put("ctrlChannel", CTRL_CHANNEL).toString())

    fun stop() {
        if (stopped) return
        ws?.let {
            if (state >= 2) sendCtrl(JSONObject().put("type", "close"))
            it.close(1000, null)
        }
        ws = null
        stopped = true
        keepAlive.removeCallbacks(pinger)
        val cb = onState
        onState = null
        state = 0
        cb?.invoke(0)
    }
}
