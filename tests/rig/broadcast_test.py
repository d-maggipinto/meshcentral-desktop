# LOCALHOST TESTING ONLY (xvfb-run). mode=send: app(admin) sends via dialog, raw ws(limited) receives.
# mode=recv: raw ws(admin) broadcasts, app(limited) must show cards (10 s auto-close + sticky).
import sys, ssl, time, json, base64, threading
import rigenv  # puts the app on sys.path (see rigenv.py)
ssl.CERT_REQUIRED = ssl.CERT_NONE
import websocket
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, GLib
from mcdesktop import app as appmod, client
from mcdesktop.admin_panel import BroadcastDialog
appmod.APP_ID = rigenv.TEST_APP_ID
MODE = sys.argv[1]
def raw(u, p):
    b = lambda s: base64.b64encode(s.encode()).decode()
    w = websocket.create_connection("wss://127.0.0.1:8443/control.ashx", header=[f"x-meshauth: {b(u)},{b(p)}"],
                                    sslopt={"cert_reqs": 0}); w.settimeout(1); return w
GOT = []
def listen(w):
    while True:
        try: m = json.loads(w.recv())
        except websocket.WebSocketTimeoutException: continue
        except Exception: return
        if m.get("type") == "notify": GOT.append(m)

class T(appmod.App):
    def do_activate(self):
        u, p = ("admin", "Test-1234") if MODE == "send" else ("limited", "Limit-12345!")
        ctrl = client.ControlConnection("https://127.0.0.1:8443", u, p)
        def ready():
            if ctrl.userinfo:
                self.on_login(ctrl); GLib.timeout_add(1500, self.go); return False
            return True
        ctrl.connect(); GLib.timeout_add(200, ready); self.hold()
    def go(self):
        mw = self.main_win
        if MODE == "send":
            self.rx = raw("limited", "Limit-12345!"); threading.Thread(target=listen, args=(self.rx,), daemon=True).start()
            mw.show_page("usergroups")
            GLib.timeout_add(2000, self.send_step)
        else:
            self.tx = raw("admin", "Test-1234"); time.sleep(0.5)
            self.tx.send(json.dumps({"action": "usergroups"}))
            gid = None
            end = time.time() + 3
            while time.time() < end and not gid:
                try: m = json.loads(self.tx.recv())
                except Exception: continue
                if m.get("action") == "usergroups": gid = next(k for k, v in m["ugroups"].items() if v["name"] == "Admins")
            self.tx.send(json.dumps({"action": "userbroadcast", "msg": "Server maintenance at 18:00 (auto-closes)", "target": gid, "maxtime": 10}))
            self.tx.send(json.dumps({"action": "userbroadcast", "msg": "Sticky message until dismissed", "target": gid, "maxtime": 0}))
            self.t0 = time.time()
            GLib.timeout_add(1500, self.recv_check1)
        return False
    # --- send mode
    def send_step(self):
        mw = self.main_win
        ug = mw._pages["usergroups"]
        gid = next(k for k, v in ug.groups.items() if v.get("name") == "Admins")
        page = ug.open_group(gid)                    # 2.22.0: list + group page (group_panel.py)
        texts = []
        def walk(w):
            if isinstance(w, Gtk.Label): texts.append(w.get_text())
            elif isinstance(w, Gtk.Button) and w.get_label(): texts.append(f"[{w.get_label()} sensitive={w.get_sensitive()}]")
            if isinstance(w, Gtk.Container) and not isinstance(w, Gtk.Button):
                for c in w.get_children(): walk(c)
        walk(page)
        print("GROUP DETAILS:", [t for t in texts if t][:16], flush=True)
        d = BroadcastDialog(mw, mw.ctrl, gid, "Admins")
        d.view.get_buffer().set_text("x" * 600)
        print("600 chars -> Send sensitive:", d.send_btn.get_sensitive(), "| counter:", d.count.get_text(), flush=True)
        d.view.get_buffer().set_text("Hello operators, from the desktop app")
        d.duration.set_active(1)
        d.response(Gtk.ResponseType.OK)
        GLib.timeout_add(2500, self.send_check)
        return False
    def send_check(self):
        print("limited received:", [(m.get("title"), m.get("value"), m.get("maxtime"), m.get("tag")) for m in GOT], flush=True)
        print("SEND ->", "PASS" if any(m.get("value") == "Hello operators, from the desktop app" and m.get("maxtime") == 10 for m in GOT) else "FAIL", flush=True)
        self.quit(); return False
    # --- recv mode
    def cards(self):
        out = []
        for c in self.main_win.notify_box.get_children():
            labels = []
            for w in c.get_children():
                if isinstance(w, Gtk.Label): labels.append(w.get_text())
                elif isinstance(w, Gtk.Box): labels += [x.get_text() for x in w.get_children() if isinstance(x, Gtk.Label)][:1]
            out.append(labels)
        return out
    def recv_check1(self):
        print(f"cards @ {time.time()-self.t0:.0f}s:", self.cards(), flush=True)
        GLib.timeout_add(11000, self.recv_check2); return False
    def recv_check2(self):
        c = self.cards()
        print(f"cards @ {time.time()-self.t0:.0f}s:", c, flush=True)
        ok = len(c) == 1 and "Sticky" in c[0][-1]
        print("RECEIVE ->", "PASS (10 s card closed itself, sticky one stays)" if ok else "FAIL", flush=True)
        self.quit(); return False
T().run([])
