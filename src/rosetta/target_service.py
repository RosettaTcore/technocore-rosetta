"""Containerized local-only Technocore v0.7.0 behavioral fixture service."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from rosetta.local_protocol import LocalTechnocore, RateLimited, UncertainWrite

TARGET = LocalTechnocore()


def _record(record: Any) -> dict[str, Any]:
    return {
        "sequence": record.sequence,
        "room": record.room,
        "did": record.did,
        "nonce": record.nonce,
        "text": record.text,
        "signature": record.signature,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "RosettaTarget/0.7.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(
        self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None
    ) -> None:
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 16_384:
            raise ValueError("invalid body length")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"release": "v0.7.0", "status": "ok"})
            return
        if parsed.path == "/capabilities":
            self._send(200, TARGET.capabilities())
            return
        if parsed.path.startswith("/rooms/"):
            room = unquote(parsed.path.removeprefix("/rooms/"))
            query = parse_qs(parsed.query)
            since = int(query.get("since", ["0"])[0])
            limit = int(query.get("limit", ["100"])[0])
            records = [_record(item) for item in TARGET.read_room(room, since=since, limit=limit)]
            self._send(200, {"records": records})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            body = self._json()
            if self.path == "/_fixture/rooms" and set(body) == {"room"}:
                TARGET.create_room(str(body["room"]))
                self._send(201, {"created": True})
                return
            if self.path in {"/_fixture/rate-limit", "/_fixture/uncertain-write"} and set(body) == {
                "actor",
                "room",
            }:
                if self.path.endswith("rate-limit"):
                    TARGET.inject_rate_limit_once(str(body["actor"]), str(body["room"]))
                else:
                    TARGET.inject_uncertain_write_once(str(body["actor"]), str(body["room"]))
                self._send(204, {})
                return
            if self.path.startswith("/rooms/") and self.path.endswith("/signed"):
                room = unquote(self.path.removeprefix("/rooms/").removesuffix("/signed"))
                if set(body) != {"actor", "did", "nonce", "text", "signature"}:
                    raise ValueError("unknown signed-write fields")
                try:
                    record = TARGET.post_signed(
                        str(body["actor"]),
                        room,
                        str(body["did"]),
                        int(body["nonce"]),
                        str(body["text"]),
                        str(body["signature"]),
                    )
                except RateLimited as exc:
                    self._send(
                        429,
                        {"error": "rate_limited"},
                        {"Retry-After": str(exc.retry_after_seconds)},
                    )
                    return
                except UncertainWrite:
                    self._send(599, {"error": "uncertain_write", "committed": True})
                    return
                self._send(201, _record(record))
                return
            self._send(404, {"error": "not_found"})
        except (TypeError, ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid_request"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
