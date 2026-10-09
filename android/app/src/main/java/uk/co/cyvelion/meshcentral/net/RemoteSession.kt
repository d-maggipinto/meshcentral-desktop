// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CYVELION LTD. Unofficial MeshCentral client, see NOTICE.
package uk.co.cyvelion.meshcentral.net

import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import uk.co.cyvelion.meshcentral.data.Node
import uk.co.cyvelion.meshcentral.data.NodeCaps

/*
 * Things done in the remote user's desktop session through one-shot agent console evals, the same scripts as the
 * desktop app's remote_session.py (generated from it: keep them identical). Every console command is logged by the
 * server. Answers come back as console text "TAG:word".
 */

/** Linux: the chat page as an app window (Chromium-family --app), else the default browser. @U@ = base64 URL. */
internal const val CHAT_LINUX_JS = "(function(){try{var fs=require('fs'),NL=String.fromCharCode(10),uid=require('user-sessions').consoleUid();function senv(){var ps=fs.readdirSync('/proc'),fb=null;for(var i=0;i<ps.length;i++){var p=ps[i];if(!(parseInt(p)>0))continue;try{var ls=fs.readFileSync('/proc/'+p+'/status').toString().split(NL);var u=-1;for(var j=0;j<ls.length;j++){if(ls[j].indexOf('Uid:')==0){u=parseInt(ls[j].substring(4).trim());break;}}if(u!=uid)continue;var b=fs.readFileSync('/proc/'+p+'/environ'),e={},st=0;for(var k=0;k<=b.length;k++){if(k==b.length||b[k]==0){if(k>st){var kv=b.slice(st,k).toString();var q=kv.indexOf('=');if(q>0){e[kv.substring(0,q)]=kv.substring(q+1);}}st=k+1;}}if(!e.DISPLAY&&!e.WAYLAND_DISPLAY)continue;var r={},K=['DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','HOME','USER','LOGNAME','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','PATH','LANG','XDG_CURRENT_DESKTOP','XDG_SESSION_TYPE','XDG_DATA_DIRS','XDG_CONFIG_DIRS','XDG_SESSION_DESKTOP','DESKTOP_SESSION'];for(var m=0;m<K.length;m++){if(e[K[m]]){r[K[m]]=e[K[m]];}}if(r.DBUS_SESSION_BUS_ADDRESS){return r;}if(!fb){fb=r;}}catch(x){}}return fb;}var E=senv(),root=false;try{root=require('user-sessions').isRoot();}catch(x){}var O=root?{uid:uid,env:E}:{env:E};var RU=null,UN=null;if(root){var RP=['/usr/sbin/runuser','/sbin/runuser','/usr/bin/runuser'];for(var i=0;i<RP.length;i++){if(fs.existsSync(RP[i])){RU=RP[i];break;}}try{UN=require('user-sessions').getUsername(uid);}catch(x){}}function X(p,a){var cp=require('child_process');if(RU&&UN){var ev=[];for(var k in E){ev.push(k+'='+E[k]);}return cp.execFile(RU,['runuser','-u',UN,'--','/usr/bin/env'].concat(ev).concat([p]).concat(a.slice(1)),{env:{PATH:'/usr/sbin:/usr/bin:/sbin:/bin'}});}return cp.execFile(p,a,O);}if(!E){return 'MCDCHAT:nodisplay';}var url=Buffer.from('@U@','base64').toString();if(url.indexOf('https://')!=0){return 'MCDCHAT:bad';}var B=['google-chrome','google-chrome-stable','chromium','chromium-browser','microsoft-edge','microsoft-edge-stable','brave-browser','vivaldi'],D=['/usr/bin/','/usr/local/bin/','/snap/bin/'],p=null,a=null;for(var i=0;i<B.length&&!p;i++){for(var j=0;j<D.length;j++){if(fs.existsSync(D[j]+B[i])){p=D[j]+B[i];break;}}}var r='app';if(p){a=[B[i-1],'--app='+url,'--window-size=360,520','--user-data-dir='+E.HOME+'/.cache/meshcentral-chat','--no-first-run','--no-default-browser-check'];}else if(fs.existsSync('/usr/bin/xdg-open')){p='/usr/bin/xdg-open';a=['xdg-open',url];r='browser';}else{return 'MCDCHAT:noapp';}var c=X(p,a);c.stdout.on('data',function(){});c.stderr.on('data',function(){});return 'MCDCHAT:'+r;}catch(z){return 'MCDCHAT:err';}})()"

/** Windows: the chat page as a Microsoft Edge app window for the signed-in user (win-tasks). */
internal const val CHAT_WINDOWS_JS = "(function(){try{var B=String.fromCharCode(92),us=require('user-sessions'),fs=require('fs'),u='',d='';try{var c=us.consoleUid();u=us.getUsername(c);d=us.getDomain(c);}catch(x){}if(!u){var S=us.Current();for(var k in S){if(S[k].State=='Active'&&S[k].Username){u=S[k].Username;d=S[k].Domain;break;}}}if(!u){return 'MCDCHAT:nouser';}var e=null,P=[process.env['ProgramFiles(x86)'],process.env['ProgramFiles']];for(var i=0;i<P.length;i++){if(!P[i]){continue;}var p=P[i]+B+'Microsoft'+B+'Edge'+B+'Application'+B+'msedge.exe';if(fs.existsSync(p)){e=p;break;}}if(!e){return 'MCDCHAT:noapp';}var url=Buffer.from('@U@','base64').toString();if(url.indexOf('https://')!=0){return 'MCDCHAT:bad';}var Q=String.fromCharCode(34),pub=process.env['PUBLIC']||((process.env['SystemDrive']||'C:')+B+'Users'+B+'Public'),dir=pub+B+'MeshCentralChat'+B+String(u).replace(/[^A-Za-z0-9._-]/g,'_'),t=require('win-tasks'),n='MeshChatTask';t.addTask({name:n,user:u,domain:d,execPath:e,arguments:['--app='+url,'--window-size=360,520','--user-data-dir='+Q+dir+Q,'--no-first-run','--no-default-browser-check']});t.getTask({name:n}).run();t.deleteTask(n);return 'MCDCHAT:app';}catch(z){return 'MCDCHAT:err';}})()"


/** One console eval; done(word after "TAG:") or done(null) on timeout, on the main thread. */
fun agentEval(ctrl: ControlConnection, nodeId: String, js: String, tag: String, secs: Long = 20, done: (String?) -> Unit) {
    var finished = false
    val main = Handler(Looper.getMainLooper())
    lateinit var reply: (JSONObject) -> Unit
    val timeout = Runnable { if (!finished) { finished = true; ctrl.off("msg", reply); done(null) } }
    reply = { m ->
        val v = m.optString("value")
        if (!finished && m.optString("type") == "console" && m.optString("nodeid", nodeId) == nodeId && v.contains("$tag:")) {
            finished = true
            ctrl.off("msg", reply)
            main.removeCallbacks(timeout)
            done(Regex(Regex.escape(tag) + ":([a-z]+)").find(v)?.groupValues?.get(1) ?: "")
        }
    }
    ctrl.on("msg", reply)
    ctrl.nodeMsg(nodeId, "console", "value" to "eval \"$js\"")
    main.postDelayed(timeout, secs * 1000)
}

/**
 * Open the server's chat page for the remote user: an app window when the console right allows it, else the
 * stock path (server -> agent openUrl, a browser tab). report(text) describes what happened.
 */
fun openChatPage(ctrl: ControlConnection, node: Node, caps: NodeCaps, url: String, report: (String) -> Unit) {
    // test rigs only: `adb shell setprop debug.mcd.noremote 1` keeps the remote side closed (debug builds)
    if (uk.co.cyvelion.meshcentral.BuildConfig.DEBUG && sysProp("debug.mcd.noremote") == "1") { report("(debug) remote chat window not opened"); return }
    fun stock() {
        ctrl.send("action" to "meshmessenger", "nodeid" to node.id)
        report("The chat was opened in the remote user's web browser")
    }
    if (!(node.hasAgent && caps.console)) { stock(); return }
    val js = (if (node.isWindows) CHAT_WINDOWS_JS else CHAT_LINUX_JS).replace("@U@", b64(url))
    agentEval(ctrl, node.id, js, "MCDCHAT") { r ->
        when (r) {
            "app" -> report("The chat window was opened on the remote computer")
            "browser" -> report("The chat was opened in the remote user's web browser")
            else -> stock()
        }
    }
}

@android.annotation.SuppressLint("PrivateApi")
private fun sysProp(name: String): String = try {
    Class.forName("android.os.SystemProperties").getMethod("get", String::class.java).invoke(null, name) as String
} catch (e: Exception) { "" }
