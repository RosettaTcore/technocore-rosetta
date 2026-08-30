"""Strict signer protocol implementation."""

from __future__ import annotations

import hashlib
from typing import Protocol

from rosetta.contracts import SignRequest, SignResponse
from rosetta_signer.canonical import signed_room_payload
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
        if request.action == "technocore_message":
            if request.room is None or request.text is None or request.digest is not None:
                raise ValueError("message signing requires room and text only")
            # Technocore requires one strictly increasing nonce lane per DID and room;
            # caller-supplied role labels must never split that security scope.
            scope = f"message:{request.room}"
            nonce = self._store.next(scope, request.nonce)
            payload = signed_room_payload(request.room, nonce, request.text)
        elif request.action == "artifact_root":
            if request.digest is None or request.room is not None or request.text is not None:
                raise ValueError("artifact signing requires digest only")
            scope = f"artifact:{request.scope}"
            payload = artifact_payload(request.digest)
        elif request.action == "service_document":
            if request.digest is None or request.room is not None or request.text is not None:
                raise ValueError("service document signing requires digest only")
            scope = f"service:{request.scope}"
            payload = service_document_payload(request.digest)
        elif request.action == "evolution_proposal":
            if request.digest is None or request.room is not None or request.text is not None:
                raise ValueError("evolution proposal signing requires digest only")
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
