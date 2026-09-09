"""Method, path, identity, and body constrained Technocore pilot egress proxy."""

from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlsplit

import httpx

from rosetta.observer import WATCHED_PATHS
from rosetta.technocore_client import validate_room_name
from rosetta_signer.canonical import signed_note_payload, signed_room_payload
from rosetta_signer.did import verify_signature

_DID = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}$")
_SIG = re.compile(r"^[A-Za-z0-9_-]{85}[AQgw]$")


class PilotEgress:
    def __init__(
        self,
        origin: str,
        writer_did: str,
        service_room: str,
        request_mailbox: str,
        discovery_rooms: list[str],
        timeout_seconds: int,
        max_response_bytes: int,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("pilot egress requires one fixed HTTPS origin")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("invalid pilot egress origin")
        if not _DID.fullmatch(writer_did):
            raise ValueError("invalid writer DID")
        self.writer_did = writer_did
        self.service_room = validate_room_name(service_room)
        self.request_mailbox = validate_room_name(request_mailbox)
        self.read_rooms = {self.request_mailbox, *map(validate_room_name, discovery_rooms)}
        self.client = httpx.Client(
            base_url=origin.rstrip("/"),
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"User-Agent": "technocore-rosetta-egress/0.2"},
        )
        self.max_response_bytes = max_response_bytes

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _room_path(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "r":
            try:
                return validate_room_name(parts[2])
            except ValueError:
                return None
        return None

    def _read_allowed(self, path: str, query: str) -> bool:
        if path in WATCHED_PATHS:
            return not query
        if path in {
            f"/kv/room-owners/{self.service_room}",
            f"/kv/room-allow/{self.service_room}",
        }:
            return not query
        room = self._room_path(path)
        if room is None or (room not in self.read_rooms and not room.startswith("mb-")):
            return False
        try:
            fields = parse_qs(query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            return False
        if set(fields) - {"format", "since", "limit", "wait"}:
            return False
        if fields.get("format") != ["json"]:
            return False
        numeric = {"since": (0, 2**63 - 1), "limit": (1, 200), "wait": (0, 10)}
        for name, (low, high) in numeric.items():
            if name not in fields:
                continue
            if len(fields[name]) != 1 or not fields[name][0].isdigit():
                return False
            if not low <= int(fields[name][0]) <= high:
                return False
        return True

    def _write_allowed(self, path: str, query: str, body: bytes) -> bool:
        if parse_qs(query, keep_blank_values=True) != {"format": ["json"]}:
            return False
        room = self._room_path(path)
        note_namespace = next(
            (
                namespace
                for namespace in ("room-owners", "room-allow")
                if path == f"/kv/{namespace}/{self.service_room}"
            ),
            None,
        )
        is_note = note_namespace is not None
        if room is None and not is_note:
            return False
        if room is not None and room != self.service_room and not room.startswith("mb-"):
            return False
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("did") != self.writer_did:
            return False
        required = {"did", "sig", "nonce", "value" if is_note else "text"}
        optional = {"if_absent"} if note_namespace == "room-owners" else set()
        if not required <= set(payload) or set(payload) - required - optional:
            return False
        signature = payload.get("sig")
        if not isinstance(signature, str) or not _SIG.fullmatch(signature):
            return False
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not nonce.isdigit() or not 1 <= len(nonce) <= 19:
            return False
        content = payload.get("value" if is_note else "text")
        cap = 8192 if is_note else 4096
        if not isinstance(content, str) or not content or len(content) > cap:
            return False
        if is_note and content != self.writer_did:
            return False
        if payload.get("if_absent") not in (
            {None, True} if note_namespace == "room-owners" else {None}
        ):
            return False
        nonce_value = int(nonce)
        signed_payload = (
            signed_note_payload(str(note_namespace), self.service_room, nonce_value, content)
            if is_note
            else signed_room_payload(str(room), nonce_value, content)
        )
        if not verify_signature(self.writer_did, signed_payload, signature):
            return False
        return True

    def forward(
        self, method: str, target: str, body: bytes = b""
    ) -> tuple[int, str, bytes, str | None]:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            return HTTPStatus.BAD_REQUEST, "text/plain", b"invalid request target\n", None
        allowed = (
            self._read_allowed(parsed.path, parsed.query)
            if method == "GET"
            else method == "POST" and self._write_allowed(parsed.path, parsed.query, body)
        )
        if not allowed:
            return HTTPStatus.FORBIDDEN, "text/plain", b"egress policy rejected request\n", None
        try:
            with self.client.stream(
                method,
                parsed.path + (("?" + parsed.query) if parsed.query else ""),
                content=body if method == "POST" else None,
                headers={"Content-Type": "application/json"} if method == "POST" else None,
            ) as response:
                if response.is_redirect:
                    return HTTPStatus.BAD_GATEWAY, "text/plain", b"redirect rejected\n", None
                output = bytearray()
                for chunk in response.iter_bytes():
                    output.extend(chunk)
                    if len(output) > self.max_response_bytes:
                        return (
                            HTTPStatus.BAD_GATEWAY,
                            "text/plain",
                            b"upstream response too large\n",
                            None,
                        )
                content_type = response.headers.get("content-type", "application/octet-stream")
                return (
                    response.status_code,
                    content_type,
                    bytes(output),
                    response.headers.get("retry-after"),
                )
        except httpx.HTTPError:
            return HTTPStatus.BAD_GATEWAY, "text/plain", b"upstream unavailable\n", None


def handler_for(gateway: PilotEgress) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._forward(b"")

        def do_POST(self) -> None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None or not raw_length.isdigit():
                self._respond(HTTPStatus.LENGTH_REQUIRED, "text/plain", b"length required\n")
                return
            length = int(raw_length)
            if length > 20_000:
                self._respond(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "text/plain",
                    b"body too large\n",
                )
                return
            self._forward(self.rfile.read(length))

        def _forward(self, body: bytes) -> None:
            status, content_type, output, retry_after = gateway.forward(
                self.command, self.path, body
            )
            self._respond(status, content_type, output, retry_after)

        def _respond(
            self,
            status: int,
            content_type: str,
            body: bytes,
            retry_after: str | None = None,
        ) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if retry_after is not None:
                self.send_header("Retry-After", retry_after)
            self.end_headers()
            self.wfile.write(body)

        def _reject_method(self) -> None:
            self._respond(HTTPStatus.METHOD_NOT_ALLOWED, "text/plain", b"method not allowed\n")

        do_PUT = _reject_method
        do_PATCH = _reject_method
        do_DELETE = _reject_method
        do_HEAD = _reject_method
        do_OPTIONS = _reject_method
        do_CONNECT = _reject_method
        do_TRACE = _reject_method

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(prog="rosetta-pilot-egress")
    parser.add_argument("--origin", default="https://technocore.chat")
    parser.add_argument("--writer-did", required=True)
    parser.add_argument("--service-room", required=True)
    parser.add_argument("--request-mailbox", required=True)
    parser.add_argument("--discovery-room", action="append", default=[])
    parser.add_argument("--listen", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--max-response-bytes", type=int, default=1_048_576)
    args = parser.parse_args()
    gateway = PilotEgress(
        args.origin,
        args.writer_did,
        args.service_room,
        args.request_mailbox,
        args.discovery_room,
        args.timeout_seconds,
        args.max_response_bytes,
    )
    server = ThreadingHTTPServer((args.listen, args.port), handler_for(gateway))
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        gateway.close()


if __name__ == "__main__":
    main()
