# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Server-wide admin panels: users, user groups, server events, my account.

These panels take node=None. They read from the control connection with the same
documented actions the MeshCentral web UI uses (users / usergroups / events) and
from the already-cached app.ctrl.userinfo / app.ctrl.serverinfo.
"""
import csv
import io
import json
import re
import time

from gi.repository import Gtk, GLib, Pango

from . import ui, rights

BROADCAST_MAX = 512          # server limit (meshuser.js validates 1..512 chars)


class BroadcastDialog(Gtk.Dialog):
    """Same as the web UI's "Broadcast Message": {action:'userbroadcast', msg, target, maxtime}.
    target = a user group id (only its connected members) or None (all connected users).
    Needs site right 2 (manage users). Note the server only delivers to users who share a user
    group with the sender when the sender is in any user group."""
    DURATIONS = [("Show message until dismissed by user", 0), ("Show for 10 seconds", 10),
                 ("Show for 1 minute", 60), ("Show for 5 minutes", 300)]

    def __init__(self, parent, ctrl, target=None, target_name=None):
        super().__init__(title="Broadcast Message", transient_for=parent, modal=True)
        self.ctrl, self.target = ctrl, target
        self.set_default_size(460, 320)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        who = f"all connected members of “{target_name}”" if target else "all connected users"
        box.pack_start(Gtk.Label(label=f"Broadcast a message to {who}.", xalign=0), False, False, 0)
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(8)
        self.view.set_top_margin(6)
        self.view.get_buffer().connect("changed", lambda *_: self._changed())
        scr = Gtk.ScrolledWindow(hexpand=True, vexpand=True, min_content_height=150)
        scr.add(self.view)
        frame = Gtk.Frame()
        frame.add(scr)
        box.pack_start(frame, True, True, 0)
        row = Gtk.Box(spacing=8)
        self.duration = Gtk.ComboBoxText()
        for label, _v in self.DURATIONS:
            self.duration.append_text(label)
        self.duration.set_active(0)
        row.pack_start(self.duration, True, True, 0)
        self.count = Gtk.Label()
        self.count.get_style_context().add_class("dim-label")
        row.pack_start(self.count, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.result = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.result, False, False, 0)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.send_btn = self.add_button("Send", Gtk.ResponseType.OK)
        self.send_btn.get_style_context().add_class("suggested-action")
        self.connect("response", self._on_response)
        self._changed()
        self.show_all()
        self.view.grab_focus()

    def _text(self):
        b = self.view.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()

    def _changed(self):
        n = len(self._text())
        self.count.set_text(f"{n}/{BROADCAST_MAX}")
        self.send_btn.set_sensitive(0 < n <= BROADCAST_MAX)

    def _on_response(self, _d, resp):
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        self.send_btn.set_sensitive(False)
        self.result.set_text("Sending…")
        maxtime = self.DURATIONS[self.duration.get_active()][1]
        msg = {"action": "userbroadcast", "msg": self._text(), "maxtime": maxtime}
        if self.target:
            msg["target"] = self.target

        def reply(r):
            if r.get("result") == "ok":
                self.destroy()
            else:
                self.result.set_markup(f"<span foreground='#e01b24'>{GLib.markup_escape_text(str(r.get('result')))}</span>")
                self.send_btn.set_sensitive(True)
        self.ctrl.send(msg, reply)


def _has_2fa(u):
    return bool(u.get("otphkeys") or u.get("otpkeys") or u.get("otpsecret") or u.get("otpdev"))


def _rights_summary(u):
    sa = u.get("siteadmin")
    # accounts created without server rights have NO siteadmin field (web UI: "User")
    if sa == 0xFFFFFFFF or (isinstance(sa, int) and sa & 0xFFFFFFFF == 0xFFFFFFFF):
        return "Full administrator"
    if not sa:
        return "User"
    bits = {1: "Backup", 2: "Manage users", 4: "Restore", 8: "File upload", 16: "Update",
            32: "Locked", 64: "No new groups", 128: "No MeshCmd", 256: "User groups",
            512: "Recordings", 1024: "Locked settings", 2048: "Web relay", 4096: "SMS"}
    names = [v for k, v in bits.items() if isinstance(sa, int) and sa & k]
    return ", ".join(names) if names else "Admin (%s)" % sa


def permissions_label(u):
    """Users list "Permissions" column exactly like the web UI's addUserHtml."""
    sa = u.get("siteadmin")
    pre = "Locked, " if isinstance(sa, int) and sa & 32 and sa != 0xFFFFFFFF else ""
    ur = sa & (0xFFFFFFFF - 1248) if isinstance(sa, int) else 0
    if not isinstance(sa, int) or ur == 0:
        label = "User"
    elif ur == 8:
        label = "User + Files"
    elif sa == 0xFFFFFFFF:
        label = "Administrator"
    elif ur & 2:
        label = "Manager"
    else:
        label = "Partial"
    if isinstance(sa, int) and sa != 0xFFFFFFFF and sa & (64 + 128 + 1024):
        label += "*"
    return pre + label


# ---- user list export / batch import (web UI "My Users" download + upload icons) ----------

EXPORT_CSV_COLUMNS = ["id", "name", "email", "creation", "lastlogin", "groups", "authfactors",
                      "siteadmin", "useradmin", "locked"]
# Same regex as the server's common.validateEmail: the web UI's own example "x1@x" is REJECTED
# by the server (no TLD) and would fail the whole batch.
_EMAIL_RE = re.compile(r'^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@'
                       r'((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$')


def _export_time(secs):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(secs)) if secs else ""


def _no_formula(v):
    """Spreadsheets run a cell starting with = + - @ as a formula: user names and emails are chosen
    by other users, so such a value gets a leading quote."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def users_to_csv(users):
    """userlist.csv with the web UI's columns (p4downloadUserInfoCSV). Dates are local time
    instead of JavaScript's Date string; fields are properly quoted/escaped; a full admin is never
    reported as locked."""
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\r\n")
    w.writerow(EXPORT_CSV_COLUMNS)
    for u in users:
        sa = u.get("siteadmin") if isinstance(u.get("siteadmin"), int) else 0
        factors = []
        if u.get("otpsecret") or u.get("otphkeys"):      # web UI: backup codes only count with a real factor
            if u.get("otpsecret"):
                factors.append("AuthApp")
            if u.get("otphkeys"):
                factors.append("SecurityKey")
            if u.get("otpkeys"):
                factors.append("BackupCodes")
        w.writerow([_no_formula(u.get("_id", "")), _no_formula(u.get("name", "")), _no_formula(u.get("email") or ""),
                    _export_time(u.get("creation")), _export_time(u.get("login")),
                    _no_formula(",".join(u.get("groups") or [])), ",".join(factors),
                    # the web UI tests `& 32` on 0xFFFFFFFF too and marks every full admin "locked"
                    1 if sa == 0xFFFFFFFF else 0, 1 if sa & 2 else 0,
                    1 if sa != 0xFFFFFFFF and sa & 32 else 0])
    return out.getvalue()


def users_to_json(users):
    """userlist.json = the user objects exactly as the server sent them (CloneSafeUser: no
    password hashes or 2FA secrets), like p4downloadUserInfoJSON."""
    return json.dumps(list(users), indent=2)


def parse_user_import(text, name=""):
    """JSON array or CSV (header user,pass,email,resetNextLogin[,realname]) → list of dicts.
    CSV like the web UI: blank rows skipped, empty cells omitted, "true" → True.
    Raises ValueError with a readable message."""
    stripped = text.lstrip("﻿ \t\r\n")
    if name.lower().endswith(".json") or (not name.lower().endswith(".csv") and stripped.startswith("[")):
        try:
            data = json.loads(stripped)
        except ValueError as ex:
            raise ValueError("Invalid JSON file: %s" % ex)
        if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
            raise ValueError("The JSON file must contain an array of objects.")
        return data
    rows = list(csv.reader(io.StringIO(stripped)))
    if not rows:
        raise ValueError("The file is empty.")
    headers = [h.strip() for h in rows[0]]
    if "user" not in headers or "pass" not in headers:
        raise ValueError("The CSV header must contain at least the columns user and pass.")
    out = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        entry = {}
        for h, v in zip(headers, row):
            v = v.strip()
            if h and v:
                entry[h] = True if v.lower() == "true" else v
        out.append(entry)
    return out


def validate_import_entry(e, email_is_name=False):
    """Mirror the checks of the web UI and of meshuser.js serverCommandAddUserBatch, so a bad row
    is shown here, the server rejects the WHOLE batch and does not say which row failed.
    Password strength rules are only known to the server (not sent on the control channel).
    email_is_name (domain.usernameisemail): the server copies email→user, or user→email when there
    is no email, so the resulting name must be a valid email address."""
    u, p, em = e.get("user"), e.get("pass"), e.get("email")
    if not isinstance(u, str) or not 1 <= len(u) <= 64:
        return "user name must be 1-64 characters"
    if any(c in u for c in ' ",') or u.startswith("~") or "/" in u:
        return "user name contains a space, quote, comma, / or starts with ~"
    if not isinstance(p, str) or not 1 <= len(p) <= 256:
        return "password must be 1-256 characters"
    if em is not None and (not isinstance(em, str) or not 1 <= len(em) <= 128 or not _EMAIL_RE.match(em)):
        return "invalid email address"
    if email_is_name and em is None and not _EMAIL_RE.match(u):
        return "this server uses email addresses as user names. Add an email or use one as user"
    if "resetNextLogin" in e and not isinstance(e["resetNextLogin"], bool):
        return "resetNextLogin must be true or false"
    return None


class UserImportDialog(Gtk.Dialog):
    """"User Account Import": pick a JSON/CSV file, preview + validate every row, then send
    {action:'adduserbatch', users}. The server replies ONLY on error (with our responseid); on
    success it just emits one {event:{action:'accountcreate'}} per new account and silently skips
    names that already exist, so we count those events to report the result."""
    WAIT_S = 15

    def __init__(self, parent, ctrl, existing_names, on_done=None):
        super().__init__(title="User Account Import", transient_for=parent, modal=True)
        self.ctrl, self.on_done = ctrl, on_done
        self.existing = {n.lower() for n in existing_names}
        # domain.usernameisemail: the server replaces each row's user with its email (if any)
        self.email_is_name = bool(_features(ctrl) & FEAT_USERNAME_IS_EMAIL)
        self.entries, self.to_send, self.created = [], [], set()
        self._listening = False
        self._timer = None
        self.set_default_size(820, 540)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        help_text = ("Create many accounts at once by importing a JSON or CSV file.\n\n"
                     "JSON:  [ {\"user\":\"x1\",\"pass\":\"…\",\"email\":\"x1@example.com\"},\n"
                     "         {\"user\":\"x2\",\"pass\":\"…\",\"resetNextLogin\":true} ]\n\n"
                     "CSV:   user,pass,email,resetNextLogin\n"
                     "       x1,…,x1@example.com,\n"
                     "       x2,…,,true")
        lbl = Gtk.Label(label=help_text, xalign=0, selectable=True)
        lbl.get_style_context().add_class("monospace")
        box.pack_start(lbl, False, False, 0)
        self.chooser = Gtk.FileChooserButton(title="Choose a JSON or CSV file")
        filt = Gtk.FileFilter()
        filt.set_name("JSON or CSV files")
        for pat in ("*.json", "*.csv", "*.JSON", "*.CSV"):
            filt.add_pattern(pat)
        self.chooser.add_filter(filt)
        self.chooser.connect("file-set", lambda *_: self._load())
        box.pack_start(self.chooser, False, False, 0)
        # user, email, reset, status
        self.store = Gtk.ListStore(str, str, str, str)
        tv = Gtk.TreeView(model=self.store)
        for i, (title, expand) in enumerate([("User", False), ("Email", False),
                                             ("Reset password", False), ("Status", True)]):
            tv.append_column(ui.text_column(title, i, expand))
        ui.row_tooltip(tv, 3)
        box.pack_start(ui.scrolled(tv), True, True, 0)
        self.result = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.result, False, False, 0)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.ok_btn = self.add_button("Import", Gtk.ResponseType.OK)
        self.ok_btn.get_style_context().add_class("suggested-action")
        self.ok_btn.set_sensitive(False)
        self.connect("response", self._on_response)
        self.connect("destroy", lambda *_: self._stop())
        self.show_all()

    def _account_name(self, e):
        if self.email_is_name and isinstance(e.get("email"), str) and e["email"]:
            return e["email"]
        return e.get("user") if isinstance(e.get("user"), str) else ""

    def _set_result(self, text, error=False):
        if error:
            self.result.set_markup(f"<span foreground='#e01b24'>{GLib.markup_escape_text(text)}</span>")
        else:
            self.result.set_text(text)

    def load_file(self, path):
        self.chooser.set_filename(path)
        self._load(path)

    def _load(self, path=None):
        path = path or self.chooser.get_filename()
        self.store.clear()
        self.entries, self.to_send = [], []
        self.ok_btn.set_sensitive(False)
        try:
            with open(path, encoding="utf-8-sig") as f:
                self.entries = parse_user_import(f.read(), path)
        except (OSError, UnicodeDecodeError, ValueError) as ex:
            self._set_result(str(ex), True)
            return
        bad = skipped = 0
        seen = set()
        for e in self.entries:
            err = validate_import_entry(e, self.email_is_name)
            name = self._account_name(e)
            if err:
                status, bad = "Invalid: " + err, bad + 1
            elif name.lower() in seen:
                status, bad = "Invalid: duplicate user name in the file", bad + 1
            elif name.lower() in self.existing:
                status, skipped = "Already exists, will be skipped", skipped + 1
            else:
                status = "New"
                self.to_send.append(e)
            seen.add(name.lower())
            self.store.append([name, e.get("email") or "", "Yes" if e.get("resetNextLogin") is True else "",
                               status])
        if not self.entries:
            self._set_result("The file contains no accounts.", True)
        elif bad:
            self._set_result(f"{bad} invalid row(s). Fix the file and choose it again "
                             "(the server rejects the whole batch if any row is invalid).", True)
        elif not self.to_send:
            self._set_result("All accounts in the file already exist.")
        else:
            extra = f", {skipped} already exist" if skipped else ""
            self._set_result(f"{len(self.to_send)} new account(s){extra}.")
            self.ok_btn.set_sensitive(True)

    def _on_response(self, _d, resp):
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        self.ok_btn.set_sensitive(False)
        self.chooser.set_sensitive(False)
        self.created = set()
        self._pending = {self._account_name(e).lower() for e in self.to_send}
        self._set_result(f"Creating {len(self._pending)} account(s)…")
        self.ctrl.on("event", self._on_event)
        self.ctrl.on("msg", self._on_msg)
        self._listening = True
        self._timer = GLib.timeout_add_seconds(self.WAIT_S, self._timeout)
        self.ctrl.send({"action": "adduserbatch", "users": self.to_send}, self._on_error_reply)

    def _stop(self):
        if self._listening:
            self.ctrl.off("event", self._on_event)
            self.ctrl.off("msg", self._on_msg)
            self._listening = False
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def _on_error_reply(self, msg):
        # only sent on failure: 'Access denied', 'Invalid password' (strength rules), LDAP/SSPI…
        self._stop()
        err = str(msg.get("result"))
        if err == "Invalid password":
            err += ", at least one password does not meet the server's password requirements"
        self._set_result("Import failed: " + err + ". No accounts were created.", True)
        self.chooser.set_sensitive(True)
        self.ok_btn.set_sensitive(True)

    def _on_event(self, msg):
        ev = msg.get("event") or {}
        name = (ev.get("account") or {}).get("name") or ev.get("username") or ""
        if ev.get("action") == "accountcreate" and name.lower() in self._pending:
            self.created.add(name.lower())
            self._set_result(f"Created {len(self.created)} of {len(self._pending)} account(s)…")
            if self.created == self._pending:
                self._finish()

    def _on_msg(self, msg):
        if msg.get("type") == "notify" and msg.get("msgid") == 10:     # "Account limit reached."
            self._finish("The server's account limit was reached.")

    def _timeout(self):
        self._timer = None
        self._finish()
        return False

    def _finish(self, reason=None):
        self._stop()
        n, total = len(self.created), len(self._pending)
        if n == total:
            self._set_result(f"Created {n} account(s).")
        else:
            self._set_result(f"Created {n} of {total} account(s). " + (reason or
                             "The server did not confirm the others (they may have been created by "
                             "someone else meanwhile). Check the user list."), True)
        for row in self.store:
            if row[0].lower() in self.created:
                row[3] = "Created"
        self.set_response_sensitive(Gtk.ResponseType.CANCEL, True)
        self.get_widget_for_response(Gtk.ResponseType.CANCEL).set_label("Close")
        if self.on_done:
            self.on_done()


# serverinfo.features bits (same value the web UI gets from its page template, webserver.js)
FEAT_NOUSERS = 0x4                  # single-user server: no account creation
FEAT_LDAP_SSPI = 0x80000            # LDAP/SSPI sign-in: no batch import
FEAT_USERNAME_IS_EMAIL = 0x200000   # domain.usernameisemail: the email IS the user name


def _features(ctrl):
    f = (ctrl.serverinfo or {}).get("features")
    return f if isinstance(f, int) else 0


class NewAccountDialog(Gtk.Dialog):
    """Web UI "New Account…" (showCreateNewAccountDialog): {action:'adduser', username, email, pass,
    resetNextLogin, randomPassword, removeEvents[, emailVerified, emailInvitation][, domain]}.
    With a responseid the server answers {action:'adduser', result:'ok' | error text}."""
    ERRORS = {"maxUsersExceed": "The server's account limit was reached.",
              "passwordHashError": "The server could not store the password.",
              "Invalid password": "Invalid password. It does not meet the server's password requirements."}

    def __init__(self, parent, ctrl, on_done=None):
        super().__init__(title="Create Account", transient_for=parent, modal=True)
        self.ctrl, self.on_done = ctrl, on_done
        info = ctrl.serverinfo or {}
        self.email_is_name = bool(_features(ctrl) & FEAT_USERNAME_IS_EMAIL)
        self.emailcheck = bool(info.get("emailcheck"))
        self.domains = info.get("crossDomain") if isinstance(info.get("crossDomain"), list) else None
        self._timer = None
        self.set_resizable(False)
        box = self.get_content_area()
        box.set_spacing(6)
        box.set_border_width(12)
        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        box.pack_start(grid, False, False, 0)
        self.labels = {}
        row = 0

        def add(key, title, widget):
            nonlocal row
            lbl = Gtk.Label(label=title, xalign=0)
            self.labels[key] = lbl
            grid.attach(lbl, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
            row += 1
            return widget

        def entry(password=False):
            e = Gtk.Entry(hexpand=True, width_chars=32, max_length=256, activates_default=True)
            if password:
                e.set_visibility(False)
                e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            e.connect("changed", lambda *_: self._validate())
            return e

        self.domain = None
        if self.domains:
            self.domain = Gtk.ComboBoxText()
            for d in self.domains:
                self.domain.append_text(d or "Default")
            self.domain.set_active(0)
            add("domain", "Domain", self.domain)
        self.name = None
        if not self.email_is_name:
            self.name = add("name", "Username", entry())
            self.name.set_max_length(64)
        self.email = add("email", "Email", entry())
        self.email.set_input_purpose(Gtk.InputPurpose.EMAIL)
        self.pass1 = add("pass1", "Password", entry(True))
        self.pass2 = add("pass2", "Password", entry(True))

        def check(label):
            c = Gtk.CheckButton(label=label)
            c.connect("toggled", lambda *_: self._validate())
            box.pack_start(c, False, False, 0)
            return c
        self.random = check("Randomize the password.")
        self.remove_events = check("Remove all previous events for this userid.")
        self.reset = check("Force password reset on next login.")
        self.verified = self.invite = None
        if self.emailcheck:
            self.verified = check("Email is verified.")
            self.invite = check("Send invitation email.")
            self.invite.set_tooltip_text("Email verified and forced password reset required.")
        self.hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=52)
        self.hint.get_style_context().add_class("dim-label")
        box.pack_start(self.hint, False, False, 0)
        self.result = Gtk.Label(xalign=0, wrap=True, max_width_chars=52)
        box.pack_start(self.result, False, False, 0)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.ok_btn = self.add_button("OK", Gtk.ResponseType.OK)
        self.ok_btn.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self._on_response)
        self.connect("destroy", lambda *_: self._stop_timer())
        self._validate()
        self.show_all()
        (self.name or self.email).grab_focus()

    def _mark(self, key, ok):
        lbl = self.labels.get(key)
        if lbl is not None:
            text = GLib.markup_escape_text(lbl.get_text())
            lbl.set_markup(text if ok else f"<span foreground='#e01b24'>{text}</span>")

    def _validate(self):
        email = self.email.get_text()
        email_ok = bool(_EMAIL_RE.match(email))          # the web UI requires a valid email too
        name_ok = True
        if self.name is not None:
            n = self.name.get_text()
            name_ok = 0 < len(n) and not any(c in n for c in ' ",') and not n.startswith("~") and "/" not in n
            self._mark("name", name_ok)
        self._mark("email", email_ok)
        rnd = self.random.get_active()
        self.pass1.set_sensitive(not rnd)
        self.pass2.set_sensitive(not rnd)
        p1, p2 = self.pass1.get_text(), self.pass2.get_text()
        pass_ok = rnd or (0 < len(p1) and p1 == p2)
        self._mark("pass1", pass_ok)
        self._mark("pass2", pass_ok)
        if self.emailcheck:
            self.verified.set_sensitive(email_ok)
            if not email_ok:
                self.verified.set_active(False)
            can_invite = email_ok and self.reset.get_active() and self.verified.get_active()
            self.invite.set_sensitive(can_invite)
            if not can_invite:
                self.invite.set_active(False)
        hints = []
        if self.email_is_name:
            hints.append("This server uses the email address as the user name.")
        if rnd:
            hints.append("The server generates a password that is not shown to anyone, "
                         "send an invitation email or set a new password later.")
        elif p1 and p2 and p1 != p2:
            hints.append("The passwords do not match.")
        self.hint.set_text(" ".join(hints))
        self.hint.set_visible(bool(hints))
        self.ok_btn.set_sensitive(name_ok and email_ok and pass_ok)

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def request(self):
        email = self.email.get_text().strip()
        msg = {"action": "adduser", "username": email if self.email_is_name else self.name.get_text(),
               "email": email, "pass": "" if self.random.get_active() else self.pass1.get_text(),
               "resetNextLogin": self.reset.get_active(), "randomPassword": self.random.get_active(),
               "removeEvents": self.remove_events.get_active()}
        if self.emailcheck:
            msg["emailVerified"] = self.verified.get_active()
            msg["emailInvitation"] = self.invite.get_active()
        if self.domains:
            msg["domain"] = self.domains[self.domain.get_active()]
        return msg

    def _on_response(self, _d, resp):
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        self.ok_btn.set_sensitive(False)
        self.result.set_text("Creating the account…")
        self._timer = GLib.timeout_add_seconds(15, self._timeout)
        self.ctrl.send(self.request(), self._on_reply)

    def _timeout(self):
        self._timer = None
        self._fail("No response from the server.")
        return False

    def _fail(self, text):
        self.result.set_markup(f"<span foreground='#e01b24'>{GLib.markup_escape_text(text)}</span>")
        self._validate()

    def _on_reply(self, msg):
        self._stop_timer()
        res = msg.get("result")
        if res == "ok":
            if self.on_done:
                self.on_done()
            self.destroy()
            return
        self._fail(self.ERRORS.get(res, str(res)))


def _save_text(parent, title, filename, text):
    ch = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SAVE, "_Save", "_Cancel")
    ch.set_current_name(filename)
    ch.set_do_overwrite_confirmation(True)
    ok = ch.run() == Gtk.ResponseType.ACCEPT
    dest = ch.get_filename() if ok else None
    ch.destroy()
    if not dest:
        return
    try:
        with open(dest, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError as ex:
        ui.message(parent, "Could not save the file", str(ex), Gtk.MessageType.ERROR)


def _toolbar(refresh_cb):
    bar = Gtk.Box(spacing=6, margin=8)
    b = Gtk.Button(label="Refresh",
                   image=Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON),
                   always_show_image=True)
    b.connect("clicked", lambda *_: refresh_cb())
    bar.pack_start(b, False, False, 0)
    return bar


def _make_tree(columns):
    """columns: list of (title, expand). Returns (treeview, liststore) with str columns."""
    store = Gtk.ListStore(*([str] * len(columns)))
    tv = Gtk.TreeView(model=store, enable_search=True)
    for i, (title, expand) in enumerate(columns):
        tv.append_column(ui.text_column(title, i, expand))
    # hovering a row shows the (possibly ellipsized) main text in full
    wide = [i for i, (_t, expand) in enumerate(columns) if expand]
    if wide:
        ui.row_tooltip(tv, wide[-1])
    return tv, store


class _TablePanel(Gtk.Box):
    """Base for a toolbar + status + table panel.

    Uses an ACTION *listener* rather than a responseid callback, because the server
    does not echo our responseid on these broadcast-style replies (users/usergroups/
    events), which previously left the panel stuck on "Loading…".
    """
    COLUMNS = []
    ACTION = None            # reply action to listen for
    NOREPLY_MSG = "No response from server."

    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self._listening = False
        self.pack_start(_toolbar(self.refresh), False, False, 0)
        self.status = Gtk.Label(xalign=0, margin_start=10)
        self.status.get_style_context().add_class("dim-label")
        self.pack_start(self.status, False, False, 0)
        self.tree, self.store = _make_tree(self.COLUMNS)
        self.pack_start(ui.scrolled(self.tree), True, True, 0)
        self.show_all()

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.refresh()

    def refresh(self):
        self.status.set_text("Loading…")
        self._replied = False
        if not self._listening and self.ACTION:
            self.app.ctrl.on(self.ACTION, self._on_reply)
            self._listening = True
        self.request()
        GLib.timeout_add(5000, self._check_timeout)

    def _on_reply(self, msg):
        self._replied = True
        try:
            self._fill(msg)
        except Exception as ex:
            self.status.set_text("Error: %s" % ex)

    def _check_timeout(self):
        if not self._replied:
            self.status.set_text(self.NOREPLY_MSG)
        return False

    def request(self):
        raise NotImplementedError

    def _fill(self, msg):
        raise NotImplementedError

    def teardown(self):
        if self._listening and self.ACTION:
            self.app.ctrl.off(self.ACTION, self._on_reply)
            self._listening = False


class UsersPanel(_TablePanel):
    """Web UI "My Users": online / offline sections, checkboxes (Select All / None, Group Action),
    Device Groups, Last Access (live session count from wssessioncount), Permissions, filter."""
    COLUMNS = [("Name", True)]          # replaced by the tree built in _build_tree
    ACTION = "users"
    # TreeStore columns
    C_CHECK, C_NAME, C_GROUPS, C_ACCESS, C_PERMS, C_2FA, C_ID, C_TIP, C_ISUSER, C_CHECKABLE, C_WEIGHT = range(11)

    def __init__(self, app, node=None):
        super().__init__(app, node)
        self._users = []
        self.sessions = {}               # userid -> number of open web/app sessions (wssessioncount)
        self._checked = set()
        self.usergroups = None           # {ugrp id: group} for the user page (None = not allowed/loaded)
        self.page = None                 # the open user_panel.UserPage
        self._soon = None
        manage = rights.has_site(app.ctrl, rights.SITE_MANAGEUSERS)
        self._build_tree()
        app.ctrl.on("event", self._on_event)
        app.ctrl.on("usergroups", self._on_usergroups)
        app.ctrl.on("wssessioncount", self._on_sessions)
        bar = self.get_children()[0]
        # web UI: Select All / Select None, Group Action, New Account…, Filter
        self.select_btn = Gtk.Button(label="Select All")
        self.select_btn.connect("clicked", lambda *_: self.toggle_select_all())
        bar.pack_start(self.select_btn, False, False, 0)
        self.group_btn = Gtk.Button(label="Group Action…", sensitive=False,
                                    tooltip_text="Perform an operation on all selected users")
        self.group_btn.connect("clicked", lambda *_: self.group_action())
        bar.pack_start(self.group_btn, False, False, 0)
        b = Gtk.Button(label="Broadcast to all users",
                       image=Gtk.Image.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.BUTTON),
                       always_show_image=True)
        b.connect("clicked", lambda *_: BroadcastDialog(self.get_toplevel(), self.app.ctrl))
        b.set_sensitive(manage)
        bar.pack_end(b, False, False, 0)
        feats = _features(app.ctrl)
        # web UI "New Account…": hidden on single-user (--nousers) and SSPI servers
        self.new_btn = Gtk.Button(label="New Account…", tooltip_text="Create a new user account",
                                  image=Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON),
                                  always_show_image=True)
        self.new_btn.connect("clicked", lambda *_: self.new_account())
        self.new_btn.set_sensitive(manage)
        self.new_btn.set_no_show_all(bool(feats & FEAT_NOUSERS) or bool((app.ctrl.serverinfo or {}).get("domainauth")))
        bar.pack_start(self.new_btn, False, False, 0)
        self.filter = Gtk.SearchEntry(placeholder_text="Filter", width_chars=18,
                                      tooltip_text="Filter by name or email; prefix with name: or email: to search only one")
        self.filter.connect("search-changed", lambda *_: self._render())
        bar.pack_start(self.filter, False, False, 0)
        # web UI: "Batch create many user accounts" (upload icon), hidden with LDAP/SSPI sign-in
        self.import_btn = Gtk.Button(label="Import…", tooltip_text="Batch create many user accounts from a JSON or CSV file",
                                     image=Gtk.Image.new_from_icon_name("document-open-symbolic", Gtk.IconSize.BUTTON),
                                     always_show_image=True)
        self.import_btn.connect("clicked", lambda *_: self.import_users())
        self.import_btn.set_sensitive(False)          # until the list has loaded (existing-name check)
        self.import_btn.set_no_show_all(bool(feats & FEAT_LDAP_SSPI))
        bar.pack_end(self.import_btn, False, False, 0)
        # web UI: "Download user information" (download icon) → userlist.csv / userlist.json
        menu = Gtk.Menu()
        for label, fmt in (("CSV format (userlist.csv)", "csv"), ("JSON format (userlist.json)", "json")):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, f=fmt: self.export_users(f))
            menu.append(item)
        menu.show_all()
        self.export_btn = Gtk.MenuButton(popup=menu, tooltip_text="Download the list of users")
        ebox = Gtk.Box(spacing=4)
        ebox.pack_start(Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        ebox.pack_start(Gtk.Label(label="Export"), False, False, 0)
        ebox.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        self.export_btn.add(ebox)
        self.export_btn.set_sensitive(False)          # until the list has loaded
        bar.pack_end(self.export_btn, False, False, 0)
        bar.show_all()

    # ---- table ------------------------------------------------------------------------------
    def _build_tree(self):
        scr = self.get_children()[-1]
        self.remove(scr)
        self.store = Gtk.TreeStore(bool, str, str, str, str, str, str, str, bool, bool, int)
        tv = Gtk.TreeView(model=self.store, enable_search=False)
        chk = Gtk.CellRendererToggle()
        chk.connect("toggled", self._on_toggled)
        tv.append_column(Gtk.TreeViewColumn("", chk, active=self.C_CHECK, visible=self.C_ISUSER,
                                            activatable=self.C_CHECKABLE, sensitive=self.C_CHECKABLE))
        r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        name = Gtk.TreeViewColumn("Name", r, text=self.C_NAME, weight=self.C_WEIGHT)
        name.set_expand(True)
        name.set_resizable(True)
        tv.append_column(name)
        for title, col in (("Device Groups", self.C_GROUPS), ("Last Access", self.C_ACCESS),
                           ("Permissions", self.C_PERMS), ("2FA", self.C_2FA)):
            c = ui.text_column(title, col)
            c.set_sort_column_id(-1)                 # sections + sorting do not mix
            tv.append_column(c)
        ui.row_tooltip(tv, self.C_TIP)
        # web UI: click a user → "General - <user>" page
        tv.connect("row-activated", lambda t, path, _c: self._activated(path))
        self.tree = tv
        self.pack_start(ui.scrolled(tv), True, True, 0)

    def _activated(self, path):
        row = self.store[path]
        if row[self.C_ISUSER]:
            self.open_user(row[self.C_ID])

    def _on_toggled(self, _r, path):
        row = self.store[path]
        if not row[self.C_ISUSER] or not row[self.C_CHECKABLE]:
            return
        row[self.C_CHECK] = not row[self.C_CHECK]
        (self._checked.add if row[self.C_CHECK] else self._checked.discard)(row[self.C_ID])
        self._update_selection_buttons()

    def _visible_ids(self):
        ids = []
        for sec in self.store:
            for row in sec.iterchildren():
                if row[self.C_CHECKABLE]:
                    ids.append(row[self.C_ID])
        return ids

    def _update_selection_buttons(self):
        self._checked &= {u.get("_id") for u in self._users}
        n = len(self._checked)
        self.select_btn.set_label("Select None" if n else "Select All")
        self.group_btn.set_sensitive(n > 0)

    def toggle_select_all(self):
        """web UI: Select All (every listed user except yourself) / Select None"""
        self._checked = set() if self._checked else set(self._visible_ids())
        self._render()

    def _matches(self, u, q):
        if not q:
            return True
        name, email = (u.get("name") or "").lower(), (u.get("email") or "").lower()
        for pre, only in (("email:", "e"), ("e:", "e"), ("name:", "n"), ("n:", "n")):
            if q.startswith(pre):
                q = q[len(pre):]
                return (q in email) if only == "e" else (q in name)
        return q in name or q in email

    def _render(self):
        self.store.clear()
        me = (self.app.ctrl.userinfo or {}).get("_id")
        q = self.filter.get_text().strip().lower()
        users = sorted((u for u in self._users if self._matches(u, q)), key=lambda x: (x.get("name") or "").lower())
        online = [u for u in users if self.sessions.get(u.get("_id"))]
        offline = [u for u in users if not self.sessions.get(u.get("_id"))]
        for title, group in (("Online Users", online), ("Offline Users", offline)):
            if not group:
                continue
            sec = self.store.append(None, [False, f"{title} ({len(group)})", "", "", "", "", "", "", False, False,
                                           Pango.Weight.BOLD])
            for u in group:
                uid = u.get("_id", "")
                n = sum(1 for k in (u.get("links") or {}) if k.startswith("mesh/"))
                s = self.sessions.get(uid)
                if s:
                    access = "1 session" if s == 1 else f"{s} sessions"
                else:
                    access = ui.fmt_date(u.get("access") or u.get("login"))
                tip = f"{u.get('name', '')} - {uid}\nServer rights: {_rights_summary(u)}"
                self.store.append(sec, [uid in self._checked, u.get("name", ""), str(n), access,
                                        permissions_label(u), "Yes" if _has_2fa(u) else "No", uid, tip, True,
                                        uid != me, Pango.Weight.NORMAL])
        self.tree.expand_all()
        shown, total = len(users), len(self._users)
        self.status.set_text(("%d user(s)" % total if shown == total else "%d of %d user(s)" % (shown, total))
                             + ", double-click a user to open it")
        self._update_selection_buttons()

    def _on_sessions(self, msg):
        ws = msg.get("wssessions")
        if isinstance(ws, dict):
            self.sessions = {k: v for k, v in ws.items() if isinstance(v, int) and v > 0}
            self._render()
            if self.page is not None:
                self.page.render()

    def group_action(self):
        """web UI p3usersGroupActionFunction: lock / unlock / (in)validate email / delete the checked users."""
        ids = [u for u in self._checked]
        if not ids:
            return
        users = {u.get("_id"): u for u in self._users}
        emailcheck = bool((self.app.ctrl.serverinfo or {}).get("emailcheck"))
        ops = [("Lock account", "lock"), ("Unlock account", "unlock")]
        if emailcheck:
            ops += [("Validate Email", "verify"), ("Invalidate Email", "unverify")]
        ops.append(("Delete account", "delete"))
        d = Gtk.Dialog(title="Group Action", transient_for=self.get_toplevel(), modal=True)
        area = d.get_content_area()
        area.set_spacing(8)
        area.set_border_width(12)
        area.pack_start(Gtk.Label(label=f"Select an operation to perform on the {len(ids)} selected user(s).",
                                  xalign=0), False, False, 0)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label="Operation"), False, False, 0)
        combo = Gtk.ComboBoxText(hexpand=True)
        for label, key in ops:
            combo.append(key, label)
        combo.set_active(0)
        row.pack_start(combo, True, True, 0)
        area.pack_start(row, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        op = combo.get_active_id()
        d.destroy()
        if not ok:
            return
        ctrl = self.app.ctrl
        if op == "delete":
            if not ui.confirm(self.get_toplevel(), "Delete Accounts",
                              f"Confirm deletion of {len(ids)} selected account(s)?", "Delete", True):
                return
            for uid in ids:
                ctrl.send({"action": "deleteuser", "userid": uid, "username": users.get(uid, {}).get("name")})
            self._checked.clear()
        for uid in ids if op != "delete" else []:
            u = users.get(uid) or {}
            sa = u.get("siteadmin") if isinstance(u.get("siteadmin"), int) else 0
            if op == "lock" and not sa & 32:
                ctrl.send({"action": "edituser", "id": uid, "siteadmin": sa + 32})
            elif op == "unlock" and sa & 32 and sa != 0xFFFFFFFF:
                ctrl.send({"action": "edituser", "id": uid, "siteadmin": sa - 32})
            elif op == "verify" and u.get("emailVerified") is not True:
                ctrl.send({"action": "edituser", "id": uid, "emailVerified": True})
            elif op == "unverify" and u.get("emailVerified") is True:
                ctrl.send({"action": "edituser", "id": uid, "emailVerified": False})
        self.refresh_soon(1200)

    def export_users(self, fmt):
        users = sorted(self._users, key=lambda x: (x.get("name") or "").lower())
        if fmt == "csv":
            _save_text(self.get_toplevel(), "Export users", "userlist.csv", users_to_csv(users))
        else:
            _save_text(self.get_toplevel(), "Export users", "userlist.json", users_to_json(users))

    def new_account(self):
        return NewAccountDialog(self.get_toplevel(), self.app.ctrl, on_done=self.refresh)

    # ---- user page ------------------------------------------------------------------------------
    def open_user(self, userid):
        from .user_panel import UserPage
        user = next((u for u in self._users if u.get("_id") == userid), None)
        if user is None:
            return
        if self.page is not None:
            self.page.destroy()
        for w in self.get_children():
            w.hide()
        self.page = UserPage(self, user)
        self.pack_start(self.page, True, True, 0)
        self.page.show()
        self.app.ctrl.send({"action": "usergroups"})     # memberships section (needs site right 256 to change)
        return self.page

    def close_user(self):
        if self.page is not None:
            self.page.destroy()
            self.page = None
        for w in self.get_children():
            w.show()

    def _on_usergroups(self, msg):
        ug = msg.get("ugroups")
        if isinstance(ug, dict):
            self.usergroups = ug
            if self.page is not None:
                self.page.render()

    def refresh_soon(self, ms=700):
        """Re-read the user list shortly (after our own change; events also trigger this)."""
        if self._soon:
            GLib.source_remove(self._soon)
        self._soon = GLib.timeout_add(ms, self._refresh_now)

    def _refresh_now(self):
        self._soon = None
        self.refresh()
        return False

    def _on_event(self, msg):
        ev = msg.get("event") or {}
        act = ev.get("action")
        if act == "wssessioncount" and ev.get("userid"):         # a user opened / closed a session
            c = ev.get("count") or 0
            if c > 0:
                self.sessions[ev["userid"]] = c
            else:
                self.sessions.pop(ev["userid"], None)
            if self._started:
                self._render()
                if self.page is not None and self.page.user.get("_id") == ev["userid"]:
                    self.page.render()
            return
        if act in ("accountcreate", "accountchange", "accountremove", "usergroupchange", "meshchange",
                   "changenode", "removenode"):
            acc = ev.get("account") or {}
            if self.page is not None and act == "accountchange" and acc.get("_id") == self.page.user.get("_id"):
                self.page.on_account_event(ev)
            if act == "usergroupchange" and self.page is not None:
                self.app.ctrl.send({"action": "usergroups"})
            if self._started:
                self.refresh_soon(1000)

    def teardown(self):
        super().teardown()
        self.app.ctrl.off("event", self._on_event)
        self.app.ctrl.off("usergroups", self._on_usergroups)
        self.app.ctrl.off("wssessioncount", self._on_sessions)
        if self._soon:
            GLib.source_remove(self._soon)
            self._soon = None
        if self.page is not None:
            self.page.destroy()
            self.page = None

    def import_users(self):
        return UserImportDialog(self.get_toplevel(), self.app.ctrl,
                                [u.get("name") or "" for u in self._users], on_done=self.refresh)

    def request(self):
        self.app.ctrl.send({"action": "users"})
        self.app.ctrl.send({"action": "wssessioncount"})

    def _check_timeout(self):
        if not self._replied:
            sa = (self.app.ctrl.userinfo or {}).get("siteadmin") or 0
            # MESHRIGHT manage-users bit is 2; full admin is 0xFFFFFFFF.
            if isinstance(sa, int) and (sa == 0xFFFFFFFF or (sa & 2)):
                self.status.set_text("No response from server.")
            else:
                self.status.set_text("Your account does not have rights to list users "
                                     "(requires site user-management permission).")
        return False

    def _fill(self, msg):
        userslist = msg.get("users") or []
        if isinstance(userslist, dict):
            userslist = list(userslist.values())
        self._users = userslist
        self.export_btn.set_sensitive(bool(userslist))
        self.import_btn.set_sensitive(rights.has_site(self.app.ctrl, rights.SITE_MANAGEUSERS))
        self._render()
        if self.page is not None:                        # keep the open user page current
            fresh = next((u for u in userslist if u.get("_id") == self.page.user.get("_id")), None)
            if fresh is None:
                self.close_user()                        # deleted (here or elsewhere)
            else:
                self.page.set_user(fresh)


# UserGroupsPanel lives in group_panel.py (list + GroupPage).


class ServerEventsPanel(_TablePanel):
    COLUMNS = [("Time", False), ("User", False), ("Action", False), ("Message", True)]
    ACTION = "events"

    def request(self):
        self.app.ctrl.send({"action": "events", "limit": 300})

    def _on_reply(self, msg):
        if msg.get("nodeid") or msg.get("userid"):
            return          # a device's or a user's events (other panels), not the server-wide list
        super()._on_reply(msg)

    def _fill(self, msg):
        self.store.clear()
        events = msg.get("events") or []
        for e in events:
            m = e.get("msg")
            self.store.append([ui.fmt_time(e.get("time")), e.get("username", ""),
                               e.get("action", ""), m if isinstance(m, str) else ""])
        self.status.set_text("%d event(s)" % len(events))


class AccountPanel(Gtk.Box):
    """My account + server info, rendered from cached userinfo / serverinfo."""

    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.node = node
        self._started = False
        self.pack_start(_toolbar(self.refresh), False, False, 0)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self.pack_start(ui.scrolled(self.box), True, True, 0)
        self.show_all()

    def on_shown(self):
        if self._started:
            return
        self._started = True
        self.refresh()

    def _section(self, title):
        lbl = Gtk.Label(xalign=0, margin_top=6)
        lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
        self.box.pack_start(lbl, False, False, 0)

    def _kv(self, grid, row, key, val):
        k = Gtk.Label(label=str(key), xalign=1)
        k.get_style_context().add_class("dim-label")
        grid.attach(k, 0, row, 1, 1)
        v = Gtk.Label(label="" if val is None else str(val), xalign=0, selectable=True,
                      wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        grid.attach(v, 1, row, 1, 1)

    def _grid(self, pairs):
        grid = Gtk.Grid(row_spacing=4, column_spacing=16, margin_start=8)
        for i, (k, v) in enumerate(pairs):
            self._kv(grid, i, k, v)
        self.box.pack_start(grid, False, False, 0)

    def refresh(self):
        for c in self.box.get_children():
            self.box.remove(c)
        ui_info = self.app.ctrl.userinfo or {}
        srv = self.app.ctrl.serverinfo or {}

        self._section("My account")
        acct = [("Name", ui_info.get("name")),
                ("User ID", ui_info.get("_id")),
                ("Email", ui_info.get("email")),
                ("Email verified", ui_info.get("emailVerified")),
                ("Rights", _rights_summary(ui_info)),
                ("Two-factor", "Enabled" if _has_2fa(ui_info) else "Not enabled")]
        self._grid([(k, v) for k, v in acct if v not in (None, "")])

        self._section("Server")
        s = [("Server name", srv.get("name")),
             ("Version", srv.get("ver") or srv.get("serverversion")),
             ("Host", self.app.ctrl.server.host),
             ("Domain", srv.get("domain")),
             ("Agent count", srv.get("agentCount")),
             ("Time", ui.fmt_time(srv.get("serverTime")) if srv.get("serverTime") else None)]
        self._grid([(k, v) for k, v in s if v not in (None, "")])

        # Full dumps for anything not surfaced above.
        if ui_info:
            self._section("Account details (raw)")
            self.box.pack_start(ui.json_tree(ui_info), False, False, 0)
        if srv:
            self._section("Server details (raw)")
            self.box.pack_start(ui.json_tree(srv), False, False, 0)
        self.box.show_all()

    def teardown(self):
        pass
