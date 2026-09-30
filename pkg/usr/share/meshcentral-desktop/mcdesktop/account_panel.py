# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""My Account (web UI "My Account"): account security (authenticator app, backup codes, security
keys), account actions (previous logins, notification / localization settings, change password,
login tokens, delete account), device groups (+ New) and the profile image.

Protocol (meshuser.js / webserver.js):
  otpauth-request -> {secret, url} | {err}      otpauth-setup {secret, token} -> {success}
  otpauth-clear -> {success}                     otpauth-getpasswords {subaction 1 new / 2 clear} -> {passwords}
  otp-hkey-get -> {keys:[{i, name, type}]}       otp-hkey-remove {index}
  previousLogins -> {events:[{t, m, a, tn}]}     (m 107 = "Account login from {0}, {1}, {2}")
  changelang {lang}                              changepassword {oldpass, newpass}   (result via notify)
  loginTokens {remove?} -> {loginTokens}         createLoginToken {name, expire} -> {tokenUser, tokenPass, expire}
  updateUserImage {image: dataURL | 0}           GET userimage.ashx (web session)
  createmesh {meshname, meshtype: 2, desc}       POST /deleteaccount {authcookie, apassword1, apassword2}
Two-factor state in userinfo: otpsecret (1 = app set up), otpkeys (backup codes left), otphkeys (keys).
Settings-locked accounts (site right 1024, not full admin) cannot change security settings.
"""
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango

from . import ui, rights
from .client import WebSession, http_ssl_context, USER_AGENT

SITE_LOCKSETTINGS = 0x400
SITE_NONEWGROUPS = 0x40
TOKEN_EXPIRY = [("Unlimited", 0), ("1 minute", 1), ("5 minutes", 5), ("10 minutes", 10), ("15 minutes", 15),
                ("30 minutes", 30), ("45 minutes", 45), ("60 minutes", 60), ("2 hours", 120), ("4 hours", 240),
                ("8 hours", 480), ("12 hours", 720), ("16 hours", 960), ("24 hours", 1440), ("2 days", 2880),
                ("4 days", 5760)]
OTP_ERRORS = {1: "Two-factor settings are locked by the server administrator.",
              3: "Not allowed when signed in with a login token.",
              4: "Authenticator apps are disabled on this server.",
              5: "Your account settings are locked.",
              6: "The server cannot generate authenticator secrets (missing otplib)."}
DATE_FORMATS = [("2026-09-29 21:40:05", "%Y-%m-%d %H:%M:%S"), ("29/09/2026 21:40", "%d/%m/%Y %H:%M"),
                ("09/29/2026 9:40 PM", "%m/%d/%Y %I:%M %p"), ("29 Sep 2026, 21:40", "%d %b %Y, %H:%M")]


def _section(text):
    l = Gtk.Label(xalign=0, margin_top=16, margin_bottom=4)
    l.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return l


def _link(label, cb, tooltip=None, sensitive=True):
    b = Gtk.Button(label=label, relief=Gtk.ReliefStyle.NONE, halign=Gtk.Align.START)
    b.get_child().set_xalign(0)
    b.get_style_context().add_class("mcd-link")
    b.connect("clicked", lambda *_: cb())
    b.set_sensitive(sensitive)
    if tooltip:
        b.set_tooltip_text(tooltip)
    return b


class QrCode(Gtk.DrawingArea):
    """Draws an otpauth:// URL as a QR code (python3-qrcode)."""

    def __init__(self, text, size=220):
        super().__init__()
        self.set_size_request(size, size)
        import qrcode                                       # optional dependency (Recommends)
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        self.matrix = qr.get_matrix()
        self.connect("draw", self._draw)

    def _draw(self, w, cr):
        a = w.get_allocation()
        n = len(self.matrix)
        cell = min(a.width, a.height) / n
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, n * cell, n * cell)
        cr.fill()
        cr.set_source_rgb(0, 0, 0)
        for y, row in enumerate(self.matrix):
            for x, v in enumerate(row):
                if v:
                    cr.rectangle(x * cell, y * cell, cell + 0.5, cell + 0.5)
        cr.fill()
        return False


class AccountPanel(Gtk.Box):
    def __init__(self, app, node=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.ctrl = app.ctrl
        self._started = False
        self._handlers = []
        self._web = None
        self.body = Gtk.Box(spacing=32, margin=18, margin_top=10)
        self.pack_start(ui.scrolled(self.body), True, True, 0)
        self._build()
        self.show_all()

    # ---- helpers ------------------------------------------------------------------
    @property
    def user(self):
        return self.ctrl.userinfo or {}

    @property
    def locked(self):
        sa = rights.site_rights(self.ctrl)
        return sa != rights.FULL and bool(sa & SITE_LOCKSETTINGS)

    def _top(self):
        t = self.get_toplevel()
        return t if isinstance(t, Gtk.Window) else None

    def _session(self):
        if self._web is None:
            self._web = WebSession(self.ctrl)
        return self._web

    def _once(self, action, cb, timeout_s=15, on_timeout=None):
        state = {"done": False}

        def handler(msg):
            if not state["done"]:
                state["done"] = True
                self.ctrl.off(action, handler)
                cb(msg)

        def expire():
            if not state["done"]:
                state["done"] = True
                self.ctrl.off(action, handler)
                if on_timeout:
                    on_timeout()
            return False
        self.ctrl.on(action, handler)
        GLib.timeout_add_seconds(timeout_s, expire)

    def _dialog(self, title, width=460):
        d = Gtk.Dialog(title=title, transient_for=self._top(), modal=True)
        d.set_default_size(width, -1)
        area = d.get_content_area()
        area.set_spacing(8)
        area.set_border_width(14)
        return d, area

    def _copy(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)

    # ---- layout -------------------------------------------------------------------
    def _build(self):
        for c in self.body.get_children():
            self.body.remove(c)
        u = self.user
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>My Account</span>")
        left.pack_start(title, False, False, 0)
        sub = [u.get("name") or "", u.get("email") or "", self._rights_text()]
        who = Gtk.Label(label="  ·  ".join(s for s in sub if s), xalign=0, selectable=True)
        who.get_style_context().add_class("dim-label")
        left.pack_start(who, False, False, 2)

        lock_tip = "Your account settings are locked by an administrator" if self.locked else None
        left.pack_start(_section("Account security"), False, False, 0)
        grid = Gtk.Grid(column_spacing=18, row_spacing=2, margin_start=8)
        rows = [
            ("Authenticator app", "Enabled ✓" if u.get("otpsecret") else "Not set up", self.manage_authenticator),
            ("Backup codes", (f"{u.get('otpkeys')} unused" if u.get("otpkeys") else "None"), self.manage_backup_codes),
            ("Security keys", (f"{u.get('otphkeys')} registered" if u.get("otphkeys") else "None"), self.manage_security_keys),
        ]
        for i, (label, state, cb) in enumerate(rows):
            grid.attach(_link(f"Manage {label.lower()}", cb, lock_tip, not self.locked), 0, i, 1, 1)
            st = Gtk.Label(label=state, xalign=0)
            st.get_style_context().add_class("dim-label")
            grid.attach(st, 1, i, 1, 1)
        left.pack_start(grid, False, False, 0)

        left.pack_start(_section("Account actions"), False, False, 0)
        acts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=8)
        for label, cb, sens in (("View previous logins", self.previous_logins, True),
                                ("Notification settings", self.notification_settings, True),
                                ("Localization settings", self.localization_settings, True),
                                ("Change password", self.change_password, not self.locked),
                                ("Login tokens", self.login_tokens, True),
                                ("Delete account", self.delete_account, not self.locked)):
            acts.pack_start(_link(label, cb, None if sens else lock_tip, sens), False, False, 0)
        left.pack_start(acts, False, False, 0)

        head = Gtk.Box(spacing=8, margin_top=16, margin_bottom=4)
        hl = Gtk.Label(xalign=0)
        hl.set_markup("<b>Device groups</b>")
        head.pack_start(hl, False, False, 0)
        can_new = rights.site_rights(self.ctrl) == rights.FULL or not (rights.site_rights(self.ctrl) & SITE_NONEWGROUPS)
        new = Gtk.Button(label="New", image=Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON),
                         always_show_image=True, relief=Gtk.ReliefStyle.NONE)
        new.connect("clicked", lambda *_: self.new_device_group())
        new.set_sensitive(can_new)
        if not can_new:
            new.set_tooltip_text("Your account may not create device groups")
        head.pack_start(new, False, False, 0)
        left.pack_start(head, False, False, 0)
        self.groups_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                                      min_children_per_line=1, column_spacing=10, row_spacing=10, margin_start=8)
        left.pack_start(self.groups_box, False, False, 0)
        self._fill_groups()
        self.body.pack_start(left, True, True, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.START)
        self.avatar = Gtk.Image()
        frame = Gtk.Frame()
        frame.add(self.avatar)
        right.pack_start(frame, False, False, 0)
        row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        row.pack_start(_link("Change image", self.change_image, None, not self.locked), False, False, 0)
        if u.get("flags", 0) & 1:
            row.pack_start(_link("Remove", self.remove_image, None, not self.locked), False, False, 0)
        right.pack_start(row, False, False, 0)
        self.body.pack_start(right, False, False, 0)
        self._load_avatar()
        self.body.show_all()

    def _rights_text(self):
        sa = rights.site_rights(self.ctrl)
        return "Full administrator" if sa == rights.FULL else ("Administrator" if sa else "User")

    def _fill_groups(self):
        for c in self.groups_box.get_children():
            self.groups_box.remove(c)
        meshes = getattr(self.app, "meshes", {}) or {}
        items = sorted(meshes.values(), key=lambda m: (m.get("name") or "").lower())
        for m in items:
            r = rights.mesh_rights(self.ctrl, m)
            if not r:
                continue
            card = Gtk.Box(spacing=10, margin=8, width_request=260)
            card.pack_start(Gtk.Image.new_from_icon_name("network-workgroup-symbolic", Gtk.IconSize.DND), False, False, 0)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            n = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            n.set_markup(f"<span size='large'>{GLib.markup_escape_text(m.get('name') or '?')}</span>")
            txt.pack_start(n, False, False, 0)
            s = Gtk.Label(label="Full Administrator" if r == rights.FULL else "Partial rights", xalign=0)
            s.get_style_context().add_class("dim-label")
            txt.pack_start(s, False, False, 0)
            card.pack_start(txt, True, True, 0)
            fr = Gtk.Frame()
            fr.add(card)
            self.groups_box.add(fr)
        if not self.groups_box.get_children():
            l = Gtk.Label(label="No device groups", xalign=0)
            l.get_style_context().add_class("dim-label")
            self.groups_box.add(l)
        self.groups_box.show_all()

    def _load_avatar(self, size=200):
        self.avatar.set_from_icon_name("avatar-default-symbolic", Gtk.IconSize.DIALOG)
        self.avatar.set_pixel_size(size)
        if not (self.user.get("flags", 0) & 1):
            return
        fd, path = tempfile.mkstemp(suffix=".img")
        os.close(fd)

        def done(err):
            if not err:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
                    self.avatar.set_from_pixbuf(pb)
                except GLib.Error:
                    pass
            try:
                os.remove(path)
            except OSError:
                pass
        self._session().fetch(f"/userimage.ashx?rnd={int(time.time())}", path, None, done)

    # ---- lifecycle ------------------------------------------------------------------
    def on_shown(self):
        if self._started:
            return
        self._started = True
        for action, cb in (("event", self._on_event), ("meshes", lambda *_: self._fill_groups())):
            self.ctrl.on(action, cb)
            self._handlers.append((action, cb))

    def _on_event(self, msg):
        ev = msg.get("event") or {}
        if ev.get("action") == "accountchange" and (ev.get("account") or {}).get("_id") == self.user.get("_id"):
            GLib.idle_add(lambda: (self._build(), False)[1])     # ControlConnection already updated userinfo

    def teardown(self):
        for action, cb in self._handlers:
            self.ctrl.off(action, cb)
        self._handlers = []

    def refresh(self):
        self._build()

    # ---- account security -------------------------------------------------------------
    def manage_authenticator(self):
        if self.user.get("otpsecret"):
            if ui.confirm(self._top(), "Remove the authenticator app?",
                          "Two-step sign-in with the app will no longer be required. Backup codes and security "
                          "keys are not affected.", "Remove", destructive=True):
                self._once("otpauth-clear", lambda m: ui.message(
                    self._top(), "Authenticator app removed" if m.get("success") else "Could not remove it"))
                self.ctrl.send({"action": "otpauth-clear"})
            return

        def got(msg):
            if msg.get("err") or not msg.get("secret"):
                ui.message(self._top(), "Cannot set up an authenticator app",
                           OTP_ERRORS.get(msg.get("err"), f"Server error {msg.get('err')}"), Gtk.MessageType.ERROR)
                return
            self._authenticator_setup(msg["secret"], msg.get("url") or "")
        self._once("otpauth-request", got, on_timeout=lambda: ui.message(
            self._top(), "No answer from the server",
            "Two-step sign-in may be disabled on this server (it needs a DNS host name and otplib)."))
        self.ctrl.send({"action": "otpauth-request"})

    def _authenticator_setup(self, secret, url):
        d, area = self._dialog("Add authenticator app", 480)
        area.pack_start(Gtk.Label(label="Scan this code with Google Authenticator, Microsoft Authenticator, "
                                        "Aegis or any TOTP app, then enter the 6-digit code it shows.",
                                  wrap=True, xalign=0, max_width_chars=60), False, False, 0)
        try:
            qr = QrCode(url)
            box = Gtk.Box(halign=Gtk.Align.CENTER, margin=6)
            box.pack_start(qr, False, False, 0)
            area.pack_start(box, False, False, 0)
        except ImportError:
            area.pack_start(Gtk.Label(label="(Install python3-qrcode to show a QR code.)", xalign=0), False, False, 0)
        grouped = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
        srow = Gtk.Box(spacing=8)
        sl = Gtk.Label(xalign=0, selectable=True)
        sl.set_markup(f"Secret: <tt>{GLib.markup_escape_text(grouped)}</tt>")
        srow.pack_start(sl, True, True, 0)
        cp = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
        cp.set_tooltip_text("Copy secret")
        cp.connect("clicked", lambda *_: self._copy(secret))
        srow.pack_start(cp, False, False, 0)
        area.pack_start(srow, False, False, 0)
        code = Gtk.Entry(placeholder_text="6-digit code", max_length=6, input_purpose=Gtk.InputPurpose.DIGITS,
                         activates_default=True)
        area.pack_start(code, False, False, 0)
        status = Gtk.Label(xalign=0)
        area.pack_start(status, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("Enable", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        ok.set_sensitive(False)
        ok.set_can_default(True)
        ok.grab_default()
        code.connect("changed", lambda e: ok.set_sensitive(e.get_text().isdigit() and len(e.get_text()) == 6))

        def response(_d, r):
            if r != Gtk.ResponseType.OK:
                d.destroy()
                return
            ok.set_sensitive(False)
            status.set_text("Checking…")

            def res(m):
                if m.get("success"):
                    d.destroy()
                    ui.message(self._top(), "Authenticator app enabled",
                               "Two-step sign-in is now on. Consider creating backup codes (Manage backup codes) "
                               "in case you lose the phone.")
                else:
                    status.set_markup("<span foreground='#e01b24'>Wrong code. Check the phone's time and try again.</span>")
                    code.set_text("")
            self._once("otpauth-setup", res)
            self.ctrl.send({"action": "otpauth-setup", "secret": secret, "token": code.get_text()})
        d.connect("response", response)
        d.show_all()

    def manage_backup_codes(self):
        if not (self.user.get("otpsecret") or self.user.get("otphkeys")):
            ui.message(self._top(), "Backup codes need two-step sign-in",
                       "Set up an authenticator app or a security key first.")
            return

        def show(msg):
            codes = msg.get("passwords") or []
            d, area = self._dialog("Backup codes", 420)
            if codes:
                area.pack_start(Gtk.Label(label="Each code can be used once instead of the authenticator app. Keep "
                                                "them somewhere safe.", wrap=True, xalign=0), False, False, 0)
                grid = Gtk.Grid(column_spacing=24, row_spacing=4, halign=Gtk.Align.CENTER, margin=8)
                for i, c in enumerate(codes):
                    l = Gtk.Label(selectable=True)
                    l.set_markup(f"<tt><big>{GLib.markup_escape_text(str(c))}</big></tt>")
                    grid.attach(l, i % 2, i // 2, 1, 1)
                area.pack_start(grid, False, False, 0)
            else:
                area.pack_start(Gtk.Label(label="You have no backup codes.", xalign=0), False, False, 0)
            if codes:
                d.add_button("Copy", 3)
                d.add_button("Clear codes", 2)
            d.add_button("Generate new codes", 1)
            d.add_button("Close", Gtk.ResponseType.CLOSE)

            def response(_d, r):
                if r == 3:
                    self._copy("\n".join(str(c) for c in codes))
                    return
                d.destroy()
                if r in (1, 2):
                    if r == 2 and not ui.confirm(self._top(), "Clear all backup codes?", "", "Clear", destructive=True):
                        return
                    self._once("otpauth-getpasswords", show)
                    self.ctrl.send({"action": "otpauth-getpasswords", "subaction": r})
            d.connect("response", response)
            d.show_all()
        self._once("otpauth-getpasswords", show, on_timeout=lambda: ui.message(
            self._top(), "No answer from the server", "Backup codes may be disabled on this server."))
        self.ctrl.send({"action": "otpauth-getpasswords"})

    def manage_security_keys(self):
        def show(msg):
            keys = msg.get("keys") or []
            d, area = self._dialog("Security keys", 460)
            store = Gtk.ListStore(str, str, int)
            for k in keys:
                store.append([k.get("name") or "?", {1: "YubiKey OTP", 2: "WebAuthn / FIDO2"}.get(k.get("type"), "Key"),
                              int(k.get("i") or 0)])
            tv = Gtk.TreeView(model=store)
            tv.append_column(ui.text_column("Name", 0, True))
            tv.append_column(ui.text_column("Type", 1))
            scr = ui.scrolled(tv)
            scr.set_min_content_height(140)
            area.pack_start(scr, True, True, 0)
            note = Gtk.Label(label="Registering a new key (WebAuthn / FIDO2) needs a web browser; “Add key” "
                                   "opens your MeshCentral web UI.", wrap=True, xalign=0, max_width_chars=60)
            note.get_style_context().add_class("dim-label")
            area.pack_start(note, False, False, 0)
            d.add_button("Add key in browser", 1)
            rm = d.add_button("Remove", 2)
            rm.get_style_context().add_class("destructive-action")
            rm.set_sensitive(False)
            tv.get_selection().connect("changed", lambda s: rm.set_sensitive(s.get_selected()[1] is not None))
            d.add_button("Close", Gtk.ResponseType.CLOSE)

            def response(_d, r):
                if r == 1:
                    self.app.open_uri(self.ctrl.server.url + "/")
                    return
                if r == 2:
                    model, it = tv.get_selection().get_selected()
                    if it and ui.confirm(self._top(), f"Remove security key “{model[it][0]}”?", "", "Remove",
                                         destructive=True):
                        self.ctrl.send({"action": "otp-hkey-remove", "index": model[it][2]})
                        model.remove(it)
                    return
                d.destroy()
            d.connect("response", response)
            d.show_all()
        self._once("otp-hkey-get", show, on_timeout=lambda: ui.message(
            self._top(), "No answer from the server", "Security keys may be disabled on this server."))
        self.ctrl.send({"action": "otp-hkey-get"})

    # ---- account actions ----------------------------------------------------------------
    def previous_logins(self):
        from .user_panel import show_previous_logins
        show_previous_logins(self._top(), self.ctrl, None, "Previous logins")

    def notification_settings(self):
        cfg = self.app.config.setdefault("notify", {})
        d, area = self._dialog("Notification settings", 420)
        area.pack_start(Gtk.Label(label="Notifications shown by this app (stored on this computer):",
                                  xalign=0, wrap=True), False, False, 0)
        opts = [("sound", "Notification sound", False), ("groupname", "Display device group name", True),
                ("connect", "Device connections", False), ("disconnect", "Device disconnections", False),
                ("desktop", "Also show as desktop notifications when the window is in the background", True)]
        checks = {}
        for key, label, default in opts:
            cb = Gtk.CheckButton(label=label, active=bool(cfg.get(key, default)))
            checks[key] = cb
            area.pack_start(cb, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Save", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            for key, cb in checks.items():
                cfg[key] = cb.get_active()
            self.app.save_config()
        d.destroy()

    def localization_settings(self):
        d, area = self._dialog("Localization settings", 440)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        langs = (self.ctrl.serverinfo or {}).get("languages") or []
        lang = None
        if langs:
            grid.attach(Gtk.Label(label="Web UI language", xalign=1), 0, 0, 1, 1)
            lang = Gtk.ComboBoxText()
            lang.append("*", "Browser default")
            for l in langs:
                lang.append(l, l)
            lang.set_active_id(self.user.get("lang") or "*")
            grid.attach(lang, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Dates & times in this app", xalign=1), 0, 1, 1, 1)
        fmt = Gtk.ComboBoxText()
        for label, f in DATE_FORMATS:
            fmt.append(f, label)
        fmt.set_active_id(self.app.config.get("date_format") or DATE_FORMATS[0][1])
        grid.attach(fmt, 1, 1, 1, 1)
        area.pack_start(grid, False, False, 0)
        if langs:
            n = Gtk.Label(label="The language is an account setting on the server (it applies to the web UI and the "
                                "embedded remote desktop); this app itself is in English.", wrap=True, xalign=0,
                          max_width_chars=58)
            n.get_style_context().add_class("dim-label")
            area.pack_start(n, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Save", Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            if lang is not None and lang.get_active_id() != (self.user.get("lang") or "*"):
                self.ctrl.send({"action": "changelang", "lang": lang.get_active_id()})
            self.app.config["date_format"] = fmt.get_active_id()
            self.app.save_config()
            ui.set_time_format(fmt.get_active_id())
        d.destroy()

    def change_password(self):
        d, area = self._dialog("Change password", 420)
        area.pack_start(Gtk.Label(label="Enter your current password and the new password twice.", xalign=0,
                                  wrap=True), False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        ents = []
        for i, label in enumerate(("Current password", "New password", "Repeat new password")):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            e = Gtk.Entry(visibility=False, hexpand=True, activates_default=True)
            grid.attach(e, 1, i, 1, 1)
            ents.append(e)
        area.pack_start(grid, False, False, 0)
        status = Gtk.Label(xalign=0, wrap=True)
        area.pack_start(status, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("Change password", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        ok.set_can_default(True)
        ok.grab_default()

        def validate(*_):
            a, b, c = (e.get_text() for e in ents)
            good = bool(a) and bool(b) and b == c and b != a
            ok.set_sensitive(good)
            status.set_text("" if good or not c else ("The new passwords do not match." if b != c else
                                                       "The new password must differ from the current one."))
        for e in ents:
            e.connect("changed", validate)
        validate()
        d.show_all()
        r = d.run()
        old, new = ents[0].get_text(), ents[1].get_text()
        d.destroy()
        if r != Gtk.ResponseType.OK:
            return

        # The server answers with a notify message ("Password changed." = msgid 20; errors 17-19, 21 =
        # "Current password not correct.");
        # MainWindow shows those cards. On success keep our own copies of the password current.
        def watch(msg):
            if msg.get("type") != "notify" or msg.get("msgid") not in (17, 18, 19, 20, 21):
                return
            self.ctrl.off("msg", watch)
            if msg.get("msgid") == 20:
                self.ctrl.password = new
                if self.app.config.get("remember"):
                    from .login import store_password
                    store_password(self.app.config.get("server", ""), self.app.config.get("username", ""), new)
        self.ctrl.on("msg", watch)
        GLib.timeout_add_seconds(20, lambda: (self.ctrl.off("msg", watch), False)[1])
        self.ctrl.send({"action": "changepassword", "oldpass": old, "newpass": new})

    def login_tokens(self):
        d, area = self._dialog("Login tokens", 620)
        d.set_default_size(620, 380)
        area.pack_start(Gtk.Label(label="A login token is a temporary username and password that can sign in to your "
                                        "account instead of your real credentials (for tools and scripts).",
                                  wrap=True, xalign=0, max_width_chars=70), False, False, 0)
        store = Gtk.ListStore(str, str, str, str)        # name, user, created, expires
        tv = Gtk.TreeView(model=store)
        for i, (t, ex) in enumerate((("Name", True), ("Token user", False), ("Created", False), ("Expires", False))):
            tv.append_column(ui.text_column(t, i, ex))
        area.pack_start(ui.scrolled(tv), True, True, 0)

        def fill(msg):
            store.clear()
            for t in msg.get("loginTokens") or []:
                store.append([t.get("name") or "", t.get("tokenUser") or "", ui.fmt_time(t.get("created")),
                              "Never" if not t.get("expire") else ui.fmt_time(t.get("expire"))])
        self.ctrl.on("loginTokens", fill)
        d.connect("destroy", lambda *_: self.ctrl.off("loginTokens", fill))
        self.ctrl.send({"action": "loginTokens"})
        d.add_button("Create…", 1)
        rm = d.add_button("Remove", 2)
        rm.get_style_context().add_class("destructive-action")
        rm.set_sensitive(False)
        tv.get_selection().connect("changed", lambda s: rm.set_sensitive(s.get_selected()[1] is not None))
        d.add_button("Close", Gtk.ResponseType.CLOSE)

        def response(_d, r):
            if r == 1:
                self._create_token()
            elif r == 2:
                model, it = tv.get_selection().get_selected()
                if it and ui.confirm(self._top(), f"Remove login token “{model[it][0]}”?",
                                     "Anything using it will no longer be able to sign in.", "Remove", destructive=True):
                    self.ctrl.send({"action": "loginTokens", "remove": [model[it][1]]})
            else:
                d.destroy()
        d.connect("response", response)
        d.show_all()

    def _create_token(self):
        d, area = self._dialog("Create login token", 400)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        name = Gtk.Entry(hexpand=True, max_length=100, activates_default=True)
        exp = Gtk.ComboBoxText()
        for label, v in TOKEN_EXPIRY:
            exp.append(str(v), label)
        exp.set_active(0)
        grid.attach(Gtk.Label(label="Token name", xalign=1), 0, 0, 1, 1)
        grid.attach(name, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Expire time", xalign=1), 0, 1, 1, 1)
        grid.attach(exp, 1, 1, 1, 1)
        area.pack_start(grid, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("Create", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        ok.set_can_default(True)
        ok.grab_default()
        ok.set_sensitive(False)
        name.connect("changed", lambda e: ok.set_sensitive(bool(e.get_text().strip())))
        d.show_all()
        r = d.run()
        nm, ex = name.get_text().strip(), int(exp.get_active_id())
        d.destroy()
        if r != Gtk.ResponseType.OK:
            return

        def show(msg):
            if not msg.get("tokenUser"):
                ui.message(self._top(), "Cannot create a login token", str(msg.get("result") or "Refused by the server"),
                           Gtk.MessageType.ERROR)
                return
            rd, ra = self._dialog("Login token created", 460)
            ra.pack_start(Gtk.Label(label="Copy the password now. It is shown only once.", xalign=0), False, False, 0)
            g = Gtk.Grid(column_spacing=10, row_spacing=6)
            for i, (label, val) in enumerate((("Username", msg["tokenUser"]), ("Password", msg.get("tokenPass") or ""))):
                g.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
                v = Gtk.Label(xalign=0, selectable=True)
                v.set_markup(f"<tt>{GLib.markup_escape_text(val)}</tt>")
                g.attach(v, 1, i, 1, 1)
                b = Gtk.Button.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
                b.connect("clicked", lambda *_, t=val: self._copy(t))
                g.attach(b, 2, i, 1, 1)
            ra.pack_start(g, False, False, 0)
            expire = msg.get("expire")
            ra.pack_start(Gtk.Label(label="Expires: " + ("never" if not expire else ui.fmt_time(expire)), xalign=0),
                          False, False, 0)
            rd.add_button("Close", Gtk.ResponseType.CLOSE)
            rd.connect("response", lambda *_: rd.destroy())
            rd.show_all()
            self.ctrl.send({"action": "loginTokens"})
        self._once("createLoginToken", show)
        self.ctrl.send({"action": "createLoginToken", "name": nm, "expire": ex})

    def delete_account(self):
        d, area = self._dialog("Delete account", 440)
        area.pack_start(Gtk.Label(label=f"This permanently deletes the account “{self.user.get('name')}” and "
                                        "removes it from all device groups and user groups. This cannot be undone.\n\n"
                                        "Type your password in both boxes to confirm.", wrap=True, xalign=0,
                                  max_width_chars=58), False, False, 0)
        e1 = Gtk.Entry(visibility=False, placeholder_text="Password")
        e2 = Gtk.Entry(visibility=False, placeholder_text="Password again")
        area.pack_start(e1, False, False, 0)
        area.pack_start(e2, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("Delete my account", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("destructive-action")
        ok.set_sensitive(False)
        for e in (e1, e2):
            e.connect("changed", lambda *_: ok.set_sensitive(bool(e1.get_text()) and e1.get_text() == e2.get_text()))
        d.show_all()
        r = d.run()
        pw = e1.get_text()
        d.destroy()
        if r != Gtk.ResponseType.OK:
            return

        def post(cookie, _r):
            def run():
                try:
                    body = urllib.parse.urlencode({"authcookie": cookie or "", "apassword1": pw, "apassword2": pw}).encode()
                    req = urllib.request.Request(self.ctrl.server.url + "/deleteaccount", data=body,
                                                 headers={"User-Agent": USER_AGENT})
                    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=http_ssl_context()))
                    opener.open(req, timeout=30).read()
                    err = None
                except Exception as ex:                    # a redirect / closed session is the normal outcome
                    err = None if "302" in str(ex) or "303" in str(ex) else str(ex)
                GLib.idle_add(lambda: (self._after_delete(err), False)[1])
            threading.Thread(target=run, daemon=True).start()
        self.ctrl.get_auth_cookie(post)

    def _after_delete(self, err):
        # The server answers a deleted account and a wrong password with the same redirect and does
        # not close our session, so probe with a fresh sign-in using the password we signed in with:
        # "noauth" means the account is gone; a session (or a 2FA prompt) means it still exists.
        from .client import ControlConnection
        probe = ControlConnection(self.ctrl.server.url, self.ctrl.username, self.ctrl.password)
        state = {"done": False}

        def finish(deleted):
            if state["done"]:
                return
            state["done"] = True
            probe.on_close = None
            probe.close()
            if deleted:
                self._account_deleted()
            else:
                ui.message(self._top(), "The account was not deleted",
                           err or "The password was not accepted (or account deletion is not allowed on this server).",
                           Gtk.MessageType.ERROR)

        def on_close(reason):
            reason = reason or {}
            if reason.get("msg") in ("tokenrequired", "badtlscert", "badargs") or reason.get("cause") != "noauth":
                finish(False)
            else:
                finish(True)
        probe.on_close = on_close
        probe.on("serverinfo", lambda _m: finish(False))
        probe.connect()
        GLib.timeout_add(15000, lambda: (finish(False), False)[1])

    def _account_deleted(self):
        try:
            from .login import clear_password
            clear_password(self.app.config.get("server", ""), self.app.config.get("username", ""))
        except Exception:
            pass
        ui.message(self._top(), "Account deleted", f"The account “{self.user.get('name')}” was deleted. "
                   "You will now be signed out.", Gtk.MessageType.INFO)
        GLib.idle_add(lambda: (self.app.sign_out(), False)[1])

    # ---- device groups & image ---------------------------------------------------------------
    def new_device_group(self):
        r = ui.form_dialog(self._top(), "New device group", [("name", "Name:", "text", ""),
                                                            ("desc", "Description:", "text", "")], "Create")
        if r and r["name"].strip():
            self.ctrl.send({"action": "createmesh", "meshname": r["name"].strip(), "meshtype": 2,
                            "desc": r["desc"].strip()})
            GLib.timeout_add(800, lambda: (self.ctrl.send({"action": "meshes"}), False)[1])

    def change_image(self):
        from .user_panel import choose_account_image
        picked = choose_account_image(self._top())
        if picked:
            url, pb = picked
            self.ctrl.send({"action": "updateUserImage", "image": url})
            self.avatar.set_from_pixbuf(pb.scale_simple(200, 200, GdkPixbuf.InterpType.BILINEAR))

    def remove_image(self):
        if ui.confirm(self._top(), "Remove your account image?", "", "Remove", destructive=True):
            self.ctrl.send({"action": "updateUserImage", "image": 0})
