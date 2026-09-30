#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Build dist/meshcentral-desktop_<version>_all.deb from pkg/.
# The version is read from pkg/DEBIAN/control and must match mcdesktop/__init__.py.
set -eu
cd "$(dirname "$0")/.."

CTRL_VER=$(sed -n 's/^Version: *//p' pkg/DEBIAN/control)
PY_VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' pkg/usr/share/meshcentral-desktop/mcdesktop/__init__.py)
if [ "$CTRL_VER" != "$PY_VER" ]; then
    echo "Version mismatch: pkg/DEBIAN/control=$CTRL_VER, mcdesktop/__init__.py=$PY_VER" >&2
    exit 1
fi

# Never ship bytecode: the build machine's Python may differ from the target's.
find pkg -name __pycache__ -type d -prune -exec rm -rf {} +
find pkg -name '*.pyc' -delete

find pkg -type d -exec chmod 755 {} +
find pkg -type f ! -path '*/DEBIAN/*' -exec chmod 644 {} +
chmod 755 pkg/usr/bin/meshcentral-desktop pkg/usr/share/meshcentral-desktop/main.py \
          pkg/DEBIAN/postinst pkg/DEBIAN/postrm

# Syntax check, then remove the bytecode it creates.
python3 -m py_compile pkg/usr/share/meshcentral-desktop/main.py pkg/usr/share/meshcentral-desktop/mcdesktop/*.py
find pkg -name __pycache__ -type d -prune -exec rm -rf {} +

mkdir -p dist
OUT="dist/meshcentral-desktop_${CTRL_VER}_all.deb"
fakeroot dpkg-deb --build --root-owner-group pkg "$OUT"

if dpkg-deb -c "$OUT" | grep -q pycache; then
    echo "Error: $OUT contains __pycache__" >&2
    exit 1
fi
echo "Built $OUT"
