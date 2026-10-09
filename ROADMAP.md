# Roadmap

This page lists the features planned for MeshCentral Desktop. It is a plan, not a promise: items
may change order, and there are no fixed dates. Each item links to the MeshCentral web interface
feature it mirrors where there is one, and respects the account's permissions like the rest of the
app (see [docs/PERMISSIONS.md](docs/PERMISSIONS.md)).

Suggestions and contributions are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md).

**Status:** Planned (agreed, not started) · In progress · Done (released, see the
[changelog](CHANGELOG.md))

## 1. Remote desktop toolbar

The goal is to offer every action of the MeshCentral web viewer's toolbar in the native toolbar.

| Feature | Status | Notes |
|---|---|---|
| **Share the device with a guest** | Done (3.0.0) | Create, list and revoke guest sharing links (desktop, terminal, files, view only; expiry). Uses the server's device sharing (`createDeviceShareLink`, `deviceShares`, `removeDeviceShare`). Needs the guest sharing right and a server that allows guest sharing. |
| **Refresh the desktop** | Done (3.0.0) | Ask the agent for a full screen update, useful after display glitches. Built into the embedded viewer (`SendRefresh`). |
| **Record the remote desktop session to a file** | Done (3.0.0) | Record the session locally with the viewer's recorder and save it as a MeshCentral recording (`.mcrec`), playable in the MeshCentral player. Hidden when the server disables local desktop recording. |
| **Save a screenshot of the remote desktop** | Done (3.0.0) | Save the current remote screen as a PNG (`Desktop-<device>-<date>.png`), like the web viewer. |
| **Toggle the remote desktop wallpaper** | Done (3.0.0) | Hide or restore the wallpaper of the remote computer for a faster, cleaner session (`deskBackground` agent message). |
| **Open a web address on the remote computer** | Done (3.0.0) | Open a URL in the default browser of the remote user (`openUrl` agent message), from the toolbar and the device menu. |
| **Display a notification on the remote computer** | Done (3.0.0) | Message box and toast notification are already available in the device actions; they will also be reachable from the remote desktop toolbar, also in fullscreen. Needs the chat and notify right. |
| **Open a chat window on the remote computer** | Done (3.0.0) | Open MeshCentral's chat (messenger) on the remote computer and a matching chat window in the app. Needs the chat and notify right. |

## 2. More platforms

MeshCentral Desktop runs on Linux (tested on Debian and Debian based distributions), on Windows 10 / 11
as a preview since 2.26.0 (see [docs/WINDOWS.md](docs/WINDOWS.md)) and on Android 8 or later as a preview
since 3.0.5 (see [docs/ANDROID.md](docs/ANDROID.md)). macOS is next.

| Feature | Status | Notes |
|---|---|---|
| **Test with Windows and macOS remote computers** | Partly done | Windows agents: Registry, terminal (cmd and PowerShell, admin and user), files and the remote desktop are tested (Windows Server 2025 in CI, Windows 11). Still to do: processes, services and the other tools on Windows, and everything on macOS agents (for example the screen recording permission). |
| **Windows app** | Preview (2.26.0) | Same GTK code base; Edge WebView2 replaces WebKitGTK, xterm.js replaces VTE, Windows Credential Manager replaces the keyring. Setup `.exe`, `.msi` and portable `.exe`, built and tested on Windows in CI. Windows 11 look since 2.28.0. Still to do: code signing (Azure Artifact Signing), testing the remaining features on Windows. |
| **Android app** | Preview (3.0.5) | Native Kotlin / Jetpack Compose app with the same pages as the desktop app, a touch remote desktop (touchpad cursor, pinch zoom, full keyboard), automatic reconnect, background connection and app lock. Signed APK on every release, built and signed in CI. Still to do: Google Play, certificate pinning, importing users and deleting your own account. |
| **macOS app** | Planned (next) | A macOS client for Apple silicon and Intel Macs, signed and notarised, distributed as a `.dmg`, with the same features as the Linux and Windows versions. |
| **Test the client on more Linux distributions** | Planned | Fedora, Arch and openSUSE with the same libraries, then document the required packages. |

## 3. User interface

| Feature | Status | Notes |
|---|---|---|
| **Modern look** | Planned | Refresh the layout, spacing and icons; consider GTK 4 with libadwaita on Linux. |
| **Settings page** | Planned | One place for the options now spread across menus and toolbars (theme, clipboard sync, hotkeys, date format, notifications). |
| **Translations** | Planned | Make every text translatable and follow the language set in My Account. |
| **Accessibility** | Planned | Keyboard navigation for every page, screen reader labels, high contrast support. |
| **Multiple servers** | Planned | Save several servers and switch between them without signing out. |

## 4. Security

| Feature | Status | Notes |
|---|---|---|
| **Signed releases** | Partly done | 2.25.1: Sigstore build provenance for the `.deb` and source archives (`gh attestation verify`), actions pinned to commit SHAs, least-privilege CI. Still planned: a signed `SHA256SUMS`. |
| **APT repository** | Planned | A signed APT repository, so Debian based systems receive updates with `apt upgrade`. |
| **Certificate pinning and custom CA** | Planned | Optionally pin the server certificate, or trust a private certificate authority, for servers that do not use a public certificate. |
| **Hardened embedded web profile** | Done (2.25.1) | Web views stay on the server's https origin, no pop-ups, downloads or page clipboard access; cookies cleared on sign-out; password auto-fill checks the origin. |
| **Automated code scanning** | Done | CodeQL runs on every push; Dependabot keeps the SHA-pinned GitHub Actions up to date. |
| **Clipboard patch consent** | Planned | Ask once before sending the in-memory clipboard patch to a Linux agent, instead of only allowing it to be switched off (see [docs/REMOTE_DESKTOP.md](docs/REMOTE_DESKTOP.md)). |

## Done

Everything already released is listed in the [changelog](CHANGELOG.md).
