"""Strict signer protocol implementation."""

from __future__ import annotations

import hashlib
from typing import Protocol

from rosetta.contracts import SignRequest, SignResponse
from rosetta_signer.canonical import signed_note_payload, signed_room_payload
from rosetta_signer.did import (
    artifact_payload,
    evolution_proposal_payload,
    service_document_payload,
)
from rosetta_signer.nonce_store import NonceStore


class SigningIdentity(Protocol):
    did: str

    def sign(self, payload: bytes) -> str: ...


class SignerProtocol:
    def __init__(self, identity: SigningIdentity, store: NonceStore) -> None:
        self._identity = identity
        self._store = store

    @property
    def did(self) -> str:
        return self._identity.did

    def handle(self, request: SignRequest) -> SignResponse:
        nonce: int | None = None
        present = {
            field
            for field in ("room", "text", "digest", "namespace", "key", "value")
            if getattr(request, field) is not None
        }
        required = {
            "technocore_message": {"room", "text"},
            "technocore_note": {"namespace", "key", "value"},
            "artifact_root": {"digest"},
            "service_document": {"digest"},
            "evolution_proposal": {"digest"},
        }
        if present != required[request.action]:
            raise ValueError(f"{request.action} has invalid signing fields")
        if request.action == "technocore_message":
            if request.room is None or request.text is None:
                raise ValueError("message signing requires room and text")
            # Technocore requires one strictly increasing nonce lane per DID and room;
            # caller-supplied role labels must never split that security scope.
            scope = f"message:{request.room}"
            nonce = self._store.next(scope, request.nonce)
            payload = signed_room_payload(request.room, nonce, request.text)
        elif request.action == "technocore_note":
            if request.namespace is None or request.key is None or request.value is None:
                raise ValueError("note signing requires namespace, key, and value")
            # Technocore shares one replay counter between room ownership and allow-list
            # writes. Namespace must therefore never split this nonce lane.
            scope = f"note:{request.key}"
            nonce = self._store.next(scope, request.nonce)
            payload = signed_note_payload(request.namespace, request.key, nonce, request.value)
        elif request.action == "artifact_root":
            if request.digest is None:
                raise ValueError("artifact signing requires digest")
            scope = f"artifact:{request.scope}"
            payload = artifact_payload(request.digest)
        elif request.action == "service_document":
            if request.digest is None:
                raise ValueError("service document signing requires digest")
            scope = f"service:{request.scope}"
            payload = service_document_payload(request.digest)
        elif request.action == "evolution_proposal":
            if request.digest is None:
                raise ValueError("evolution proposal signing requires digest")
            scope = f"evolution:{request.scope}"
            payload = evolution_proposal_payload(request.digest)
        else:  # pragma: no cover - Pydantic rejects this first
            raise ValueError("unknown signing action")
        payload_hash = hashlib.sha256(payload).hexdigest()
        signature = self._identity.sign(payload)
        self._store.record(
            request.action,
            hashlib.sha256(scope.encode()).hexdigest(),
            payload_hash,
            nonce,
        )
        return SignResponse(
            did=self.did,
            signature=signature,
            nonce=nonce,
            signed_digest="sha256:" + payload_hash,
        )
