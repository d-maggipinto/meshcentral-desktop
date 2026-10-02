# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows: send system shortcuts to the remote computer ("Send hotkeys").

Windows handles Win, Win+<key>, Alt+Tab, Alt+Esc, Ctrl+Esc, Alt+Space and Alt+F4 itself before an
application sees them. While the remote screen has the focus (and our window is in front), a
low-level keyboard hook (WH_KEYBOARD_LL) takes those keys away from Windows and hands them to
`forward(vk, down, extended)`, which sends them to the remote as key codes. While Win is held every
key goes that way, so Win+R reaches the remote as a shortcut, not as typed text.

The hook runs on the GTK thread (GTK's Win32 loop pumps the messages it needs); forwarding is
queued with GLib.idle_add so the hook procedure returns at once. Keys injected by other software
(LLKHF_INJECTED) are never touched. Ctrl+Alt+Del cannot be intercepted (Windows secure sequence).
"""
import ctypes
from ctypes import wintypes

from gi.repository import GLib

WH_KEYBOARD_LL = 13
LLKHF_EXTENDED, LLKHF_INJECTED, LLKHF_UP = 0x01, 0x10, 0x80
VK_TAB, VK_ESCAPE, VK_SPACE, VK_F4 = 0x09, 0x1B, 0x20, 0x73
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_CONTROL, VK_MENU = 0x11, 0x12

_ALT_KEYS = (VK_TAB, VK_ESCAPE, VK_SPACE, VK_F4)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
_user32.SetWindowsHookExW.restype = ctypes.c_void_p
_user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user32.CallNextHookEx.restype = _LRESULT
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_user32.GetAncestor.restype = ctypes.c_void_p


def _down(vk):
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class KeyboardHook:
    """forward(vk, down, extended); top_hwnd: our top-level window (keys only while it is in front)."""

    def __init__(self, forward, top_hwnd):
        self.forward = forward
        self.top_hwnd = top_hwnd
        self._hook = None
        self._proc = _HOOKPROC(self._on_key)     # keep a reference: the hook calls it
        self._win_held = set()
        self._taken = set()                      # keys whose key-down we took (their key-up follows)

    @property
    def active(self):
        return self._hook is not None

    def start(self):
        if self._hook is None:
            self._hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)

    def stop(self):
        if self._hook is not None:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        for vk in sorted(self._win_held | self._taken):   # never leave a key held on the remote
            self._send(vk, False, vk in (VK_LWIN, VK_RWIN))
        self._win_held.clear()
        self._taken.clear()

    def _send(self, vk, down, ext):
        GLib.idle_add(lambda: (self.forward(vk, down, ext), False)[1])

    def _ours_in_front(self):
        fg = _user32.GetForegroundWindow()
        return bool(fg) and _user32.GetAncestor(fg, 2) == self.top_hwnd    # GA_ROOT

    def _on_key(self, code, wparam, lparam):
        try:
            if code == 0:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not kb.flags & LLKHF_INJECTED and self._take(kb):
                    return 1
        except Exception:
            pass
        return _user32.CallNextHookEx(self._hook, code, wparam, lparam)

    def _take(self, kb):
        vk, up, ext = kb.vkCode, bool(kb.flags & LLKHF_UP), bool(kb.flags & LLKHF_EXTENDED)
        if up and vk in self._taken:             # finish what we started even if focus moved meanwhile
            self._taken.discard(vk)
            self._win_held.discard(vk)
            self._send(vk, False, ext)
            return True
        if not self._ours_in_front():
            return False
        if vk in (VK_LWIN, VK_RWIN):
            if not up:
                self._win_held.add(vk)
                self._taken.add(vk)
            self._send(vk, not up, True)
            return True
        take = bool(self._win_held) or (vk in _ALT_KEYS and _down(VK_MENU)) or \
            (vk == VK_ESCAPE and _down(VK_CONTROL))
        if take and not up:
            self._taken.add(vk)
            self._send(vk, True, ext)
            return True
        return False
