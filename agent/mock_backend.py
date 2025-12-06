#!/usr/bin/env python3
"""
Minimal mock backend for local/dry-run agent testing.

Emulates the Wiretide controller routes that the agent calls:
- POST /register
- POST /status
- GET  /config
- GET  /token/current

Usage:
  python3 agent/mock_backend.py --port 9000 --shared-token drytoken

This keeps all state in-memory and serves one config package (wifi) once,
then returns 404 for config.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional


def canonical_sha(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


class MockState:
    def __init__(self, shared_token: str):
        self.shared_token = shared_token
        self.device_id = 1
        # Single config delivery for demo.
        pkg = {
            "package": "wiretide.ssid",
            "package_json": {
                "ssid": "DryRunNet",
                "password": "wiretide123",
                "band": "5g",
                "channel": 36,
                "htmode": "VHT80",
            },
        }
        pkg["sha256"] = canonical_sha(pkg["package_json"])
        self.config_queue: List[Dict] = [pkg]


class Handler(BaseHTTPRequestHandler):
    state: MockState

    def _json_response(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Silence default HTTP server logging to keep harness clean.
        return

    def _require_token(self) -> bool:
        token = self.headers.get("X-Shared-Token")
        if not token:
            self._json_response(HTTPStatus.UNAUTHORIZED, {"detail": "Missing shared token"})
            return False
        if token != self.state.shared_token:
            self._json_response(HTTPStatus.FORBIDDEN, {"detail": "Invalid shared token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/config"):
            if not self._require_token():
                return
            if not self.state.config_queue:
                self._json_response(HTTPStatus.NOT_FOUND, {"detail": "No pending config"})
                return
            pkg = self.state.config_queue.pop()
            payload = {
                "device_id": self.state.device_id,
                "package": pkg["package"],
                "package_json": pkg["package_json"],
                "sha256": pkg["sha256"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._json_response(HTTPStatus.OK, payload)
            return

        if self.path == "/token/current":
            self._json_response(HTTPStatus.OK, {"shared_token": self.state.shared_token})
            return

        self._json_response(HTTPStatus.NOT_FOUND, {"detail": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else "{}"
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/register":
            if not self._require_token():
                return
            device_type = payload.get("device_type") or "unknown"
            resp = {
                "device_id": self.state.device_id,
                "status": "approved",
                "approved": True,
                "device_type": device_type,
                "shared_token_required": True,
            }
            self._json_response(HTTPStatus.OK, resp)
            return

        if self.path == "/status":
            if not self._require_token():
                return
            resp = {"status": "ok", "last_seen": datetime.now(timezone.utc).isoformat()}
            self._json_response(HTTPStatus.OK, resp)
            return

        self._json_response(HTTPStatus.NOT_FOUND, {"detail": "Not found"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Wiretide backend for agent dry-run.")
    parser.add_argument("--port", type=int, default=9000, help="Port to listen on")
    parser.add_argument("--shared-token", type=str, default="drytoken", help="Shared token expected from agent")
    args = parser.parse_args()

    state = MockState(args.shared_token)
    Handler.state = state  # type: ignore[attr-defined]
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[mock-backend] listening on http://127.0.0.1:{args.port} token={args.shared_token}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[mock-backend] shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
