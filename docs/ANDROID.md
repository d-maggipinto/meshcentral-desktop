# Android app

The Android app (in development) is a native Kotlin / Jetpack Compose app in [`android/`](../android). It
talks to MeshCentral the same way as the desktop app: the control channel (`control.ashx`) with your user
name, password and two-factor code, and relay tunnels (`meshrelay.ashx`) for the terminal, files and chat.
Like the desktop app it never re-implements the remote desktop protocol: it shows MeshCentral's own viewer
in a web view and adds native controls around it.

It uses the same version number as the desktop app (read from `mcdesktop/__init__.py` at build time).

## Features

| Area | What it does |
|---|---|
| Sign-in | server, user name, password, two-factor code; "Remember password" keeps the password encrypted with a key in the Android Keystore (excluded from backups) |
| Devices | grouped by device group, online count per group, search (name, host, OS, tag, description), online filter, pull to refresh, groups remember whether they are open |
| Device page | General (name, group, host, OS, agent, IP, users, tags, last connection), Hardware and Network from the agent |
| Remote desktop | MeshCentral's viewer signed in automatically and reduced to the remote screen, always fitted whole (also on servers that use the Modern UI); turn the phone sideways for fullscreen; touch gestures; a keyboard with Ctrl, Alt, Shift, Win, Esc, Tab, arrows, Del, Home, End, Page Up / Down and F1 to F12; Ctrl+Alt+Del; quality presets (Data saver, Balanced, Best quality); fullscreen |
| Terminal | xterm.js over the relay; drag up / down to scroll the output (a flick keeps going; in full-screen programs such as less or vim the drag sends arrow keys), a tap opens the keyboard; Root / User / Login shell on Linux and macOS, Admin / User Shell and PowerShell on Windows; extra keys (Esc, Tab, sticky Ctrl and Alt, arrows, Home, End, Page Up / Down); copy, paste, text size |
| Files | browse, download (saved where you choose), upload (several files), new folder, rename, delete |
| Run command | Shell / Command / PowerShell, with the output |
| Power | wake up, sleep, restart, power off (everything except wake up asks first) |
| Chat | native chat with the remote user over the server's chat relay; send files to the remote user and save the files they send; opens the chat window on the remote computer like the desktop app |
| Notifications | broadcasts and server notices; optionally devices connecting or disconnecting (*Settings*) |
| Device tools | events, notes, processes (details, end process), services (start / stop / restart), installed software (uninstall), agent console, Windows registry (browse, edit, export) |
| Device actions | edit name / description / tags, user consent, connection notifications, send a message (toast, message box, alert), open a web address on the remote, log an event, share link for a guest, user authorizations, change group, delete |
| Remote desktop tools | send / get / type the clipboard, screenshot, display picker, remote input lock, lock computer (Windows), open a web address |
| Group actions | press and hold devices to select them: wake up, sleep, restart, power off, run commands (output per device), notification, tags, move to another group, uninstall agent, delete |
| Add device | agent download links and install commands per group (Windows, Linux, macOS, mobile) and invite links, to copy or share |
| Users | list with sessions, user page (details, rights, password, memberships, notes, previous logins, events), new account, broadcast, export to CSV / JSON |
| User groups | list, new / duplicate / delete, members, device group and device permissions, broadcast to a group |
| Server | status and server state, backup download, version and update, error log, configuration, statistics charts, server console and trace (full administrators) |
| Server events, Files | the server event log with filters; server file storage (browse, upload, download, new folder, rename, delete, copy / move, edit small text files) |
| Account | account picture (change from the photo picker or remove), two-factor sign-in (authenticator app, backup codes, security keys), previous logins, password, login tokens, language, device groups |
| Settings | app lock, stay connected in the background, device notifications; About: version, copyright, licence, source code |

Everything is offered according to your account's rights on each device (the same rules as the desktop
app, see [PERMISSIONS.md](PERMISSIONS.md)); the server enforces them.

### Remote desktop gestures

Two modes, switched with the mouse / hand button in the remote desktop toolbar (the choice is remembered):

**Touchpad** (default, like remote-control apps): a cursor is drawn on the remote screen and the phone screen works
like a laptop touchpad.

| Gesture | Remote action |
|---|---|
| slide one finger anywhere | move the cursor (faster swipes travel further) |
| tap | left click at the cursor |
| tap twice | double click |
| press and hold, then move | drag with the left button |
| two-finger tap | right click at the cursor |
| two-finger drag up / down | scroll wheel |
| pinch | zoom in and out; the view follows the cursor |

In fullscreen (also when the phone is turned sideways) the controls are one small see-through handle that can be
dragged to any edge; a tap opens the buttons (keyboard, touchpad / direct touch, reset zoom, tools, exit
fullscreen), which close again after a few seconds.

With the keyboard open, the remote screen keeps its size: the keyboard covers its lower part and the view moves so
the cursor stays in the visible strip (slide to move the cursor there, or pinch to zoom).

**Direct touch**: the finger is the pointer. Tap = left click where you tap, press and hold then move = drag,
one finger moves the pointer (or the view while zoomed); two-finger gestures as above.

The viewer's own touch handlers are not active in MeshCentral's page, so the app injects its own
(`app/src/main/assets/desk/touch.js`). It computes the remote pixel through its zoom and calls the viewer's
`SendMouseMsg`.

The app opens the viewer with `?sitestyle=1` (the classic page) even when the server or the account uses the
Modern UI: on a touch screen the Modern UI shows the remote screen at 1:1 pixels, so only its top-left corner was
visible. As a second safety net `desk/fit.js` switches the page's mobile modes off and sizes the canvas itself.

Account pictures appear in the menu, the users list and user pages. The server serves them only to a web
session, so the app signs in to the web interface privately for them (for accounts with two-factor sign-in it uses
the remote desktop's web session when there is one) and keeps every picture in its cache folder on the phone.

## Staying connected

- The app reconnects by itself when the connection to the server drops (network change, server restart, proxy
  time-out), first with a short-lived login cookie, so accounts with two-factor sign-in do not need a new code;
  it asks to sign in again only when the server refuses. A "Reconnecting" note shows meanwhile.
- A remote desktop session that drops is restarted automatically (up to six attempts).
- Keep-alive messages every 25 s on the server connection and on every remote session, because proxies such as
  Cloudflare close connections that carry no data for about 100 s (an idle terminal, a still remote screen).
- *Settings > Stay connected in the background* (on by default) keeps the app running with a quiet notification
  while you use other apps.

## Requirements

Android 8.0 (API 26) or later. A MeshCentral server reachable over **https**. Servers with a certificate
from a private certificate authority work when that CA certificate is installed on the phone
(*Settings > Security > Encryption & credentials > Install a certificate > CA certificate*).

## Security

- *Settings > Lock the app*: asks for the phone's fingerprint, face unlock or screen lock (PIN, pattern, password)
  when the app opens and when it comes back after being away (at once, after 1 or 5 minutes). Switching it on or off
  needs an unlock too. The lock covers the app; open remote sessions keep running behind it. With the lock on,
  Android 13 and later show no preview of the app in the recent-apps screen (older versions: no preview and no
  screenshots while the lock is on). The lock is its own window above any open dialog, and keyboard input cannot
  reach a remote session behind it. Notifications show no content on the phone's lock screen while it is on.
- HTTPS only; plain-text traffic is disabled for the whole app. Redirects are followed only within the same
  server, so the sign-in header and cookies never go to another host. Certificates installed by the user (needed for
  servers with a private certificate authority) are trusted too: only install certificates you trust.
- The password is kept only in the Android Keystore-encrypted store when "Remember password" is on.
  App data is excluded from cloud backup and device transfer.
- The remote desktop's web view only loads pages from the configured server; the sign-in script fills the
  password only into that server's own page. Signing out clears the web view's cookies and storage.
- The terminal page is a local page (served by `WebViewAssetLoader`, no file access) that talks to the app
  through a message port only that page can use.

## Known limitations

- Notifications arrive while the app is running; with *Stay connected in the background* switched off, Android
  may stop the app in the background.
- Accounts with two-factor authentication type the code once more in the remote desktop page (the
  desktop viewer needs its own web sign-in).
- Chat files are kept in memory while they move (100 MB at most, like the server's chat page).
- Not yet: importing users, deleting your own account, a QR code for the authenticator setup
  (the secret and an "Open in authenticator app" button are shown instead).

## Build

Needs JDK 21 and the Android SDK (platform 37).

```bash
cd android
scripts/fetch-assets.sh          # xterm.js, pinned by version and SHA-256 (same pins as the Windows build)
./gradlew assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
./gradlew assembleRelease        # needs a signing key, see below
```

Release signing reads `android/keystore.properties` (`storeFile`, `storePassword`, `keyAlias`,
`keyPassword`) or the environment variables `MCD_KEYSTORE`, `MCD_KEYSTORE_PASSWORD`, `MCD_KEY_ALIAS` and
`MCD_KEY_PASSWORD`. Never commit a keystore.

Toolchain: Android Gradle Plugin 9.4, Gradle 9.8 (wrapper checked by SHA-256), Kotlin Compose compiler
2.4, Compose BOM 2026.09, OkHttp 5.5; compileSdk 37, targetSdk 36, minSdk 26.
