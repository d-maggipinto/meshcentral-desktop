# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Build the Windows .ico from the app's PNG icons (PNG-compressed entries, Windows Vista and later).
Usage: python make_ico.py <out.ico>"""
import os
import struct
import sys

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pkg", "usr", "share", "icons", "hicolor")
SIZES = [16, 24, 32, 48, 64, 128, 256]


def build(out):
    images = []
    for s in SIZES:
        # re-encoded as 8-bit RGBA: the source PNGs are 16 bits per channel, which ICO readers reject
        pb = GdkPixbuf.Pixbuf.new_from_file(os.path.join(ROOT, "%dx%d" % (s, s), "apps", "meshcentral-desktop.png"))
        if not pb.get_has_alpha():
            pb = pb.add_alpha(False, 0, 0, 0)
        ok, data = pb.save_to_bufferv("png", [], [])
        data = bytes(data)
        assert ok and data[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", data[16:24])
        assert (w, h) == (s, s), (s, w, h)
        images.append((s, data))
    header = struct.pack("<HHH", 0, 1, len(images))            # reserved, type 1 = icon, count
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        dim = 0 if s >= 256 else s                              # 0 means 256 in an ICONDIRENTRY
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(out, "wb") as f:
        f.write(header + entries + blobs)


if __name__ == "__main__":
    build(sys.argv[1])
    print("wrote", sys.argv[1], os.path.getsize(sys.argv[1]))
