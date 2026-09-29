"""MeshCentral protocol layer: control channel (control.ashx) and relay tunnels (meshrelay.ashx).

All network I/O runs on background threads; every callback is marshalled back onto the
GTK main loop with GLib.idle_add, so UI code never has to worry about threads.
"""
import base64
import json
import secrets
import ssl
import threading
from urllib.parse import quote, urlparse

import websocket
from gi.repository import GLib

USER_AGENT = "MeshCentralDesktop/2.0"
CTRL = "102938"

# Relay protocols
PROTO_TERMINAL = 1          # Admin shell (bash / cmd)
PROTO_DESKTOP = 2
PROTO_FILES = 5
PROTO_POWERSHELL = 6        # Admin PowerShell
PROTO_USER_SHELL = 7
PROTO_USER_POWERSHELL = 8


def _b64(s):
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _ui(fn, *args):
    """Run fn(*args) on the GTK main loop."""
    if fn is None:
        return

    def call():
        fn(*args)
        return False
    GLib.idle_add(call)


class ServerAddress:
    def __init__(self, url):
        url = url.strip().rstrip("/")
        if "://" not in url:
            url = "https://" + url
        p = urlparse(url)
        self.https = p.scheme == "https"
        self.host = p.netloc
        self.path = p.path.rstrip("/")          # login domain path, usually ""
        self.url = f"{p.scheme}://{p.netloc}{self.path}"

    def ws(self, endpoint):
        return f"{'wss' if self.https else 'ws'}://{self.host}{self.path}/{endpoint}"


class AuthError(Exception):
    pass


class ControlConnection:
    """The main user session. Emits every server JSON message to listeners."""

    def __init__(self, server, username, password, token=None):
        self.server = ServerAddress(server)
        self.username = username
        self.password = password
        self.token = token
        self.ws = None
        self.connected = False
        self.listeners = {}          # action -> [callbacks]
        self.any_listeners = []
        self.pending = {}            # responseid -> callback
        self.serverinfo = {}
        self.userinfo = {}
        self.on_open = None
        self.on_close = None         # fn(reason_dict_or_None)
        self._close_reason = None
        self._cookie_waiters = []

    # ---- lifecycle -------------------------------------------------------
    def connect(self):
        auth = _b64(self.username) + "," + _b64(self.password)
        if self.token:
            auth += "," + _b64(self.token)
        self.ws = websocket.WebSocketApp(
            self.server.ws("control.ashx"),
            header=[f"x-meshauth: {auth}", f"User-Agent: {USER_AGENT}"],
            on_open=self._on_open, on_message=self._on_message,
            on_close=self._on_close, on_error=self._on_error)
        t = threading.Thread(target=self.ws.run_forever,
                             kwargs={"ping_interval": 30, "ping_timeout": 10,
                                     "sslopt": {"cert_reqs": ssl.CERT_REQUIRED}},
                             daemon=True)
        t.start()

    def close(self):
        self.on_close = None
        try:
            self.ws.close()
        except Exception:
            pass

    def _on_open(self, _ws):
        self.connected = True
        _ui(self.on_open)

    def _on_error(self, _ws, err):
        if self._close_reason is None:
            self._close_reason = {"cause": "error", "msg": str(err)}

    def _on_close(self, _ws, *_):
        self.connected = False
        _ui(self.on_close, self._close_reason)

    def _on_message(self, _ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        _ui(self._dispatch, msg)

    def _dispatch(self, msg):
        action = msg.get("action")
        if action == "close":
            self._close_reason = msg
            return
        if action == "serverinfo":
            self.serverinfo = msg.get("serverinfo", {})
        elif action == "userinfo":
            self.userinfo = msg.get("userinfo", {})
        elif action == "authcookie":
            waiters, self._cookie_waiters = self._cookie_waiters, []
            for w in waiters:
                w(msg.get("cookie"), msg.get("rcookie"))
        rid = msg.get("responseid")
        if rid and rid in self.pending:
            cb = self.pending.pop(rid)
            cb(msg)
        for cb in list(self.listeners.get(action, [])):
            cb(msg)
        for cb in list(self.any_listeners):
            cb(msg)

    # ---- API ---------------------------------------------------------------
    def send(self, obj, callback=None):
        if callback is not None:
            rid = "mcd" + secrets.token_hex(6)
            obj["responseid"] = rid
            self.pending[rid] = callback
        try:
            self.ws.send(json.dumps(obj))
        except Exception:
            pass

    def on(self, action, cb):
        self.listeners.setdefault(action, []).append(cb)

    def off(self, action, cb):
        try:
            self.listeners.get(action, []).remove(cb)
        except ValueError:
            pass

    def get_auth_cookie(self, cb):
        self._cookie_waiters.append(cb)
        self.send({"action": "authcookie"})

    def send_node_msg(self, nodeid, mtype, **kw):
        m = {"action": "msg", "type": mtype, "nodeid": nodeid}
        m.update(kw)
        self.send(m)


class Tunnel:
    """A relay session to one agent (terminal, desktop or files).

    Callbacks (all on GTK thread unless noted):
      on_state(state)        0 = closed, 1 = connecting, 2 = waiting for agent, 3 = connected
      on_binary(bytes)       raw binary frames   (called on the NETWORK thread if binary_in_thread)
      on_text(str)           non-control text frames
      on_console(str)        agent/server console messages (consent prompts, errors...)
    """

    def __init__(self, ctrl, nodeid, protocol, options=None, binary_in_thread=False):
        self.ctrl = ctrl
        self.nodeid = nodeid
        self.protocol = protocol
        self.options = options
        self.binary_in_thread = binary_in_thread
        self.state = 0
        self.ws = None
        self.recording = False
        self.on_state = self.on_binary = self.on_text = self.on_console = None
        self._lock = threading.Lock()

    def start(self):
        self._set_state(1)
        self.ctrl.get_auth_cookie(self._got_cookie)

    def _got_cookie(self, cookie, rcookie):
        tid = secrets.token_hex(6)
        srv = self.ctrl.server
        url = (srv.ws("meshrelay.ashx") + f"?browser=1&p={self.protocol}&nodeid={quote(self.nodeid, safe='')}"
               f"&id={tid}&auth={quote(cookie or '', safe='')}")
        self.ws = websocket.WebSocketApp(url, header=[f"User-Agent: {USER_AGENT}"],
                                         on_open=self._on_open, on_message=self._on_message,
                                         on_close=self._on_close, on_error=lambda *_: None)
        threading.Thread(target=self.ws.run_forever, kwargs={"ping_interval": 30, "ping_timeout": 10},
                         daemon=True).start()
        rurl = f"*{srv.path}/meshrelay.ashx?p={self.protocol}&nodeid={self.nodeid}&id={tid}"
        if rcookie:
            rurl += f"&rauth={rcookie}"
        self.ctrl.send({"action": "msg", "type": "tunnel", "nodeid": self.nodeid, "value": rurl,
                        "usage": self.protocol})

    def _set_state(self, s):
        if s == self.state:
            return
        self.state = s
        _ui(self.on_state, s)

    def _on_open(self, _ws):
        self._set_state(2)

    def _on_close(self, *_):
        self._set_state(0)

    def _on_message(self, _ws, data):
        if self.state < 3 and isinstance(data, str) and data in ("c", "cr"):
            self.recording = data == "cr"
            if self.options is not None:
                o = dict(self.options)
                o["type"] = "options"
                self.send_raw_text(json.dumps(o))
            self.send_raw_text(str(self.protocol))
            self._set_state(3)
            return
        if isinstance(data, str):
            if data.startswith("{"):
                try:
                    j = json.loads(data)
                except Exception:
                    j = None
                if isinstance(j, dict) and str(j.get("ctrlChannel")) == CTRL:
                    self._control(j)
                    return
            _ui(self.on_text, data)
        else:
            if self.binary_in_thread:
                if self.on_binary:
                    self.on_binary(data)
            else:
                _ui(self.on_binary, data)

    def _control(self, j):
        t = j.get("type")
        if t == "ping":
            self.send_raw_text(json.dumps({"ctrlChannel": CTRL, "type": "pong"}))
        elif t == "console":
            _ui(self.on_console, j.get("msg") or "")

    # ---- sending -------------------------------------------------------------
    def send_raw_text(self, s):
        try:
            with self._lock:
                self.ws.send(s)
        except Exception:
            pass

    def send(self, data):
        """Send binary data (bytes) or text (str -> utf-8 bytes, as the web client does)."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            with self._lock:
                self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
        except Exception:
            pass

    def send_json(self, obj):
        self.send(json.dumps(obj))

    def send_ctrl(self, obj):
        o = {"ctrlChannel": CTRL}
        o.update(obj)
        self.send_raw_text(json.dumps(o))

    def stop(self):
        if self.ws is not None:
            if self.state >= 2:
                self.send_ctrl({"type": "close"})
            try:
                self.ws.close()
            except Exception:
                pass
        self._set_state(0)


# ---- HTTP session for server-side file storage ("My Files") -------------------------
# downloadfile.ashx only accepts a WEB session (req.session.userid), not x-meshauth, so we
# sign in once exactly like the browser (POST /login, action=login) into a PRIVATE,
# in-memory cookie jar. uploadfile.ashx additionally accepts the control-channel login
# cookie in the form field "auth". All transfers run on background threads; callbacks are
# marshalled to the GTK loop.
import http.cookiejar
import os
import urllib.error
import urllib.parse
import urllib.request


def http_ssl_context():
    """TLS context for HTTP transfers (tests against a self-signed local rig override this)."""
    return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class WebSession:
    CHUNK = 256 * 1024

    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.jar = http.cookiejar.CookieJar()
        self._logged_in = False
        self._lock = threading.Lock()

    def _opener(self, follow=True):
        handlers = [urllib.request.HTTPCookieProcessor(self.jar),
                    urllib.request.HTTPSHandler(context=http_ssl_context())]
        if not follow:
            handlers.append(_NoRedirect())
        return urllib.request.build_opener(*handlers)

    def _login(self):
        with self._lock:
            if self._logged_in:
                return
            form = {"action": "login", "username": self.ctrl.username, "password": self.ctrl.password or ""}
            if self.ctrl.token:
                form["token"] = self.ctrl.token
            req = urllib.request.Request(self.ctrl.server.url + "/login",
                                         data=urllib.parse.urlencode(form).encode(),
                                         headers={"User-Agent": USER_AGENT})
            try:
                self._opener(follow=False).open(req, timeout=30).read()
            except urllib.error.HTTPError as ex:
                if ex.code not in (301, 302, 303):          # a redirect is the normal answer
                    raise
            if not any(c.name.startswith("xid") for c in self.jar):
                raise RuntimeError("the server did not accept the web sign-in "
                                   "(two-factor accounts need the web UI for large downloads)")
            self._logged_in = True

    def download(self, link, dest, on_progress=None, on_done=None):
        """link: 'user//name/folder/file' (server path). Streams to dest."""
        self.fetch("/downloadfile.ashx?link=" + urllib.parse.quote(link, safe=""), dest, on_progress, on_done)

    def fetch(self, path, dest, on_progress=None, on_done=None, timeout=60):
        """GET <server><path> with the web session and stream it to dest (e.g. /backup.zip)."""
        def run():
            try:
                self._login()
                url = self.ctrl.server.url + path
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self._opener().open(req, timeout=timeout) as r, open(dest, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    while True:
                        b = r.read(self.CHUNK)
                        if not b:
                            break
                        f.write(b)
                        got += len(b)
                        _ui(on_progress, got, total)
                _ui(on_done, None)
            except Exception as ex:
                self._logged_in = False
                try:
                    os.remove(dest)
                except OSError:
                    pass
                _ui(on_done, str(ex))
        threading.Thread(target=run, daemon=True).start()

    def upload(self, link, path, on_progress=None, on_done=None):
        """Upload local file `path` into server folder `link` (e.g. 'user//name/Public')."""
        self.post_file("/uploadfile.ashx", {"link": urllib.parse.quote(link, safe="")}, "files",
                       path, on_progress, on_done)

    def post_file(self, url_path, fields, file_field, path, on_progress=None, on_done=None, timeout=300):
        """Multipart POST of one local file plus form fields (the control-channel auth cookie is
        added as field "auth"). Used by uploadfile.ashx and restoreserver.ashx."""
        def run(cookie):
            try:
                try:
                    self._login()
                except Exception:
                    pass                                     # the "auth" cookie field may suffice
                boundary = "----mcd" + secrets.token_hex(12)
                name = os.path.basename(path)

                def field(k, v):
                    return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
                head = b"".join(field(k, v) for k, v in fields.items()) + field("auth", cookie or "") + (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
                    f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
                tail = f"\r\n--{boundary}--\r\n".encode()
                size = os.path.getsize(path)

                def body():
                    yield head
                    sent = 0
                    with open(path, "rb") as f:
                        while True:
                            b = f.read(self.CHUNK)
                            if not b:
                                break
                            sent += len(b)
                            _ui(on_progress, sent, size)
                            yield b
                    yield tail
                req = urllib.request.Request(
                    self.ctrl.server.url + url_path, data=body(), method="POST",
                    headers={"User-Agent": USER_AGENT, "Content-Length": str(len(head) + size + len(tail)),
                             "Content-Type": f"multipart/form-data; boundary={boundary}"})
                self._opener().open(req, timeout=timeout).read()
                _ui(on_done, None)
            except Exception as ex:
                _ui(on_done, str(ex))
        # a fresh control-channel login cookie for the "auth" field
        self.ctrl.get_auth_cookie(lambda cookie, _r: threading.Thread(target=run, args=(cookie,), daemon=True).start())
