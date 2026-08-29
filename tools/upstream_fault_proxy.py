"""Local-only deterministic fault proxy for the pinned upstream acceptance matrix."""

from __future__ import annotations

import http.client
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

UPSTREAM = urlsplit(os.environ.get("ROSETTA_UPSTREAM_ORIGIN", "http://technocore-upstream:8080"))
RATE_ACTOR = os.environ.get("ROSETTA_RATE_LIMIT_ACTOR", "")
UNCERTAIN_ACTOR = os.environ.get("ROSETTA_UNCERTAIN_ACTOR", "")
_consumed: set[tuple[str, str]] = set()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        actor = self.headers.get("X-Rosetta-Actor", "")
        if actor == RATE_ACTOR and (actor, "rate") not in _consumed:
            _consumed.add((actor, "rate"))
            body = b"429 deterministic Rosetta fault: retry after 1s\n"
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Retry-After", "1")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        uncertain = actor == UNCERTAIN_ACTOR and (actor, "uncertain") not in _consumed
        if uncertain:
            _consumed.add((actor, "uncertain"))
        self._forward(drop_response=uncertain)

    def _forward(self, *, drop_response: bool = False) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        connection = http.client.HTTPConnection(UPSTREAM.hostname, UPSTREAM.port or 80, timeout=5)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }
        if body is not None:
            headers["Content-Length"] = str(len(body))
        connection.request(self.command, self.path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        if drop_response:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in {
                "connection",
                "transfer-encoding",
                "content-length",
                "server",
                "date",
            }:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main()
