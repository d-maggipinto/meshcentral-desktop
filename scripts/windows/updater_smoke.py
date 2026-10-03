# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows CI: the in-app upgrade hand-over (updater.install_windows) for real. A copy of the installer is
handed to the hidden PowerShell helper exactly like the app does; this process then exits, the helper waits
for it, runs the installer silently and starts the installed app again. The CI step checks the result.
Usage: python updater_smoke.py <inno|msi> <installer> <installed MeshCentralDesktop.exe>"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pkg", "usr", "share", "meshcentral-desktop"))
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from mcdesktop import updater  # noqa: E402

kind, installer, app_exe = sys.argv[1:4]
copy = os.path.join(tempfile.mkdtemp(prefix="mcd-update-"), os.path.basename(installer))
shutil.copy(installer, copy)
updater.install_windows(kind, copy, app_exe=app_exe, sha256=updater.sha256_file(copy))   # the re-check path too
print("handed over to the update helper:", kind, copy, flush=True)
with open(os.path.join(os.getcwd(), "updater-%s.copy" % kind), "w") as f:
    f.write(copy)
