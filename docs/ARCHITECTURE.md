# Architecture

MeshCentral Desktop is a single-process GTK 3 application written in Python. It talks to a
MeshCentral server over the same WebSocket control channel as the web UI and `meshctrl`, opens
relay tunnels for terminal / file sessions, and embeds MeshCentral's own web desktop viewer in
WebKitGTK for remote desktop.

## Source layout

```
pkg/                                   Debian package root (built with dpkg-deb)
  DEBIAN/control, postinst, postrm     package metadata; postinst/postrm refresh desktop + icon caches
  usr/bin/meshcentral-desktop          launcher (sets WEBKIT_DISABLE_DMABUF_RENDERER=1, runs main.py)
  usr/share/applications/…desktop      desktop entry
  usr/share/icons/hicolor/…            app icon (PNG sizes + SVG)
  usr/share/meshcentral-desktop/
    main.py                            entry point; sets the program name so the dash shows the icon
    mcdesktop/                         the application package (below)
```

| Module | Responsibility |
|---|---|
| `__init__.py` | `__version__` (single source of the version shown in the UI) |
| `app.py` | `Gtk.Application`: config file, login → main window, shared WebKit context, desktop notifications |
| `login.py` | Sign-in window (server, user, password, 2FA code); password in the system keyring (libsecret) |
| `client.py` | Protocol layer: `ControlConnection` (control.ashx), `Tunnel` (meshrelay.ashx), `WebSession` (HTTP transfers for My Files) |
| `rights.py` | Computes the signed-in account's rights → `NodeCaps` per device, `has_site()` for server rights |
| `mainwindow.py` | Window shell: navigation rail + page stack, device tree, grouped device pages (rights-gated, lazily built), fullscreen, window shortcuts, notification cards, node-update fan-out |
| `general_actions.py` | Device action bar, power / more menus, context menu, *Run command* dialog, Notes dialog |
| `desktop_panel.py` | Remote desktop: embedded viewer, native toolbar, connection state machine, keyboard, clipboard sync |
| `terminal_panel.py` | VTE terminal over relay protocols 1 / 6 / 8 / 9 (shell choices like the web UI: `shell_options`) |
| `files_panel.py` | Device file manager over relay protocol 5 |
| `tools_panel.py` | Processes, Services, Agent Console |
| `software_panel.py` | Software (installed applications, Store apps, uninstall) |
| `registry_panel.py` | Registry (Windows devices only, relay protocol 4): browse, GoTo, new key / value, edit, rename, delete, export `.reg` |
| `webview.py` | the embedded web view API used by the remote desktop and the server-page windows: WebKitGTK on Linux, Edge WebView2 on Windows (same-origin rule, no pop-ups / downloads / page clipboard, non-blocking dialogs, session cookies) |
| `osdep.py` | operating-system services: saved passwords (Secret Service or Windows Credential Manager); on Windows also notifications, single instance (named mutex) and the app identity |
| `winweb.py` | Windows: `WebView2Widget`, Edge WebView2 in a native child window of a GTK widget (WebView2.tlb through comtypes) |
| `winterm.py` | Windows: the terminal widget, xterm.js inside WebView2 with the part of the VTE API the terminal panel uses |
| `winkeys.py` | Windows: "Send hotkeys" low-level keyboard hook |
| `servericons.py` | the signed-in server's own icons: its `/images/` sprite sheets (device types, menu, status) cut like the web UI's CSS, registered as GTK icons, cached per server, refreshed at each sign-in |
| `winstyle.py` | Windows: the Windows 11 look (style sheet from the system light / dark mode and accent colour, followed live; caption buttons; DWM title bars of dialogs) |
| `updater.py` | update check (GitHub releases, stable / preview channel), verified download (SHA256SUMS), install per installation type (pkexec apt, Inno Setup, msiexec, portable) |
| `update_ui.py` | "New version available" card and the Updates dialog |
| `selftest.py` | `--selftest`: checks a bundled or installed copy (used by the Windows build) |
| `device_general.py` | General page (web UI p10): attributes with edit dialogs (hostname, description, consent, notifications, tags), Actions / Notes / Log Event / Run / Message / Chat (`ChatWindow`, WebKit) / Share (`ShareDialog`); `PowerTimeline` (7 day power state), links (Interfaces, MeshCmd, Web-VNC / Web-RDP / Web-SSH windows with the web session cookies), Change Group, Delete Device, User Authorizations |
| `info_panel.py` | Hardware, Network, Events, Notes |
| `admin_panel.py` | Users (online / offline tree with checkboxes, Select All, Group Action, filter, live session counts from `wssessioncount`; `NewAccountDialog`, export CSV/JSON, `UserImportDialog` batch import; double-click opens `user_panel.UserPage`), User Groups (+ details, broadcast), Server Events, `BroadcastDialog` |
| `account_panel.py` | My Account: 2FA (authenticator + QR, backup codes, security keys), previous logins, notification / localization settings, password, login tokens, delete account, device groups, account image |
| `server_panel.py` | *Server*: server actions, live statistics (cairo gauges), history charts, server console |
| `server_files_panel.py` | *Files*: server-side storage (*My Files* in the web interface) |
| `device_list.py` | Devices list: status filter, search syntax, sorts, stars (`buckets`, `search_matches`, `passes_status`), `GroupActions` (+ `GroupRunDialog`), `AddAgentDialog`, `InviteDialog`, Add Device Group, MeshCmd |
| `group_panel.py` | Groups: `UserGroupsPanel` (list, Select All, Group Action, New / Duplicate Group) and `GroupPage` (group page) |
| `user_panel.py` | Users → one user's page (`UserPage`: General + Events, edit dialogs, `RightsDialog` for device-group / device permissions, `show_previous_logins` and `choose_account_image` shared with My Account) |
| `ui.py` | Small shared helpers (online/OS detection, formatting, dialogs, JSON tree view) |

## Runtime flow

1. `main.py` → `App.run()`. `App` loads `~/.config/meshcentral-desktop/config.json` and shows the
   `LoginWindow`.
2. `LoginWindow` creates a `ControlConnection` (header `x-meshauth`) and waits for the server's
   `userinfo`; on success `App.on_login()` opens the `MainWindow`.
3. `MainWindow` requests `meshes` and `nodes`, builds the tree and listens for `event` messages
   (node changes are debounced into a refresh) and `msg`/`notify` (broadcast cards).
   The window is a **navigation rail** (`NAV`) next to a `Gtk.Stack` of pages. "devices" is the tree +
   device area; every other page (Files, Server, Users, Groups, Events, Account) is constructed
   on its first visit (`show_page`). Rail entries the account cannot use are not created.
4. Selecting a device creates **empty** page containers in three group notebooks (`DEVICE_GROUPS`:
   Overview / Remote / Tools, switched by a `Gtk.StackSwitcher`). A panel is constructed only when its
   page is actually on screen (`_ensure_tab`): adding pages to a hidden group's notebook must not
   build (and auto-connect) e.g. the Desktop. Pages the account may not use get an explanatory label.
5. Every refresh of the node list is forwarded to the open device's panels via `on_node_update()`,
   so they can react to the agent going offline / coming back.

## Panel contract

Every embedded panel is a `Gtk.Box` subclass with:

- `__init__(app, node)`: builds widgets only; **no network traffic**.
- `on_shown()`: first time the tab is displayed; starts requests (guarded by `_started`). The remote
  panels (Desktop, Terminal, Files) never connect here: they wait for the user's **Connect**.
- `teardown()`: stops tunnels, removes `ctrl.on(...)` listeners, timers.
- `on_node_update(node)` *(optional)*, the device's data changed (e.g. online state).

Server panels follow the same contract with `node=None`.

## Threading model

- `ControlConnection` and each `Tunnel` run their WebSocket on a daemon thread.
- Every callback into application code is marshalled onto the GTK main loop with
  `GLib.idle_add` (`client._ui`), so UI code never runs on a network thread.
- `WebSession` transfers (Files upload / download) run on their own threads and report progress
  through the same mechanism.
- Sending is thread-safe; the main loop is never blocked by network I/O.

## Messaging patterns

- `ctrl.send(obj, callback)` assigns a `responseid` and calls `callback` with the matching reply.
- Many replies are broadcast-style and do **not** echo the `responseid` (users, usergroups, events,
  getNotes, getnetworkinfo, files, notify). Panels subscribe with `ctrl.on(action, cb)` and must
  `ctrl.off(action, cb)` in `teardown()`.
- Agent messages are wrapped as `{action:'msg', type:<agent command>, nodeid}` and answered with the
  same envelope carrying the `nodeid`.

See [PROTOCOL.md](PROTOCOL.md) for the message shapes.

## Remote desktop

The app does not implement MeshCentral's KVM protocol. `DesktopPanel` loads MeshCentral's web UI in
a private WebKit profile, signs in, opens the device's desktop view and drives the viewer through
JavaScript, while a native overlay hides everything except the remote screen. See
[REMOTE_DESKTOP.md](REMOTE_DESKTOP.md).

## Persistent state

| Location | Content |
|---|---|
| `~/.config/meshcentral-desktop/config.json` | server, username, remember flag, dark theme, `clipboard_sync`, `desktop_hotkeys`, `desktop_display` (per device), `devices_view` (filter, sort, OS name), `stars`, `devices_expanded` (open device-list sections; all start collapsed) |
| System keyring (libsecret) | password, only when *Remember password* is ticked |
| `~/.local/share/meshcentral-desktop/webkit*` | private WebKit profile of the embedded viewer (cookies, cache) |
| `~/.local/share/meshcentral-desktop/serverstats-<host>.json` | CPU of the server's live 5-minute stats samples recorded since sign-in (30 days): the server's NeDB/MongoDB history does not contain CPU |

Application id: `uk.co.cyvelion.MeshCentralDesktop` (single instance).
