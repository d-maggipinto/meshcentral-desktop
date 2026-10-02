# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows CI helper: screenshot of a GTK window's screen area (includes WebView2 content)."""
import ctypes
from ctypes import wintypes

from gi.repository import GLib, GdkPixbuf


def screenshot(widget, path):
    """BitBlt the window's screen area (includes the DirectComposition WebView2 content)."""
    top = widget.get_toplevel().get_window()
    x, y = top.get_origin()[1:]
    w, h = top.get_width() * top.get_scale_factor(), top.get_height() * top.get_scale_factor()
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    sdc = u32.GetDC(0)
    mdc = g32.CreateCompatibleDC(sdc)
    bmp = g32.CreateCompatibleBitmap(sdc, w, h)
    g32.SelectObject(mdc, bmp)
    g32.BitBlt(mdc, 0, 0, w, h, sdc, x, y, 0x00CC0020)       # SRCCOPY

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(0, sdc)
    raw = bytearray(buf.raw)
    raw[0::4], raw[2::4] = raw[2::4], raw[0::4]                # BGRA -> RGBA
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(raw)), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
    pb.savev(path, "png", [], [])
    # mostly-white page area = the web content was painted (a missing WebView2 leaves the GTK background)
    sample = raw[(h // 2) * w * 4:(h // 2) * w * 4 + w * 4]
    return sum(1 for i in range(0, len(sample), 4) if sample[i] > 240 and sample[i + 1] > 240) / max(1, w)
