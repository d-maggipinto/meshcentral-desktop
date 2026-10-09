// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.view.HapticFeedbackConstants
import android.view.ViewGroup
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Mouse
import androidx.compose.material.icons.filled.TouchApp
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.ZoomOutMap
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Monitor
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ListItem
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.ui.draw.alpha
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.Alignment
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.Session

/** Viewer value choices (desktop_panel): quality, frame interval ms, agent-side scale (1024 = 100 %). */
private data class Preset(val label: String, val quality: Int, val frameMs: Int, val scale: Int)
private val PRESETS = listOf(Preset("Data saver", 30, 300, 512), Preset("Balanced", 50, 100, 768), Preset("Best quality", 80, 50, 1024))

/** Keys a phone keyboard lacks: label, Windows key code, extended. Ctrl / Alt / Shift / Win are sticky. */
private val DESK_KEYS = listOf(Triple("Esc", 27, false), Triple("Tab", 9, false), Triple("↑", 38, true), Triple("↓", 40, true),
    Triple("←", 37, true), Triple("→", 39, true), Triple("Del", 46, true), Triple("Home", 36, true), Triple("End", 35, true),
    Triple("PgUp", 33, true), Triple("PgDn", 34, true)) + (1..12).map { Triple("F$it", 111 + it, false) }
private val MODS = listOf(Triple("Ctrl", 17, false), Triple("Alt", 18, false), Triple("Shift", 16, false), Triple("Win", 91, true))

// Injected before connect: drop the outer web chrome (the viewer's controls stay, the auto-connect click needs them).
private const val CHROME_CSS = "#page_leftbar{display:none!important;}#page_content{left:0!important;margin-left:0!important;}" +
    "#masthead,#topbar,#footer{display:none!important;}"
// After connect: only the screen, filling the whole view. NEVER hide #deskarea0 (it holds the canvas).
private const val DESK_CSS = "html,body{overflow:hidden!important;touch-action:none!important;}" +
    "#deskarea1,#deskarea4,#DeskFocus{display:none!important;}" +
    "#deskarea3x{position:fixed!important;top:0!important;left:0!important;right:0!important;bottom:0!important;" +
    "width:auto!important;height:auto!important;max-height:none!important;margin:0!important;overflow:hidden!important;" +
    "z-index:9999!important;background:#000!important;}" +
    "#DeskParent{position:absolute!important;top:0!important;left:0!important;width:100%!important;height:100%!important;" +
    "overflow:hidden!important;margin:0!important;touch-action:none!important;display:block!important;}" +
    // the whole remote screen, fitted by fit.js (more specific than any page rule, even the Modern UI's !important ones)
    "#deskarea3x #DeskParent canvas#Desk{position:absolute!important;left:var(--mcd-l,0)!important;top:var(--mcd-t,0)!important;" +
    "right:auto!important;bottom:auto!important;width:var(--mcd-w,100%)!important;height:var(--mcd-h,auto)!important;" +
    "max-width:none!important;max-height:none!important;margin:0!important;outline:none!important;}" +
    "body{min-width:0!important;}#deskFsBtn,#deskMobileActions{display:none!important;}"
private const val END_SESSION_JS = "(function(){try{window.onbeforeunload=null;if(typeof desktop!=='undefined'&&desktop&&" +
    "typeof connectDesktop==='function'){connectDesktop(null,0);}return 'ok';}catch(e){return 'err';}})()"

private fun style(id: String, css: String) = "(function(){try{var s=document.getElementById(${JSONObject.quote(id)});" +
    "if(!s){s=document.createElement('style');s.id=${JSONObject.quote(id)};document.head.appendChild(s);}" +
    "s.textContent=${JSONObject.quote(css)};return 'ok';}catch(e){return 'err';}})()"

/** The JS string result of evaluateJavascript is JSON-quoted. */
private fun unquote(r: String?): String = try { if (r == null || r == "null") "" else JSONObject("{\"v\":$r}").optString("v") } catch (e: Exception) { r ?: "" }

/**
 * Remote desktop (desktop_panel.py): MeshCentral's OWN viewer in a WebView, signed in automatically and reduced to the
 * screen, with native controls. We never re-implement KVM. Connects only on the Connect button.
 * Phases: idle, loading (sign-in / page), connecting (session starting), connected.
 */
class DesktopController(private val ctx: Context, private val session: Session, private val node: Node) {
    var phase by mutableStateOf("idle")
    var status by mutableStateOf("")
    var cover by mutableStateOf<String?>("")         // null = remote screen visible; text = cover message
    var showPage by mutableStateOf(false)             // the user must see the page (two-factor code)
    var error by mutableStateOf(false)
    val held = mutableStateOf(setOf<Int>())           // sticky modifiers
    private val main = Handler(Looper.getMainLooper())
    private var gen = 0
    private var loggedIn = false
    private var navigated = false
    private var connectTried = false
    private var attempts = 0
    private var polling = false
    private var closing = false
    var preset = 1
    /** Touchpad (a cursor moved like a laptop touchpad, default) or direct touch; remembered. */
    var touchpad by mutableStateOf(!uk.co.cyvelion.meshcentral.McdApp.instance.settings.getBool("desk_direct_touch", false))
        private set
    fun useTouchpad(on: Boolean) {
        touchpad = on
        uk.co.cyvelion.meshcentral.McdApp.instance.settings.putBool("desk_direct_touch", !on)
        js("window.__mcdMode=${JSONObject.quote(if (on) "pad" else "touch")};if(window.__mcdSetMode)window.__mcdSetMode(window.__mcdMode);")
    }
    /** displays the agent lists (65535 = all displays) and the one shown; only listed ones may be selected */
    var displays by mutableStateOf<List<Int>>(emptyList())
    var display by mutableStateOf<Int?>(null)
    /** remote user's input lock: null = unknown / not supported by this agent */
    var inputLocked by mutableStateOf<Boolean?>(null)
    private val ctrl = session.ctrl
    private val origin = ctrl.server.url.let { u -> Uri.parse(u).let { "${it.scheme}://${it.authority}" } }
    private val deskUrl = "${ctrl.server.url}/?gotonode=${node.shortId}&viewmode=11&hide=15&mobile=0&sitestyle=1"
    private val watchdog = Runnable { if (phase == "loading" || phase == "connecting") fail("The remote desktop did not start in time. Check that the device is online, then Retry.") }

    @SuppressLint("SetJavaScriptEnabled")
    val web: WebView = WebView(ctx).apply {
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        setBackgroundColor(android.graphics.Color.BLACK)
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowFileAccess = false
        settings.allowContentAccess = false
        settings.setSupportMultipleWindows(false)
        settings.javaScriptCanOpenWindowsAutomatically = false
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.builtInZoomControls = false
        webViewClient = object : WebViewClient() {
            // only the configured server's own pages
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url
                return "${u.scheme}://${u.authority}" != origin
            }
            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {}
            override fun onPageFinished(view: WebView, url: String) {
                // exactly the configured origin (a prefix match would also accept https://server.example.evil)
                val u = Uri.parse(url)
                if ("${u.scheme}://${u.authority}" == origin) onLoad()
            }
            override fun onRenderProcessGone(view: WebView, detail: android.webkit.RenderProcessGoneDetail): Boolean {
                closing = true
                phase = "idle"; error = true
                cover = "The remote desktop view stopped (the phone ended its web renderer). Go back and open the desktop again."
                return true
            }
        }
        webChromeClient = object : WebChromeClient() {
            // the viewer asks "leave page?" while a session is active: behind the cover it would hang navigation
            override fun onJsBeforeUnload(view: WebView, url: String, message: String, result: JsResult): Boolean { result.confirm(); return true }
            override fun onJsAlert(view: WebView, url: String, message: String, result: JsResult): Boolean { status = message; result.confirm(); return true }
            override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean { result.cancel(); return true }
        }
        setDownloadListener { _, _, _, _, _ -> }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(this, "mcd", setOf(origin)) { v, msg, _, isMain, _ ->
                if (isMain && msg.data?.contains("haptic") == true) v.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
            }
        }
    }

    private fun js(code: String, cb: ((String) -> Unit)? = null) =
        web.evaluateJavascript(code) { r -> if (!closing) cb?.invoke(unquote(r)) }

    private fun asset(name: String) = ctx.assets.open(name).bufferedReader().use { it.readText() }

    private fun arm() { main.removeCallbacks(watchdog); main.postDelayed(watchdog, 45_000) }

    private fun fail(text: String) {
        if (autoRetry > 0 && retryLater("The remote desktop did not come back yet.")) return
        phase = "idle"; error = true; status = ""
        cover = text
        main.removeCallbacks(watchdog)
        js(END_SESSION_JS)
    }

    // the session dropped (network, proxy time-out, agent restart): reconnect by itself a few times before giving up
    private var autoRetry = 0
    private val retryDelays = listOf(2L, 4, 8, 15, 30, 30)
    private fun retryLater(why: String): Boolean {
        if (closing || autoRetry >= retryDelays.size || session.node(node.id)?.online == false) return false
        val d = retryDelays[autoRetry++]
        phase = "idle"; error = false; showPage = false
        cover = "$why\nReconnecting automatically… (attempt $autoRetry of ${retryDelays.size})"
        status = "Reconnecting…"
        main.removeCallbacks(watchdog)
        val g = ++gen
        main.postDelayed({ if (g == gen && !closing && phase == "idle") start(auto = true) }, d * 1000)
        return true
    }

    fun start(auto: Boolean = false) {
        if (!auto) autoRetry = 0
        error = false
        gen++
        loggedIn = false; navigated = false; connectTried = false; attempts = 0; showPage = false
        phase = "loading"
        cover = "Connecting…"
        status = "Opening…"
        arm()
        val g = gen
        js(END_SESSION_JS) { if (g == gen) web.loadUrl(ctrl.server.url + "/?mobile=0") }
    }

    fun stop() {
        gen++
        autoRetry = 0
        main.removeCallbacks(watchdog)
        phase = "idle"; showPage = false; error = false
        cover = ""
        status = ""
        js(END_SESSION_JS) { web.loadUrl("about:blank") }
    }

    private fun onLoad() {
        if (closing) return
        js("(function(){var u=document.getElementById('username'),t=document.getElementById('tokenInput');" +
            "if(t&&t.offsetParent!==null)return 'token';if(u&&u.offsetParent!==null)return 'login';return 'app';})()") { route(it) }
    }

    private fun route(kind: String) {
        if (phase != "loading") return
        when {
            kind == "token" -> {
                // the web sign-in needs its own code: let the user type it into the page
                showPage = true
                status = "Enter your two-factor code to open the desktop"
                arm()
            }
            kind == "login" && !loggedIn -> {
                loggedIn = true
                status = "Signing in…"
                // the password only goes into the configured server's own page
                js("(function(){if(location.origin!==${JSONObject.quote(origin)})return 'foreign';" +
                    "var u=document.getElementById('username'),p=document.getElementById('password');if(!u||!p)return 'noform';" +
                    "u.value=${JSONObject.quote(ctrl.username)};p.value=${JSONObject.quote(ctrl.password)};" +
                    "var b=document.getElementById('loginButton');if(b){b.disabled=false;b.click();return 'ok';}" +
                    "var f=document.forms[0];if(f){f.submit();return 'ok';}return 'noform';})()") {
                    if (it == "noform") fail("Could not find the sign-in form on this server's page.")
                }
            }
            kind == "login" -> fail("The server did not accept the sign-in for the remote desktop.")
            !navigated -> {
                navigated = true
                showPage = false
                status = "Opening desktop…"
                web.loadUrl(deskUrl)
            }
            !connectTried -> {
                js(style("mcd-chrome-css", CHROME_CSS))
                js(asset("desk/fit.js"))
                connectTried = true
                status = "Starting remote session…"
                attempts = 0
                clickConnect(gen)
            }
        }
    }

    private fun clickConnect(g: Int) {
        if (g != gen || phase != "loading") return
        attempts++
        js("(function(){try{var b=document.getElementById('connectbutton1');if(b&&b.offsetParent!==null){b.click();return 'connected';}" +
            "if(typeof connectDesktop==='function'&&typeof currentNode!=='undefined'&&currentNode){connectDesktop(null,1);return 'connected';}" +
            "return 'nobtn';}catch(e){return 'err';}})()") { r ->
            if (g != gen || phase != "loading") return@js
            when (r) {
                "connected" -> {
                    phase = "connecting"
                    status = "Connecting to remote screen…"
                    js(style("mcd-desk-css", DESK_CSS))
                    js("window.__mcdTouch=null;'ok'")
                    if (!polling) { polling = true; main.postDelayed({ poll() }, 300) }
                }
                "nobtn" -> if (attempts < 80) main.postDelayed({ clickConnect(g) }, 250)
                    else fail("The desktop did not start. Check that the device is online, then Retry.")
                else -> fail("Could not start the desktop session.")
            }
        }
    }

    private fun poll() {
        if (closing) { polling = false; return }
        js("(function(){var d=document.getElementById('deskstatus'),m=document.getElementById('p11DeskConsoleMsg');" +
            "return (d?d.innerText.trim():'')+String.fromCharCode(10)+(m&&m.style.display!='none'?m.innerText.trim():'');})()") { text ->
            val lines = text.split("\n", limit = 2)
            val st = lines[0]
            val agentMsg = lines.getOrNull(1)?.trim()?.lines()?.lastOrNull()?.trim() ?: ""
            val now = st.lowercase().startsWith("connected")
            if (phase == "connecting" && cover != null) {
                if (agentMsg.isNotEmpty() && listOf("grant access", "waiting for user", "consent").any { agentMsg.lowercase().contains(it) }) {
                    cover = "Waiting for the remote user to accept the connection…"
                    arm()                                   // a person has to answer: no time-out meanwhile
                } else if (agentMsg.isNotEmpty()) cover = "Connecting…\nThe remote computer says: ${agentMsg.take(200)}"
            }
            if (now && phase == "connecting") {
                phase = "connected"
                main.removeCallbacks(watchdog)
                applyPreset(true)
                firstFrame(0, 0, gen)
            } else if (!now && phase == "connected") {
                if (!retryLater("The connection to the remote screen was lost.")) {
                    phase = "idle"
                    error = true
                    cover = "The remote session ended."
                }
            }
            if (phase == "connected" && cover == null) status = st
            if (phase == "connected") readSession()
            main.postDelayed({ poll() }, if (phase == "connected") 2000L else 300L)
        }
    }

    /** Reveal the screen only once the viewer drew a real frame (it starts with a 960x701 placeholder). */
    private fun firstFrame(tries: Int, hits: Int, g: Int) {
        if (g != gen || phase != "connected") return
        js("(function(){try{var m=desktop.m,c=m.Canvas.canvas;var real=!(m.ScreenWidth==960&&m.ScreenHeight==701)&&m.ScreenWidth>8&&m.ScreenHeight>8;" +
            "return (desktop.State===3&&real&&m.FirstDraw===false&&c.width===m.ScreenWidth)?'drawn':'wait';}catch(e){return 'wait';}})()") { v ->
            if (g != gen || phase != "connected") return@js
            val h = if (v == "drawn") hits + 1 else 0
            if (h >= 2 || tries >= 30) {
                cover = null
                status = "Connected"
                autoRetry = 0
                // keep-alive: the server pings relays only when configured, and proxies (Cloudflare) close a WebSocket
                // without data for ~100 s, e.g. a still screen; the agent answers this ping with a pong
                js("if(!window.__mcdKeep){window.__mcdKeep=setInterval(function(){try{if(desktop&&desktop.State==3&&desktop.sendCtrlMsg)" +
                    "desktop.sendCtrlMsg('{\"ctrlChannel\":\"102938\",\"type\":\"ping\"}');}catch(e){}},25000);}")
                js(asset("desk/fit.js"))                // again: a page that reloaded itself lost the first one
                js("window.__mcdMode=${JSONObject.quote(if (touchpad) "pad" else "touch")};")
                js(asset("desk/touch.js"))
                js("if(window.__mcdFitNow)window.__mcdFitNow();")
            } else main.postDelayed({ firstFrame(tries + 1, h, g) }, 200)
        }
    }

    fun applyPreset(force: Boolean = false) {
        val p = PRESETS[preset]
        js("(function(){try{var m=desktop.m;if(!m||desktop.State!==3)return 'notready';m.SendCompressionLevel(4,${p.quality},${p.scale},${p.frameMs});" +
            (if (force) "if(m.SendRefresh)m.SendRefresh();" else "") + "return 'ok';}catch(e){return 'err';}})()")
    }

    private fun desk(body: String) = js("(function(){try{if(typeof desktop==='undefined'||!desktop||desktop.State!==3||!desktop.m)return 'notready';" +
        "var m=desktop.m;$body;return 'ok';}catch(e){return 'err';}})()")

    /** A key with the held modifiers around it; the modifiers are released afterwards (sticky for one key). */
    fun key(code: Int, ext: Boolean) {
        val mods = MODS.filter { it.second in held.value }
        val sb = StringBuilder()
        mods.forEach { sb.append("m.SendKeyMsgKC(1,${it.second},${it.third});") }
        sb.append("m.SendKeyMsgKC(1,$code,$ext);m.SendKeyMsgKC(2,$code,$ext);")
        mods.reversed().forEach { sb.append("m.SendKeyMsgKC(2,${it.second},${it.third});") }
        desk(sb.toString())
        held.value = emptySet()
    }

    /** Typed text: Unicode characters, or key codes while a modifier is held (Ctrl+C must be a shortcut). */
    fun type(text: String) {
        if (held.value.isNotEmpty()) {
            text.forEach { c ->
                val up = c.uppercaseChar()
                if (up in 'A'..'Z' || up in '0'..'9') key(up.code, false) else desk(uni(c))
            }
            return
        }
        desk(text.map { uni(it) }.joinToString(""))
    }
    private fun uni(c: Char) = when (c) {
        '\n' -> "m.SendKeyMsgKC(1,13,false);m.SendKeyMsgKC(2,13,false);"
        '\t' -> "m.SendKeyMsgKC(1,9,false);m.SendKeyMsgKC(2,9,false);"
        else -> "m.SendKeyUnicode(1,${c.code});m.SendKeyUnicode(2,${c.code});"
    }

    fun ctrlAltDel() = desk(if (node.isWindows) "m.SendCtrlAltDelMsg()" else
        "m.SendKeyMsgKC(1,17,false);m.SendKeyMsgKC(1,18,false);m.SendKeyMsgKC(1,46,true);m.SendKeyMsgKC(2,46,true);m.SendKeyMsgKC(2,18,false);m.SendKeyMsgKC(2,17,false)")
    fun refresh() = desk("if(m.SendRefresh)m.SendRefresh()")

    /** The viewer's display list and the remote input lock state (desktop_panel _refresh_displays / _read_input_lock). */
    private fun readSession() {
        js("(function(){try{if(typeof desktop==='undefined'||!desktop||desktop.State!==3||!desktop.m)return '';var m=desktop.m;" +
            "var l=(typeof m.SendRemoteInputLock==='function')?(m.RemoteInputLock===true?1:(m.RemoteInputLock===false?0:-1)):-1;" +
            "return JSON.stringify({d:Object.keys(m.displays||{}),s:m.selectedDisplay,l:l});}catch(e){return '';}})()") { raw ->
            val o = try { JSONObject(raw) } catch (e: Exception) { return@js }
            val d = o.optJSONArray("d")
            val ids = if (d == null) emptyList() else (0 until d.length()).mapNotNull { d.optString(it).toIntOrNull() }
                .sortedWith(compareBy({ it != 65535 }, { it }))
            if (ids != displays) displays = ids
            display = if (o.has("s") && !o.isNull("s")) o.optInt("s") else null
            inputLocked = when (o.optInt("l", -1)) { 1 -> true; 0 -> false; else -> null }
        }
    }

    /** Show another display; never one the agent did not list (SetDisplay on an unlisted number breaks the stream). */
    fun setDisplay(n: Int) {
        if (n !in displays || phase != "connected") return
        desk("m.SetDisplay($n)")
        display = n
        main.postDelayed({ js("if(window.__mcdFitNow)window.__mcdFitNow();"); readSession() }, 1500)
    }

    fun setInputLock(lock: Boolean, report: (String) -> Unit) {
        js("(function(){try{desktop.m.SendRemoteInputLock(${if (lock) 1 else 0});return 'ok';}catch(e){return 'err';}})()") { r ->
            report(if (r == "ok") (if (lock) "Remote input locked" else "Remote input unlocked") else "Connect the desktop first")
            main.postDelayed({ readSession() }, 700)
        }
    }

    /** Windows lock screen, through the viewer's control channel like the web UI's deviceLockFunction. */
    fun lockRemote(report: (String) -> Unit) =
        js("(function(){try{if(!desktop||desktop.State!==3)return 'notready';" +
            "desktop.sendCtrlMsg(JSON.stringify({ctrlChannel:'102938',type:'lock'}));return 'ok';}catch(e){return 'err';}})()") {
            report(if (it == "ok") "Lock sent" else "Connect the desktop first")
        }

    /** The remote screen as PNG bytes (null when nothing is shown yet). */
    fun screenshot(done: (ByteArray?) -> Unit) =
        js("(function(){try{var c=document.getElementById('Desk');" +
            "if(!c||typeof desktop==='undefined'||!desktop||desktop.State!==3)return '';" +
            "return c.toDataURL('image/png');}catch(e){return '';}})()") { url ->
            val prefix = "data:image/png;base64,"
            done(if (url.startsWith(prefix)) try { android.util.Base64.decode(url.substring(prefix.length), android.util.Base64.DEFAULT) }
                catch (e: Exception) { null } else null)
        }

    /**
     * Clipboard over our own control connection (desktop_panel _clip_to_remote / _clip_from_remote): setclip and
     * getclip tag 2. The agent answers getclip only when its clipboard holds text; the server drops both when the
     * domain disables ClipboardGet / ClipboardSet.
     */
    private fun clipRequest(type: String, extra: Pair<String, Any?>, done: (JSONObject?) -> Unit) {
        var finished = false
        lateinit var cb: (JSONObject) -> Unit
        val timeout = Runnable { if (!finished) { finished = true; ctrl.off("msg", cb); if (!closing) done(null) } }
        cb = { m ->
            if (!finished && m.optString("type") == type && m.optString("nodeid", node.id) == node.id &&
                (type != "getclip" || m.optInt("tag") == 2)) {
                finished = true
                ctrl.off("msg", cb)
                main.removeCallbacks(timeout)
                if (!closing) done(m)
            }
        }
        ctrl.on("msg", cb)
        ctrl.nodeMsg(node.id, type, extra)
        main.postDelayed(timeout, 10_000)
    }

    fun sendClipboard(text: String, report: (String) -> Unit) = clipRequest("setclip", "data" to text) { m ->
        report(when {
            m == null -> "The remote computer did not confirm the clipboard (clipboard writing may be disabled on the server)"
            m.optBoolean("success") -> "Clipboard sent to the remote computer"
            else -> "The remote computer rejected the clipboard"
        })
    }

    fun readClipboard(done: (String?) -> Unit) = clipRequest("getclip", "tag" to 2) { m ->
        done(m?.optString("data")?.takeIf { it.isNotEmpty() })
    }
    /** How much of the remote screen (CSS px from the bottom) the keyboard covers; touch.js keeps the cursor above it. */
    fun setInset(cssPx: Float) = js("if(window.__mcdSetInset)window.__mcdSetInset(${cssPx.toInt()});else window.__mcdInset=${cssPx.toInt()};")

    fun resetZoom() = js("if(window.__mcdResetZoom)window.__mcdResetZoom();")

    fun destroy() {
        closing = true
        gen++
        main.removeCallbacksAndMessages(null)
        web.evaluateJavascript(END_SESSION_JS, null)
        web.loadUrl("about:blank")
        web.destroy()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DesktopScreen(session: Session, id: String, onBack: () -> Unit) {
    val node = session.node(id)
    if (node == null) { Text("This device is not in the list any more.", Modifier.padding(24.dp)); return }
    val ctx = LocalContext.current
    val caps = remember(node.id) { session.caps(node) }
    val c = remember(node.id) { DesktopController(ctx, session, node) }
    var full by rememberSaveable { mutableStateOf(false) }
    var kb by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    var preset by rememberSaveable { mutableIntStateOf(1) }
    c.preset = preset
    var tools by remember { mutableStateOf(false) }
    var urlDialog by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<Triple<String, String, () -> Unit>?>(null) }
    var shot by remember { mutableStateOf<ByteArray?>(null) }
    fun say(text: String) = android.widget.Toast.makeText(ctx, text, android.widget.Toast.LENGTH_SHORT).show()
    val saveShot = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("image/png")) { uri ->
        val data = shot
        shot = null
        if (uri != null && data != null) try {
            ctx.contentResolver.openOutputStream(uri)?.use { it.write(data) }
            say("Screenshot saved")
        } catch (e: Exception) { say("Could not save the screenshot: ${e.message}") }
    }
    val clipboard = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
    fun phoneClip(): String? = clipboard.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(ctx)?.toString()
    val windowsAgent = (node.json.optJSONObject("agent")?.optInt("id") ?: 0) in 1..4
    val noShots = session.ctrl.serverinfo.optLong("features2") and 0x400L != 0L
    val window = (ctx as? Activity)?.window
    val darkTheme = androidx.compose.foundation.isSystemInDarkTheme()

    DisposableEffect(Unit) { onDispose { c.destroy() } }
    // fullscreen: the system bars hide too (swipe from the edge shows them for a moment)
    DisposableEffect(full) {
        val w = window
        if (w != null) {
            val ic = WindowCompat.getInsetsController(w, w.decorView)
            ic.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            if (full) ic.hide(WindowInsetsCompat.Type.systemBars()) else ic.show(WindowInsetsCompat.Type.systemBars())
            ic.isAppearanceLightStatusBars = false          // light icons on the dark bars
            ic.isAppearanceLightNavigationBars = false
        }
        onDispose { w?.let {
            val ic = WindowCompat.getInsetsController(it, it.decorView)
            ic.show(WindowInsetsCompat.Type.systemBars())
            ic.isAppearanceLightStatusBars = !darkTheme
            ic.isAppearanceLightNavigationBars = !darkTheme
        } }
    }
    BackHandler(enabled = full) { full = false }
    val connected = c.phase == "connected"
    // turning the phone sideways while connected: the remote screen gets the whole display
    val landscape = androidx.compose.ui.platform.LocalConfiguration.current.orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE
    var autoFull by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(landscape, connected) {
        if (landscape && connected) { if (!full) { full = true; autoFull = true } }
        else if (!landscape && autoFull) { full = false; autoFull = false }
    }
    val busy = c.phase == "loading" || c.phase == "connecting"

    val bar = Color(0xFF16181C)
    val onBar = Color(0xFFE6E8EC)
    var hint by remember { mutableStateOf(false) }
    LaunchedEffect(c.cover == null && connected) {
        if (c.cover == null && connected) hint = true
    }
    LaunchedEffect(hint, c.touchpad) { if (hint) { kotlinx.coroutines.delay(6000); hint = false } }
    Scaffold(containerColor = Color.Black, topBar = {
        if (!full) TopAppBar(
            colors = TopAppBarDefaults.topAppBarColors(containerColor = bar, titleContentColor = onBar,
                navigationIconContentColor = onBar, actionIconContentColor = onBar),
            title = {
                Column {
                    Text(node.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(c.status.ifEmpty { if (node.online) "Online" else "Offline" }, style = MaterialTheme.typography.bodySmall,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                        color = if (connected) Color(0xFF6FD08C) else onBar.copy(alpha = 0.7f))
                }
            },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (connected || busy) OutlinedButton({ c.stop() }, colors = ButtonDefaults.outlinedButtonColors(contentColor = onBar)) {
                    Text(if (busy) "Cancel" else "Disconnect") }
                else Button({ c.start() }, enabled = node.online) { Text(if (c.error) "Retry" else "Connect") }
                Box {
                    IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem({ Text("Fullscreen") }, leadingIcon = { Icon(Icons.Filled.Fullscreen, null) },
                            onClick = { menu = false; full = true })
                        DropdownMenuItem({ Text("Tools") }, leadingIcon = { Icon(Icons.Filled.Build, null) },
                            onClick = { menu = false; tools = true })
                        DropdownMenuItem({ Text("Ctrl+Alt+Del") }, enabled = connected && caps.desktopInput,
                            onClick = { menu = false; c.ctrlAltDel() })
                        DropdownMenuItem({ Text("Refresh screen") }, enabled = connected, onClick = { menu = false; c.refresh() })
                        DropdownMenuItem({ Text("Reset zoom") }, enabled = connected, onClick = { menu = false; c.resetZoom() })
                        PRESETS.forEachIndexed { i, p ->
                            DropdownMenuItem({ Text((if (i == preset) "✓ " else "   ") + p.label) },
                                onClick = { menu = false; preset = i; c.preset = i; c.applyPreset(true) })
                        }
                    }
                }
            })
    }) { pad ->
        // the remote screen keeps its full size while the keyboard is open: the key row and the soft keyboard cover its
        // lower part and touch.js keeps the cursor in the part that is still visible (setInset), instead of squeezing
        // the whole screen into the strip above the keyboard
        var deskBottom by remember { mutableStateOf(0f) }
        var keysTop by remember { mutableStateOf(Float.MAX_VALUE) }
        val density = androidx.compose.ui.platform.LocalDensity.current.density
        LaunchedEffect(kb) { if (!kb) keysTop = Float.MAX_VALUE }
        LaunchedEffect(deskBottom, keysTop, kb) { c.setInset(if (kb && keysTop < deskBottom) (deskBottom - keysTop) / density else 0f) }
        // fullscreen draws under the (hidden) system bars, so nothing is consumed there and the key row sits right on
        // top of the keyboard
        Box(Modifier.fillMaxSize().then(if (full) Modifier else Modifier.padding(pad).consumeWindowInsets(pad))) {
        Column(Modifier.fillMaxSize().background(Color.Black)) {
            Box(Modifier.weight(1f).fillMaxWidth().onGloballyPositioned { deskBottom = it.boundsInWindow().bottom }) {
                AndroidView({ c.web }, Modifier.fillMaxSize())
                if (!c.showPage) c.cover?.let { text ->
                    Column(Modifier.fillMaxSize().background(Color(0xFF16181C)).padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                        when {
                            text.isEmpty() -> Text(if (node.online) "Tap Connect to see the remote screen." else "The device is offline.",
                                color = Color(0xFFD8DADE), textAlign = TextAlign.Center)
                            else -> {
                                if (busy) CircularProgressIndicator(Modifier.size(36.dp))
                                Spacer(Modifier.height(16.dp))
                                Text(text, color = Color(0xFFD8DADE), textAlign = TextAlign.Center)
                                if (c.error) { Spacer(Modifier.height(16.dp)); Button({ c.start() }, enabled = node.online) { Text("Retry") } }
                            }
                        }
                    }
                }
                androidx.compose.animation.AnimatedVisibility(hint && caps.desktopInput, Modifier.align(Alignment.BottomCenter).padding(12.dp),
                    enter = androidx.compose.animation.fadeIn(), exit = androidx.compose.animation.fadeOut()) {
                    Text(if (c.touchpad) "Touchpad: slide to move the cursor · Tap to click, tap twice to double click · Hold, then move to drag · " +
                        "Two fingers: tap for right click, drag to scroll, pinch to zoom"
                        else "Direct touch: tap where you want to click · Hold, then move to drag · Two fingers: tap for right click, drag to scroll, pinch to zoom",
                        Modifier.background(Color(0xCC16181C), RoundedCornerShape(14.dp)).padding(horizontal = 14.dp, vertical = 10.dp),
                        color = onBar, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
                }
                if (full) FullscreenHandle(
                    buttons = buildList {
                        if (connected && caps.desktopInput) add(HandleButton(Icons.Filled.Keyboard, "Keyboard", kb) { kb = !kb })
                        if (connected && caps.desktopInput) add(HandleButton(if (c.touchpad) Icons.Filled.Mouse else Icons.Filled.TouchApp,
                            if (c.touchpad) "Touchpad mode" else "Direct touch") { c.useTouchpad(!c.touchpad); hint = true })
                        if (connected) add(HandleButton(Icons.Filled.ZoomOutMap, "Reset zoom") { c.resetZoom() })
                        if (connected) add(HandleButton(Icons.Filled.Build, "Tools") { tools = true })
                        add(HandleButton(Icons.Filled.FullscreenExit, "Exit fullscreen") { full = false })
                    })
            }
            if (connected && caps.desktopInput) {
                if (!full) Row(Modifier.fillMaxWidth().background(bar).padding(horizontal = 4.dp, vertical = 2.dp),
                    horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
                    @Composable fun tool(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, on: Boolean = false, f: () -> Unit) =
                        IconButton(f, colors = IconButtonDefaults.iconButtonColors(
                            containerColor = if (on) Color(0xFF2F6FD6) else Color.Transparent, contentColor = onBar)) { Icon(icon, label) }
                    tool(Icons.Filled.Keyboard, "Keyboard", kb) { kb = !kb }
                    // switch between touchpad (cursor) and direct touch, like remote-control apps
                    tool(if (c.touchpad) Icons.Filled.Mouse else Icons.Filled.TouchApp,
                        if (c.touchpad) "Touchpad mode (tap for direct touch)" else "Direct touch (tap for touchpad mode)") {
                        c.useTouchpad(!c.touchpad); hint = true
                    }
                    tool(Icons.Filled.ZoomOutMap, "Reset zoom") { c.resetZoom() }
                    tool(Icons.Filled.Refresh, "Refresh screen") { c.refresh() }
                    tool(Icons.Filled.Build, "Tools", tools) { tools = true }
                    tool(Icons.Filled.Fullscreen, "Fullscreen") { full = true }
                }
            }
        }
        if (connected && caps.desktopInput && kb) Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().imePadding()
            .onGloballyPositioned { keysTop = it.boundsInWindow().top }) {
            RemoteKeyboard(c) { kb = false }
        }
        }
    }
    if (tools) DesktopToolsSheet(onDismiss = { tools = false }, items = buildList {
        val input = caps.desktopInput
        if (input) add(ToolItem("Send phone clipboard", "Puts this phone's clipboard text on the remote computer", Icons.Filled.ContentPaste, connected) {
            val t = phoneClip()
            if (t.isNullOrEmpty()) say("The phone's clipboard has no text") else { c.sendClipboard(t) { say(it) } }
        })
        add(ToolItem("Get remote clipboard", "Copies the remote computer's clipboard text to this phone", Icons.Filled.ContentCopy, connected) {
            say("Reading the remote clipboard…")
            c.readClipboard { t ->
                if (t == null) say("The remote computer returned no clipboard text (empty, or clipboard reading is disabled on the server)")
                else { clipboard.setPrimaryClip(android.content.ClipData.newPlainText("Remote clipboard", t)); say("Remote clipboard copied (${t.length} characters)") }
            }
        })
        if (input) add(ToolItem("Type phone clipboard", "Types this phone's clipboard text as key presses", Icons.Filled.Keyboard, connected) {
            val t = phoneClip()
            if (t.isNullOrEmpty()) say("The phone's clipboard has no text") else c.type(t.take(4096))
        })
        if (!noShots) add(ToolItem("Screenshot", "Saves the remote screen as a PNG image", Icons.Filled.PhotoCamera, connected) {
            c.screenshot { data ->
                if (data == null) say("No remote screen to save yet")
                else { shot = data; saveShot.launch("Desktop-" + node.name.replace(Regex("[^A-Za-z0-9._-]"), "_") + "-" +
                    java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.US).format(java.util.Date()) + ".png") }
            }
        })
        if (c.displays.size > 1) c.displays.forEach { n ->
            add(ToolItem((if (n == c.display) "✓ " else "") + (if (n == 65535) "All displays" else "Display $n"), "Show this display",
                Icons.Filled.Monitor, connected && n != c.display) { c.setDisplay(n) })
        }
        if (input && c.inputLocked != null) {
            val lock = c.inputLocked != true
            add(ToolItem(if (lock) "Lock remote input" else "Unlock remote input",
                if (lock) "The remote user's mouse and keyboard stop working" else "The remote user can use the mouse and keyboard again",
                if (lock) Icons.Filled.Lock else Icons.Filled.LockOpen, connected) {
                confirm = Triple(if (lock) "Lock the remote user's mouse and keyboard?" else "Unlock the remote user's mouse and keyboard?",
                    if (lock) "Lock" else "Unlock") { c.setInputLock(lock) { say(it) } }
            })
        }
        if (caps.chat && input && windowsAgent) add(ToolItem("Lock computer", "Shows the Windows lock screen", Icons.Filled.Lock, connected) {
            confirm = Triple("Lock the remote computer? The remote user's session goes to the Windows lock screen.", "Lock") { c.lockRemote { say(it) } }
        })
        if (input && node.hasAgent) add(ToolItem("Open a web address", "Opens a page in the remote user's browser", Icons.AutoMirrored.Filled.OpenInNew, node.online) {
            urlDialog = true
        })
    })
    confirm?.let { (text, verb, run) ->
        AlertDialog(onDismissRequest = { confirm = null }, text = { Text(text) },
            confirmButton = { TextButton({ confirm = null; run() }) { Text(verb) } },
            dismissButton = { TextButton({ confirm = null }) { Text("Cancel") } })
    }
    if (urlDialog) {
        var url by remember { mutableStateOf("https://") }
        AlertDialog(onDismissRequest = { urlDialog = false }, title = { Text("Open a web address") },
            text = { OutlinedTextField(url, { url = it.take(2048) }, singleLine = true, placeholder = { Text("https://example.com") }) },
            confirmButton = {
                TextButton({ urlDialog = false; openRemoteUrl(session.ctrl, node, caps, url.trim()) { say(it) } }, enabled = validUrl(url)) { Text("Open") }
            },
            dismissButton = { TextButton({ urlDialog = false }) { Text("Cancel") } })
    }
}

/**
 * Receives the soft keyboard (and hardware keys) directly, like remote-desktop apps: no text field in between, so
 * nothing can be typed twice. No suggestions / composing; any composing text is diffed and replayed.
 */
@SuppressLint("ViewConstructor")
class RemoteInputView(context: Context, private val c: DesktopController) : android.view.View(context) {
    private var composing = ""
    init { isFocusable = true; isFocusableInTouchMode = true }
    override fun onCheckIsTextEditor() = true
    override fun onCreateInputConnection(out: android.view.inputmethod.EditorInfo): android.view.inputmethod.InputConnection {
        out.inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD or
            android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        out.imeOptions = android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI or android.view.inputmethod.EditorInfo.IME_FLAG_NO_FULLSCREEN or
            android.view.inputmethod.EditorInfo.IME_ACTION_NONE
        return object : android.view.inputmethod.BaseInputConnection(this, false) {
            override fun commitText(text: CharSequence, newCursorPosition: Int): Boolean { replace(text.toString()); composing = ""; return true }
            override fun setComposingText(text: CharSequence, newCursorPosition: Int): Boolean { replace(text.toString()); return true }
            override fun finishComposingText(): Boolean { composing = ""; return true }
            override fun deleteSurroundingText(before: Int, after: Int): Boolean { repeat(before.coerceAtMost(64)) { c.key(8, false) }; return true }
            override fun sendKeyEvent(event: android.view.KeyEvent): Boolean { if (event.action == android.view.KeyEvent.ACTION_DOWN) keyDown(event); return true }
        }
    }
    /** composing text replaces the previous composing text: send only the difference */
    private fun replace(text: String) {
        var p = 0
        while (p < composing.length && p < text.length && composing[p] == text[p]) p++
        repeat(composing.length - p) { c.key(8, false) }
        if (text.length > p) c.type(text.substring(p))
        composing = text
    }
    private fun keyDown(e: android.view.KeyEvent): Boolean {
        val code = when (e.keyCode) {
            android.view.KeyEvent.KEYCODE_DEL -> 8; android.view.KeyEvent.KEYCODE_FORWARD_DEL -> 46
            android.view.KeyEvent.KEYCODE_ENTER, android.view.KeyEvent.KEYCODE_NUMPAD_ENTER -> 13
            android.view.KeyEvent.KEYCODE_TAB -> 9; android.view.KeyEvent.KEYCODE_ESCAPE -> 27
            android.view.KeyEvent.KEYCODE_DPAD_LEFT -> 37; android.view.KeyEvent.KEYCODE_DPAD_UP -> 38
            android.view.KeyEvent.KEYCODE_DPAD_RIGHT -> 39; android.view.KeyEvent.KEYCODE_DPAD_DOWN -> 40
            else -> 0
        }
        if (code != 0) { c.key(code, code in 37..40 || code == 46); return true }
        val ch = e.unicodeChar
        if (ch != 0) { c.type(ch.toChar().toString()); return true }
        return false
    }
    override fun onKeyDown(keyCode: Int, event: android.view.KeyEvent): Boolean = keyDown(event) || super.onKeyDown(keyCode, event)
}

/** Key row for the remote keyboard; the soft keyboard itself types through RemoteInputView. */
@Composable
private fun RemoteKeyboard(c: DesktopController, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val input = remember { RemoteInputView(ctx, c) }
    DisposableEffect(Unit) {
        input.post {
            input.requestFocus()
            (ctx.getSystemService(Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).showSoftInput(input, 0)
        }
        onDispose {
            (ctx.getSystemService(Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).hideSoftInputFromWindow(input.windowToken, 0)
        }
    }
    val held by c.held
    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainer)) {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 4.dp, vertical = 2.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
            MODS.forEach { (label, code, _) ->
                val on = code in held
                val toggle = { c.held.value = if (on) held - code else held + code }
                // compact (32 dp): in landscape the phone keyboard leaves only a thin strip of the remote screen
                if (on) Button(toggle, Modifier.height(32.dp), contentPadding = PaddingValues(horizontal = 10.dp)) { Text(label, style = MaterialTheme.typography.labelMedium) }
                else FilledTonalButton(toggle, Modifier.height(32.dp), contentPadding = PaddingValues(horizontal = 10.dp)) { Text(label, style = MaterialTheme.typography.labelMedium) }
            }
            DESK_KEYS.forEach { (label, code, ext) ->
                FilledTonalButton({ c.key(code, ext) }, Modifier.height(32.dp), contentPadding = PaddingValues(horizontal = 10.dp)) {
                    Text(label, style = MaterialTheme.typography.labelMedium) }
            }
        }
        AndroidView({ input }, Modifier.size(1.dp))
    }
}

private class ToolItem(val label: String, val detail: String, val icon: androidx.compose.ui.graphics.vector.ImageVector,
                       val enabled: Boolean, val run: () -> Unit)

/** The desktop tools (desktop_panel's toolbar) as a bottom sheet; a tool closes the sheet and runs. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DesktopToolsSheet(onDismiss: () -> Unit, items: List<ToolItem>) {
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 8.dp)) {
            Text("Tools", Modifier.padding(horizontal = 24.dp, vertical = 4.dp), style = MaterialTheme.typography.titleMedium)
            if (items.isEmpty()) Text("No tools are available with your rights on this device.", Modifier.padding(24.dp))
            items.forEach { t ->
                ListItem(headlineContent = { Text(t.label) }, supportingContent = { Text(t.detail) },
                    leadingContent = { Icon(t.icon, null, tint = MaterialTheme.colorScheme.primary) },
                    modifier = Modifier.clickable(enabled = t.enabled) { onDismiss(); t.run() }.alpha(if (t.enabled) 1f else 0.4f))
            }
        }
    }
}

private class HandleButton(val icon: androidx.compose.ui.graphics.vector.ImageVector, val label: String, val on: Boolean = false, val run: () -> Unit)

/**
 * Fullscreen controls that stay out of the way: one small see-through handle the user can drag to any edge
 * (its place is remembered). A tap opens the buttons next to it; they close again after a few seconds, and the
 * handle fades while unused.
 */
@Composable
private fun androidx.compose.foundation.layout.BoxScope.FullscreenHandle(buttons: List<HandleButton>) {
    val settings = uk.co.cyvelion.meshcentral.McdApp.instance.settings
    val density = androidx.compose.ui.platform.LocalDensity.current
    var open by remember { mutableStateOf(false) }
    var idle by remember { mutableStateOf(false) }
    var touch by remember { mutableIntStateOf(0) }                 // bumps on every use: restarts the timers
    var box by remember { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
    // position as fractions of the screen (survives rotation); default: right edge, a third down
    var fx by remember { mutableStateOf(settings.getString("desk_handle_x").toFloatOrNull() ?: 1f) }
    var fy by remember { mutableStateOf(settings.getString("desk_handle_y").toFloatOrNull() ?: 0.33f) }
    LaunchedEffect(touch, open) {
        idle = false
        kotlinx.coroutines.delay(if (open) 4000 else 2500)
        if (open) open = false else idle = true
    }
    val size = 40.dp
    val sizePx = with(density) { size.toPx() }
    androidx.compose.foundation.layout.Box(Modifier.matchParentSize().onSizeChanged { box = it }) {
        val x = ((box.width - sizePx) * fx).toInt()
        val y = ((box.height - sizePx) * fy).toInt()
        val leftSide = fx < 0.5f
        Row(Modifier.offset { androidx.compose.ui.unit.IntOffset(
                if (open && !leftSide) (x - with(density) { (48.dp * buttons.size + 8.dp).roundToPx() }).coerceAtLeast(0) else x, y) },
            verticalAlignment = Alignment.CenterVertically) {
            @Composable fun handle() = Box(Modifier.size(size)
                .graphicsLayer { alpha = if (idle && !open) 0.35f else 0.9f }
                .background(Color(0xCC16181C), CircleShape)
                .border(1.dp, Color(0x55FFFFFF), CircleShape)
                .pointerInput(Unit) {
                    detectDragGestures(onDragStart = { touch++ }, onDragEnd = {
                        settings.putString("desk_handle_x", fx.toString()); settings.putString("desk_handle_y", fy.toString())
                    }) { change, d ->
                        change.consume()
                        fx = ((fx * (box.width - sizePx) + d.x) / (box.width - sizePx)).coerceIn(0f, 1f)
                        fy = ((fy * (box.height - sizePx) + d.y) / (box.height - sizePx)).coerceIn(0f, 1f)
                        touch++
                    }
                }
                .clickable { open = !open; touch++ }
                .semantics { contentDescription = if (open) "Hide the controls" else "Show the controls" },
                contentAlignment = Alignment.Center) {
                Icon(if (open) Icons.Filled.Close else Icons.Filled.MoreHoriz, null, tint = Color.White, modifier = Modifier.size(22.dp))
            }
            val panel: @Composable () -> Unit = {
                if (open) Row(Modifier.padding(horizontal = 6.dp).background(Color(0xE616181C), RoundedCornerShape(24.dp)).padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    buttons.forEach { b ->
                        IconButton({ b.run(); touch++ }, colors = IconButtonDefaults.iconButtonColors(
                            containerColor = if (b.on) Color(0xFF2F6FD6) else Color.Transparent, contentColor = Color.White)) { Icon(b.icon, b.label) }
                    }
                }
            }
            if (leftSide) { handle(); panel() } else { panel(); handle() }
        }
    }
}
