# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Shared settings for the local test-rig scripts (LOCALHOST TESTING ONLY).

Importing this module puts the application (pkg/usr/share/meshcentral-desktop) on sys.path, so the
scripts run from any directory:  python3 tests/rig/<script>.py

The rig is a throwaway MeshCentral server on https://127.0.0.1:8443 with the test accounts
admin / Test-1234 (full administrator) and limited / Limit-12345! (restricted). These are local
test defaults, never real credentials. See docs/DEVELOPMENT.md for the setup.
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APP_DIR = os.path.join(REPO, "pkg", "usr", "share", "meshcentral-desktop")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Directory that contains the rig's "mctest" folder (server + agent), used by the agent restart tests.
RIG_DIR = os.environ.get("MCD_RIG_DIR", os.path.expanduser("~/mcd-rig"))

# Separate application id, so a test never activates (or collides with) an installed, running app.
TEST_APP_ID = "uk.co.cyvelion.MeshCentralDesktop.RigTest"
