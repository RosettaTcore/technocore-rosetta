"""Pinned, in-memory Technocore v0.7.0 behavioral fixture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rosetta_signer.canonical import signed_room_payload
from rosetta_signer.did import verify_signature


class RateLimited(Exception):
    def __init__(self, retry_after_seconds: int = 1) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = retry_after_seconds


class UncertainWrite(Exception):
    """The connection failed after the server may have committed the record."""


@dataclass(frozen=True)
class ProtocolRecord:
    sequence: int
    room: str
    did: str
    nonce: int
    text: str
    signature: str

    @property
    def signed(self) -> bool:
        return verify_signature(
            self.did,
            signed_room_payload(self.room, self.nonce, self.text),
            self.signature,
        )


class TechnocoreTarget(Protocol):
    release: str
    image_digest: str

    def inject_rate_limit_once(self, actor: str, room: str) -> None: ...

    def inject_uncertain_write_once(self, actor: str, room: str) -> None: ...

    def capabilities(self) -> dict[str, object]: ...

    def create_room(self, room: str) -> None: ...

    def read_room(self, room: str, *, since: int = 0, limit: int = 100) -> list[ProtocolRecord]: ...

    def post_signed(
        self,
        actor: str,
        room: str,
        did: str,
        nonce: int,
        text: str,
        signature: str,
    ) -> ProtocolRecord: ...


class LocalTechnocore:
    """No-network test double with explicit restart/429/partial-write semantics."""

    release = "v0.7.0"
    image_digest = "sha256:" + "0" * 64

    def __init__(self) -> None:
        self._rooms: dict[str, list[ProtocolRecord]] = {}
        self._next_sequence = 1
        self._rate_limit_once: set[tuple[str, str]] = set()
        self._uncertain_once: set[tuple[str, str]] = set()
        self._rate_limit_consumed: set[tuple[str, str]] = set()
        self._uncertain_consumed: set[tuple[str, str]] = set()

    def inject_rate_limit_once(self, actor: str, room: str) -> None:
        self._rate_limit_once.add((actor, room))

    def inject_uncertain_write_once(self, actor: str, room: str) -> None:
        self._uncertain_once.add((actor, room))

    def capabilities(self) -> dict[str, object]:
        return {
            "release": self.release,
            "operations": ["read_room", "post_signed", "wait_room", "rooms", "events"],
            "max_message_chars": 4096,
        }

    def create_room(self, room: str) -> None:
        if not room or len(room) > 64:
            raise ValueError("invalid room")
        self._rooms.setdefault(room, [])

    def list_rooms(self) -> list[str]:
        return sorted(self._rooms)

    def events(self) -> list[str]:
        return sorted(room for room in self._rooms if room.startswith("d-"))

    def read_room(self, room: str, *, since: int = 0, limit: int = 100) -> list[ProtocolRecord]:
        if limit < 1 or limit > 100:
            raise ValueError("limit outside bounded range")
        return [record for record in self._rooms.get(room, []) if record.sequence > since][:limit]

    def post_signed(
        self,
        actor: str,
        room: str,
        did: str,
        nonce: int,
        text: str,
        signature: str,
    ) -> ProtocolRecord:
        fault_key = (actor, room)
        if fault_key in self._rate_limit_once and fault_key not in self._rate_limit_consumed:
            self._rate_limit_consumed.add(fault_key)
            raise RateLimited(1)
        payload = signed_room_payload(room, nonce, text)
        if not verify_signature(did, payload, signature):
            raise ValueError("invalid signature")
        records = self._rooms.setdefault(room, [])
        for existing in records:
            if existing.did == did and existing.nonce == nonce:
                if existing.text == text and existing.signature == signature:
                    return existing
                raise ValueError("nonce replay conflict")
        record = ProtocolRecord(self._next_sequence, room, did, nonce, text, signature)
        self._next_sequence += 1
        records.append(record)
        if fault_key in self._uncertain_once and fault_key not in self._uncertain_consumed:
            self._uncertain_consumed.add(fault_key)
            raise UncertainWrite("record committed before connection loss")
        return record


def verify_record(record: ProtocolRecord) -> bool:
    return record.signed
