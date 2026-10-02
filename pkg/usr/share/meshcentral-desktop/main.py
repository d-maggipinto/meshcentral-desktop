#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--debug-hang":     # diagnostics: Python stacks every N seconds
        import faulthandler
        _d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MeshCentralDesktop")
        os.makedirs(_d, exist_ok=True)
        _hang_log = open(os.path.join(_d, "hang-dump.txt"), "w")
        faulthandler.dump_traceback_later(int(sys.argv[2]), repeat=True, file=_hang_log)
        del sys.argv[1:3]
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":      # packaged-build check, see mcdesktop/selftest.py
        from mcdesktop import selftest
        sys.exit(selftest.run(sys.argv[2] if len(sys.argv) > 2 else "selftest.json"))
    from mcdesktop.app import main
    sys.exit(main())
