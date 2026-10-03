# -*- mode: python -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
# PyInstaller spec for the Windows build (MSYS2 UCRT64). Run from the repository root:
#   scripts/windows/build.sh   (fetches the third-party files, makes the icon, then runs this spec)
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
APP = os.path.join(ROOT, "pkg", "usr", "share", "meshcentral-desktop")
BUILD = os.path.join(ROOT, "build")

datas = [
    (os.path.join(BUILD, "webview2", "WebView2.tlb"), os.path.join("mcdesktop", "webview2")),
    (os.path.join(BUILD, "assets", "xterm"), os.path.join("mcdesktop", "assets", "xterm")),
    # without index.theme GTK does not treat share/icons/hicolor as a theme and the app icon is missing
    (os.path.join(sys.prefix, "share", "icons", "hicolor", "index.theme"), os.path.join("share", "icons", "hicolor")),
    (os.path.join(BUILD, "meshcentral-desktop.ico"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "NOTICE"), "."),
    (os.path.join(SPECPATH, "THIRD-PARTY-NOTICES.txt"), "."),
    # licence texts of the bundled MSYS2 packages (Python, GTK, GLib, cairo, Pango, OpenSSL...)
    (os.path.join(sys.prefix, "share", "licenses"), "licenses"),
]
# the app icon as PNG only: GTK would pick the scalable SVG, and the bundle has no SVG image loader
for _size in (16, 24, 32, 48, 64, 128, 256):
    _d = os.path.join("share", "icons", "hicolor", "%dx%d" % (_size, _size), "apps")
    datas.append((os.path.join(ROOT, "pkg", "usr", _d, "meshcentral-desktop.png"), _d))
binaries = [(os.path.join(BUILD, "webview2", "WebView2Loader.dll"), os.path.join("mcdesktop", "webview2"))]
hidden = (collect_submodules("mcdesktop") + collect_submodules("comtypes.gen")
          + ["comtypes.client", "websocket"])

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hooksconfig={"gi": {"icons": ["Adwaita"], "themes": ["Adwaita"], "languages": ["en_GB", "en"],
                        "module-versions": {"Gtk": "3.0", "Gdk": "3.0"}}},
    excludes=["tkinter", "unittest", "pydoc_data"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [("X utf8_mode=1", None, "OPTION")],     # UTF-8 everywhere (the Windows code page cannot show every name)
    exclude_binaries=True,
    name="MeshCentralDesktop",
    console=False,
    icon=os.path.join(BUILD, "meshcentral-desktop.ico"),
    version=os.path.join(BUILD, "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="MeshCentralDesktop")

# Portable single-file .exe (no installation): same app, unpacked to a temporary folder at each start,
# so it starts more slowly than the installed copy.
portable = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [("X utf8_mode=1", None, "OPTION")],
    name="MeshCentralDesktop-portable",
    console=False,
    icon=os.path.join(BUILD, "meshcentral-desktop.ico"),
    version=os.path.join(BUILD, "version_info.txt"),
)
