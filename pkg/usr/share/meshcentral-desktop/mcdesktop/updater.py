# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Update check and in-app upgrade (Linux .deb, Windows setup .exe / .msi / portable .exe).

Releases come from this project's GitHub releases: the "stable" channel takes the latest release, the
"preview" channel also accepts pre-releases. A newer version is offered only when its tag is a plain
vX.Y.Z above the running version. The download is the exact file name the release workflow publishes for
how this copy was installed, fetched over HTTPS from GitHub only, and installed only if its SHA-256 matches
the release's SHA256SUMS.

Installing:
  deb       pkexec apt-get install <file>   (the system asks for an administrator password), then restart
  inno      setup .exe /SILENT, same mode as the installed copy (per user / all users), after the app exits
  msi       msiexec /i <file> /passive (Windows asks for administrator rights), after the app exits
  portable  the new portable .exe is saved next to the running one and started
  source    (running from a source tree) no installer: the release page is offered instead
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

from . import __version__
from .osdep import IS_WINDOWS

REPO = "d-maggipinto/meshcentral-desktop"
API = "https://api.github.com/repos/%s/releases?per_page=10" % REPO
RELEASES_PAGE = "https://github.com/%s/releases" % REPO
# GitHub serves release files from these hosts (downloads redirect to the asset host)
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                 "objects.githubusercontent.com"}
CHECK_EVERY_S = 12 * 3600
_UA = "MeshCentralDesktop/%s (update check)" % __version__


def parse_version(text):
    """'v2.26.1' / '2.26.1' -> (2, 26, 1); None for anything else (no suffixes, no pre-release tags)."""
    m = re.fullmatch(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def install_kind():
    """How this copy was installed: deb, inno, msi, portable or source."""
    if IS_WINDOWS:
        if not getattr(sys, "frozen", False):
            return "source"
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass = os.path.abspath(getattr(sys, "_MEIPASS", exe_dir))
        if not meipass.lower().startswith(exe_dir.lower()):
            return "portable"                    # single-file build: unpacked to a temporary folder
        if any(n.lower().startswith("unins") and n.lower().endswith(".exe") for n in os.listdir(exe_dir)):
            return "inno"
        return "msi"
    here = os.path.dirname(os.path.abspath(__file__))
    if here.startswith("/usr/share/meshcentral-desktop/"):
        return "deb"
    return "source"


def asset_name(kind, version):
    v = "%d.%d.%d" % version
    return {"deb": "meshcentral-desktop_%s_all.deb" % v,
            "inno": "MeshCentralDesktop-%s-setup.exe" % v,
            "msi": "MeshCentralDesktop-%s.msi" % v,
            "portable": "MeshCentralDesktop-%s-portable.exe" % v}.get(kind)


def _check_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or (p.hostname or "") not in ALLOWED_HOSTS:
        raise ValueError("refusing to download from %s" % (p.hostname or url))


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)                       # every hop must stay on GitHub over HTTPS
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Updater:
    """check(cb) -> cb(info or None, error); download(info, progress, done); install(info, path)."""

    def __init__(self, api=API, current=__version__, ssl_context=None, check_url=_check_url):
        self.api = api
        self.current = parse_version(current) or (0, 0, 0)
        self._check_url = check_url
        self._ssl_context = ssl_context
        self._opener = None              # built at the first request: nothing network-related at app start

    def _get(self, url, timeout=30):
        self._check_url(url)
        if self._opener is None:
            from .client import http_ssl_context
            ctx = self._ssl_context or http_ssl_context()
            self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), _CheckedRedirect())
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
        return self._opener.open(req, timeout=timeout)

    # ---- check -----------------------------------------------------------------------
    def _latest_without_api(self):
        """GitHub's API allows 60 anonymous requests per hour per address (shared by everyone behind
        one public IP). Without it: the "latest release" page redirects to its tag, and the release
        files have fixed URLs. No release notes in that case. -> releases list like the API's"""
        page = RELEASES_PAGE + "/latest"
        with self._get(page) as r:
            tag = r.geturl().rstrip("/").rsplit("/", 1)[-1]
        if not parse_version(tag):
            raise ValueError("the latest release could not be identified")
        names = [asset_name(k, parse_version(tag)) for k in ("deb", "inno", "msi", "portable")] + ["SHA256SUMS"]
        base = "https://github.com/%s/releases/download/%s/" % (REPO, tag)
        return [{"tag_name": tag, "prerelease": False, "draft": False, "html_url": RELEASES_PAGE + "/tag/" + tag,
                 "body": "", "assets": [{"name": n, "browser_download_url": base + n} for n in names]}]

    def latest(self, channel="stable"):
        """The newest release for the channel, as info dict, or None if this copy is up to date."""
        try:
            with self._get(self.api) as r:
                releases = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code not in (403, 429):                 # rate limited: use the release page instead
                raise
            releases = self._latest_without_api()
        best = None
        for rel in releases if isinstance(releases, list) else []:
            if rel.get("draft") or (rel.get("prerelease") and channel != "preview"):
                continue
            v = parse_version(rel.get("tag_name"))
            if v and (best is None or v > best[0]):
                best = (v, rel)
        if best is None or best[0] <= self.current:
            return None
        v, rel = best
        assets = {a.get("name"): a for a in rel.get("assets") or [] if isinstance(a, dict)}
        kind = install_kind()
        name = asset_name(kind, v)
        return {"version": v, "text": "%d.%d.%d" % v, "tag": rel.get("tag_name"), "notes": rel.get("body") or "",
                "page": rel.get("html_url") or RELEASES_PAGE, "kind": kind,
                "asset": assets.get(name), "sums": assets.get("SHA256SUMS"), "asset_name": name}

    def check(self, cb, channel="stable"):
        def run():
            try:
                info, err = self.latest(channel), None
            except Exception as ex:
                info, err = None, str(ex)
            GLib.idle_add(lambda: (cb(info, err), False)[1])
        threading.Thread(target=run, daemon=True).start()

    # ---- download + verify -----------------------------------------------------------
    def _expected_sha256(self, info):
        with self._get(info["sums"]["browser_download_url"]) as r:
            text = r.read(1 << 20).decode("utf-8", "replace")
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == info["asset_name"]:
                if re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                    return parts[0]
        raise ValueError("%s is not listed in SHA256SUMS" % info["asset_name"])

    def download(self, info, progress, done):
        """Background download into a private folder; progress(fraction) and done(path, error) on the GTK
        thread. The file is kept only if its SHA-256 matches the release's SHA256SUMS."""
        def run():
            path, err, folder = None, None, None
            try:
                if not info.get("asset") or not info.get("sums"):
                    raise ValueError("this release has no %s" % info.get("asset_name"))
                want = self._expected_sha256(info)
                folder = tempfile.mkdtemp(prefix="mcd-update-")
                path = os.path.join(folder, info["asset_name"])
                h = hashlib.sha256()
                with self._get(info["asset"]["browser_download_url"], timeout=60) as r, open(path, "wb") as f:
                    total = int(r.headers.get("Content-Length") or info["asset"].get("size") or 0)
                    got = 0
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        if total:
                            GLib.idle_add(progress, min(1.0, got / total))
                if h.hexdigest() != want:
                    os.remove(path)
                    path = None
                    raise ValueError("the download does not match its published SHA-256 checksum")
            except Exception as ex:
                err, path = str(ex), None
                if folder:
                    shutil.rmtree(folder, ignore_errors=True)
            GLib.idle_add(lambda: (done(path, err), False)[1])
        threading.Thread(target=run, daemon=True).start()


# ---- install ---------------------------------------------------------------------------
_WIN_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
Start-Transcript -Path $env:MCD_UPD_LOG -Append | Out-Null
# full Windows paths (backslashes): msiexec cannot open "C:/..." (error 1619)
$env:MCD_UPD_FILE = [System.IO.Path]::GetFullPath($env:MCD_UPD_FILE)
$env:MCD_UPD_APP = [System.IO.Path]::GetFullPath($env:MCD_UPD_APP)
"update helper: waiting for process $env:MCD_UPD_PID, then $env:MCD_UPD_KIND $env:MCD_UPD_FILE"
Wait-Process -Id $env:MCD_UPD_PID -Timeout 120 -ErrorAction SilentlyContinue
if ($env:MCD_UPD_KIND -eq 'msi') {
  $p = Start-Process msiexec.exe -ArgumentList @('/i', ('"' + $env:MCD_UPD_FILE + '"'), '/passive', '/norestart') -Wait -PassThru
} else {
  $p = Start-Process $env:MCD_UPD_FILE -ArgumentList @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
}
"installer exit code: $($p.ExitCode)"
Remove-Item -LiteralPath $env:MCD_UPD_FILE -Force
Start-Process $env:MCD_UPD_APP
"started $env:MCD_UPD_APP"
Stop-Transcript | Out-Null
"""


def install_windows(kind, path, app_exe=None):
    """Hand over to a hidden PowerShell that waits for this process to exit, runs the installer and starts
    the (updated) app again. The caller quits the app right after. Paths go through environment variables,
    never through a command line built from strings."""
    import base64
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MeshCentralDesktop")
    os.makedirs(log_dir, exist_ok=True)
    env = dict(os.environ, MCD_UPD_PID=str(os.getpid()), MCD_UPD_KIND=kind,
               MCD_UPD_FILE=os.path.abspath(path), MCD_UPD_APP=os.path.abspath(app_exe or sys.executable),
               MCD_UPD_LOG=os.path.join(log_dir, "update.log"))
    # -EncodedCommand: the script needs no command-line quoting at all (UTF-16LE, base64)
    encoded = base64.b64encode(_WIN_SCRIPT.encode("utf-16-le")).decode("ascii")
    flags = 0x00000200 | 0x08000000                    # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-WindowStyle", "Hidden", "-EncodedCommand", encoded], env=env, creationflags=flags,
                     close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def install_portable(path):
    """Save the new portable .exe next to the running one (or in Downloads) and start it. -> new path"""
    folder = os.path.dirname(os.path.abspath(sys.executable))
    if not os.access(folder, os.W_OK):
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
    dest = os.path.join(folder, os.path.basename(path))
    shutil.move(path, dest)
    subprocess.Popen([dest], close_fds=True, creationflags=0x00000008 | 0x00000200)
    return dest


def install_deb(path, done):
    """pkexec apt-get install <file> in the background; done(ok, message) on the GTK thread."""
    def run():
        try:
            p = subprocess.run(["pkexec", "apt-get", "install", "-y", path], capture_output=True, text=True,
                               timeout=1800)
            ok = p.returncode == 0
            msg = "" if ok else ((p.stderr or p.stdout or "").strip().splitlines() or ["apt-get failed"])[-1]
            if p.returncode in (126, 127):
                msg = "Authorisation was cancelled or pkexec is not available."
        except FileNotFoundError:
            ok, msg = False, "pkexec is not installed: install the package with sudo apt install " + path
        except Exception as ex:
            ok, msg = False, str(ex)
        GLib.idle_add(lambda: (done(ok, msg), False)[1])
    threading.Thread(target=run, daemon=True).start()


def restart_linux():
    """Start a fresh copy once this process has exited (single instance), then the caller quits."""
    pid = str(os.getpid())
    subprocess.Popen(["sh", "-c", 'while kill -0 "$0" 2>/dev/null; do sleep 0.2; done; exec meshcentral-desktop', pid],
                     start_new_session=True, close_fds=True)
