// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.ui

import android.annotation.SuppressLint
import android.content.Context
import android.net.Uri
import android.text.InputType
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import androidx.webkit.JavaScriptReplyProxy
import androidx.webkit.WebMessageCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature

/** Origin of the app's own pages (WebViewAssetLoader): https, no file:// access. */
const val ASSET_ORIGIN = "https://appassets.androidplatform.net"

/**
 * A WebView that shows one of the app's own pages from assets/ and talks to it through the "mcd" message
 * port, which only that origin can use. It never navigates anywhere else.
 */
@SuppressLint("SetJavaScriptEnabled")
class AssetPage(context: Context, page: String, rawKeyboard: Boolean = false, private val onMessage: (String) -> Unit) {
    val view: WebView = if (rawKeyboard) RawKeyboardWebView(context) else WebView(context)
    private var reply: JavaScriptReplyProxy? = null
    private val queue = ArrayList<String>()

    init {
        view.layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(context))
            .build()
        view.settings.javaScriptEnabled = true
        view.settings.allowFileAccess = false
        view.settings.allowContentAccess = false
        view.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(v: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)
            override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest) = true
            // the page's renderer crashed or was killed for memory: the app stays up, the page is gone
            override fun onRenderProcessGone(v: WebView, detail: android.webkit.RenderProcessGoneDetail): Boolean { reply = null; return true }
        }
        view.webChromeClient = object : android.webkit.WebChromeClient() {
            override fun onConsoleMessage(m: android.webkit.ConsoleMessage): Boolean {
                if (uk.co.cyvelion.meshcentral.BuildConfig.DEBUG) android.util.Log.d("McdWeb", "${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                return true
            }
        }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(view, "mcd", setOf(ASSET_ORIGIN)) { _, message: WebMessageCompat, _: Uri, isMainFrame, proxy ->
                if (!isMainFrame) return@addWebMessageListener
                reply = proxy
                message.data?.let(onMessage)
            }
        }
        view.loadUrl("$ASSET_ORIGIN/assets/$page")
    }

    /** Messages before the page said "ready" are queued. */
    @SuppressLint("RequiresFeature")         // reply is only ever set by the listener, which needs the feature
    fun post(json: String) {
        val r = reply
        if (r == null) queue.add(json) else r.postMessage(json)
    }

    @SuppressLint("RequiresFeature")
    fun ready() {
        val r = reply ?: return
        queue.forEach { r.postMessage(it) }
        queue.clear()
    }

    fun destroy() {
        reply = null
        view.destroy()
    }
}

/**
 * A WebView whose soft keyboard sends plain keys: no suggestions, auto-correct or composing text, which made
 * xterm.js repeat letters (the keyboard re-sends the whole composing word). Same trick as native terminals.
 */
class RawKeyboardWebView(context: Context) : WebView(context) {
    override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection? {
        val ic = super.onCreateInputConnection(outAttrs)
        outAttrs.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD or
            InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        outAttrs.imeOptions = outAttrs.imeOptions or EditorInfo.IME_FLAG_NO_EXTRACT_UI or EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        return ic
    }
}
