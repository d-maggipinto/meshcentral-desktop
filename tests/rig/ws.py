import base64, json, ssl, sys, time, websocket
def b(s): return base64.b64encode(s.encode()).decode()
def conn():
    ws = websocket.create_connection("wss://127.0.0.1:8443/control.ashx",
        header=[f"x-meshauth: {b('admin')},{b('Test-1234')}"], sslopt={"cert_reqs": ssl.CERT_NONE})
    ws.settimeout(1)
    return ws
def drain(ws, secs, want=None):
    out=[]; end=time.time()+secs
    while time.time()<end:
        try: m=json.loads(ws.recv())
        except Exception: continue
        out.append(m)
        if want and want(m): break
    return out
