"""Strict production client for the pinned Technocore HTTP protocol.

The client accepts no caller-provided URL. Every request target is constructed from a
validated room or ownership key and sent to one fixed fetch origin. When a local egress
proxy is used, ``authority_origin`` remains the public TLS authority whose metadata is
validated by the observer/canary before the pilot is activated.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from rosetta.local_protocol import ProtocolRecord, RateLimited, UncertainWrite
from rosetta.observer import ReadOnlyProbeClient
from rosetta_signer.canonical import signed_note_payload, signed_room_payload
from rosetta_signer.did import verify_signature

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_DID = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}$")
_SIG = re.compile(r"^[A-Za-z0-9_-]{85}[AQgw]$")


class TechnocoreRefusal(RuntimeError):
    """A definite, non-retryable upstream refusal."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(f"technocore_refused:{status_code}:{reason}")
        self.status_code = status_code
        self.reason = reason


def validate_room_name(room: str) -> str:
    if not _NAME.fullmatch(room):
        raise ValueError("invalid Technocore room name")
    return room


def _origin(value: str, *, https_required: bool) -> str:
    parsed = urlparse(value)
    allowed = {"https"} if https_required else {"http", "https"}
    if parsed.scheme not in allowed or not parsed.netloc:
        raise ValueError("invalid fixed origin")
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError("origin must not contain credentials or a path")
    if parsed.query or parsed.fragment:
        raise ValueError("origin must not contain a query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "technocore-egress",
    }:
        raise ValueError("plain HTTP is limited to the local egress boundary")
    return value.rstrip("/")


class TechnocoreHttpClient:
    release = "v0.13.0"
    image_digest = "sha256:" + "0" * 64

    def __init__(
        self,
        fetch_origin: str,
        authority_origin: str,
        pinned_release: str,
        *,
        timeout_seconds: int = 20,
        max_response_bytes: int = 1_048_576,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.fetch_origin = _origin(fetch_origin, https_required=False)
        self.authority_origin = _origin(authority_origin, https_required=True)
        if pinned_release != "v0.13.0":
            raise ValueError("production pilot requires reviewed Technocore v0.13.0")
        if not 1_024 <= max_response_bytes <= 4_194_304:
            raise ValueError("invalid response byte limit")
        self.release = pinned_release
        self.max_response_bytes = max_response_bytes
        self._transport = transport
        self._room_generations: dict[str, int] = {}
        self.client = httpx.Client(
            base_url=self.fetch_origin,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "technocore-rosetta-pilot/0.2",
            },
        )

    def close(self) -> None:
        self.client.close()

    def inject_rate_limit_once(self, actor: str, room: str) -> None:
        del actor, room

    def inject_uncertain_write_once(self, actor: str, room: str) -> None:
        del actor, room

    def create_room(self, room: str) -> None:
        # Technocore creates a room atomically on its first accepted message.
        validate_room_name(room)

    def capabilities(self) -> dict[str, object]:
        probe = ReadOnlyProbeClient(
            self.fetch_origin,
            self.authority_origin,
            self.release,
            timeout_seconds=int(self.client.timeout.read or 20),
            max_response_bytes=self.max_response_bytes,
            transport=self._transport,
        )
        try:
            observation = probe.probe()
        finally:
            probe.close()
        if observation.compatibility_status != "compatible":
            raise RuntimeError("technocore_release_drift")
        return {
            "release": self.release,
            "operations": ["read_room", "post_signed", "wait_room", "rooms", "events"],
            "max_message_chars": 4096,
            "authority": self.authority_origin,
            "protocol_digest": observation.protocol_digest,
        }

    def _bounded(self, response: httpx.Response) -> bytes:
        if response.is_redirect:
            raise TechnocoreRefusal(response.status_code, "redirect_rejected")
        body = response.content
        if len(body) > self.max_response_bytes:
            raise TechnocoreRefusal(502, "response_too_large")
        return body

    @staticmethod
    def _rate_limited(response: httpx.Response) -> None:
        if response.status_code != 429:
            return
        raw = response.headers.get("retry-after", "1")
        try:
            wait = int(raw)
        except ValueError:
            wait = 3
        raise RateLimited(max(1, min(wait, 60)))

    def _json(self, response: httpx.Response, expected_status: int = 200) -> dict[str, Any]:
        self._rate_limited(response)
        body = self._bounded(response)
        if response.status_code != expected_status:
            raise TechnocoreRefusal(response.status_code, "upstream_refusal")
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise TechnocoreRefusal(502, "unexpected_content_type")
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TechnocoreRefusal(502, "invalid_json") from exc
        if not isinstance(value, dict):
            raise TechnocoreRefusal(502, "invalid_json_shape")
        return value

    def read_room(self, room: str, *, since: int = 0, limit: int = 100) -> list[ProtocolRecord]:
        validate_room_name(room)
        if since < 0 or limit < 1 or limit > 200:
            raise ValueError("invalid bounded room cursor")
        try:
            response = self.client.get(
                f"/r/{room}", params={"format": "json", "since": since, "limit": limit}
            )
        except httpx.RequestError:
            raise
        view = self._json(response)
        generation = view.get("generation")
        last_seq = view.get("last_seq")
        if (
            view.get("room") != room
            or not isinstance(view.get("messages"), list)
            or not isinstance(generation, int)
            or generation < 0
            or not isinstance(last_seq, int)
            or last_seq < since
        ):
            raise TechnocoreRefusal(502, "invalid_room_view")
        self._room_generations[room] = generation
        records: list[ProtocolRecord] = []
        previous = since
        for item in view["messages"]:
            if not isinstance(item, dict):
                raise TechnocoreRefusal(502, "invalid_room_record")
            sequence = item.get("seq")
            sender = item.get("from")
            text = item.get("text")
            nonce = item.get("nonce", 0)
            signature = item.get("sig", "")
            if (
                not isinstance(sequence, int)
                or sequence <= previous
                or not isinstance(sender, str)
                or not isinstance(text, str)
                or not isinstance(nonce, int)
                or len(text) > 4096
            ):
                raise TechnocoreRefusal(502, "invalid_room_record")
            previous = sequence
            if signature:
                if (
                    not isinstance(signature, str)
                    or not _SIG.fullmatch(signature)
                    or not _DID.fullmatch(sender)
                    or nonce < 1
                    or not verify_signature(
                        sender, signed_room_payload(room, nonce, text), signature
                    )
                ):
                    raise TechnocoreRefusal(502, "invalid_record_signature")
            elif not isinstance(signature, str):
                raise TechnocoreRefusal(502, "invalid_room_record")
            records.append(ProtocolRecord(sequence, room, sender, nonce, text, signature))
        return records

    def room_generation(self, room: str) -> int | None:
        """Return the generation from the most recent validated read of ``room``."""
        return self._room_generations.get(validate_room_name(room))

    def reconcile(self, room: str, did: str, nonce: int, text: str) -> ProtocolRecord | None:
        matches = [
            record
            for record in self.read_room(room, since=0, limit=200)
            if record.did == did and record.nonce == nonce and record.text == text
        ]
        if len(matches) > 1:
            raise RuntimeError("duplicate_remote_delivery")
        return matches[0] if matches else None

    def post_signed(
        self,
        actor: str,
        room: str,
        did: str,
        nonce: int,
        text: str,
        signature: str,
    ) -> ProtocolRecord:
        del actor
        validate_room_name(room)
        if (
            not _DID.fullmatch(did)
            or nonce < 1
            or len(text) > 4096
            or not isinstance(signature, str)
            or not _SIG.fullmatch(signature)
            or not verify_signature(did, signed_room_payload(room, nonce, text), signature)
        ):
            raise ValueError("invalid signed Technocore message")
        try:
            response = self.client.post(
                f"/r/{room}",
                params={"format": "json"},
                json={"did": did, "sig": signature, "nonce": str(nonce), "text": text},
            )
        except httpx.RequestError as exc:
            try:
                reconciled = self.reconcile(room, did, nonce, text)
            except Exception:
                raise UncertainWrite("write outcome could not be reconciled") from exc
            if reconciled is not None:
                return ProtocolRecord(reconciled.sequence, room, did, nonce, text, signature)
            raise UncertainWrite("write outcome remains uncertain") from exc
        value = self._json(response)
        posted = value.get("posted")
        if not isinstance(posted, dict):
            raise TechnocoreRefusal(502, "missing_posted_record")
        if (
            posted.get("from") != did
            or posted.get("nonce") != nonce
            or posted.get("text") != text
            or posted.get("sig") != signature
            or not isinstance(posted.get("seq"), int)
        ):
            raise TechnocoreRefusal(502, "posted_record_mismatch")
        return ProtocolRecord(int(posted["seq"]), room, did, nonce, text, signature)

    def post_signed_note(
        self,
        namespace: str,
        key: str,
        did: str,
        nonce: int,
        value: str,
        signature: str,
        *,
        if_absent: bool = False,
    ) -> dict[str, Any]:
        if namespace not in {"room-owners", "room-allow"}:
            raise ValueError("signed note namespace is not allowed")
        validate_room_name(key)
        if (
            not _DID.fullmatch(did)
            or nonce < 1
            or not isinstance(signature, str)
            or not _SIG.fullmatch(signature)
            or len(value) > 8192
            or not verify_signature(
                did, signed_note_payload(namespace, key, nonce, value), signature
            )
        ):
            raise ValueError("invalid signed Technocore note")
        payload: dict[str, object] = {
            "did": did,
            "sig": signature,
            "nonce": str(nonce),
            "value": value,
        }
        if if_absent:
            payload["if_absent"] = True
        try:
            response = self.client.post(
                f"/kv/{namespace}/{key}", params={"format": "json"}, json=payload
            )
        except httpx.RequestError as exc:
            raise UncertainWrite("signed note outcome is uncertain") from exc
        return self._json(response)

    def read_note(self, namespace: str, key: str) -> str | None:
        if namespace not in {"room-owners", "room-allow"}:
            raise ValueError("note namespace is not allowed")
        validate_room_name(key)
        response = self.client.get(f"/kv/{namespace}/{key}")
        self._rate_limited(response)
        body = self._bounded(response)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise TechnocoreRefusal(response.status_code, "note_read_refused")
        if response.headers.get("content-type", "").split(";", 1)[0] != "text/plain":
            raise TechnocoreRefusal(502, "unexpected_content_type")
        text = body.decode("utf-8")
        # The upstream warning is followed by a blank line and the exact value.
        marker = "\n\n"
        if marker not in text:
            raise TechnocoreRefusal(502, "invalid_note_view")
        return text.split(marker, 1)[1].strip()
