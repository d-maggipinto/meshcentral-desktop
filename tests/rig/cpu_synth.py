import sys, os, time
import rigenv  # puts the app on sys.path (see rigenv.py)
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from mcdesktop import server_panel as sp
SP = os.path.dirname(os.path.abspath(__file__))
Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
now = time.time()
def samp(dt, cpu=None, first=False):
    s = {"time": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + dt)), "conn": {"ca": 12, "cu": 1, "us": 2, "rs": 0, "am": 0}}
    if cpu is not None: s["cpu"] = cpu
    if first: s["first"] = True
    return s
samples = [samp(-3 * 3600 + i * 300) for i in range(33)] + [samp(-240, {"0": 0}, first=True), samp(+90, {"0": 0.15})]
class P:  # just the bits _render_chart needs
    pass
win = Gtk.Window(); win.resize(1400, 560)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
info = Gtk.Label(xalign=1); chart = sp.TimeChart()
box.pack_start(info, False, False, 4); box.pack_start(chart, True, True, 0); win.add(box); win.show_all()
p = P(); p.chart = chart; p.chart_info = info; p._timeline = samples
p.chart_kind = type("K", (), {"get_active": lambda self: 2})(); p.chart_log = type("L", (), {"get_active": lambda self: False})()
p._hours = lambda: 3
sp.MyServerPanel._render_chart(p)
print("info:", info.get_text())
def snap():
    a = win.get_allocation(); Gdk.pixbuf_get_from_window(win.get_window(), 0, 0, a.width, a.height).savev(f"{SP}/cpu-fixed.png", "png", [], [])
    Gtk.main_quit(); return False
GLib.timeout_add(500, snap); Gtk.main()
