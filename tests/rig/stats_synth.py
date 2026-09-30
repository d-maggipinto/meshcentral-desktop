# Render the Stats chart with synthetic data shaped like the maintainer's server (no network).
import sys, os, time, math, random
import rigenv  # puts the app on sys.path (see rigenv.py)
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from mcdesktop import server_panel as sp
SP = os.path.dirname(os.path.abspath(__file__))
settings = Gtk.Settings.get_default(); settings.set_property("gtk-application-prefer-dark-theme", True)
now = time.time(); samples = []
for i in range(36):
    t = now - 3 * 3600 + i * 300
    if 27 <= i <= 28: continue                      # server down for 10 minutes
    ca = 12 if i < 23 else (11 if i == 24 else 13)
    busy = 18 <= i <= 21
    s = {"time": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t)),
         "conn": {"ca": ca, "cu": 1, "us": 3 if busy else 2, "rs": 2 if busy else 0, "am": 0},
         "mem": {"rss": 180e6 + i * 1e6, "heapTotal": 90e6, "heapUsed": 60e6 + 5e6 * math.sin(i / 3), "external": 20e6},
         "cpu": [0.2 + 0.3 * (busy) + random.random() * 0.1, 0.2, 0.2],
         "traffic": {"AgentCtrlIn": 3e5, "httpIn": 1e6 + 2e5 * math.sin(i), "relayIn": [0, 0, 8e6 if busy else 0],
                     "AgentCtrlOut": 2e5, "httpOut": 3e6, "relayOut": [0, 0, 2e7 if busy else 0]}}
    if i == 29: s["first"] = True
    samples.append(s)
win = Gtk.Window(); win.resize(1500, 620)
chart = sp.TimeChart(); win.add(chart); win.show_all()
def render(kind, name, log=False, hover=None):
    chart.set_data(sp.build_series(samples, kind), now - 3 * 3600, now, sp.Y_TITLES[kind],
                   stacked=kind in ("in", "out"), log=log)
    chart.hover = hover
    def snap():
        a = win.get_allocation()
        Gdk.pixbuf_get_from_window(win.get_window(), 0, 0, a.width, a.height).savev(f"{SP}/{name}.png", "png", [], [])
        return False
    GLib.timeout_add(300, snap)
seq = [("connections", "synth-connections", False, 900), ("in", "synth-inbound", False, None), ("memory", "synth-memory", False, None)]
def step():
    if not seq: Gtk.main_quit(); return False
    k, n, l, h = seq.pop(0); render(k, n, l, h); GLib.timeout_add(700, step); return False
GLib.timeout_add(300, step); Gtk.main()
