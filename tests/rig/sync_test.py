# LOCALHOST TESTING ONLY: automatic clipboard sync plumbing against an agent with the empty-display bug.
import sys, ssl, time, json
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, WebKit2
from mcdesktop import app as appmod, client
from mcdesktop.desktop_panel import DesktopPanel
appmod.APP_ID = rigenv.TEST_APP_ID

SENT = []
_orig_send = client.ControlConnection.send_node_msg
BLOCK_POLL = [False]
def spy(self, nodeid, mtype, **kw):
    if mtype == "getclip" and BLOCK_POLL[0]:
        return    # rig only: local and "remote" share one clipboard, so hide the remote side briefly
    SENT.append((round(time.time(), 2), mtype, kw.get("data") if mtype == "setclip" else kw.get("tag") if mtype == "getclip" else str(kw.get("value"))[:30]))
    return _orig_send(self, nodeid, mtype, **kw)
client.ControlConnection.send_node_msg = spy
REMOTE_SEEN = []
_orig_rem = DesktopPanel._sync_on_remote
def rem(self, data):
    REMOTE_SEEN.append(data); return _orig_rem(self, data)
DesktopPanel._sync_on_remote = rem

class T(appmod.App):
    def do_activate(self):
        orig = self.web_context
        def wc():
            c = orig(); c.set_tls_errors_policy(WebKit2.TLSErrorsPolicy.IGNORE); return c
        self.web_context = wc
        self.ctrl0 = ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        self.patch_replies = []
        def ready():
            if ctrl.userinfo:
                ctrl.on("msg", lambda m: m.get("type") == "console" and "MCDPATCH" in str(m.get("value")) and self.patch_replies.append(m.get("value")))
                self.on_login(ctrl); GLib.timeout_add(2000, self.pick); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready)
        self.hold()
    def panel(self):
        return next(t["panel"] for t in self.main_win._device_tabs if t["label"] == "Desktop")
    def pick(self):
        mw = self.main_win
        self.node = node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(500, lambda: (mw.goto_device_tab("Desktop"), False)[1])
        GLib.timeout_add(500, self.wait)
        return False
    def wait(self):
        p = self.panel()
        if isinstance(p, DesktopPanel) and p._connected and not p._cover.get_visible():
            print("connected; sync switch:", p.clip_sync.get_active(), flush=True)
            GLib.timeout_add(3500, self.step_local)
            return False
        return True
    def step_local(self):
        p = self.panel()
        print("patch reply:", self.patch_replies, "| tag3 replies so far:", len(REMOTE_SEEN), flush=True)
        self.mark_local = "local-copy-%d" % int(time.time())
        self.n0 = len(SENT)
        BLOCK_POLL[0] = True
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.mark_local, -1)   # user copies locally
        GLib.timeout_add(3000, lambda: (BLOCK_POLL.__setitem__(0, False), False)[1])
        GLib.timeout_add(5000, self.step_remote)
        return False
    def step_remote(self):
        sets = [s for s in SENT[self.n0:] if s[1] == "setclip"]
        print("LOCAL->REMOTE: setclip sent:", [s[2] for s in sets], "->",
              "PASS" if len(sets) == 1 and sets[0][2] == self.mark_local else "FAIL", flush=True)
        # remote-side change: write via the (patched) agent writer, like a copy on the remote
        self.mark_remote = "remote-copy-%d" % int(time.time())
        self.n1 = len(SENT); self.r1 = len(REMOTE_SEEN)
        self.main_win.ctrl.send_node_msg(self.node["_id"], "console",
            value='eval "(function(){require(\'clipboard\').dispatchWrite(\'' + self.mark_remote + '\');return 1;})()"')
        GLib.timeout_add(5000, self.finish)
        return False
    def finish(self):
        p = self.panel()
        seen = REMOTE_SEEN[self.r1:]
        sets = [s for s in SENT[self.n1:] if s[1] == "setclip"]
        polls = [s for s in SENT if s[1] == "getclip"]
        print("REMOTE->LOCAL: poll saw remote value:", self.mark_remote in seen, "| status:", p.status.get_text())
        print("echo check: setclips after remote change:", len(sets), "(0 or 1 ok, no storm)")
        print("polls sent:", len(polls), "| all tag 3:", all(s[2] == 3 for s in polls))
        self.quit(); return False

T().run([])
