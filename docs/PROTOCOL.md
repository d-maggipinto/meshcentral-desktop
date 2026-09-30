# MeshCentral protocol notes

What the app sends and receives, as **verified against a live MeshCentral server and agent**.
Several shapes differ from what a first reading of the MeshCentral source suggests, those are
marked ⚠.

## Authentication and channels

| Channel | How |
|---|---|
| Control | `wss://<server>/control.ashx`, header `x-meshauth: base64(user),base64(pass)[,base64(2FA code)]` |
| Relay tunnel | `{action:'authcookie'}` → cookie; `{action:'msg', type:'tunnel', nodeid, value:'*/meshrelay.ashx?p=<proto>&nodeid=…&id=…&rauth=…'}`; then connect `wss://<server>/meshrelay.ashx?…&auth=<cookie>` |
| Web session | `POST /login` form `action=login, username, password[, token]` → session cookie (only for `downloadfile.ashx`) |

Close reasons on the control channel: `{action:'close', cause:'noauth', msg:'tokenrequired'}` → a
2FA code is needed; `cause:'noauth'` → wrong credentials.

Relay protocols: `1` terminal (admin shell), `2` desktop, `5` files, `6` admin PowerShell,
`7` user shell, `8` user PowerShell. The agent answers `c` / `cr` (recorded) before the session starts.
⚠ The file relay sends its JSON control messages as **binary** frames starting with `{`.

## Devices

| Request | Reply |
|---|---|
| `{action:'meshes'}` | `{meshes:[{_id, name, links:{<user or ugrp id>:{rights}}}]}` |
| `{action:'nodes'}` | `{nodes:{<meshid>:[node, …]}}`: `node.conn & 1` = agent online |
| `{action:'getsysinfo', nodeid, cache:true, nodeinfo:true}` | `message.hardware` |
| `{action:'getnetworkinfo', nodeid}` | ⚠ data is in `message.netif2` (object keyed by interface) |
| `{action:'events', nodeid, limit}` | `{events:[…]}`; `time` is ISO-8601 **or** epoch ms |
| `{action:'getNotes', id:nodeid}` | ⚠ reply action is `getNotes` (not `notes`), field `notes` |
| `{action:'setNotes', id, notes}` | no reply |
| `{action:'changedevice', nodeid, name / tags}` |, |
| `{action:'poweraction', nodeids, actiontype}` | wake 100, off 2, reset 3, sleep 4 |
| `{action:'toast', nodeids, title, msg}` / `{action:'msg', type:'messagebox', …}` |, |

⚠ When an agent goes offline (restart, `agentupdate`) the server may **drop the device from the
`nodes` reply entirely** instead of listing it with `conn = 0`.

Agent identification: `node.agent.ver` is `0` on modern agents; the web UI shows the agent type
from its `agentsStr` table (`node.agent.id`, e.g. 6 = "Linux 64bit") and `node.agent.core`
(the running core's build, e.g. `Feb 15 2026, 1740302142`). `agent.root === false` → restricted agent.

## Agent messages (`{action:'msg', type, nodeid, …}`)

Routed only if the account has remote-control (8) or view-only (256) rights on the device.

| type | Notes |
|---|---|
| `ps` | ⚠ `value` is a JSON **string** `{pid:{cmd, user}}` |
| `pskill` | `value: pid` |
| `services` | ⚠ `value` is a JSON string array; every Linux unit appears **twice**; names have **no** `.service` suffix; running units carry `state:'RUNNING'`. Slow on Linux (seconds). |
| `serviceStart` / `serviceStop` / `serviceRestart` | `serviceName`; needs a root / SYSTEM agent |
| `console` | ⚠ the **MeshAgent console** (agent commands such as `help`, `ls`, `eval`), not a shell |
| `getclip` | `tag: 2` manual, `tag: 3` auto-polling (tag 3 is not written to the event log). Reply `{type:'getclip', data, tag, nodeid}` only if the clipboard holds text |
| `setclip` | `data`; reply `{type:'setclip', success:true}` |

The server **silently drops** `getclip` / `setclip` when the domain disables `ClipboardGet` /
`ClipboardSet`. Linux agents only use the X11 clipboard.

### Agent console `eval`
`{action:'msg', type:'console', value:'eval "<javascript>"'}` runs JavaScript in the agent
(requires rights 8 + 16). The result is returned only to the requesting session. **Every console
command is written to the server's event log.** The JavaScript must not contain `"` or backslashes
(it travels inside the quoted argument), and in the agent's engine `Buffer.toString()` stops at the
first NUL byte.

## Run commands

```
{action:'runcommands', nodeids:[id], type:3 (Linux shell) | 0 cmd | 2 PowerShell,
 cmds:'…', runAsUser:0, reply:true, responseid}
```
⚠ `{action:'runcommands', result:'OK', responseid}` is only an **acknowledgement** (or an error such
as `Access denied`). The output arrives later as
`{action:'msg', type:'runcommands', result:'<output>', responseid, nodeid}`.
Needs the "run commands" right (131072).

## Users, groups, broadcast

User groups (site right 256 for every change): `usergroups` → `{ugroups:{id:{name, desc, links:{user/…:{name,
rights}, mesh/…:{rights}, node/…:{rights}}, consent?, flags?, membershipType?}}}`. `createusergroup {name ≤64,
desc ≤1024[, clone: ugrp id][, domain]}` → `{result:'ok', ugrpid}` (the creator is NOT made a member; `clone`
copies user and mesh links only, never node links). `deleteusergroup {ugrpid}` → `ok`. `editusergroup {ugrpid,
name?, desc?, consent?, flags?(2 = record sessions)}` → no reply, `event usergroupchange`; the name of a group
with `membershipType` (identity-provider sync) cannot change. Members: `addusertousergroup {ugrpid,
usernames:[short ids]}` → `{result:'ok', added, failed}`, `removeuserfromusergroup {ugrpid, userid}`. Group
permissions: `addmeshuser {…, userids:[ugrp id]}` / `removemeshuser {meshid, userid: ugrp id}` /
`adddeviceuser {…, userids:[ugrp id]}`. Events: `createusergroup`, `deleteusergroup`, `usergroupchange`.

`serverinfo.features` (sent at sign-in) is the same bitmask the web UI gets from its page template:
`0x4` single-user server (no New Account), `0x80000` LDAP/SSPI sign-in (no batch import),
`0x200000` user name is the email address (`usernameisemail`: the Create Account form has no
username field). `serverinfo.emailcheck` → *Email is verified* / *Send invitation email*;
`serverinfo.domainauth` (SSPI) → no New Account; `serverinfo.crossDomain` → domain picker.

| Request | Reply / notes |
|---|---|
| `{action:'users'}` | `{users:[CloneSafeUser…]}` (a user without server rights has NO `siteadmin` field → "User") (no hash/salt; 2FA fields reduced to counts/flags); no reply at all without site right 2. The web UI's user export (`userlist.csv` / `.json`) is built client-side from this list |
| `{action:'usergroups'}` | `{ugroups:{<id>:{name, desc, links:{user/…:{name, rights}, mesh/…:{rights}}}}}` |
| `{action:'adduser', username, email, pass, resetNextLogin, randomPassword, removeEvents[, emailVerified, emailInvitation][, domain]}` | with `responseid`: `{action:'adduser', result:'ok'}` or `{result:<error>, msgid}`: `Permission denied`(1), `Invalid username`(2), `Invalid password`(3, incl. password requirements), `Invalid email`(4), `Invalid domain`(5), `User already exists`(7), `Unable to add user in this mode`(8), `maxUsersExceed`, `passwordHashError`. Without responseid errors arrive as a notify. `randomPassword:true` → the server generates a password it never reveals. `usernameisemail` servers: username := email (the NAME keeps the typed case, id/email are lowercased). Also emits `event accountcreate`. Site right 2 |
| `{action:'edituser', id, email? realname? phone? flags+removeRights? siteadmin(+quota k*1024)? consent? groups?}` | errors only with `responseid` (`{result:<text>}`); success = `event accountchange` (none when nothing changed). `usernameisemail` servers IGNORE `email`. Only a full admin may change a full admin; `siteadmin` never on yourself |
| `{action:'changeuserpass', userid, pass, removeMultiFactor(bool), resetNextLogin[, hint]}` | NO reply at all; success = `event accountchange` with `msgid:75`; a password failing `passwordrequirements` is silently dropped (the app warns after 6 s) |
| `{action:'deleteuser', userid, username}` | `{result:'ok'}` with responseid |
| `{action:'addmeshuser', meshid, meshname, userids:[id], meshadmin}` | `{result:"Added user x, …", success, failed}`: NOT `ok`; `removemeshuser {meshid, userid}` → `ok` |
| `{action:'adddeviceuser', nodeid, nodename, userids:[id], rights[, remove:true]}` | `ok`; rights may not contain 1/2/4; silently ignored if the node is unknown or you lack Manage Users on it |
| `{action:'addusertousergroup', ugrpid, usernames:[short id]}` / `{action:'removeuserfromusergroup', ugrpid, userid}` | `{result:'ok'}` (+ `added`/`failed`) |
| `{action:'events', userid, limit?, filter?}` | `{action:'events', events, userid}`; device requests are echoed with `nodeid`, server-wide ones with neither → each table filters its own replies. `filter` ∈ agentlog, relaylog, manual, runcommands, batchupload, changenode, removenode |
| `getNotes`/`setNotes {id:'user/…'}` | user notes, need site right 2 |
| `{action:'updateUserImage', userid?, image: 'data:image/png|jpeg;base64,…' (<600000 chars) \| 0}` | no reply; sets/clears `flags & 1` → `event accountchange`; `userid` (another user) needs site right 2, ignored with a login token. Read back: `GET /userimage.ashx?id=<short id>` (web session) |
| `{action:'wssessioncount'}` | `{wssessions:{userid: count}}` (only users with open web/app sessions; `{}` without site right 2). Live: `{action:'event', event:{action:'wssessioncount', userid, count}}` (count 0 = offline). The server stores `user.access` on session close ONLY if the user already had one (never-web users keep none → blank Last Access, web UI too) |
| `{action:'previousLogins', userid}` | another user's logins (site right 2), reply carries `userid` |
| `{action:'adduserbatch', users:[{user, pass, email?, resetNextLogin?, realname?, emailVerified?}]}` | replies ONLY on error, and only if `responseid` is set: `{result:'Access denied' \| 'Invalid username' \| 'Invalid password' \| 'Invalid email' \| 'Unable to create users when in SSPI or LDAP mode'}`: one bad row rejects the whole batch and the error does not say which row (last one wins). Success is silent: one `{action:'event', event:{action:'accountcreate', account:{name,…}}}` per NEW account; names that already exist are skipped without notice. Account limit → `{action:'msg', type:'notify', msgid:10}`. Password strength = domain `passwordrequirements` (not sent on the control channel). `usernameisemail` servers: user := email, or email := user when there is no email (then the user must be a valid email or the WHOLE batch fails with `Invalid email`). Email must match `validateEmail` (needs a TLD). `resetNextLogin:true` → `passchange:-1`. Site right 2 |
| `{action:'userbroadcast', msg, target?, maxtime}` | `msg` 1-512 chars (longer → `Message is too long`); `target` = user group id, omitted = all users; `maxtime` seconds, 0 = until dismissed; needs site right 2 |

Receivers get `{action:'msg', type:'notify', title:<sender>, value, tag:'broadcast', maxtime}`.
Other notices may arrive as `{action:'event', event:{action:'notify', title, value, tag}}`.
If the sender belongs to any user group, the server only delivers to users who share a group.

## My Server

Statistics need site right backup (1), restore (4) or update (16); a domain can disable the whole
section (`myserver: false`) or parts of it (`myserver.backup / restore / upgrade / errorlog / config /
console`).

| Request | Reply / notes |
|---|---|
| `{action:'serverstats', interval:<ms>}` | periodic `{totalmem, freemem, availablemem, cpuavg:[1,5,15 min], values:{ServerState:{UserAccounts, DeviceGroups, AgentSessions, ConnectedUsers, UsersSessions, RelaySessions, RelayCount, ConnectedIntelAMT, ConnectedIntelAMTCira?, RelayErrors?}, AgentErrorCounters?}}`; send without `interval` to stop |
| `{action:'servertimelinestats', hours}` | `{events:[{time, conn:{ca, cu, us, rs, am, amc?}, mem:{rss, heapTotal, heapUsed, external}, cpu:[…], traffic, first?, s?}]}`: one sample every 5 minutes (thinned over time: kept 3 h / 8 h / 24 h / 48 h / 72 h / 30 days). `first: true` marks the first sample after a server start (the web UI breaks the line there); `s` = server id with peering. `traffic` holds per-sample byte deltas: `AgentCtrlIn/Out`, `CIRAIn/Out`, `LMSIn/Out`, `httpIn/Out`, `relayIn/Out[protocol]` (0 relay, 1 terminal, 2 desktop, 5 files, 10 WebRDP, 11 WebSSH, 12 WebVNC), `desktopMultiplex.in/out` |
| *(event, every 5 min)* | `{action:'event', event:{action:'servertimelinestats', data:<sample>}}`: live append |

⚠ The **MongoDB and NeDB** backends (NeDB is the default) return the history with `find(…, {_id: 0, cpu: 0})`: **CPU is never in the history**, only in live samples (events) and `serverstats.cpuavg`. SQL backends
(SQLite, MySQL/MariaDB, PostgreSQL) return the whole document including `cpu`. `cpu` is accepted as an
array or an object keyed `"0"`. The live event is sent to every session (no page needs to be open);
the app records its CPU from sign-in in `~/.local/share/meshcentral-desktop/serverstats-<host>.json`
(30 days) and merges it into the history by timestamp.
| `{action:'serverversion'}` | `{action:'serverversion', tags:{current, latest, stable}}` (update right; the server queries the npm registry, can take seconds). With a `responseid` newer servers answer `{result:'OK', tags, responseid}`; the app listens for the action instead so it works either way |
| *(pushed once at sign-in)* | `{action:'serverwarnings', warnings:[{id, msg, args}]}`: ids map to the web UI's warning texts (22 = "Failed to sign agent {0}: {1}") |
| `{action:'serverupdate', version?}` | server installs the version and restarts |
| `{action:'servererrors'}` / `{action:'serverclearerrorlog'}` | `{data}` error log text (update right) |
| `{action:'serverconfig'}` | `{data}` = `config.json`: sensitive (update right) |
| `{action:'serverconsole', value}` | `{action:'serverconsole', value}`: full administrators only |
| `{action:'traceinfo', traceSources:[…]}` | full admins; sets the SERVER-WIDE trace sources (`[]` = off): cookie, dispatch, main, peer, agent, agentupdate, cert, db, email, web, webrequest, relay, httpheaders, authlog, amt, webrelay, mps, mpscmd. Current sources are sent at sign-in (`{action:'traceinfo'}`) and broadcast on change (`{action:'event', event:{action:'traceinfo', traceSources}}`) |
| *(trace line)* | `{action:'trace', source, args:[…], time:<ms>}` to every full-admin session; the server clears the sources when no full admin is connected |
| `GET /backup.zip` | web session + backup right; the server creates the backup first (up to 2 min); `403 Backup disabled` when `settings.autobackup.backupintervalhours` is -1 |
| `POST /restoreserver.ashx` | multipart `datafile` (+ `auth`), web session + restore right; replaces the server database and restarts |

## Server file storage ("My Files")

| Request | Notes |
|---|---|
| `{action:'files'}` | `{action:'files', filetree:{n:'Root', f:{<user id>:{t:1, n:'My Files', f, maxbytes}, <mesh id>:{t:4, …}}}}`; entries `t` 2 folder, 3 file (`s` size, `d` mtime ms); re-sent after every change |
| `{action:'fileoperation', fileop, path:[rootid, sub…], …}` | `createfolder` (newfolder), `delete` (delfiles, rec), `rename` (oldname, newname), `copy` / `move` (scpath, names), `get` (file → base64 `data`, < 200 KB), `set` (file, data) |
| `POST /uploadfile.ashx` | multipart: `link` = URL-encoded `<rootid>/<sub…>`, `auth` = control-channel auth cookie, `files` |
| `GET /downloadfile.ashx?link=<rootid>/<sub…>/<file>` | requires a **web session** |

Needs site right 8; a device group's folder needs group right 32.

## My Account

| Request | Reply / notes |
|---|---|
| `{action:'otpauth-request'}` | `{secret, url}` (otpauth:// URL for the QR code) |
| `{action:'otpauth-setup', secret, token}` | `{success}` |
| `{action:'otpauth-clear'}` | `{success}` |
| `{action:'otpauth-getpasswords', subaction}` | backup codes: `{passwords}`; `subaction` 1 = create new, 2 = clear |
| `{action:'otp-hkey-get'}` / `{action:'otp-hkey-remove', index}` | security keys `{keys:[{i, name, type}]}` / remove one |
| `{action:'previousLogins'}` | `{events:[{t, m:107, a:[ip, browser, os], tn?}]}`: ⚠ only **web** sign-ins are recorded; control-channel (app) sign-ins are not |
| `{action:'changepassword', oldpass, newpass}` | ⚠ no direct reply, a `notify` with `msgid` 20 (changed) or 17/18/19/21 (21 = current password wrong) |
| `{action:'loginTokens', remove?}` / `{action:'createLoginToken', name, expire}` | token list `{loginTokens}` (pass `remove` to delete); create returns `{tokenUser, tokenPass, expire}` |
| `{action:'updateUserImage', image:<data URL> \| 0}` | `0` removes it; read back with `GET /userimage.ashx` (web session) |
| `{action:'changelang', lang}` |, |
| `{action:'createmesh', meshname, meshtype:2, desc}` |, (refused with site right 64 "no new groups") |
| `POST /deleteaccount` | form `authcookie, apassword1, apassword2`. ⚠ Success and a wrong password return the **same** redirect and the deleted user's control session is **not** closed, the app confirms by trying a fresh sign-in (`noauth` = deleted, `tokenrequired` = still exists) |

Changes to the signed-in account are echoed as `{action:'event', event:{action:'accountchange', account}}`.
Site right `1024` (lock account settings) makes the server refuse the security and account actions.
