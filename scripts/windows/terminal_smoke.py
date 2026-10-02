# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows build check: the terminal widget (xterm.js in WebView2, mcdesktop.winterm).

Run by the Windows CI job after scripts/windows/fetch-assets.sh. Exit code 0 = every check passed.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pkg", "usr", "share", "meshcentral-desktop"))

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402
from mcdesktop.winterm import XtermTerminal  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("  " + repr(info) if info != "" else ""), flush=True)


class Smoke:
    def __init__(self):
        self.commits = []
        self.sizes = []
        self.win = Gtk.Window(title="MeshCentral Desktop terminal smoke")
        self.win.set_default_size(900, 500)
        self.term = XtermTerminal()
        self.term.set_scrollback_lines(5000)
        self.term.connect("commit", lambda _t, text, n: self.commits.append(text))
        self.term.connect("char-size-changed", lambda _t, c, r: self.sizes.append((c, r)))
        self.win.add(self.term)
        # output queued before the page exists must still appear, in order
        self.term.feed(b"Hello \x1b[1;32mMCD\x1b[0m\r\n")
        self.term.feed("caf\u00e9 \u2713\r\n")
        self.win.show_all()
        GLib.timeout_add_seconds(60, lambda: (check("finished in time", False), self.finish()))
        GLib.timeout_add(4000, self.step1)

    def js(self, code, cb):
        self.term.web.run_javascript(code, cb)

    def step1(self):
        check("page ready", self.term._ready)
        c, r = self.term.get_column_count(), self.term.get_row_count()
        check("size reported by the page", c > 40 and r > 10 and self.sizes, (c, r, self.sizes))
        self.js("term.buffer.active.getLine(0).translateToString(true) + '|' + "
                "term.buffer.active.getLine(1).translateToString(true)",
                lambda v: (check("queued output rendered (escape codes, UTF-8)", v == "Hello MCD|caf\u00e9 \u2713", v),
                           self.step2()))
        return False

    def step2(self):
        self.js("term.paste('dir C:\\\\'); 1", lambda v: GLib.timeout_add(500, self.step3))

    def step3(self):
        check("typed text reaches the app (commit)", "".join(self.commits) == "dir C:\\", self.commits)
        self.before = (self.term.get_column_count(), self.term.get_row_count())
        self.term.set_font_scale(1.5)
        GLib.timeout_add(1000, self.step4)
        return False

    def step4(self):
        after = (self.term.get_column_count(), self.term.get_row_count())
        check("zoom changes the terminal size", after[0] < self.before[0], (self.before, after))
        self.term.reset(True, True)
        self.term.feed(b"copy me\r\n")
        GLib.timeout_add(500, self.step5)
        return False

    def step5(self):
        self.js("term.selectAll(); 1", lambda v: (self.term.copy_clipboard_format(None),
                                                  GLib.timeout_add(800, self.step6)))

    def step6(self):
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""
        check("copy goes to the GTK clipboard", "copy me" in text, text[:40])
        self.finish()
        return False

    def finish(self):
        print("%d/%d" % (sum(R), len(R)), flush=True)
        Gtk.main_quit()
        return False


Smoke()
Gtk.main()
sys.exit(0 if R and all(R) else 1)
