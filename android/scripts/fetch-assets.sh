#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Third-party web assets for the Android app, pinned by version AND SHA-256 (same pins as
# scripts/windows/fetch-assets.sh), into app/src/main/assets/xterm/ (git-ignored):
#   xterm.js + xterm.css + addon-fit (MIT, https://github.com/xtermjs/xterm.js) for the terminal
set -euo pipefail
cd "$(dirname "$0")/.."
XTERM_VERSION=6.0.0
XTERM_SHA256=908e66e04af6c8dc6b00dd3b54de088e2e81e5ed866284fd6c2fb3c2d1c7a3f6
FIT_VERSION=0.11.0
FIT_SHA256=26003b4517a132b64e4ff228fd88a5fda3fff5e606c76093f6dcff772e9ecec0

T=build/download
OUT=app/src/main/assets/xterm
mkdir -p "$T" "$OUT"
get() {  # url sha256 file
  [ -f "$3" ] && echo "$2  $3" | sha256sum -c --quiet - 2>/dev/null && return 0
  curl -sSfL -o "$3" "$1"
  echo "$2  $3" | sha256sum -c --quiet -
}
get "https://registry.npmjs.org/@xterm/xterm/-/xterm-$XTERM_VERSION.tgz" "$XTERM_SHA256" "$T/xterm.tgz"
get "https://registry.npmjs.org/@xterm/addon-fit/-/addon-fit-$FIT_VERSION.tgz" "$FIT_SHA256" "$T/addon-fit.tgz"
rm -rf "$T/package"
tar -xzf "$T/xterm.tgz" -C "$T" package/lib/xterm.js package/css/xterm.css package/LICENSE
cp "$T/package/lib/xterm.js" "$T/package/css/xterm.css" "$OUT/"
cp "$T/package/LICENSE" "$OUT/LICENSE-xterm.txt"
rm -rf "$T/package"
tar -xzf "$T/addon-fit.tgz" -C "$T" package/lib/addon-fit.js package/LICENSE
cp "$T/package/lib/addon-fit.js" "$OUT/"
cp "$T/package/LICENSE" "$OUT/LICENSE-addon-fit.txt"
rm -rf "$T/package"
ls -l "$OUT"
