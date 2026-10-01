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
| **Share the device with a guest** | Planned | Create, list and revoke guest sharing links (desktop, terminal, files, view only; expiry). Uses the server's device sharing (`createDeviceShareLink`, `deviceShares`, `removeDeviceShare`). Needs the guest sharing right and a server that allows guest sharing. |
| **Refresh the desktop** | Planned | Ask the agent for a full screen update, useful after display glitches. Built into the embedded viewer (`SendRefresh`). |
| **Record the remote desktop session to a file** | Planned | Record the session locally with the viewer's recorder and save it as a MeshCentral recording (`.mcrec`), playable in the MeshCentral player. Hidden when the server disables local desktop recording. |
| **Save a screenshot of the remote desktop** | Planned | Save the current remote screen as a PNG (`Desktop-<device>-<date>.png`), like the web viewer. |
| **Toggle the remote desktop wallpaper** | Planned | Hide or restore the wallpaper of the remote computer for a faster, cleaner session (`deskBackground` agent message). |
| **Open a web address on the remote computer** | Planned | Open a URL in the default browser of the remote user (`openUrl` agent message), from the toolbar and the device menu. |
| **Display a notification on the remote computer** | Planned | Message box and toast notification are already available in the device actions; they will also be reachable from the remote desktop toolbar, also in fullscreen. Needs the chat and notify right. |
| **Open a chat window on the remote computer** | Planned | Open MeshCentral's chat (messenger) on the remote computer and a matching chat window in the app. Needs the chat and notify right. |

## 2. More platforms

MeshCentral Desktop runs on Linux today and is tested on Debian and Debian based distributions.

| Feature | Status | Notes |
|---|---|---|
| **Test with Windows and macOS remote computers** | Planned | Verify remote desktop, terminal (PowerShell), files, processes, services and the other tools against Windows and macOS agents, and document the differences (for example Windows services, macOS screen recording permission). |
| **Windows app** | Planned | A native Windows client with an installer. The current app is built on GTK 3, WebKitGTK and VTE, and WebKitGTK and VTE are not available on Windows, so this needs a decision on the toolkit first (for example a cross-platform toolkit with an embedded web engine for the MeshCentral viewer). The protocol layer (`client.py`) and the permission rules (`rights.py`) can be shared. |
| **macOS app** | Planned | A native macOS client, signed and notarised, distributed as a `.dmg`. Same toolkit decision as the Windows app. |
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
