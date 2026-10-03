# Windows version

MeshCentral Desktop for Windows 10 / 11 (x64) is built from the same source code as the Linux package.
The interface is the same GTK application; the parts that depend on Linux-only libraries have Windows
equivalents. Nothing opens in a browser: the remote desktop, the terminal and the chat windows are
embedded in the app.

**Status: preview since 2.26.0, not code-signed yet.** Every change is built and tested on a Windows
machine in CI (see [Tests](#tests)) and checked on Windows 11. Tested on Windows so far: sign-in, the
device list, Registry, Files, the terminal (cmd and PowerShell, admin and user), the remote desktop,
notifications, the saved password and the installers. Not yet tested there: Send hotkeys, clipboard
sync, the chat and Web-VNC / RDP / SSH windows, My Files transfers, the server charts and the account
settings.

## What is different on Windows

| Linux | Windows | Module |
|---|---|---|
| WebKitGTK (remote desktop viewer, chat, Web-VNC / RDP / SSH) | Microsoft Edge **WebView2**, embedded in a native child window of the GTK window | `winweb.py`, behind `webview.py` |
| VTE terminal | **xterm.js** (MIT) inside WebView2, same panel and relay code | `winterm.py` |
| Secret Service / GNOME keyring | **Windows Credential Manager** (generic credential of the current user) | `osdep.py` |
| "Send hotkeys": keyboard grab (X11) / shortcuts inhibit (Wayland) | low-level keyboard hook while the remote screen has focus: Windows key, Win+key, Alt+Tab, Alt+Esc, Alt+Space, Alt+F4, Ctrl+Esc go to the remote computer | `winkeys.py` |
| desktop notifications (D-Bus) | Windows notifications (notification area, shown as toasts) | `osdep.py` |
| single instance through D-Bus | named mutex: a second launch brings the running window to the front | `osdep.py` |
| GTK theme (Adwaita), app setting for dark mode | **Windows 11 look**: Segoe UI, the system light / dark mode and accent colour (followed live), Windows 11 controls and caption buttons, native dialog title bars in the same mode | `winstyle.py` |

`webview.py` is the one API the panels use; on Linux it is the previous WebKit code, unchanged. Both
backends apply the same rules: a view bound to the server never leaves its origin, pages cannot open
windows, download files or read the clipboard, and page dialogs never block.

Notes:

- GTK cannot draw over a native window, so on Windows the "connecting" cover hides the web page instead of
  covering it, and the fullscreen hint is shown in the status line.
- Keys typed in the remote screen go to WebView2, not to GTK; Ctrl+Alt+F (fullscreen) is caught through
  WebView2's accelerator event.
- Ctrl+Alt+Del cannot be captured on Windows (secure attention sequence): use the toolbar button.

### Windows 11 look

`winstyle.py` lays a style sheet over GTK's own theme. It reads *Settings > Personalization > Colors*
from the registry (`AppsUseLightTheme` and the `AccentPalette` Windows derives from the accent colour)
and checks again every 2 seconds, so switching between light and dark, or changing the accent colour,
applies to the open app. Accent fills use the palette shade Windows 11 itself uses (a lighter shade in
dark mode, a darker one in light mode). The header bars get drawn minimise / maximise / close buttons
with the Windows 11 glyphs (GTK's own title buttons come from theme icons that CSS cannot replace);
dialogs keep the native title bar, which DWM is told to draw in the same mode and colour, with rounded
corners. The style can be previewed on Linux with `MCD_WIN11_STYLE=dark` (or `light`) in the
environment; without it Linux keeps its normal look.

## Requirements

- Windows 10 version 1809 or later, or Windows 11, 64-bit.
- The Microsoft Edge WebView2 Runtime (part of Windows 11 and current Windows 10). The installer warns
  when it is missing.

## Installers

| File | Use |
|---|---|
| `MeshCentralDesktop-<version>-setup.exe` | Inno Setup wizard. Installs for the current user (no administrator needed) or, if chosen, for all users. Start menu entry, optional desktop shortcut, uninstall from *Settings > Apps*. Closes a running copy before upgrading. |
| `MeshCentralDesktop-<version>.msi` | Per-machine Windows Installer package for managed deployment (Group Policy, Intune, `msiexec /i ... /qn`). Major upgrades replace older versions. |
| `MeshCentralDesktop-<version>-portable.exe` | Single file, runs without installation. It unpacks itself to a temporary folder at each start, so it starts more slowly than the installed copy. Settings are the same as the installed app's. |

The setup `.exe` and the `.msi` install the same program folder (`MeshCentralDesktop.exe` with its own Python, GTK, the WebView2
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

## Updates

The app offers new versions itself (card *New version available*, menu *Check for updates*). On Windows the
upgrade closes the app, runs the new installer of the same kind silently (setup `.exe` keeps the per-user /
all-users choice; the `.msi` asks for administrator rights) and starts the app again; the portable `.exe`
downloads the new portable file next to the old one. Downloads are checked against the release's
`SHA256SUMS`. The CI tests this hand-over for real with both installers.

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

Two CI jobs run on Windows Server 2025 machines. The `windows` job builds what is published and runs
no third-party server code:

1. `scripts/windows/webview2_smoke.py`: WebView2 inside a GTK window (page, scripts, injected CSS, blocked
   pop-ups and cross-site navigation, no clipboard access).
2. `scripts/windows/terminal_smoke.py`: the xterm.js terminal (output, UTF-8, typing, resize, copy).
3. Bundle, `--selftest` of the bundle, both installers built, each installed silently, self-tested and
   uninstalled, and the in-app upgrade hand-over for both installers.

The `windows-app` job runs `scripts/windows/app_smoke.py`: the whole app against a throwaway local
MeshCentral server (installed from `scripts/windows/ci-server/package-lock.json` with `npm ci
--ignore-scripts`) and a real Windows agent: Registry (list, create a key and a value, export, delete),
terminal (Admin Shell), Files, the remote desktop in WebView2, a notification. Nothing from this job
reaches the installers; the release waits for both jobs.

The installed or portable app loads WebView2Loader.dll, WebView2.tlb and xterm.js only from its own
bundle. `MCD_WEBVIEW2_DIR`, `MCD_ASSETS_DIR` and `MCD_TEST_INSECURE_TLS` are honoured only when the
app runs from the source tree (development, CI).

Known on the CI machine only: the agent closes the **Admin PowerShell** console right after opening it
(cmd works through the same agent code and the app sends the web interface's exact options); this is
reported, not failed, and is checked by hand on Windows 11.
