#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcdesktop.app import main
if __name__ == "__main__":
    sys.exit(main())
