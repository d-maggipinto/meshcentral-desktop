# Remote desktop internals

`desktop_panel.py`: the most involved part of the app.

## Design choice: embed MeshCentral's own viewer

The app does **not** re-implement MeshCentral's KVM protocol (screen tiles, input encoding,
multi-display handling). It embeds the web UI's own desktop viewer in a WebKitGTK view and drives
it with JavaScript. This keeps full compatibility with every agent and server version the web UI
supports, while the native toolbar, overlay and shortcuts make it feel like part of the app.

## Connecting

Opening the Desktop tab does not connect: the cover shows "Not connected" and a **Connect**
button. Pressing it (or the toolbar's Connect) starts the flow below.

1. Load `<server>/` in a private WebKit profile. If the login form is shown, fill in the account's
   username and password and submit (2FA forms cannot be completed automatically).
2. Navigate to `<server>/?gotonode=<short id>&viewmode=11&hide=15`: the short id is the part of
   the node `_id` after the last `/`; `hide=15` removes the web UI's masthead, tabs and footer.
3. Poll every 250 ms until the viewer's `#connectbutton1` exists, then click it (the viewer never
   connects on its own).
4. Poll the viewer's `#deskstatus`. When it reports "Connected", wait for the **first real frame**
   (`FirstDraw === false`, the canvas has the remote screen size, not the 960×701 placeholder, on two
   consecutive checks), then remove the cover.

### Native cover
A `Gtk.Overlay` covers the WebView from the first navigation until the first frame, showing a
spinner and native status text ("Signing in…", "Opening desktop…", "Connecting to remote screen…").
The web login page and the viewer's own connection screens are never visible.

### State machine
`_phase`: `idle` → `loading` → `connecting` → `connected`, plus a generation counter `_gen` that
invalidates callbacks and retries of older attempts (reconnect, cancel). Only a session started in
the `connecting` phase may become `connected`, so a stale "Connected" from a page being replaced
is ignored. A 45 s watchdog turns a stalled attempt into an error with **Retry**. The toolbar button
shows **Connect**, **Cancel** or **Disconnect**. When the device page is already loaded, Connect
only clicks the viewer's Connect button (≈0.6 s).

### Pitfall: the page's "leave page?" dialog
While a session is active, the web UI registers a `beforeunload` confirmation. Any navigation
(reconnect, closing the tab) raises it, and behind the cover nobody could answer it, freezing the
navigation. The panel therefore ends the session and clears the handler before navigating, and
auto-confirms `BEFORE_UNLOAD_CONFIRM` script dialogs (other page dialogs are swallowed; alerts are
shown as notes).

### Agent restarts
When the device goes offline while a session is wanted, the cover shows "reconnecting
automatically…" and a full reconnect starts as soon as the agent is back online.

## Display and performance

- Injected CSS hides the viewer's own toolbars (`#deskarea1`, `#deskarea4`) and focus rectangle
  (`#DeskFocus`), pins the screen container to the viewport (`position: fixed`, `max-height: none`: the viewer sets an inline `max-height: calc(100vh - 74px)`) so the viewer's `deskAdjust()` sizes the
  canvas to the full area. `#deskarea0` must never be hidden: it contains the canvas.
- **Fullscreen** (Ctrl+Alt+F) hides the app's sidebar, tabs and toolbars and makes the window
  fullscreen on its current monitor; the canvas is refitted several times while the window manager
  settles.
- **Quality / Speed / Encoding / Scale** call `desktop.m.SendCompressionLevel(type, quality, scaling,
  frame timer)`. WebP is the default, like the web UI. Settings are sent even before the remote's native
  size is known (the scale stays as it is until then). *Auto* scale records the remote's native size at
  100 % and asks the agent for the size actually displayed (25-100 %).
- After every change the app asks for a full frame (`SendRefresh`) and reads the first bytes of the next
  tile (JPEG `FF D8`, PNG `89 50`, WebP `RIFF`): the status shows "Encoding: WEBP", or "Requested WEBP,
  the agent sends JPEG" when the agent does not honour the choice. The viewer labels every tile
  `image/jpeg` and relies on the decoder sniffing the real format.
- **Display picker** appears only when the agent reports more than one display, and only offers the
  displays it lists, asking an agent for a display it did not list crashed the agent in testing.

## Keyboard

- The viewer sends printable characters as Unicode, which is layout-independent. On Linux, however,
  AltGr arrives as its own key (`AltGraph`) and the viewer forwarded it as a held Right-Alt *before*
  the character, so the remote received e.g. Alt+@. The panel wraps the viewer's key handlers and
  drops `AltGraph`; the character AltGr produced still arrives.
- **Windows / Super key**: WebKitGTK reports Super with `keyCode` 0 and `metaKey` false, so the viewer
  sent key 0 (ignored by the remote) and typed the letter of Win+R, Win+E... as Unicode text, which
  Windows never treats as a shortcut. The wrapper sends Super as VK_LWIN / VK_RWIN with the extended
  flag (like the web UI's Start button) and, while it is held, printable keys as key codes; their key-up
  is sent with the same code even if Win was released first. Releasing keys on focus loss resets it.
  Accounts limited to basic input still cannot send it (the page's own rights check runs first).
- **Send hotkeys** (switch, default on): while the remote screen has keyboard focus the panel grabs
  the keyboard (`Gdk.Seat.grab`). On Wayland, GTK turns this into the *keyboard shortcuts inhibit*
  protocol (GNOME asks the user once; Super+Esc restores local shortcuts); on X11 it is a keyboard
  grab. It is released when focus leaves the remote screen, on disconnect and when switched off.
- **Ctrl+Alt+F** is handled by the main window before the WebView sees the key, so it always works;
  **Esc** is not intercepted and reaches the remote.
- **Ctrl+Alt+Del**: on Windows it is the secure attention sequence, which Windows never acts on when it
  arrives as injected keys, so for Windows devices the button (and Ctrl+Alt+Delete typed while the remote
  screen has focus) sends the viewer's own Ctrl+Alt+Del message, like the web interface's button. On
  Linux the button sends a real key sequence (`SendKeyMsgKC`), which Linux desktops act on.
- **Elevated windows (Windows)**: Windows drops input sent to an administrator window (UAC, admin
  PowerShell) by a process with a lower integrity level. Whether that works depends on how the agent
  runs on the device (installed as a service versus a user-level agent such as MeshCentral Assistant),
  not on this app: it sends the same input messages as the web interface.
- **Type clipboard** sends the local clipboard as Unicode keystrokes (Enter / Tab as real keys): useful
  when clipboard sharing is not available.

## Clipboard

The viewer's own clipboard code depends on the browser Clipboard API and page focus, which WebKitGTK
does not provide reliably. The app therefore uses MeshCentral's clipboard messages directly over its
own control connection (`getclip` / `setclip`) and the GTK clipboard; the page's
`navigator.clipboard` is replaced by a stub so the viewer cannot push stale data.

Security limits (2.25.1):
- The page itself has **no clipboard access** (`javascript-can-access-clipboard` off; in WebKitGTK it
  would also let a page script read the local clipboard) and the stub cannot be redefined.
- **Clipboard sync** only works while you look at the remote screen: the Desktop page is shown and
  the app window is active. While the session sits in the background a device cannot change the local
  clipboard and local copies are not sent; pending changes are applied when you come back.
- Texts larger than 256 KB are not synced.

## Web view limits (2.25.1)

The viewer and the app's other server windows (chat, Web-VNC, Web-RDP, Web-SSH) only navigate within
the configured server's https origin, cannot open new windows, and page-initiated downloads are
cancelled. The automatic sign-in fills the password only when the page's origin is the server's.
Page alerts are shown as "Message from the server page: …".

### Why Linux agents need help
On Linux, when the agent runs as a root service, MeshCentral's clipboard module:
- looks up the logged-in user's X display, on some systems (seen with XFCE/LightDM) this
  returns an **empty** display, so every read fails with `Can't open display:` and the agent sends no
  reply at all;
- writes by starting `xclip` as the user and **kills it after 20 seconds**, which empties the remote
  clipboard (an X11 clipboard only exists while its owner process runs).

### Agent patch (clipboard sync)
When **Clipboard sync** is on and the account has agent-console rights (8 + 16), the panel sends one
agent-console `eval` on connect that patches the running agent **in memory only**:
1. `monitor-info.getXInfo`: if it returns an empty display, use `DISPLAY` / `XAUTHORITY` from a
   process of the desktop user (`/proc/<pid>/environ`);
2. `clipboard.dispatchWrite` (Linux with xclip): start `xclip -selection clipboard -i` as the user
   and leave it running until something else takes the clipboard.

The patch is idempotent (version tag `mcd1`), disappears when the agent restarts, and is re-applied
on the next connection. Like every console command it appears in the server's event log. After the
patch, MeshCentral's standard messages work, and sync uses them:
- remote → local: `getclip` with `tag: 3` every second (the agent does not event-log tag 3);
- local → remote: GTK clipboard `owner-change` and window focus-in → `setclip`. On Wayland a client
  only learns about clipboard changes while it has focus, so a copy made in another local app is sent
  when you return to the app.
- Baselines are taken at connect (connecting never overwrites either clipboard); echo prevention keeps
  a synced value from bouncing back. View-only accounts only receive.

### Manual buttons
Paste to remote (`setclip`), Type clipboard (keystrokes), Copy from remote (`getclip` plus a parallel
`eval` read that uses the same display discovery and reports the agent's actual error instead of
timing out silently).

## Desktop tools (the web UI's desktop bar)

| Button | How |
|---|---|
| Tools | window with the device's processes (`ps`, double-click = `psinfo` details) and services |
| Run a script, Chat, Share | the same dialogs as the device's General page (`op_run`, `/messenger`, `createDeviceShareLink`) |
| Notification | toast, message box (2/10/30/60 minutes or until dismissed) or alert box, as in the web UI |
| Lock the computer | the viewer's control channel: `desktop.sendCtrlMsg('{"ctrlChannel":"102938","type":"lock"}')` (Windows agents) |
| Web address | `openUrl` (http / https only) |
| Background | `deskBackground` op 1 (toggle); the icon shows the state |
| Screenshot | the viewer's canvas `#Desk` at the remote resolution, `toDataURL('image/png')`, saved as `Desktop-<device>-<date>.png` |
| Record | the viewer's own recorder: `desktop.m.StartRecording()` (asynchronous: it first stores a PNG key frame), `StopRecording()` returns the `.mcrec` data, moved out of the page in base64 slices and saved as `DesktopSession-<device>-<date>.mcrec`; a recording running when the session ends is offered for saving first |
| Refresh | `desktop.m.SendRefresh()` |
| Input lock | `desktop.m.SendRemoteInputLock(1|0)`, state from `desktop.m.RemoteInputLock` (reported by the agent shortly after the session starts) |

Visibility follows the web UI: Chat, Notification and Lock need Chat & Notify `16384`, Run needs `131072`,
input-related tools need remote-control input, screenshot and recording are hidden when the server disables
them (`features2 & 0x400`). The icons are the server's own (`icon-play.png`, `icon-camera.png`... through
`servericons`), so a restyled server looks the same in the app.

## Fullscreen toolbar

In fullscreen the panel's toolbar moves into an auto-hiding bar at the top of the screen (`desktop_fsbar.py`),
with the image settings in a popover, a pin and Exit fullscreen; it moves back when fullscreen ends, so there
is one set of buttons. The bar is shown for 3 seconds, then hides; a thin handle at the top edge brings it back
on hover and it hides again shortly after the pointer leaves it (not while pinned or while a menu is open).
On Linux it is a revealer in the panel's overlay above the WebKit view. On Windows the remote screen is a
native WebView2 window GTK cannot draw over, so the bar and the handle are small popup windows at the top of
the monitor, made topmost through `SetWindowPos(HWND_TOPMOST)`; on screens narrower than 1500 px the long
labels are dropped.

## Permissions

The panel reads the account's rights (`rights.py`): without remote-control input rights the session is
view-only (Ctrl+Alt+Del, paste, type, hotkeys and pushing the clipboard are disabled; copying from the
remote still works). The agent patch is only sent with agent-console rights.
