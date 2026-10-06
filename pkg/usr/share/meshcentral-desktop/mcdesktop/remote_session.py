# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Things done in the remote user's desktop session through one-shot agent console evals.

The stock agent shows Linux notifications / message boxes and opens web pages from its own service context:
xdg-open and notify-send then miss the desktop's DISPLAY / D-Bus (fails or is very slow on many Linux
desktops), and the chat page always opens as a plain browser tab. With the agent console right (8 + 16) these
evals find the console user's session (environment from /proc on Linux, the Windows session's user) and start
the program as that user. Every console command is logged by the server; nothing stays in the agent except the
saved XFCE background styles. Agent-JS rules: no double quote and no backslash in the JS.
Answers come back as console text "TAG:word" (the agent quotes the value).
"""
import base64
import re

from gi.repository import GLib

from . import ui

LINUX_ENV_JS = (
    "var fs=require('fs'),NL=String.fromCharCode(10),uid=require('user-sessions').consoleUid();"
    "function senv(){var ps=fs.readdirSync('/proc'),fb=null;for(var i=0;i<ps.length;i++){var p=ps[i];"
    "if(!(parseInt(p)>0))continue;try{var ls=fs.readFileSync('/proc/'+p+'/status').toString().split(NL);"
    "var u=-1;for(var j=0;j<ls.length;j++){if(ls[j].indexOf('Uid:')==0){u=parseInt(ls[j].substring(4).trim());"
    "break;}}if(u!=uid)continue;var b=fs.readFileSync('/proc/'+p+'/environ'),e={},st=0;"
    "for(var k=0;k<=b.length;k++){if(k==b.length||b[k]==0){if(k>st){var kv=b.slice(st,k).toString();"
    "var q=kv.indexOf('=');if(q>0){e[kv.substring(0,q)]=kv.substring(q+1);}}st=k+1;}}"
    "if(!e.DISPLAY&&!e.WAYLAND_DISPLAY)continue;var r={},K=['DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS',"
    "'HOME','USER','LOGNAME','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','PATH','LANG','XDG_CURRENT_DESKTOP',"
    "'XDG_SESSION_TYPE'];for(var m=0;m<K.length;m++){if(e[K[m]]){r[K[m]]=e[K[m]];}}"
    "if(r.DBUS_SESSION_BUS_ADDRESS){return r;}if(!fb){fb=r;}}catch(x){}}return fb;}"
    "var E=senv(),root=false;try{root=require('user-sessions').isRoot();}catch(x){}"
    "var O=root?{uid:uid,env:E}:{env:E};")
URL_JS = (
    "(function(){try{" + LINUX_ENV_JS +
    "if(!E){return 'MCDURL:nodisplay';}var url=Buffer.from('%s','base64').toString();"
    "if(url.indexOf('http://')!=0&&url.indexOf('https://')!=0){return 'MCDURL:bad';}"
    "var x='/usr/bin/xdg-open';if(!fs.existsSync(x)){return 'MCDURL:noxdg';}"
    "var c=require('child_process').execFile(x,['xdg-open',url],O);"
    "c.stdout.on('data',function(){});c.stderr.on('data',function(){});return 'MCDURL:ok';}"
    "catch(z){return 'MCDURL:err';}})()")
BG_JS = (
    "(function(){try{" + LINUX_ENV_JS +
    "var q='/usr/bin/xfconf-query';if(!E||!fs.existsSync(q)||"
    "(E.XDG_CURRENT_DESKTOP||'').toUpperCase().indexOf('XFCE')<0){return 'MCDBG:other';}"
    "function run(a){var c=require('child_process').execFile(q,['xfconf-query','-c','xfce4-desktop'].concat(a),O);"
    "c.stdout.str='';c.stdout.on('data',function(d){this.str+=d.toString();});c.stderr.on('data',function(){});"
    "c.waitExit();return c.stdout.str;}var A=require('MeshAgent');"
    "if(A.__mcdBg){var s=A.__mcdBg;for(var p in s){run(['-p',p,'-s',s[p]]);}A.__mcdBg=null;return 'MCDBG:shown';}"
    "var ls=run(['-l']).split(NL),sv={},n=0;for(var i=0;i<ls.length;i++){var p=ls[i].trim();"
    "if(p.length>12&&p.substring(p.length-12)=='/image-style'){sv[p]=run(['-p',p]).trim();"
    "run(['-p',p,'-s','0']);n++;}}if(!n){return 'MCDBG:other';}A.__mcdBg=sv;return 'MCDBG:hidden';}"
    "catch(z){return 'MCDBG:err';}})()")

# Linux: toast / message box / alert box with the session's own tools. @K@ = toast | msg | alert, @W@ = message
# box time limit in seconds (0 = until dismissed). zenity and notify-send bodies are Pango markup -> escaped.
NOTIFY_JS = (
    "(function(){try{" + LINUX_ENV_JS +
    "if(!E){return 'MCDNOTE:nodisplay';}var t=Buffer.from('@T@','base64').toString(),"
    "m=Buffer.from('@M@','base64').toString(),k='@K@',w=@W@;"
    "function esc(s){return s.split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;');}"
    "function f(n){var D=['/usr/bin/','/bin/','/usr/local/bin/'];for(var i=0;i<D.length;i++){"
    "if(fs.existsSync(D[i]+n)){return D[i]+n;}}return null;}var p=null,a=null;"
    "if(k=='toast'&&E.DBUS_SESSION_BUS_ADDRESS&&(p=f('notify-send'))){a=['notify-send','-a','MeshCentral',t,esc(m)];}"
    "else if(p=f('zenity')){a=(k=='toast')?['zenity','--notification','--text='+esc(t)+NL+esc(m)]:"
    "['zenity',(k=='alert')?'--warning':'--info','--title='+t,'--text='+esc(m),'--width=360'];"
    "if(k=='msg'&&w>0){a.push('--timeout='+w);}}"
    "else if(p=f('kdialog')){a=(k=='toast')?['kdialog','--title',t,'--passivepopup',m,'10']:"
    "['kdialog','--title',t,'--msgbox',m];}"
    "else if(p=f('xmessage')){a=['xmessage','-center','-title',t,m];if(k=='msg'&&w>0){a.push('-timeout',String(w));}}"
    "if(!a){return 'MCDNOTE:notool';}var c=require('child_process').execFile(p,a,O);"
    "c.stdout.on('data',function(){});c.stderr.on('data',function(){});return 'MCDNOTE:ok';}"
    "catch(z){return 'MCDNOTE:err';}})()")

# Linux: the chat page as an app window (Chromium-family --app: no tabs, no address bar), else the default
# browser through xdg-open. Answers MCDCHAT:app | browser | nodisplay | noapp | bad | err.
CHAT_LINUX_JS = (
    "(function(){try{" + LINUX_ENV_JS +
    "if(!E){return 'MCDCHAT:nodisplay';}var url=Buffer.from('@U@','base64').toString();"
    "if(url.indexOf('https://')!=0){return 'MCDCHAT:bad';}"
    "var B=['google-chrome','google-chrome-stable','chromium','chromium-browser','microsoft-edge',"
    "'microsoft-edge-stable','brave-browser','vivaldi'],D=['/usr/bin/','/usr/local/bin/','/snap/bin/'],p=null,a=null;"
    "for(var i=0;i<B.length&&!p;i++){for(var j=0;j<D.length;j++){if(fs.existsSync(D[j]+B[i])){p=D[j]+B[i];break;}}}"
    "var r='app';if(p){a=[B[i-1],'--app='+url,'--window-size=440,640'];}"
    "else if(fs.existsSync('/usr/bin/xdg-open')){p='/usr/bin/xdg-open';a=['xdg-open',url];r='browser';}"
    "else{return 'MCDCHAT:noapp';}var c=require('child_process').execFile(p,a,O);"
    "c.stdout.on('data',function(){});c.stderr.on('data',function(){});return 'MCDCHAT:'+r;}"
    "catch(z){return 'MCDCHAT:err';}})()")

# Windows: the chat page as a Microsoft Edge app window, started like the agent's own openUrl (a one-shot
# scheduled task as the signed-in user, win-tasks). The user is the console session's, else the first active
# session's (a user signed in through Remote Desktop).
CHAT_WINDOWS_JS = (
    "(function(){try{var B=String.fromCharCode(92),us=require('user-sessions'),fs=require('fs'),u='',d='';"
    "try{var c=us.consoleUid();u=us.getUsername(c);d=us.getDomain(c);}catch(x){}"
    "if(!u){var S=us.Current();for(var k in S){if(S[k].State=='Active'&&S[k].Username){u=S[k].Username;"
    "d=S[k].Domain;break;}}}if(!u){return 'MCDCHAT:nouser';}"
    "var e=null,P=[process.env['ProgramFiles(x86)'],process.env['ProgramFiles']];"
    "for(var i=0;i<P.length;i++){if(!P[i]){continue;}var p=P[i]+B+'Microsoft'+B+'Edge'+B+'Application'+B+'msedge.exe';"
    "if(fs.existsSync(p)){e=p;break;}}if(!e){return 'MCDCHAT:noapp';}"
    "var url=Buffer.from('@U@','base64').toString();if(url.indexOf('https://')!=0){return 'MCDCHAT:bad';}"
    "var t=require('win-tasks'),n='MeshChatTask';t.addTask({name:n,user:u,domain:d,execPath:e,"
    "arguments:['--app='+url,'--window-size=440,640']});t.getTask({name:n}).run();t.deleteTask(n);"
    "return 'MCDCHAT:app';}catch(z){return 'MCDCHAT:err';}})()")


def _b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def linux_session(node, caps):
    """The Linux session tools apply: a Linux agent and the right to use its console."""
    return bool(node.get("agent")) and not ui.is_windows(node) and caps.console


def agent_eval(ctrl, nodeid, js, tag, done, secs=20):
    """One console eval; done(word after 'TAG:') or done(None) on timeout (on the GTK loop)."""
    state = {"done": False}

    def reply(msg):
        v = str(msg.get("value") or "")
        if state["done"] or msg.get("type") != "console" or tag + ":" not in v:
            return
        finish()
        m = re.search(re.escape(tag) + r":([a-z]+)", v)
        done(m.group(1) if m else "")

    def finish():
        state["done"] = True
        ctrl.off("msg", reply)

    def timeout():
        if not state["done"]:
            finish()
            done(None)
        return False
    ctrl.on("msg", reply)
    ctrl.send_node_msg(nodeid, "console", value='eval "%s"' % js)
    GLib.timeout_add_seconds(secs, timeout)


def send_stock_notification(ctrl, node, kind, title, msg, minutes=2):
    """The web UI's messages: toast / message box (time limit in ms) / alert box."""
    if kind == "toast":
        ctrl.send({"action": "toast", "nodeids": [node["_id"]], "title": title, "msg": msg})
    elif kind == "msg":
        ctrl.send({"action": "msg", "type": "messagebox", "nodeid": node["_id"], "title": title, "msg": msg,
                   "timeout": int(minutes) * 60000})
    else:
        ctrl.send({"action": "msg", "type": "alertbox", "nodeid": node["_id"], "title": title, "msg": msg})


def notify(ctrl, node, caps, kind, title, msg, minutes=2, report=None):
    """kind toast | msg | alert. Linux devices with console rights: shown directly in the user's session
    (falls back to the stock message when the session or a tool is missing); others: the stock message."""
    if not linux_session(node, caps):
        send_stock_notification(ctrl, node, kind, title, msg, minutes)
        return

    def done(r):
        if r == "ok":
            if report:
                report("Shown on the remote computer")
        else:
            send_stock_notification(ctrl, node, kind, title, msg, minutes)
            if report:
                report("Sent through the agent (no desktop session tool found)" if r in ("nodisplay", "notool")
                       else "Sent through the agent")
    js = (NOTIFY_JS.replace("@T@", _b64(title)).replace("@M@", _b64(msg)).replace("@K@", kind)
          .replace("@W@", str(int(minutes) * 60 if kind == "msg" else 0)))
    agent_eval(ctrl, node["_id"], js, "MCDNOTE", done)


def open_chat_page(ctrl, node, caps, url, report=None):
    """Open the server's chat page (url, no login cookie) for the remote user: an app window when the console
    right allows it, else the stock path (server -> agent openUrl, a browser tab). report(text) on the GTK loop."""
    def stock():
        ctrl.send({"action": "meshmessenger", "nodeid": node["_id"]})
        if report:
            report("The chat was opened in the remote user's web browser")
    if not (node.get("agent") and caps.console):
        stock()
        return

    def done(r):
        if r == "app":
            if report:
                report("The chat window was opened on the remote computer")
        elif r == "browser":
            if report:
                report("The chat was opened in the remote user's web browser")
        else:
            stock()
    js = (CHAT_WINDOWS_JS if ui.is_windows(node) else CHAT_LINUX_JS).replace("@U@", _b64(url))
    agent_eval(ctrl, node["_id"], js, "MCDCHAT", done)
