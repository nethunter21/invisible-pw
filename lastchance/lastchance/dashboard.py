"""Local-only setup dashboard for building an emergency kit.

Runs a tiny web server bound to 127.0.0.1 with a random one-time token in the
URL. Nothing is exposed to the network and nothing leaves the machine. You add
each wallet (chain + destination + optional key), preview/validate addresses
offline, then build the sealed `model9x` kit.
"""

from __future__ import annotations

import json
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import kit, prompts, ui
from .chains import make_sweeper

TOKEN = secrets.token_urlsafe(18)
HERE = os.path.dirname(os.path.abspath(__file__))


def _html() -> bytes:
    with open(os.path.join(HERE, "web", "dashboard.html"), "rb") as fh:
        return fh.read()


def preview(entry: dict) -> dict:
    """Offline: derive source addresses + validate the destination."""
    try:
        s = make_sweeper({**entry, "name": entry.get("name", entry.get("chain", "?"))}, {}, lambda *a, **k: None)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    out = {"ok": True, "addresses": [], "dest_ok": True, "dest_error": ""}
    try:
        out["addresses"] = s.addresses()[:12]
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"key problem: {exc}"
    try:
        s.validate_destination()
    except Exception as exc:
        out["dest_ok"] = False
        out["dest_error"] = str(exc)
    return out


def build(payload: dict) -> dict:
    config = {"settings": payload.get("settings", {}), "wallets": payload["wallets"]}
    # structural validation, with throwaway keys for ask-mode entries
    from .cli import validate
    problems = validate(prompts.probe(config) if any(w.get("ask") for w in config["wallets"]) else config)
    if problems:
        return {"ok": False, "problems": problems}
    out_dir = payload.get("out_dir") or os.path.join(os.getcwd(), "lastchance-kit")
    info = kit.build_kit(config, payload["passphrase"], out_dir, make_zip=True)
    return {"ok": True, **info}


class Handler(BaseHTTPRequestHandler):
    def _auth(self) -> bool:
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        return (q.get("t", [None])[0] == TOKEN) or (self.headers.get("X-Token") == TOKEN)

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth():
            return self._send(403, b"forbidden")
        if self.path.split("?")[0] in ("/", "/index.html"):
            return self._send(200, _html(), "text/html; charset=utf-8")
        self._send(404, b"not found")

    def do_POST(self):
        if not self._auth():
            return self._send(403, b'{"ok":false,"error":"bad token"}')
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send(400, b'{"ok":false,"error":"bad json"}')
        route = self.path.split("?")[0]
        try:
            if route == "/api/preview":
                return self._send(200, json.dumps(preview(payload)).encode())
            if route == "/api/build":
                return self._send(200, json.dumps(build(payload)).encode())
        except Exception as exc:
            return self._send(200, json.dumps({"ok": False, "error": str(exc)}).encode())
        self._send(404, b'{"ok":false,"error":"no route"}')

    def log_message(self, *a):  # keep the console clean
        pass


def serve(open_browser: bool = True, port: int = 8787) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"
    ui.banner("fire")
    ui.say("  SETUP DASHBOARD - build your emergency kit", "ok")
    ui.say("  open this in your browser (local only, not on the network):\n")
    ui.say(f"    {url}\n", "ok")
    ui.say("  press Ctrl+C here when you're done.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        ui.say("\n  dashboard closed", "warn")
        httpd.shutdown()
