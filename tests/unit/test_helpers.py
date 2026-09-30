# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Offline unit tests: pure helpers that need no server and no display.

Run:  python3 -m unittest discover -s tests/unit -v
Needs the same Python packages as the app (python3-gi with GTK 3), but no running MeshCentral.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "pkg", "usr", "share",
                                       "meshcentral-desktop"))
sys.path.insert(0, APP_DIR)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from mcdesktop import admin_panel as ap, user_panel as up, rights, ui  # noqa: E402


class FakeCtrl:
    def __init__(self, userinfo=None, serverinfo=None):
        self.userinfo = userinfo or {"_id": "user//me"}
        self.serverinfo = serverinfo or {}


class ImportTests(unittest.TestCase):
    def test_csv_like_web_ui(self):
        text = "user,pass,email,resetNextLogin\r\nx1,Aa-123456!,x1@example.com,\r\n,,,\r\nx2,Aa-123456!,,TRUE\r\n"
        self.assertEqual(ap.parse_user_import(text, "a.csv"), [
            {"user": "x1", "pass": "Aa-123456!", "email": "x1@example.com"},
            {"user": "x2", "pass": "Aa-123456!", "resetNextLogin": True}])

    def test_json(self):
        self.assertEqual(ap.parse_user_import('[{"user":"a","pass":"b"}]', "x.json"), [{"user": "a", "pass": "b"}])

    def test_bad_files(self):
        for text, name in (("name,password\nx,y\n", "a.csv"), ("{}", "a.json"), ("[1, 2]", "a.json"), ("", "a.csv")):
            with self.assertRaises(ValueError):
                ap.parse_user_import(text, name)

    def test_validation_matches_server(self):
        bad = [{"user": "a b", "pass": "x"}, {"user": "~a", "pass": "x"}, {"user": "a/b", "pass": "x"},
               {"user": "a", "pass": ""}, {"user": "a", "pass": "x", "email": "x1@x"}, {"pass": "x"},
               {"user": "a", "pass": "x", "resetNextLogin": "yes"}]
        for e in bad:
            self.assertIsNotNone(ap.validate_import_entry(e), e)
        self.assertIsNone(ap.validate_import_entry({"user": "a", "pass": "x", "email": "a@b.co", "resetNextLogin": True}))

    def test_email_as_user_name(self):
        self.assertIsNotNone(ap.validate_import_entry({"user": "plain", "pass": "x"}, email_is_name=True))
        self.assertIsNone(ap.validate_import_entry({"user": "a@b.co", "pass": "x"}, email_is_name=True))
        self.assertIsNone(ap.validate_import_entry({"user": "plain", "pass": "x", "email": "a@b.co"}, email_is_name=True))


class ExportTests(unittest.TestCase):
    def test_csv_columns_and_flags(self):
        rows = ap.users_to_csv([{"_id": "user//a", "name": "a", "siteadmin": 0xFFFFFFFF},
                                {"_id": "user//b", "name": "b", "siteadmin": 2 | 32, "otpsecret": 1, "otpkeys": 1}])
        lines = rows.strip().split("\r\n")
        self.assertEqual(lines[0], '"' + '","'.join(ap.EXPORT_CSV_COLUMNS) + '"')
        self.assertTrue(lines[1].endswith(",1,1,0"))            # full admin is never reported as locked
        self.assertIn('"AuthApp,BackupCodes"', lines[2])
        self.assertTrue(lines[2].endswith(",0,1,1"))


class LabelTests(unittest.TestCase):
    def test_permissions_label(self):
        cases = [({}, "User"), ({"siteadmin": 0}, "User"), ({"siteadmin": 8}, "User + Files"),
                 ({"siteadmin": 0xFFFFFFFF}, "Administrator"), ({"siteadmin": 2}, "Manager"),
                 ({"siteadmin": 1}, "Partial"), ({"siteadmin": 32}, "Locked, User"), ({"siteadmin": 64}, "User*")]
        for user, label in cases:
            self.assertEqual(ap.permissions_label(user), label, user)

    def test_server_rights_text(self):
        self.assertEqual(up.server_rights_text({}), "No server rights")
        self.assertEqual(up.server_rights_text({"siteadmin": 33}), "Locked account, Partial rights")
        self.assertEqual(up.server_rights_text({"siteadmin": 0xFFFFFFFF}), "Full administrator")

    def test_rights_strings(self):
        self.assertEqual(up.group_rights_text(0xFFFFFFFF), "Full Rights")
        self.assertEqual(up.group_rights_text(8 | 16), "Control, Console")
        self.assertEqual(up.group_rights_text(8 | 256), "Control (No Input)")
        self.assertEqual(up.device_rights_text(0), "No Rights")
        self.assertEqual(up.device_rights_text(8 | 64), "Control, Wake")

    def test_features_and_consent(self):
        self.assertEqual(up.features_text({"removeRights": 0x200 | 0x40}, {}), "No Terminal, No Wake")
        self.assertEqual(up.features_text({"removeRights": 0x8}, {}), "No Remote Control")
        self.assertEqual(up.consent_text({"consent": 1}, {}), "Desktop Notify")
        self.assertEqual(up.consent_text({"consent": 0x87}, {}), "Always Notify")
        self.assertEqual(up.consent_text({}, {"consent": 8}), "Desktop Prompt")      # server-wide consent counts


class RightsTests(unittest.TestCase):
    def test_mesh_rights_direct_and_group(self):
        ctrl = FakeCtrl({"_id": "user//me", "links": {"ugrp//g": {}}})
        mesh = {"links": {"user//me": {"rights": 8}, "ugrp//g": {"rights": 16}}}
        self.assertEqual(rights.mesh_rights(ctrl, mesh), 8 | 16)

    def test_account_restrictions(self):
        ctrl = FakeCtrl({"_id": "user//me", "removeRights": rights.REMOTECONTROL})
        mesh = {"links": {"user//me": {"rights": rights.FULL}}}
        self.assertFalse(rights.mesh_rights(ctrl, mesh) & rights.REMOTECONTROL)

    def test_node_caps(self):
        caps = rights.NodeCaps(rights.REMOTEVIEWONLY)
        self.assertTrue(caps.desktop and caps.view_only)
        self.assertFalse(caps.terminal or caps.files or caps.desktop_input)
        self.assertTrue(rights.NodeCaps(rights.FULL).console)


class FormatTests(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(ui.fmt_size(512), "512 B")
        self.assertEqual(ui.fmt_size(2048), "2.0 KB")
        self.assertEqual(ui.fmt_size(None), "")

    def test_dates(self):
        self.assertEqual(ui.fmt_time(None), "")
        self.assertEqual(ui.fmt_date(0), "")
        self.assertRegex(ui.fmt_date(1790000000), r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(ui.fmt_time("2026-09-30T10:00:00Z"), r"^2026-09-30 \d{2}:00:00$")


if __name__ == "__main__":
    unittest.main()
