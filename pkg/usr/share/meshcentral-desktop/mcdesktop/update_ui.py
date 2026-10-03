# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Update notification and dialog: "a new version is available" card in the main window and the
Updates dialog (check now, automatic checks on / off, channel, release notes, upgrade with progress).
The work itself is in updater.py."""
import re

from gi.repository import Gtk, GLib, Pango

from . import updater, ui, __version__

CHANNELS = [("stable", "Stable releases"), ("preview", "Stable and preview releases")]
_HOW = {"deb": "The update is installed with your administrator password and the app restarts.",
        "inno": "The app closes, installs the update and starts again.",
        "msi": "The app closes, Windows asks for administrator rights, installs the update and starts the app again.",
        "portable": "The new portable version is saved next to this one and started.",
        "source": "This copy runs from the source code: get the new version from the release page."}


def _plain(md):
    """Release notes (GitHub markdown) as readable plain text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", md or "")
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


class UpdateUI:
    def __init__(self, app):
        self.app = app
        self.updater = updater.Updater()
        self.info = None              # newest release found (dict) or None
        self._timer = None
        self._card = None
        self._dialog = None

    # ---- automatic checks ------------------------------------------------------------
    @property
    def cfg(self):
        return self.app.config

    def start(self):
        if self._timer is None:
            GLib.timeout_add_seconds(5, self._auto_check)
            self._timer = GLib.timeout_add_seconds(updater.CHECK_EVERY_S, self._auto_check)

    def _auto_check(self):
        if self.cfg.get("update_check", True):
            self.updater.check(self._on_auto_result, self.cfg.get("update_channel", "stable"))
        return True

    def _on_auto_result(self, info, err):
        if info is None:
            return                     # up to date, or offline: automatic checks stay quiet
        self.info = info
        if self.cfg.get("update_skip") != info["text"]:
            self.show_card()

    # ---- card in the main window -----------------------------------------------------
    def show_card(self):
        win = self.app.main_win
        if win is None or self.info is None or self._card is not None:
            return
        info = self.info
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=360)
        card.get_style_context().add_class("mcd-notify")
        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Image.new_from_icon_name("software-update-available-symbolic", Gtk.IconSize.MENU),
                       False, False, 0)
        t = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        t.set_markup("<b>New version available</b>")
        top.pack_start(t, True, True, 0)
        card.pack_start(top, False, False, 0)
        card.pack_start(Gtk.Label(label="MeshCentral Desktop %s is available (you have %s)." % (info["text"], __version__),
                                  xalign=0, wrap=True, max_width_chars=48), False, False, 0)
        row = Gtk.Box(spacing=6)
        for label, cb, main in (("Upgrade…", self.open_dialog, True), ("Later", self._dismiss_card, False),
                                ("Skip this version", self._skip, False)):
            b = Gtk.Button(label=label)
            if main:
                b.get_style_context().add_class("suggested-action")
            b.connect("clicked", lambda _b, f=cb: f())
            row.pack_start(b, False, False, 0)
        card.pack_start(row, False, False, 0)
        self._card = card
        win.notify_box.pack_start(card, False, False, 0)
        card.show_all()
        if not win.is_active():
            self.app.notify("New version available", "MeshCentral Desktop %s is available." % info["text"])

    def _dismiss_card(self):
        if self._card is not None:
            if self._card.get_parent():
                self._card.get_parent().remove(self._card)
            self._card = None

    def _skip(self):
        if self.info:
            self.cfg["update_skip"] = self.info["text"]
            self.app.save_config()
        self._dismiss_card()

    # ---- dialog ------------------------------------------------------------------------
    def open_dialog(self, check=False):
        """The Updates dialog; check=True (menu "Check for updates") checks again first."""
        self._dismiss_card()
        if self._dialog is not None:
            self._dialog.present()
            return
        parent = self.app.main_win or self.app.login_win
        d = Gtk.Dialog(title="Updates", transient_for=parent, modal=True)
        d.set_default_size(560, -1)
        self._dialog = d
        box = d.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        self.title = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        box.pack_start(self.title, False, False, 0)
        self.how = Gtk.Label(xalign=0, wrap=True, max_width_chars=70)
        self.how.get_style_context().add_class("dim-label")
        box.pack_start(self.how, False, False, 0)
        self.notes = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                  left_margin=8, right_margin=8, top_margin=6, bottom_margin=6)
        self.notes_sw = Gtk.ScrolledWindow(min_content_height=220, hexpand=True, vexpand=True)
        self.notes_sw.add(self.notes)
        box.pack_start(self.notes_sw, True, True, 0)
        self.progress = Gtk.ProgressBar(show_text=True, no_show_all=True)
        box.pack_start(self.progress, False, False, 0)
        opts = Gtk.Box(spacing=12)
        self.auto = Gtk.CheckButton(label="Check for updates automatically",
                                    active=bool(self.cfg.get("update_check", True)))
        self.auto.connect("toggled", lambda w: self._set_cfg("update_check", w.get_active()))
        opts.pack_start(self.auto, False, False, 0)
        self.channel = Gtk.ComboBoxText()
        for cid, label in CHANNELS:
            self.channel.append(cid, label)
        self.channel.set_active_id(self.cfg.get("update_channel", "stable"))
        self.channel.connect("changed", lambda w: (self._set_cfg("update_channel", w.get_active_id()),
                                                   self._check_now()))
        opts.pack_end(self.channel, False, False, 0)
        box.pack_start(opts, False, False, 0)
        acts = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        self.skip_btn = Gtk.Button(label="Skip this version")
        self.skip_btn.connect("clicked", lambda *_: (self._skip(), d.destroy()))
        self.later_btn = Gtk.Button(label="Close")
        self.later_btn.connect("clicked", lambda *_: d.destroy())
        self.go_btn = Gtk.Button(label="Upgrade now")
        self.go_btn.get_style_context().add_class("suggested-action")
        self.go_btn.connect("clicked", lambda *_: self._upgrade())
        for b in (self.skip_btn, self.later_btn, self.go_btn):
            acts.pack_start(b, False, False, 0)
        box.pack_start(acts, False, False, 0)
        d.connect("destroy", lambda *_: setattr(self, "_dialog", None))
        d.show_all()
        if check or self.info is None:
            self._check_now()
        else:
            self._show_info()

    def _set_cfg(self, key, value):
        self.cfg[key] = value
        self.app.save_config()

    def _check_now(self):
        self.title.set_markup("<b>Checking for updates…</b>")
        self.how.set_text("")
        self.notes_sw.hide()
        for b in (self.skip_btn, self.go_btn):
            b.hide()
        self.updater.check(self._on_manual_result, self.cfg.get("update_channel", "stable"))

    def _on_manual_result(self, info, err):
        if self._dialog is None:
            return
        if err:
            self.title.set_markup("<b>Could not check for updates</b>")
            self.how.set_text(err)
            return
        self.info = info
        if info is None:
            self.title.set_markup("<b>MeshCentral Desktop is up to date</b> (version %s)" % __version__)
            self.how.set_text("")
            return
        self._show_info()

    def _show_info(self):
        info = self.info
        self.title.set_markup("<b>MeshCentral Desktop %s is available</b> (you have %s)"
                              % (GLib.markup_escape_text(info["text"]), __version__))
        how = _HOW.get(info["kind"], "")
        if info["kind"] != "source" and not info.get("asset"):
            how = "This release has no %s for this installation: see the release page." % info["asset_name"]
        self.how.set_text(how)
        self.notes.get_buffer().set_text(_plain(info["notes"]) or
                                         "Release notes: %s" % info.get("page", updater.RELEASES_PAGE))
        self.notes_sw.show_all()
        self.skip_btn.show()
        self.later_btn.set_label("Later")
        can_install = info["kind"] != "source" and bool(info.get("asset")) and bool(info.get("sums"))
        self.go_btn.set_label("Upgrade now" if can_install else "Open release page")
        self.go_btn.show()

    # ---- upgrade -------------------------------------------------------------------------
    def _upgrade(self):
        info = self.info
        if info is None:
            return
        if info["kind"] == "source" or not info.get("asset") or not info.get("sums"):
            self.app.open_uri(info["page"])
            return
        for b in (self.go_btn, self.skip_btn, self.later_btn):
            b.set_sensitive(False)
        self.progress.show()
        self.progress.set_fraction(0)
        self.progress.set_text("Downloading %s…" % info["asset_name"])
        self.updater.download(info, self.progress.set_fraction, self._downloaded)

    def _downloaded(self, path, err):
        if self._dialog is None:
            return
        if err or not path:
            self._failed("Download failed: %s" % (err or "unknown error"))
            return
        kind = self.info["kind"]
        self.progress.set_fraction(1)
        if kind == "deb":
            self.progress.set_text("Installing… enter your password when asked")
            updater.install_deb(path, self._deb_done)
        elif kind in ("inno", "msi"):
            self.progress.set_text("Closing the app to install the update…")
            updater.install_windows(kind, path)
            GLib.timeout_add(600, lambda: (self.app.quit(), False)[1])
        elif kind == "portable":
            dest = updater.install_portable(path)
            self.progress.set_text("Started %s" % dest)
            GLib.timeout_add(600, lambda: (self.app.quit(), False)[1])

    def _deb_done(self, ok, msg):
        if self._dialog is None:
            return
        if not ok:
            self._failed("Installation failed: %s" % msg)
            return
        self.progress.set_text("Installed version %s" % self.info["text"])
        if ui.confirm(self._dialog, "Restart MeshCentral Desktop now?",
                      "The new version is installed. It starts when the app restarts.", "Restart now"):
            updater.restart_linux()
            self.app.quit()

    def _failed(self, text):
        self.progress.set_text(text)
        for b in (self.go_btn, self.skip_btn, self.later_btn):
            b.set_sensitive(True)
