# Rig tests (local MeshCentral server)

These scripts drive the real application against a **local, throwaway MeshCentral server** and,
for the remote desktop / terminal / files tests, a real MeshCentral agent. They are how every
feature of this app was verified. They are not unit tests: they need a running server, a display
server (use Xvfb) and, for some of them, an agent.

**LOCALHOST TESTING ONLY.** The scripts connect to `https://127.0.0.1:8443`, turn off TLS
certificate checks for that self-signed local server, and use the test accounts below. Never point
them at a real server.

| Account | Password | Rights |
|---|---|---|
| `admin` | `Test-1234` | full administrator |
| `limited` | `Limit-12345!` | no server rights, device group rights view only (0x100 + 0x100000) |

These are local test defaults, not real credentials. Tests that change accounts create their own
throwaway users, groups and devices and delete them at the end.

## Setup

The full procedure (server, accounts, agent, email-as-user-name mode) is in
[docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md). In short:

```bash
mkdir -p ~/mcd-rig/mctest && cd ~/mcd-rig/mctest
npm install meshcentral
node node_modules/meshcentral/meshcentral --cert 127.0.0.1 --createaccount admin --pass Test-1234
node node_modules/meshcentral/meshcentral --adminaccount admin
node node_modules/meshcentral/meshcentral --cert 127.0.0.1 --port 8443 --redirport 8080 --exactports &
```

Set `MCD_RIG_DIR` if the rig is not in `~/mcd-rig` (the agent restart tests start the agent from
`$MCD_RIG_DIR/mctest/agent`). `rigenv.py` puts the application on `sys.path`, so the scripts run
from any directory.

## Running

Run GUI tests under Xvfb, so windows, keyboard grabs and dialogs never touch your desktop:

```bash
GDK_BACKEND=x11 WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  xvfb-run -a -s "-screen 0 1920x1080x24" python3 tests/rig/userpage_test.py /tmp
```

Most scripts print `PASS` / `FAIL` lines and a final `N/M passed`. Scripts marked `<tmpdir>` take a
directory for temporary files and screenshots.

Important: the agent controls the computer it runs on. Tests that send keys stub the viewer's
key sending, but read the script before running it on a machine you care about. Stop the agent
with SIGTERM, never SIGKILL (a killed agent can corrupt its local database).

## Index

| Script | Covers |
|---|---|
| `userlist_test.py` | Users list: online / offline sections and live session counts, device groups, permissions labels, filter, Select All / None, Group Action lock / unlock / delete |
| `userpage_test.py <tmpdir>` | user page: every edit dialog, device group / user group / device permissions, notes, password change, previous logins, account image, events, delete |
| `newaccount_test.py name\|email` | New Account: validation, create, duplicate, random password, password policy (`email` = rig in email-as-user-name mode) |
| `userimport_test.py <tmpdir>` | user list export (CSV / JSON) and batch import |
| `groups_test.py <tmpdir>` | Groups list and group page, Add Users suggestions, duplicate, delete |
| `account_test.py`, `account_test2.py`, `account_delete_test.py` | My Account (throwaway account `acctest`) |
| `myfiles_test.py` | My Files: folders, upload, download (checksum), rename, copy, edit, delete |
| `version_test.py`, `trace_test.py`, `stats_test.py`, `cpu_live_test.py` | My Server: version check, trace, statistics, CPU recorder |
| `stats_synth.py`, `cpu_synth.py` | render the statistics charts with synthetic data (no server needed) |
| `broadcast_test.py send\|recv` | user group broadcast (needs the `limited` account in a group named `Admins`) |
| `limited_test.py`, `limited_test2.py`, `layout_test.py` `<user> <pw>` | permissions of a restricted account, navigation rail |
| `dialog_test.py`, `dialog_test2.py`, `events_test.py` | run command output, event tables |
| `reconnect_test.py`, `cover_test.py`, `disp_test.py`, `kb_test.py` | remote desktop: state machine, first-frame cover, display picker, keyboard (needs an agent) |
| `sync_test.py`, `clipfb_test.py` | clipboard sync and the agent display fallback (needs an agent) |
| `restart_test.py`, `restart_test2.py`, `restart_test3.py`, `update_test.py` | agent restart / update handling (needs an agent) |
| `probe_test.py`, `probe2.py`, `probe3.py`, `fs_test.py`, `ws.py` | protocol probes used while developing |
