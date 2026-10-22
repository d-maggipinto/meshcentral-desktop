# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Happy Eyeballs address ordering (a simplified RFC 8305) for the app's own TCP clients.

websocket-client (control channel, relay tunnels) and urllib (My Files transfers, updater,
server icons) connect to a host's addresses one after the other and treat the first *timeout*
as fatal: only "connection refused" / "network unreachable" move them on to the next address.
On a network whose IPv6 is configured but carries no traffic (the router advertises a prefix,
the uplink silently drops the packets) the operating system lists the IPv6 addresses first,
so every connection hangs on them for up to two minutes while a browser quietly falls back to
IPv4 within a fraction of a second. That showed up as the app no longer signing in while the
web UI still worked (3.0.6).

install() wraps socket.getaddrinfo: when a host name resolves to both families, the first
IPv6 and the first IPv4 address are raced (IPv6 gets the usual 250 ms head start) and the
family that connects first is listed first. The verdict is cached per (host, port) for a few
minutes, so the race costs one extra TCP connection every few minutes, not one per request.
A host with a single family, numeric addresses, passive (listening) lookups and non-stream
lookups are passed through untouched. Set MCD_ADDRESS_RACE=0 to disable it.
"""
import os
import socket
import threading
import time

HEAD_START = 0.25        # seconds IPv6 is allowed before IPv4 is also tried (RFC 8305: 250 ms)
CONNECT_TIMEOUT = 3.0    # seconds a single probe may take
CACHE_SECONDS = 300

_orig_getaddrinfo = None
_cache = {}              # (host, port) -> (winning family, expiry time)
_lock = threading.Lock()


def _probe(addr, family, state, cond):
    """Try one TCP connection; the first family to succeed becomes state['family']."""
    s = None
    ok = False
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(CONNECT_TIMEOUT)
        s.connect(addr)
        ok = True
    except OSError:
        pass
    finally:
        try:
            if s is not None:
                s.close()
        except OSError:
            pass
    with cond:
        if ok and "family" not in state:
            state["family"] = family
        state["finished"] += 1
        cond.notify_all()


def race(addr6, addr4):
    """Return the family (AF_INET6 / AF_INET) that connected first, or None if neither did."""
    state = {"finished": 0}
    cond = threading.Condition()
    threading.Thread(target=_probe, args=(addr6, socket.AF_INET6, state, cond), daemon=True).start()
    with cond:
        cond.wait_for(lambda: "family" in state or state["finished"] >= 1, HEAD_START)
        if "family" in state:
            return state["family"]
    threading.Thread(target=_probe, args=(addr4, socket.AF_INET, state, cond), daemon=True).start()
    with cond:
        cond.wait_for(lambda: "family" in state or state["finished"] >= 2, CONNECT_TIMEOUT + 0.5)
        return state.get("family")


def _is_numeric(host):
    for fam in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(fam, host.split("%", 1)[0])
            return True
        except (OSError, ValueError, AttributeError):
            pass
    return False


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _orig_getaddrinfo(host, port, family, type, proto, flags)
    try:
        if family not in (0, socket.AF_UNSPEC) or (flags & socket.AI_PASSIVE):
            return res
        if not isinstance(host, str) or not host or _is_numeric(host):
            return res
        stream = [r for r in res if r[1] == socket.SOCK_STREAM]
        first = {}
        for r in stream:
            first.setdefault(r[0], r[4])
        if socket.AF_INET6 not in first or socket.AF_INET not in first:
            return res
        key = (host.lower(), port)
        now = time.monotonic()
        with _lock:
            hit = _cache.get(key)
        if hit and hit[1] > now:
            winner = hit[0]
        else:
            winner = race(first[socket.AF_INET6], first[socket.AF_INET])
            if winner is None:
                return res                       # nothing answers: leave the OS order alone
            with _lock:
                _cache[key] = (winner, now + CACHE_SECONDS)
        if winner == socket.AF_INET6:
            return res
        return [r for r in res if r[0] == winner] + [r for r in res if r[0] != winner]
    except Exception:
        return res


def install():
    """Wrap socket.getaddrinfo process-wide (idempotent)."""
    global _orig_getaddrinfo
    if os.environ.get("MCD_ADDRESS_RACE", "1") == "0" or _orig_getaddrinfo is not None:
        return
    _orig_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = _getaddrinfo


def uninstall():
    global _orig_getaddrinfo
    if _orig_getaddrinfo is not None:
        socket.getaddrinfo = _orig_getaddrinfo
        _orig_getaddrinfo = None
    _cache.clear()
