# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""`meshcentral-desktop --selftest <out.json>`: checks that an installed or bundled copy has everything it
needs (used by the Windows build to test the packaged .exe). Never contacts a MeshCentral server; the
TLS check opens one HTTPS connection to www.microsoft.com to prove the system certificate store works."""
import importlib
import json
import os
import pkgutil
import socket
import ssl
import sys
import traceback


def _save(results, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def _check(results, name, fn):
    results[name] = {"ok": False, "error": "running (did not finish)"}
    _save(results, results["_out"])              # progress: a hang shows which step it was
    try:
        val = fn()
        results[name] = {"ok": True, "value": val}
    except Exception as ex:
        results[name] = {"ok": False, "error": "%s: %s" % (type(ex).__name__, ex),
                         "trace": traceback.format_exc()[-1500:]}


def run(out_path):
    import faulthandler
    # a hung step must not block the build: dump every thread's stack and exit after 2 minutes
    hang_log = open(out_path + ".hang.txt", "w")
    faulthandler.dump_traceback_later(120, exit=True, file=hang_log)
    import gi
    gi.require_version("Gtk", "3.0")                  # before any app module (they import Gtk unversioned)
    import mcdesktop
    from . import osdep
    from . import __version__
    r = {"_out": out_path}

    def modules():
        names = sorted(m.name for m in pkgutil.iter_modules(mcdesktop.__path__))
        skip = set() if osdep.IS_WINDOWS else {"winweb", "winkeys", "winterm"}
        for n in names:
            if n not in skip:
                importlib.import_module("mcdesktop." + n)
        return names
    _check(r, "version", lambda: __version__)
    _check(r, "modules", modules)

    def gtk():
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GdkPixbuf
        theme = Gtk.IconTheme.get_default()
        return {"gtk": "%d.%d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()),
                "app_icon": theme.has_icon("meshcentral-desktop"),
                "symbolic_icons": theme.has_icon("view-refresh-symbolic"),
                "png_loader": "png" in [f.get_name() for f in GdkPixbuf.Pixbuf.get_formats()]}
    _check(r, "gtk", gtk)

    def tls():
        ctx = ssl.create_default_context()
        with socket.create_connection(("www.microsoft.com", 443), timeout=15) as s:
            with ctx.wrap_socket(s, server_hostname="www.microsoft.com") as t:
                return t.version()
    _check(r, "tls_system_store", tls)

    if osdep.IS_WINDOWS:
        def webview2():
            from . import winweb
            winweb.module()                                    # WebView2.tlb wrapper
            return winweb.runtime_version()
        _check(r, "webview2", webview2)

        def xterm():
            from . import winterm
            return len(winterm.page_html())
        _check(r, "xterm_page", xterm)

        def credentials():
            srv, user = "selftest.invalid", "mcd-selftest"
            assert osdep.store_password(srv, user, "päss-✓")
            got = osdep.load_password(srv, user)
            osdep.clear_password(srv, user)
            assert got == "päss-✓", got
            assert osdep.load_password(srv, user) is None
            return True
        _check(r, "credential_manager", credentials)

    def ok(v):
        if not v["ok"]:
            return False
        val = v.get("value")
        return all(val.values()) if isinstance(val, dict) else bool(val)
    r.pop("_out")
    r["all_ok"] = all(ok(v) for k, v in r.items() if isinstance(v, dict))
    _save(r, out_path)
    faulthandler.cancel_dump_traceback_later()
    hang_log.close()
    try:
        os.remove(out_path + ".hang.txt")
    except OSError:
        pass
    return 0 if r["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "selftest.json")))
