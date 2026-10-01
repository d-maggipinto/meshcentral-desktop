# Permissions

MeshCentral enforces every permission on the server. The app additionally reads the signed-in
account's rights so it only **offers** what the account can do and explains the rest, instead of
showing buttons that fail silently. The logic lives in `mcdesktop/rights.py` and ports the web UI's
`GetMeshRights`, `GetNodeRights` and `removeUserRights`.

## How rights are computed

For a device, the account's rights are the combination of:
1. rights on the device's **device group**: directly (`mesh.links[userid]`) or through **user
   groups** the account belongs to (`mesh.links[ugrp/…]`); full rights (`0xFFFFFFFF`) anywhere wins;
2. rights granted **directly on the device** (`node.links`), directly or through user groups;
3. server-wide **"manage all device groups"** (`serverinfo.manageAllDeviceGroups`) → full rights;
4. account-wide **restrictions** (`userinfo.removeRights`): e.g. "no terminal", "no remote
   control", applied last.

Server-wide ("site") rights come from `userinfo.siteadmin`; `0xFFFFFFFF` is a full administrator.

## Device rights → app features

| Feature | Required (device rights) |
|---|---|
| Any agent feature (desktop, terminal, files, tools, clipboard) | Remote control `8` or view only `256` |
| Desktop tab | `8` or `256`, and not "no desktop" `65536` |
| Desktop input (keyboard, mouse, Ctrl+Alt+Del, paste/type, hotkeys, push clipboard) | Remote control `8` and not view only `256` |
| Terminal | `8`, not "no terminal" `512`, not view only |
| Device files | `8`, not "no files" `1024`, not view only |
| Processes / Services (list, kill, start/stop) | `8` |
| Agent Console | `8` + agent console `16` |
| Group Action: wake / sleep, reset, power off / run commands / notification / tags / upload files / delete / uninstall | Wake `64` / reset-off `262144` / remote commands `131072` / chat & notify `16384` / manage computers `4` / remote control `8` / uninstall `32768` (uninstall: agent online) |
| Group Action: move to device group | Edit group `1` on the device and the target, manage computers `4` on the target, same group type |
| Add Agent / Invite (+ button on the device group header, or right-click it) | Manage computers `4` on an agent group and not "no new devices" (site `4096`); Invite also needs a server that is not LAN-only |
| Add Device Group / MeshCmd | Not "no new groups" (site `64`) / not "no MeshCmd" (site `128`) |
| Run command; fast `systemctl` services listing | Remote command `131072` |
| Wake up | Wake device `64` |
| Sleep / Restart / Power off | Reset/off `262144` |
| Edit notes (viewing is always allowed) | Set notes `128` |
| Rename, edit tags | Manage devices `4` |
| Message box, toast | `8` |
| Clipboard agent patch | `8` + `16` |
| Device group folder in *Files* | Server files `32` on that group |

## Site rights → app features

| Feature | Required (site rights) |
|---|---|
| *Files* | File access `8` |
| *Server* (statistics, history) | Backup `1`, restore `4` or update `16` |
| Download server backup | Backup `1` |
| Restore server | Restore `4` |
| Check version / update, error log, configuration | Update `16` |
| Server console, server tracing | Full administrator |
| Users list: Select All / Group Action (lock, unlock, delete, email validation): same checks as the single-user actions, applied per user by the server | Manage users `2` |
| User page: edit email / real name, only full admins may edit a full admin; **Server Permissions**: full-admin-only boxes (full admin, backup, restore, updates, server files) vs. manage-users boxes (lock, no new groups/devices, no tools, lock settings), never your own; **Change Password / Delete**: manage users and target not a full admin (or you are); device-group / device permission edits need Manage Users `2` on that group / device; user-group memberships need site `256` | Manage users `2` |
| Users tab, **Broadcast** (user group or all users), user list **Export**, batch **Import**, **New Account…** | Manage users `2` (plus server features: no New Account on single-user / SSPI servers, no Import with LDAP / SSPI) |
| User Groups tab | User groups `256` |
| Groups: New / Duplicate / Group Action / rename / description / consent / members / delete | User groups `256`; Broadcast also needs Manage users `2`; group device-group / device permissions need Manage Users `2` on that group / device; synced (identity-provider) groups keep name and members |
| Server Events, My Account | always |
| My Account security / account actions | not when *Lock account settings* `1024` is set |
| My Account → New device group | not when *No new device groups* `64` is set |

## Behaviour when a right is missing

- Device tabs are greyed out; opening one shows *"Your account does not have permission to use …
  on this device"*.
- Action-bar buttons, power menu items and context-menu entries are disabled individually.
- The desktop opens in **view-only** mode with a "View only" status.
- Notes open read-only.
- Server tabs the account cannot use are greyed out; *Files* explains how to get access.
- The Services tab falls back to the agent's (slower) service list when the account may not run commands.

## Testing

The local test server has two accounts: a full administrator and a restricted account with no site
rights and only "view only" + "device details" on the test device group; both are exercised by the
regression tests (see [DEVELOPMENT.md](DEVELOPMENT.md)).
