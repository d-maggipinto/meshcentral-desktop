# Development

MeshCentral Desktop is plain Python 3 with GTK 3 (PyGObject), WebKitGTK and VTE. There is no build
step besides packaging: the source in `pkg/usr/share/meshcentral-desktop/` is what gets installed.

## Requirements

```bash
sudo apt install python3 python3-gi python3-websocket python3-cairo \
  gir1.2-gtk-3.0 gir1.2-vte-2.91 gir1.2-secret-1 gir1.2-webkit2-4.1 \
  fakeroot dpkg-dev
# optional, for the authenticator QR code in My Account:
sudo apt install python3-qrcode
# for testing against a local server:
sudo apt install xvfb nodejs npm xclip
```

The app is developed and tested on Debian and Debian based distributions (Debian 12, Ubuntu 22.04
and later). Keep the code compatible with **Python 3.11** (Debian 12): no Python 3.12
f-string syntax (backslashes or reused quotes inside `{...}`).

## Run from source

```bash
python3 pkg/usr/share/meshcentral-desktop/main.py
```

The app is single instance: if an installed copy is already running, this command only brings it to
the front. Quit it first (`pkill -f meshcentral-desktop`).

## Build the package

1. Set the version in both places: `pkg/DEBIAN/control` (`Version:`) and
   `pkg/usr/share/meshcentral-desktop/mcdesktop/__init__.py` (`__version__`). The About dialog and
   the window subtitle read `__version__`.
2. Run the build script:

   ```bash
   scripts/build-deb.sh
   ```

   It checks that both versions match, normalises file permissions, runs a syntax check, removes
   all Python bytecode (the build machine's Python may differ from the target's) and writes
   `dist/meshcentral-desktop_<version>_all.deb`.

### Windows build

The Windows version is built from the same sources in an MSYS2 UCRT64 shell (`scripts/windows/build.sh`,
PyInstaller, then Inno Setup and WiX). The `windows` job of the CI workflow builds it on every push, runs
the Windows tests and installs both installers; on a version tag the release gets the setup `.exe` and
the `.msi` next to the `.deb`. Details in [WINDOWS.md](WINDOWS.md).

## Tests

The test scripts are kept outside the public repository. Every feature is verified against a
local MeshCentral server and, for remote desktop features, a real agent, as described below.
GitHub Actions checks the Python syntax and builds the package on every push.

### Local test server

All protocol work is verified against a **local** MeshCentral server, never against a production
server.

```bash
mkdir -p ~/mcd-rig/mctest && cd ~/mcd-rig/mctest
npm install meshcentral            # or meshcentral@<version> to match the server you target
node node_modules/meshcentral/meshcentral --cert 127.0.0.1 --createaccount admin --pass Test-1234
node node_modules/meshcentral/meshcentral --adminaccount admin
node node_modules/meshcentral/meshcentral --cert 127.0.0.1 --port 8443 --redirport 8080 --exactports &
```

Then, over the control channel as `admin`, create a device group (`createmesh`), a restricted test
user `limited` (`adduser` with `siteadmin: 0`, then `addmeshuser` with `meshadmin: 0x100 | 0x100000`)
and a user group (`createusergroup`, `addusertousergroup`).

Features that depend on server settings must be tested in each mode. For example the Users page on
a server where the email address is the user name: set `"userNameIsEmail": true` (and, to test
password rules, `"passwordRequirements": {"min": 8, "upper": 1, "numeric": 1}`) in `domains.""` of
`meshcentral-data/config.json`, restart the server, and restore the file afterwards.

Devices without an agent (for permission tests): create a device group with `meshtype: 3` and add a
device with `addlocaldevice {meshid, devicename, hostname, type: 4}`.

**Agent** (remote desktop, terminal, files, tools): download the Linux agent from
`GET /meshagents?id=6` and its settings from
`GET /meshsettings?id=<URL encoded part of the mesh id after "mesh//">` (save as `meshagent.msh`),
then run `./meshagent connect &` from a normal desktop shell. **The agent controls the computer it
runs on.**

The MeshCentral source (`npm pack meshcentral`) is the protocol reference:
`views/default.handlebars` (web interface), `meshuser.js` (control channel), `webserver.js` (HTTP),
`agents/meshcore.js` (agent), `public/scripts/agent-desktop-0.0.2.js` (desktop viewer).

### Testing rules

- **Run GUI tests under Xvfb**, so windows, keyboard grabs and system dialogs never touch your
  session:
  ```bash
  GDK_BACKEND=x11 WEBKIT_DISABLE_DMABUF_RENDERER=1 xvfb-run -a -s "-screen 0 1920x1080x24" python3 <script>.py
  ```
  Under Xvfb the app's clipboard is separate from the desktop session's, which makes clipboard sync
  tests meaningful.
- Test instances use their own application id. With the default id a running installed copy would
  be activated instead, and the test would exit silently.
- Test instances also use their own config, data and cache folders, so they never change your real
  settings: set `XDG_CONFIG_HOME` / `XDG_DATA_HOME` before GLib is imported (the app reads its paths
  when its modules are imported).
- For the self-signed local certificate the scripts turn off TLS verification (WebSocket client,
  WebKit and HTTP transfers). **Local testing only.**
- The test agent drives the real desktop it runs on: when testing keyboard handling, stub the
  viewer's `desktop.m.send`. Do not restart the agent from inside `xvfb-run` (it would capture the
  virtual display).
- `pkill -f` with a pattern that also appears in your own command line kills your shell: use bracket
  patterns such as `pkill -f "[m]eshagent connect"` in a separate command.
- Stop the test agent with SIGTERM, never SIGKILL. A killed agent can corrupt its local database
  (`Unable to open database` on the next start; move `meshagent.db` aside to re-register). Never
  run two agent instances from the same folder. When a test restarts the agent, restore its
  original environment (read `/proc/<pid>/environ` before stopping it).

### Regression scenarios

| Area | Checks |
|---|---|
| Remote desktop | connect, reconnect while connected, disconnect, quick connect, cancel, connect after cancel; first-frame reveal; fullscreen geometry |
| Agent restart | offline detection, console notices, automatic desktop reconnect, no main-loop stalls |
| Keyboard | AltGr filtering, hotkey grab and release, Ctrl+Alt+F, Esc not intercepted |
| Clipboard | agent patch with the empty-display bug simulated, local to remote, remote to local, no echo loops |
| Services / General | systemctl listing speed and states; agent type and core version |
| Files | folder, upload, download (checksum), rename, copy, edit, delete |
| Permissions | full admin and restricted account: tabs, actions, server tabs, view-only desktop, read-only notes |
| Broadcast | send from the app to a user group; receive web-style broadcasts (auto-close and sticky) |
| Run command | `whoami` output |
| My Account | authenticator (TOTP verified), backup codes, login tokens, image upload and read back, new device group, language, connection cards, password change, delete account; always on throwaway accounts |
| Devices list | status filters, search syntax, every sort, stars, checked devices and Select All, Group Action edit tags / move / delete / export, Add Agent links and commands, invite link, Add Device Group (agentless test devices) |
| Users | list with live session counts, filter, Select All, Group Action; New Account (plain and email-as-user-name server, password policy); import and export; user page: every edit dialog, memberships, notes, password change, previous logins, account image, events, delete |
| Groups | list counts, Select All, Group Action delete, New Group, Duplicate Group; group page: rename, description, consent, members with suggestions, device group and device permissions, delete |
| Registry | tab only for Windows devices with an agent and without "no registry"; browse, GoTo, new key / value, edit (number validation), rename, delete, export `.reg`; a non-Windows agent answers with its "Windows agents only" error over the real tunnel |
| Layout / Server | rail entries per account, only the visible device page is built, fullscreen hides the rail; live statistics, history, server console, backup download |

## Release checklist

1. Version set in both places, `scripts/build-deb.sh` succeeds.
2. The changed areas are tested against the local server.
3. `CHANGELOG.md` updated; `README.md` and `docs/` updated for behaviour changes.
4. Push a tag `vX.Y.Z` (`git tag -a vX.Y.Z -m "MeshCentral Desktop X.Y.Z"`, then
   `git push origin vX.Y.Z`). GitHub Actions builds the package and publishes the release with the
   `.deb`, the source as `.tar.gz` and `.zip`, a `SHA256SUMS` file and the release notes taken from
   the matching `CHANGELOG.md` section.
5. Upgrade note for users: quit the running app (`pkill -f meshcentral-desktop`) before installing
   the new package, because the app is single instance.

## Windows test desktop (manual testing)

The `Windows test desktop` workflow (Actions tab, Run workflow) gives a fresh GitHub Windows Server 2025
machine for testing by hand, for 1 to 6 hours: the app installed (latest release or the newest build from
main), optionally a throwaway MeshCentral server on the machine with the machine's own Windows agent (the app
opens on it; its root certificate is trusted on the machine, so TLS is really checked), and Remote Desktop
reachable over Tailscale only. Cancelling the run deletes the machine.

It needs two repository secrets: `TAILSCALE_AUTHKEY` (an ephemeral, reusable key of your Tailscale network)
and `WINDOWS_RDP_PASSWORD` (Remote Desktop as `runneradmin`, also the test server's `admin` password). The
secrets never appear in the logs. `check-only` sets everything up, verifies it and stops (no Tailscale needed).
