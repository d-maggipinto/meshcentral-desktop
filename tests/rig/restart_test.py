# LOCALHOST TESTING ONLY (run under xvfb-run): agentupdate with desktop connected + sync/hotkeys on.
# Measures GTK main-loop stalls, device online state in the app, and when the agent answers again.
import sys, ssl, time, json
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, WebKit2
from mcdesktop import app as appmod, client, ui
from mcdesktop.desktop_panel import DesktopPanel
from mcdesktop.tools_panel import ConsolePanel
appmod.APP_ID = rigenv.TEST_APP_ID

T0 = [None]
SP = rigenv.RIG_DIR
def ts(): return f"{time.time() - T0[0]:6.1f}s" if T0[0] else "   pre"

class T(appmod.App):
    def do_activate(self):
        orig = self.web_context
        def wc():
            c = orig(); c.set_tls_errors_policy(WebKit2.TLSErrorsPolicy.IGNORE); return c
        self.web_context = wc
        ctrl = client.ControlConnection("https://127.0.0.1:8443", "admin", "Test-1234")
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(2000, self.pick); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready)
        self.hold()
        # main-loop stall monitor
        self.last_tick = time.time(); self.max_gap = 0
        def tick():
            now = time.time(); gap = now - self.last_tick; self.last_tick = now
            if gap > 0.5: print(f"{ts()}  !! MAIN LOOP STALL {gap:.1f}s", flush=True)
            self.max_gap = max(self.max_gap, gap); return True
        GLib.timeout_add(100, tick)
    def tab(self, label):
        return next(t["panel"] for t in self.main_win._device_tabs if t["label"] == label)
    def pick(self):
        mw = self.main_win
        self.node = node = next(n for n in mw.nodes.values() if n.get("conn", 0) & 1)
        self.nid = node["_id"]
        mw._open_node_id = node["_id"]; mw.current = node; mw._open_device(node)
        GLib.timeout_add(500, lambda: (mw.goto_device_tab("Desktop"), False)[1])
        GLib.timeout_add(500, self.wait)
        return False
    def wait(self):
        p = self.tab("Desktop")
        if isinstance(p, DesktopPanel) and p._connected and not p._cover.get_visible():
            self.main_win.goto_device_tab("Console")
            GLib.timeout_add(1500, self.update)
            return False
        return True
    def update(self):
        c = self.tab("Console")
        self.console = c
        import subprocess
        T0[0] = time.time()
        subprocess.run("pkill -KILL -f '[m]eshagent connect'", shell=True)
        print(f"{ts()}  KILLED agent (simulates agentupdate execv restart)", flush=True)
        def restart():
            subprocess.Popen("cd %s/mctest/agent && exec ./meshagent connect > agent.log 2>&1" % SP, shell=True,
                             start_new_session=True)
            print(f"{ts()}  RESTARTED agent", flush=True); return False
        GLib.timeout_add(20000, restart)
        self.last_state = None; self.last_lines = 0; self.answered = False
        GLib.timeout_add(500, self.watch)
        GLib.timeout_add(5000, self.probe)
        return False
    def probe(self):
        if self.answered or time.time() - T0[0] > 240: return False
        self.console.entry.set_text("help"); self.console.send()
        return True
    def watch(self):
        mw = self.main_win
        n = mw.nodes.get(self.nid) or {}
        online = ui.is_online(n)
        d = self.tab("Desktop")
        st = f"tree:{'online' if online else 'OFFLINE'} desktop:{getattr(d, '_phase', '?')}"
        if st != self.last_state:
            print(f"{ts()}  {st}", flush=True); self.last_state = st
        buf = self.console.buffer
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        lines = text.splitlines()
        for l in lines[self.last_lines:]:
            if l.strip() and not l.startswith("> help"): print(f"{ts()}  console: {l[:90]}", flush=True)
            if "Available commands" in l and T0[0]: self.answered = True
        self.last_lines = len(lines)
        if self.answered:
            print(f"{ts()}  AGENT ANSWERS AGAIN | max main-loop gap overall: {self.max_gap:.2f}s", flush=True)
            GLib.timeout_add(3000, lambda: (print(f"{ts()}  final: {self.last_state}", flush=True), self.quit(), False)[2])
            return False
        if time.time() - T0[0] > 240:
            print(f"{ts()}  TIMEOUT: agent never answered | max gap {self.max_gap:.2f}s", flush=True); self.quit(); return False
        return True

T().run([])
