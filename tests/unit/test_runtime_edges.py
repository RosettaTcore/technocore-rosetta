from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rosetta import adapters
from rosetta.adapters import FixtureAdapter
from rosetta.contracts import SignRequest, SignResponse
from rosetta.local_protocol import LocalTechnocore, RateLimited
from rosetta.registry import AdapterRegistry
from rosetta_signer.canonical import signed_room_payload
from rosetta_signer.did import SyntheticIdentity

ROOT = Path(__file__).resolve().parents[2]


class NoNonceSigner:
    async def sign(self, request: SignRequest) -> SignResponse:
        return SignResponse(
            did=SyntheticIdentity("synthetic-no-nonce").did,
            signature="x" * 86,
            nonce=None,
            signed_digest="sha256:" + "a" * 64,
        )


class SigningFixture:
    def __init__(self) -> None:
        self.identity = SyntheticIdentity("synthetic-runtime-edge")
        self.nonce = 0

    async def sign(self, request: SignRequest) -> SignResponse:
        self.nonce += 1
        assert request.room is not None and request.text is not None
        signature = self.identity.sign(signed_room_payload(request.room, self.nonce, request.text))
        return SignResponse(
            did=self.identity.did,
            signature=signature,
            nonce=self.nonce,
            signed_digest="sha256:" + "a" * 64,
        )


def test_local_protocol_room_cursor_and_replay_edges() -> None:
    target = LocalTechnocore()
    with pytest.raises(ValueError, match="room"):
        target.create_room("")
    target.create_room("room")
    target.create_room("d-service")
    assert target.list_rooms() == ["d-service", "room"]
    assert target.events() == ["d-service"]
    with pytest.raises(ValueError, match="limit"):
        target.read_room("room", limit=0)

    identity = SyntheticIdentity("synthetic-replay-edge")
    signature = identity.sign(signed_room_payload("room", 1, "first"))
    first = target.post_signed("actor", "room", identity.did, 1, "first", signature)
    assert target.post_signed("actor", "room", identity.did, 1, "first", signature) == first
    conflict_signature = identity.sign(signed_room_payload("room", 1, "different"))
    with pytest.raises(ValueError, match="replay conflict"):
        target.post_signed("actor", "room", identity.did, 1, "different", conflict_signature)


def test_adapter_rejects_missing_nonce_and_excessive_backoff() -> None:
    registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
    target = LocalTechnocore()
    adapter = FixtureAdapter("python-http", registry, target, NoNonceSigner(), "role")
    with pytest.raises(RuntimeError, match="nonce"):
        asyncio.run(adapter.post_signed("room", "text"))

    signer = SigningFixture()
    limited = FixtureAdapter("python-http", registry, target, signer, "role")

    def always_limited(*args: object, **kwargs: object):
        raise RateLimited(3)

    target.post_signed = always_limited  # type: ignore[method-assign]
    with pytest.raises(RateLimited):
        asyncio.run(limited.post_signed("limited", "text"))


def test_runtime_probe_rejects_unknown_oversized_and_mismatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="unallowlisted"):
        adapters._runtime_probe("unknown")

    monkeypatch.setattr(
        adapters.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="x" * 4097),
    )
    with pytest.raises(ValueError, match="oversized"):
        adapters._runtime_probe("raw-fetch")

    monkeypatch.setattr(
        adapters.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps({"id": "wrong"})),
    )
    with pytest.raises(ValueError, match="mismatched"):
        adapters._runtime_probe("raw-fetch")
