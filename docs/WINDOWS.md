# Windows version

MeshCentral Desktop for Windows 10 / 11 (x64) is built from the same source code as the Linux package.
The interface is the same GTK application; the parts that depend on Linux-only libraries have Windows
equivalents. Nothing opens in a browser: the remote desktop, the terminal and the chat windows are
embedded in the app.

**Status: in development, not released yet.** Every change is built and tested on a Windows machine in
CI (see [Tests](#tests)); the installers are published with a release once they have also been checked
by hand on Windows 11.

## What is different on Windows

| Linux | Windows | Module |
|---|---|---|
| WebKitGTK (remote desktop viewer, chat, Web-VNC / RDP / SSH) | Microsoft Edge **WebView2**, embedded in a native child window of the GTK window | `winweb.py`, behind `webview.py` |
| VTE terminal | **xterm.js** (MIT) inside WebView2, same panel and relay code | `winterm.py` |
| Secret Service / GNOME keyring | **Windows Credential Manager** (generic credential of the current user) | `osdep.py` |
| "Send hotkeys": keyboard grab (X11) / shortcuts inhibit (Wayland) | low-level keyboard hook while the remote screen has focus: Windows key, Win+key, Alt+Tab, Alt+Esc, Alt+Space, Alt+F4, Ctrl+Esc go to the remote computer | `winkeys.py` |
| desktop notifications (D-Bus) | Windows notifications (notification area, shown as toasts) | `osdep.py` |
| single instance through D-Bus | named mutex: a second launch brings the running window to the front | `osdep.py` |

`webview.py` is the one API the panels use; on Linux it is the previous WebKit code, unchanged. Both
backends apply the same rules: a view bound to the server never leaves its origin, pages cannot open
windows, download files or read the clipboard, and page dialogs never block.

Notes:

- GTK cannot draw over a native window, so on Windows the "connecting" cover hides the web page instead of
  covering it, and the fullscreen hint is shown in the status line.
- Keys typed in the remote screen go to WebView2, not to GTK; Ctrl+Alt+F (fullscreen) is caught through
  WebView2's accelerator event.
- Ctrl+Alt+Del cannot be captured on Windows (secure attention sequence): use the toolbar button.

## Requirements

- Windows 10 version 1809 or later, or Windows 11, 64-bit.
- The Microsoft Edge WebView2 Runtime (part of Windows 11 and current Windows 10). The installer warns
  when it is missing.

## Installers

| File | Use |
|---|---|
| `MeshCentralDesktop-<version>-setup.exe` | Inno Setup wizard. Installs for the current user (no administrator needed) or, if chosen, for all users. Start menu entry, optional desktop shortcut, uninstall from *Settings > Apps*. Closes a running copy before upgrading. |
| `MeshCentralDesktop-<version>.msi` | Per-machine Windows Installer package for managed deployment (Group Policy, Intune, `msiexec /i ... /qn`). Major upgrades replace older versions. |

Both install the same program folder (`MeshCentralDesktop.exe` with its own Python, GTK, the WebView2
loader and xterm.js). Settings are kept in `%LOCALAPPDATA%\meshcentral-desktop`, the web view data in
`%LOCALAPPDATA%\MeshCentralDesktop\webview2`.

The installers are not code-signed yet, so Windows SmartScreen may show "Windows protected your PC";
choose *More info > Run anyway*. The build has a signing step ready (`scripts/windows/sign.ps1`): it
signs every binary of the app (the `.exe` and all its `.dll` / `.pyd` libraries) and both installers as
soon as the repository has a code-signing certificate (secrets `WINDOWS_SIGN_PFX_BASE64` and
`WINDOWS_SIGN_PFX_PASSWORD`).

**Windows 11 Smart App Control** (on by default on new Windows 11 installations) checks every binary a
program loads. With the current unsigned build:

- in its *evaluation* mode each unsigned library is looked up online the first time, so the first start
  takes several minutes (later starts are normal);
- once it switches to *enforcement*, unsigned libraries without a reputation are blocked and the app does
  not start.

Code signing removes both problems; until then the app is meant for computers where Smart App Control is
off (*Windows Security > App & browser control > Smart App Control*).

## Building

The build runs in an MSYS2 **UCRT64** shell on Windows:

```bash
pacman -S --needed unzip mingw-w64-ucrt-x86_64-{gtk3,python,python-gobject,python-cairo,python-websocket-client,python-comtypes,adwaita-icon-theme,pyinstaller,pyinstaller-hooks-contrib}
scripts/windows/build.sh            # -> dist/MeshCentralDesktop/MeshCentralDesktop.exe
```

`build.sh` downloads the third-party files pinned by version and SHA-256 (`scripts/windows/fetch-assets.sh`:
WebView2 SDK, xterm.js, its fit add-on) into `build/`, makes the icon and the version resource, and runs
PyInstaller (`packaging/windows/meshcentral-desktop.spec`). The installers are then made with Inno Setup
(`packaging/windows/installer.iss`) and WiX 5 (`packaging/windows/MeshCentralDesktop.wxs`); the exact
commands are in `.github/workflows/ci.yml`.

`MeshCentralDesktop.exe --selftest <file.json>` checks a bundled or installed copy: every module, GTK and
its icons, TLS with the Windows certificate store, the WebView2 runtime, the terminal page and a Credential
Manager round trip. It never contacts a MeshCentral server.

## Tests

The `windows` job of the CI workflow runs on a Windows Server 2025 machine:

1. `scripts/windows/webview2_smoke.py`: WebView2 inside a GTK window (page, scripts, injected CSS, blocked
   pop-ups and cross-site navigation, no clipboard access).
2. `scripts/windows/terminal_smoke.py`: the xterm.js terminal (output, UTF-8, typing, resize, copy).
3. `scripts/windows/app_smoke.py`: the whole app against a throwaway local MeshCentral server and a real
   Windows agent: Registry (list, create a key and a value, export, delete), terminal (Admin Shell),
   Files, the remote desktop in WebView2, a notification.
4. Bundle, `--selftest` of the bundle, both installers built, each installed silently, self-tested and
   uninstalled.

Known on the CI machine only: the agent closes the **Admin PowerShell** console right after opening it
(cmd works through the same agent code and the app sends the web interface's exact options); this is
reported, not failed, and is checked by hand on Windows 11.
