#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Windows build (MSYS2 UCRT64 shell): PyInstaller folder dist/MeshCentralDesktop/ from the same sources as the
# Linux package. The installers (Inno Setup .exe, WiX .msi) are made from that folder by the CI workflow.
set -euo pipefail
cd "$(dirname "$0")/../.."
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' pkg/usr/share/meshcentral-desktop/mcdesktop/__init__.py)
echo "MeshCentral Desktop $VER"
scripts/windows/fetch-assets.sh
python scripts/windows/make_ico.py build/meshcentral-desktop.ico
python scripts/windows/make_meta.py "$VER"
# comtypes wrapper of WebView2.tlb, generated now so the bundle carries it (no code generation at run time)
python -c "import sys, comtypes.client; comtypes.client.GetModule(sys.argv[1])" "$(cygpath -w "$PWD/build/webview2/WebView2.tlb")"
PYTHONPATH="$PWD/pkg/usr/share/meshcentral-desktop" pyinstaller --noconfirm --clean \
  --distpath dist --workpath build/pyinstaller packaging/windows/meshcentral-desktop.spec
mv -f dist/MeshCentralDesktop-portable.exe "dist/MeshCentralDesktop-$VER-portable.exe"
echo "$VER" > dist/VERSION
du -sh dist/MeshCentralDesktop "dist/MeshCentralDesktop-$VER-portable.exe"
