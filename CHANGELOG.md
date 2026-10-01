# Changelog

All notable changes to MeshCentral Desktop. Versions follow `MAJOR.MINOR.PATCH`.

2.23.0 is the first version published on GitHub. Versions 1.0.0 and 2.8.0 to 2.22.1 were built
before that and are available as archived builds on the
[releases page](https://github.com/d-maggipinto/meshcentral-desktop/releases); their dates are the
original build dates. Versions 2.0.0 to 2.7.x were never packaged and are listed for reference.

## [2.25.0] - 2026-10-01
### Added
- Device **General** page like the web UI's: OS name, hostname, description, Linux / Windows security,
  Windows Defender, pending reboot, antivirus, active users, idle time, user consent, notifications,
  connectivity and tags. Hostname, description, user consent, notifications and tags are edited in place
  (pencil button). Buttons **Actions** (wake, run commands, sleep, reset, power off, uninstall agent),
  **Notes**, **Log Event**, **Run**, **Message** (with display time), **Chat** (the server's chat window)
  and **Share** (guest link for desktop, terminal or files: starting now, time range or recurring), shown
  only with the rights the web UI asks for.
- **Software** page (Tools → Software, like the web UI of MeshCentral 1.2): the device's installed
  applications with version, publisher, install date and location, search, Microsoft Store apps on
  Windows and uninstall (full device rights, Windows agents). Loads when opened; a Linux agent can
  take about half a minute for a few thousand packages.
- General page, lower half like the web UI: **7 Day Power State** chart (green bars, hover for details), links
  **Interfaces**, **MeshCmd** (action file routed to this device), **Web-VNC**, **Web-RDP** (and Web-SSH
  when the server enables it) opened in an app window, **Change Group**, **Delete Device** (red button), and **User
  Authorizations** with **Add User** / **Add User Group**, edit and remove. Adding an unknown user name
  now says so (the server silently ignores it).
- Remote desktop: after an encoding change the status shows the format the agent really sends
  ("Encoding: WEBP", or "Requested WEBP, the agent sends JPEG").
### Changed
- Device page: **Overview | Remote | Tools** and **Run command | Power** share one line.
- Remote desktop encoding defaults to **WebP** (like the web UI) instead of JPEG.
- Opening the **Remote** group no longer connects anything. Desktop, Terminal and Files each wait
  for their **Connect** button (Files has a new Connect / Disconnect button), so no session is
  started on a device until you ask for one.
### Fixed
- Terminal **User Shell** did not work (only the admin / root shell did): the app asked the agent for
  protocol 7, which is its plugin channel, instead of 8 (user PowerShell: 9 instead of 8). The shell
  choices now match the web UI: Root Shell, User Shell and Login Shell on Linux / macOS, Admin Shell,
  Admin PowerShell, User Shell and User PowerShell on Windows; a server that forces a Linux shell type
  (`linuxShell`) is respected.
- Remote desktop: with Scale on *Auto*, encoding, quality and speed changes made before the remote
  screen size was known were not sent to the agent.

## [2.24.1] - 2026-10-01
### Fixed
- Devices list: **Add Agent** and **Invite** were only reachable by right-clicking a device group
  header. Each agent group header now shows a **+** button (left-click) that opens them, like the
  web UI's links next to the group name.

## [2.24.0] - 2026-09-30
### Added
- **Devices list like the web UI's "My Devices"**:
  - status filter (All, Online, Offline, Sessions, Starred, Intel® AMT, Help, Tagged, Untagged),
    sort (Group, Power, Device, Tags, Group-Tags, Last Seen, Last Boot Up Time) and *Show OS name*,
    remembered between sessions;
  - the filter box understands the web UI's search syntax (`user:`, `ip:`, `group:`, `tag:`, `os:`,
    `desc:`, `connectivity:` and more, `!` to negate, `and` / `or`);
  - stars (right-click a device, kept in the app's settings), expand / collapse all, empty device
    groups are listed, section headers show the device counts;
  - checkboxes, **Select All / None** and **Group Action**: export device information (CSV / JSON,
    with or without device details), move to device group, device notification (toast, message box,
    alert box), edit tags (add / set / remove), run commands with the **output of every device**,
    upload files, wake-up, sleep, reset, power off, uninstall agent, delete devices. Devices without
    the needed right are skipped and counted;
  - right-click a device group for **Add Agent** (Windows, Linux / BSD, binary installer, macOS,
    mobile, MeshCentral Assistant and the uninstall variants, with downloads through the app and
    copyable install commands) and **Invite** (invitation link, or email when the server can send
    it); the list menu offers **Add Device Group** and **MeshCmd**.
### Changed
- Navigation rail: *My Files* is now **Files** and *My Server* is now **Server** (window title and
  page headings too); **Account** moved to the bottom of the rail, apart from the other sections.
- The test scripts are no longer part of the repository. CI now checks the Python syntax and
  builds the package.

## [2.23.0] - 2026-09-30
First release published on GitHub. Earlier versions are available as archived builds.
### Added
- Licensed under the **Apache License 2.0** (`LICENSE`, `NOTICE`, SPDX headers in every source
  file, Debian `copyright` file in the package). `NOTICE` credits the MeshCentral project and lists
  the parts that follow its source code.
- About dialog: author, CYVELION LTD, license, project page, credits (MeshCentral, Claude Code) and a
  note that this is an unofficial client, not affiliated with or endorsed by the MeshCentral project.
- `scripts/build-deb.sh`: one command to build the package (version check, permissions, no Python
  bytecode) into `dist/`.
- Offline unit tests (`tests/unit/`) and a GitHub Actions workflow that runs them and builds the
  package on every push; tagged releases get the `.deb` attached.
- The rig tests (`tests/rig/`) are published: no personal paths, a shared `rigenv.py`, and a README
  with setup instructions and an index.
- Documentation: new README with screenshots, `CONTRIBUTING.md`, `SECURITY.md`, issue and pull
  request templates.
### Changed
- New application id `uk.co.cyvelion.MeshCentralDesktop`. **A password saved by an earlier version
  is not found anymore: type it once more at sign-in** (it is then saved again).
- Package metadata: maintainer CYVELION LTD, homepage on GitHub, description states the unofficial
  status.
- Interface texts reworded (no long dashes), window titles use the web interface style
  `Name - Detail`.
### Fixed
- Closing a device while a file transfer was running left the file open and a partial download on
  disk; the transfer is now closed and the partial file removed.
- Removed code fragments and debug scripts left in the test folder.

## [2.22.1] - 2026-09-30
### Fixed
- Groups → **Add Users**: suggestions now appear directly under the field while typing (like the web
  UI's suggestion box: name and user id, up to 8, click or ↓ + Enter to pick; works on the last name
  of a comma separated list). The previous completion popup did not open inside the dialog.

## [2.22.0] - 2026-09-30
### Added
- **Groups like the web UI's "My User Groups"**: list with **Users / Device Groups / Devices**
  counts, checkboxes, **Select All / Select None**, **Group Action…** (delete groups), **New Group…**
  (name, description; domain on cross-domain servers) and **Duplicate Group…** (copies members and
  device group permissions, the server does not copy per-device permissions).
- **User group page** (double-click a group), like "User Group - <name>": domain, identifier, group
  type (identity-provider groups), description, features (session recording servers), user consent,
  counts; **rename / edit description**, **user consent**, **Broadcast**, **Group Members** (add users
  with name completion, remove, click a member to open the user's page), **Common Device Groups** and
  **Common Devices** (add / edit permissions / remove), **Delete User Group**. Editing needs the
  "manage user groups" server right, like the web UI.
### Changed
- The user page and the group page share the same permission dialogs and membership lists.

## [2.21.0] - 2026-09-30
### Added
- **Users list like the web UI's "My Users"**: *Online Users* / *Offline Users* sections, checkboxes
  with **Select All / Select None** (never yourself) and **Group Action…** (lock account, unlock
  account, validate / invalidate email when the server verifies emails, delete accounts), columns
  **Device Groups**, **Last Access** (live "2 sessions" for connected users, where web and app
  sessions both count; otherwise the date of the last access) and **Permissions** (Administrator, Manager,
  User + Files, Partial, User, "Locked", "*" for restrictions; the detailed rights are in the row
  tooltip), and a **Filter** box (`name:` / `email:` prefixes like the web UI).
- User page: "N active sessions" under the account picture.

## [2.20.1] - 2026-09-30
### Added
- User page: click the account picture to **Manage Account Image** like the web UI: preview,
  *Choose file…* (centre square scaled to 256×256), *Delete*, OK / Cancel.

## [2.20.0] - 2026-09-30
### Added
- **Users → user page** (double-click a user), like the web UI's "General - <user>" / "Events":
  domain, identifier, email, real name, phone (if SMS is enabled), features, server rights, quota,
  creation, last login, password date, device groups, admin realms, user consent, 2nd factors and the
  account image. Edit dialogs for email (disabled on email-as-username servers, where the server
  ignores it), real name, phone, **features** (remove remote control / desktop / terminal / files …),
  **server permissions** (full admin, backup, restore, updates, server files + quota, manage users /
  user groups / recordings, all events, lock account, no new groups / devices, no tools, lock
  settings), admin realms and **user consent**. **Common device groups**, **user group memberships**
  and **common devices** with add / edit permissions / remove. **Notes**, **Change password** (force
  reset, remove 2FA, hint), **Previous logins**, **Delete user**, and an **Events** tab (log filter
  and limit). Edit rights follow the web UI (e.g. only full administrators change another full
  administrator); the page follows changes made elsewhere.
### Fixed
- Device groups created or deleted while the app is open (e.g. in the web UI) now appear / disappear
  without restarting the app.
- Event tables no longer overwrite each other: the device *Events* tab, *Server Events* and the user
  page each keep only their own replies.

## [2.19.1] - 2026-09-30
### Fixed
- Users: accounts without server rights (e.g. just created with New Account…) showed an empty
  Rights cell; they now show **User** like the web UI (such accounts have no `siteadmin` field).

## [2.19.0] - 2026-09-30
### Added
- **Users → New Account…** like the web UI's "Create Account": username (or only the email on
  servers that use the email address as the user name), email, password twice, *Randomize the
  password*, *Remove all previous events for this userid*, *Force password reset on next login*, and
  on servers with email verification *Email is verified* / *Send invitation email*; a domain picker
  on cross-domain servers. Invalid fields turn red and OK stays disabled; server errors (user already
  exists, password requirements, account limit) are shown in the dialog. Hidden on single-user and
  SSPI servers, like the web UI.
### Fixed
- **Users → Import** on servers that use the email address as the user name: the result count now
  follows the server's renaming (email → user name) instead of reporting "Created 0 of N", and a row
  without an email whose user name is not an email address is flagged (the server would reject the
  whole batch with "Invalid email"). Import is hidden on LDAP / SSPI servers like in the web UI.

## [2.18.0] - 2026-09-30
### Added
- **Users → Export**: download the user list as `userlist.csv` (same columns as the web UI) or
  `userlist.json` (the user objects as the server sends them, no password hashes or 2FA secrets).
- **Users → Import…** ("batch create many user accounts", like the web UI): choose a JSON or CSV
  file, every row is previewed and checked (user name, password length, email, duplicates, names
  that already exist are skipped), then the accounts are created and the result is reported
  ("Created N of M"). "resetNextLogin" makes the user change the password at the first sign-in.
### Notes
- The CSV export reports full administrators as *not* locked (the web UI marks every full
  administrator as locked because it tests the lock bit on the all-rights value).
- The web UI's example email `x1@x` is rejected by the server (no top-level domain); the app flags
  such rows before sending instead of failing the whole batch.

## [2.17.0] - 2026-09-29
### Added
- **My Account** rebuilt like the web UI. *Account security*: manage the authenticator app (set up
  with a QR code or the secret, verify a code, remove), backup codes (create / show), security keys
  (list and remove). *Account actions*: view previous logins, notification settings (device
  connections / disconnections, sound, group name, desktop notifications), localization (language and
  date format), change password, login tokens (create with expiry, copy username/password, remove),
  delete account. *Device groups* with **New**, and the **account image** (change / remove).
- Device connection / disconnection notification cards (off by default; see Notification settings).
### Fixed
- Accounts whose settings are locked by the administrator see the security and action entries
  greyed out with an explanation instead of failing.

## [2.16.0] - 2026-09-29
### Added
- **My Server → Trace** (full administrators), like the web UI: choose server trace sources (Core
  Server, Web Server, Intel® AMT, same 18 sources), live trace log with time / source / message,
  Show last 100 - 1000, Clear, Download (.csv), double-click for the full event. The status shows the
  server-wide active sources and follows changes made by other administrators.
### Fixed
- CPU chart still differed from the web UI. Each client can only show the CPU samples it received
  live (the server does not keep them in NeDB/MongoDB history), and 2.15.1 charted its own 10-second
  readings instead of the server's 5-minute samples. The app now records the server's 5-minute live
  samples from sign-in (whether or not My Server is open), keeps them on disk per server for 30 days
  and charts exactly those, the same points as the web UI, plus everything recorded while the app
  was running before.

## [2.15.1] - 2026-09-29
### Fixed
- The CPU chart was empty while the web UI showed a line. Root cause: MeshCentral's MongoDB and NeDB
  (default) database backends leave CPU out of the stats history, so CPU only exists in live samples.
  The app now also collects the server's live CPU load every 10 s while My Server is open and merges
  it into the chart (the web UI only shows the 5-minute live samples), and says why older CPU data
  is missing. The chart window now extends to the newest sample if the server clock is ahead, and
  CPU values are accepted as a list or an object, like the web UI.
- The sample counter shows how many samples carry data for the selected chart.

## [2.15.0] - 2026-09-29
### Added
- **My Server → Stats** now matches the web UI: Connections (incl. Intel AMT / AMT CIRA), Memory, CPU,
  **Inbound traffic** and **Outbound traffic** (stacked, per traffic type), ranges Last 3 hours /
  8 hours / day / week / 30 days, **Log scale**, **Download data points (.csv)**.
- New chart: fixed time window, smooth filled lines with sample points, gaps where the server was
  restarted, legend and axis title, hover crosshair with the exact values; new samples appear live.

## [2.14.2] - 2026-09-29
### Fixed
- Tables were hard to read: short columns (time, user, action, PID, state…) collapsed to "2026-…".
  They now size to their content; only the long text column (message, command, service) is shortened,
  and hovering a row shows its full text. Applies to Server Events, device Events, Users, User Groups,
  Processes and Services.

## [2.14.1] - 2026-09-29
### Added
- My Server shows **Server warnings** (sent by the server at sign-in), with an explanation for the
  common "Failed to sign agent … AggregateError" warning.
### Fixed
- *Check server version* did nothing on some servers: the app now accepts the server's version reply
  whether or not it echoes the request id, shows progress while the server queries the npm registry,
  and reports an error after 30 s instead of staying silent.

## [2.14.0] - 2026-09-29
### Added
- **My Server** page (like the web UI's "My Server"): server actions (download a server backup,
  restore from a backup, check the version and update, error log with clear, configuration viewer),
  live CPU and memory gauges, server state counters refreshed every 10 s, **Stats** history charts
  (connections, memory, CPU load over 1 hour to 30 days) and the **server console**.
### Changed
- **New layout**: a navigation rail on the left (Devices, My Files, My Server, Users, Groups, Events,
  Account) replaces the "Server administration" button; sections the account cannot use are hidden.
- Device pages are grouped into **Overview** (General, Hardware, Network, Events, Notes),
  **Remote** (Desktop, Terminal, Files) and **Tools** (Processes, Services, Console).
- Only the page on screen is built, opening a device no longer prepares hidden pages.

## [2.13.0] - 2026-09-29
### Added
- **Broadcast messages**: send to a user group (User Groups → Broadcast) or to all users
  (Users → Broadcast to all users), with the same durations as the web UI (until dismissed,
  10 s, 1 min, 5 min) and the server's 512-character limit.
- Incoming broadcasts and server notices are shown as notification cards (top-right, also above
  the fullscreen desktop) plus a desktop notification when the window is not focused.
- User Groups details pane: description, members, common device groups and their rights.

## [2.12.0] - 2026-09-29
### Added
- **My Files** (server-side file storage) under Server administration: browse the personal and
  device-group folders, upload, download, new folder, rename, delete, cut / copy / paste, edit
  small text files, quota display.
- **Permission awareness** across the app (`rights.py`): device tabs, actions, menus, the desktop
  toolbar and server tabs follow the signed-in account's MeshCentral rights; denied features are
  greyed out with an explanation; view-only desktop mode; read-only notes.
### Fixed
- "Open in web UI" used the full node id instead of the short id.

## [2.11.1] - 2026-09-29
### Fixed
- *Run command* never showed output (it stopped at the server's acknowledgement).
- An agent restart or `agentupdate` looked like a frozen app: panels are now told when the agent
  goes offline / comes back, the Agent Console reports it and refuses to send meanwhile, and the
  remote desktop reconnects automatically.

## [2.11.0] - 2026-09-29
### Added
- **Send hotkeys**: while the remote screen has focus, system shortcuts go to the remote
  (keyboard grab; on Wayland via the shortcuts-inhibit protocol).
- Fullscreen toggle moved to **Ctrl+Alt+F**; Esc now reaches the remote. On-screen hint.
### Changed
- Services on Linux are listed via `systemctl` (≈5× faster, real states and enabled/disabled).
### Fixed
- AltGr characters (e.g. `@ # [ ] { } €`) were garbled on non-US keyboard layouts.
- General tab showed "Agent version 0"; it now shows the agent type and core version.

## [2.10.0] - 2026-09-29
### Added
- **Automatic two-way clipboard sync** while connected (switch in the desktop toolbar), including a
  small in-memory agent patch that fixes MeshCentral's Linux clipboard handling.

## [2.9.3] - 2026-09-29
### Fixed
- Copying from a Linux remote failed with `Can't open display:` (the agent could not find the
  user's X display); the app now locates it itself.

## [2.9.2] - 2026-09-29
### Added
- Remote → local clipboard fallback that reports the agent's actual error.

## [2.9.1] - 2026-09-29
### Fixed
- Reconnect could hang on "Opening…" and Disconnect did nothing. Connection state machine rewritten
  (Connect / Cancel / Disconnect, 45 s watchdog with Retry).

## [2.9.0] - 2026-09-29
### Added
- Native "Connecting…" cover: the web login page and the viewer's own connection steps are never
  shown, only the remote screen once the first frame is drawn. Faster connect (no fixed delays).
- Auto scaling, "Fastest" frame rate, multi-monitor display picker, "Type clipboard" button.

## [2.8.1] - 2026-09-29
### Fixed
- Fullscreen did not fill the screen (black strip, offset canvas, focus rectangle visible).
### Changed
- Clipboard now uses the app's own control connection instead of the web page.

## [2.8.0] - 2026-09-28
### Added
- Ctrl+Alt+Del sent as a real key sequence (works on Linux targets), true fullscreen.

## [2.7.x]
- Notes dialog, desktop toolbar (Ctrl+Alt+Del, clipboard, quality), canvas fills the panel, JPEG as
  default encoding (WebP tiles glitch in WebKit).

## [2.6.x]
- Application icon and name in the desktop dash, terminal disconnect banner.

## [2.5.0]
- Fixed a black remote screen; embedded web chrome stripped.

## [2.4.x]
- Administration panels, Notes editor, Services de-duplication and running state.

## [2.3.0]
- Working embedded remote desktop with a native toolbar.

## [2.2.0]
- Fixed device file listings, Services parsing, command output, network info, notes and event times.

## [2.0.0 - 2.1.0]
- Native single-window rebuild: device tree with embedded per-device tabs.

## [1.0.0] - 2026-09-28
- First prototype (a WebKit wrapper around the MeshCentral web UI), replaced by 2.x.
