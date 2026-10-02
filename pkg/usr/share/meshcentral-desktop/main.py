#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":      # packaged-build check, see mcdesktop/selftest.py
        from mcdesktop import selftest
        sys.exit(selftest.run(sys.argv[2] if len(sys.argv) > 2 else "selftest.json"))
    from mcdesktop.app import main
    sys.exit(main())
