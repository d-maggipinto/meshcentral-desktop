#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Third-party files for the Windows build, pinned by version AND SHA-256, into build/ (never in pkg/,
# so the Linux package does not change):
#   build/webview2/  WebView2Loader.dll + WebView2.tlb  (Microsoft.Web.WebView2 NuGet package)
#   build/assets/xterm/  xterm.js + addon-fit (MIT, https://github.com/xtermjs/xterm.js) for the terminal
set -euo pipefail
cd "$(dirname "$0")/../.."
WEBVIEW2_SDK_VERSION=1.0.4258.31
WEBVIEW2_SDK_SHA256=56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9
XTERM_VERSION=6.0.0
XTERM_SHA256=908e66e04af6c8dc6b00dd3b54de088e2e81e5ed866284fd6c2fb3c2d1c7a3f6
FIT_VERSION=0.11.0
FIT_SHA256=26003b4517a132b64e4ff228fd88a5fda3fff5e606c76093f6dcff772e9ecec0

T=build/download
mkdir -p "$T" build/webview2 build/assets/xterm
get() {  # url sha256 file
  [ -f "$3" ] && echo "$2  $3" | sha256sum -c --quiet - 2>/dev/null && return 0
  curl -sSfL -o "$3" "$1"
  echo "$2  $3" | sha256sum -c --quiet -
}
get "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/$WEBVIEW2_SDK_VERSION" "$WEBVIEW2_SDK_SHA256" "$T/webview2.nupkg"
get "https://registry.npmjs.org/@xterm/xterm/-/xterm-$XTERM_VERSION.tgz" "$XTERM_SHA256" "$T/xterm.tgz"
get "https://registry.npmjs.org/@xterm/addon-fit/-/addon-fit-$FIT_VERSION.tgz" "$FIT_SHA256" "$T/addon-fit.tgz"

unzip -q -j -o "$T/webview2.nupkg" "build/native/x64/WebView2Loader.dll" "WebView2.tlb" -d build/webview2
tar -xzf "$T/xterm.tgz" -C "$T" package/lib/xterm.js package/css/xterm.css package/LICENSE
cp "$T/package/lib/xterm.js" "$T/package/css/xterm.css" build/assets/xterm/
cp "$T/package/LICENSE" build/assets/xterm/LICENSE-xterm.txt
rm -rf "$T/package"
tar -xzf "$T/addon-fit.tgz" -C "$T" package/lib/addon-fit.js package/LICENSE
cp "$T/package/lib/addon-fit.js" build/assets/xterm/
cp "$T/package/LICENSE" build/assets/xterm/LICENSE-addon-fit.txt
rm -rf "$T/package"
ls -l build/webview2 build/assets/xterm
