"""Narrow network boundary for the read-only staging observer."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, urlsplit

import httpx

from rosetta.observer import WATCHED_PATHS


class ReadOnlyEgress:
    def __init__(
        self,
        origin: str,
        timeout_seconds: int,
        max_response_bytes: int,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("egress origin must be a fixed HTTPS origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("egress origin must not contain a path, query, or fragment")
        self.client = httpx.Client(
            base_url=origin.rstrip("/"),
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={
                "Accept": "application/json, text/plain;q=0.9",
                "User-Agent": "rosetta-egress/0.1",
            },
        )
        self.max_response_bytes = max_response_bytes

    def fetch(self, path: str) -> tuple[int, str, bytes]:
        if path not in WATCHED_PATHS:
            return HTTPStatus.NOT_FOUND, "text/plain", b"path not allowed\n"
        try:
            with self.client.stream("GET", path) as response:
                if response.is_redirect:
                    return HTTPStatus.BAD_GATEWAY, "text/plain", b"upstream redirect rejected\n"
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        return (
                            HTTPStatus.BAD_GATEWAY,
                            "text/plain",
                            b"upstream response too large\n",
                        )
                content_type = response.headers.get("content-type", "application/octet-stream")
                return response.status_code, content_type, bytes(body)
        except httpx.HTTPError:
            return HTTPStatus.BAD_GATEWAY, "text/plain", b"upstream unavailable\n"

    def close(self) -> None:
        self.client.close()


def handler_for(gateway: ReadOnlyEgress) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                self._respond(HTTPStatus.BAD_REQUEST, "text/plain", b"invalid request target\n")
                return
            status, content_type, body = gateway.fetch(parsed.path)
            self._respond(status, content_type, body)

        def _method_not_allowed(self) -> None:
            self._respond(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "text/plain",
                b"only allowlisted GET requests are accepted\n",
                allow="GET",
            )

        do_POST = _method_not_allowed
        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_HEAD = _method_not_allowed
        do_OPTIONS = _method_not_allowed
        do_CONNECT = _method_not_allowed
        do_TRACE = _method_not_allowed

        def _respond(
            self,
            status: int,
            content_type: str,
            body: bytes,
            *,
            allow: str | None = None,
        ) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if allow is not None:
                self.send_header("Allow", allow)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(prog="rosetta-egress")
    parser.add_argument("--origin", default="https://technocore.chat")
    # The port is reachable only on Compose's internal, unpublished network.
    parser.add_argument("--listen", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--max-response-bytes", type=int, default=1_048_576)
    args = parser.parse_args()
    gateway = ReadOnlyEgress(args.origin, args.timeout_seconds, args.max_response_bytes)
    server = ThreadingHTTPServer((args.listen, args.port), handler_for(gateway))
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        gateway.close()


if __name__ == "__main__":
    main()
