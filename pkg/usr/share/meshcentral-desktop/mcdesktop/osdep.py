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
