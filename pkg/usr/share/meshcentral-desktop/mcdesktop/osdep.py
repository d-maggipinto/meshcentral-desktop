# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Operating-system specific services, so the rest of the app is the same on Linux and Windows.

Saved passwords: the Secret Service (GNOME keyring) on Linux, the Windows Credential Manager on
Windows (a generic credential of the current user, target "MeshCentralDesktop:<user>@<server>").
"""
import sys

IS_WINDOWS = sys.platform == "win32"

KEYRING_NAME = "Windows Credential Manager" if IS_WINDOWS else "system keyring"


# ---- saved passwords ---------------------------------------------------------------
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2      # this user on this computer (not roamed to other PCs)

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _CredWrite = _advapi.CredWriteW
    _CredWrite.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
    _CredWrite.restype = wintypes.BOOL
    _CredRead = _advapi.CredReadW
    _CredRead.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                          ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    _CredRead.restype = wintypes.BOOL
    _CredDelete = _advapi.CredDeleteW
    _CredDelete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _CredDelete.restype = wintypes.BOOL
    _CredFree = _advapi.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]

    def _target(server, username):
        return f"MeshCentralDesktop:{username}@{server}"

    def store_password(server, username, password):
        blob = password.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        c = _CREDENTIAL()
        c.Type = _CRED_TYPE_GENERIC
        c.TargetName = _target(server, username)
        c.Comment = f"MeshCentral {username}@{server}"
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = buf
        c.Persist = _CRED_PERSIST_LOCAL_MACHINE
        c.UserName = username
        return bool(_CredWrite(ctypes.byref(c), 0))

    def load_password(server, username):
        p = ctypes.POINTER(_CREDENTIAL)()
        if not _CredRead(_target(server, username), _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            _CredFree(p)

    def clear_password(server, username):
        _CredDelete(_target(server, username), _CRED_TYPE_GENERIC, 0)

else:
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret

    _SCHEMA = Secret.Schema.new(
        "uk.co.cyvelion.MeshCentralDesktop", Secret.SchemaFlags.NONE,
        {"server": Secret.SchemaAttributeType.STRING, "username": Secret.SchemaAttributeType.STRING})

    def store_password(server, username, password):
        try:
            Secret.password_store_sync(
                _SCHEMA, {"server": server, "username": username}, Secret.COLLECTION_DEFAULT,
                f"MeshCentral {username}@{server}", password, None)
            return True
        except Exception:
            return False

    def load_password(server, username):
        try:
            return Secret.password_lookup_sync(_SCHEMA, {"server": server, "username": username}, None)
        except Exception:
            return None

    def clear_password(server, username):
        try:
            Secret.password_clear_sync(_SCHEMA, {"server": server, "username": username}, None)
        except Exception:
            pass


# ---- application identity, single instance, notifications (Windows) ------------------
if IS_WINDOWS:
    import atexit
    import os

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _ERROR_ALREADY_EXISTS = 183
    _mutex = None

    def set_app_identity(app_id="CYVELION.MeshCentralDesktop"):
        """Taskbar grouping and notification sender name ("MeshCentral Desktop", not "Python")."""
        try:
            _shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
        except Exception:
            pass

    def _pid_file(name):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "MeshCentralDesktop", name + ".pid")

    def acquire_single_instance(name):
        """True for the first instance of `name`. A second one brings the first one's window to the
        front and gets False (Linux does this with D-Bus through Gtk.Application)."""
        global _mutex
        _kernel32.CreateMutexW.restype = wintypes.HANDLE
        _mutex = _kernel32.CreateMutexW(None, False, "Local\\" + name)
        if ctypes.get_last_error() != _ERROR_ALREADY_EXISTS:
            try:
                os.makedirs(os.path.dirname(_pid_file(name)), exist_ok=True)
                with open(_pid_file(name), "w") as f:
                    f.write(str(os.getpid()))
            except OSError:
                pass
            return True
        try:
            pid = int(open(_pid_file(name)).read().strip())
        except (OSError, ValueError):
            return False
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _l):
            owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and _user32.IsWindowVisible(hwnd) and not _user32.GetWindow(hwnd, 4):  # GW_OWNER
                found.append(hwnd)
            return True
        _user32.EnumWindows(each, 0)
        for hwnd in found[:1]:
            _user32.ShowWindow(hwnd, 9)            # SW_RESTORE
            _user32.SetForegroundWindow(hwnd)
        return False

    class _NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                    ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]

    _NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
    _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x2, 0x4, 0x10
    _tray = {"hwnd": None}

    def _icon():
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "meshcentral-desktop.ico")
        if os.path.isfile(ico):
            _user32.LoadImageW.restype = wintypes.HANDLE
            h = _user32.LoadImageW(None, ico, 1, 0, 0, 0x10)       # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                return h
        _user32.LoadIconW.restype = wintypes.HICON
        return _user32.LoadIconW(None, ctypes.c_void_p(32512))    # IDI_APPLICATION

    def notify(hwnd, title, body):
        """A Windows notification (notification-area balloon, shown as a toast on Windows 10 / 11)."""
        if not hwnd:
            return False
        d = _NOTIFYICONDATAW()
        d.cbSize = ctypes.sizeof(d)
        d.hWnd = hwnd
        d.uID = 1
        d.uFlags = _NIF_ICON | _NIF_TIP | _NIF_INFO
        d.hIcon = _icon()
        d.szTip = "MeshCentral Desktop"
        d.szInfoTitle = (title or "")[:63]
        d.szInfo = (body or " ")[:255]
        d.dwInfoFlags = 0x4 | 0x20                                  # NIIF_USER (our icon), NIIF_LARGE_ICON
        d.hBalloonIcon = d.hIcon
        if _tray["hwnd"] != hwnd:
            if _tray["hwnd"]:
                _remove_tray()
            ok = _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(d))
            _tray["hwnd"] = hwnd if ok else None
            return bool(ok)
        return bool(_shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(d)))

    def _remove_tray():
        if _tray["hwnd"]:
            d = _NOTIFYICONDATAW()
            d.cbSize = ctypes.sizeof(d)
            d.hWnd = _tray["hwnd"]
            d.uID = 1
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(d))
            _tray["hwnd"] = None

    atexit.register(_remove_tray)

    _gdk = None

    def window_handle(gtk_window):
        """HWND of a realized Gtk.Window (None if not realized)."""
        global _gdk
        gw = gtk_window.get_window() if gtk_window is not None else None
        if gw is None:
            return None
        if _gdk is None:
            _gdk = ctypes.CDLL("libgdk-3-0.dll")
            _gdk.gdk_win32_window_get_handle.restype = ctypes.c_void_p
            _gdk.gdk_win32_window_get_handle.argtypes = [ctypes.c_void_p]
            ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
            ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
        return _gdk.gdk_win32_window_get_handle(ctypes.pythonapi.PyCapsule_GetPointer(gw.__gpointer__, None))
