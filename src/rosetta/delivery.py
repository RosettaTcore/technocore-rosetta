"""Crash-safe, at-most-once outbound Technocore delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from rosetta.contracts import SignRequest
from rosetta.local_protocol import ProtocolRecord, RateLimited, TechnocoreTarget, UncertainWrite
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.signer_client import Signer
from rosetta.technocore_client import TechnocoreRefusal
from rosetta_signer.canonical import canonical_json


class ReliableMessenger:
    """Persist the exact signed bytes before the network can observe them."""

    def __init__(
        self,
        target: TechnocoreTarget,
        signer: Signer,
        store: StateStore,
        gate: OperationalGate,
        *,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.target = target
        self.signer = signer
        self.store = store
        self.gate = gate
        self.sleeper = sleeper

    def _reconcile(self, room: str, did: str, nonce: int, text: str) -> ProtocolRecord | None:
        reconcile = getattr(self.target, "reconcile", None)
        if callable(reconcile):
            return cast(ProtocolRecord | None, reconcile(room, did, nonce, text))
        matches = [
            record
            for record in self.target.read_room(room, since=0, limit=100)
            if record.did == did and record.nonce == nonce and record.text == text
        ]
        if len(matches) > 1:
            raise RuntimeError("duplicate_remote_delivery")
        return matches[0] if matches else None

    async def send(
        self,
        delivery_key: str,
        actor: str,
        room: str,
        body: dict[str, object],
    ) -> ProtocolRecord:
        self.gate.require("public_writer")
        text = canonical_json(body).decode()
        existing = self.store.delivery(delivery_key)
        current: tuple[str, str, str, int, str, str, str, int | None]
        if existing is None:
            signed = await self.signer.sign(
                SignRequest(action="technocore_message", scope=actor, room=room, text=text)
            )
            if signed.nonce is None:
                raise RuntimeError("signer omitted message nonce")
            self.store.prepare_delivery(
                delivery_key,
                actor,
                room,
                signed.did,
                signed.nonce,
                text,
                signed.signature,
            )
            current = (
                actor,
                room,
                signed.did,
                signed.nonce,
                text,
                signed.signature,
                "prepared",
                None,
            )
        else:
            current = existing
            if current[0] != actor or current[1] != room or current[4] != text:
                raise RuntimeError("delivery_key_conflict")
        _, _, did, nonce, sent_text, signature, status, sequence = current
        if status == "confirmed":
            if sequence is None:
                raise RuntimeError("confirmed_delivery_missing_sequence")
            return ProtocolRecord(sequence, room, did, nonce, sent_text, signature)

        for attempt in range(2):
            try:
                record = self.target.post_signed(actor, room, did, nonce, sent_text, signature)
                self.store.confirm_delivery(delivery_key, record.sequence)
                return record
            except RateLimited as exc:
                if attempt or exc.retry_after_seconds > 2:
                    raise
                await self.sleeper(float(exc.retry_after_seconds))
            except (UncertainWrite, TechnocoreRefusal) as exc:
                # A replay/duplicate refusal after restart can still mean the prepared
                # bytes landed. Reconcile before considering any new signature or retry.
                if isinstance(exc, TechnocoreRefusal) and exc.status_code not in {403, 409, 422}:
                    raise
                reconciled = self._reconcile(room, did, nonce, sent_text)
                if reconciled is None:
                    raise UncertainWrite("prepared delivery was not found upstream") from exc
                self.store.confirm_delivery(delivery_key, reconciled.sequence)
                return ProtocolRecord(reconciled.sequence, room, did, nonce, sent_text, signature)
        raise RuntimeError("bounded delivery retry exhausted")
