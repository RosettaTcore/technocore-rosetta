from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rosetta.contracts import DiscoveryQuery, ServiceRequest, SignRequest, SignResponse
from rosetta.local_protocol import LocalTechnocore, ProtocolRecord
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.registry import AdapterRegistry
from rosetta.service import (
    DiscoveryGateway,
    _require_origin,
    build_service_card,
    signed_post,
    verify_service_card,
)
from rosetta_signer.did import SyntheticIdentity
from rosetta_signer.nonce_store import NonceStore
from rosetta_signer.protocol import SignerProtocol

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)
BUNDLE = "sha256:" + "b" * 64


class AsyncSigner:
    def __init__(self, state: Path, label: str) -> None:
        self.store = NonceStore(state)
        self.protocol = SignerProtocol(SyntheticIdentity(label), self.store)

    @property
    def did(self) -> str:
        return self.protocol.did

    async def sign(self, request: SignRequest) -> SignResponse:
        return self.protocol.handle(request)

    def close(self) -> None:
        self.store.close()


class NoNonceSigner:
    async def sign(self, request: SignRequest) -> SignResponse:
        return SignResponse(
            did=SyntheticIdentity("synthetic-service-no-nonce").did,
            signature="x" * 86,
            nonce=None,
            signed_digest="sha256:" + "a" * 64,
        )


def _request(request_id: str, reply_room: str, consumer: str = "official-mcp") -> ServiceRequest:
    return ServiceRequest(
        schema="rosetta.request.v1",
        request_id=request_id,
        scenario="signed-mailbox-roundtrip-v1",
        producer="python-http",
        consumer=consumer,
        target_profile="current",
        reply_room=reply_room,
        expires_at=NOW + timedelta(hours=1),
    )


def test_service_origin_card_and_nonce_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="origin"):
        _require_origin("https://user:pass@reports.invalid/path", "https://reports.invalid")

    async def exercise() -> None:
        registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
        signer = AsyncSigner(tmp_path / "card.sqlite3", "synthetic-service-card-edge")
        card, attestation = await build_service_card(
            signer.did, registry, signer, "https://reports.invalid", NOW, tmp_path / "service"
        )
        assert verify_service_card(card, attestation, NOW)
        bad = dict(attestation)
        bad["service_card_sha256"] = BUNDLE
        assert not verify_service_card(card, bad, NOW)
        expired = card.copy(update={"valid_until": NOW})
        assert not verify_service_card(expired, attestation, NOW)
        with pytest.raises(RuntimeError, match="nonce"):
            await signed_post(LocalTechnocore(), NoNonceSigner(), "actor", "room", {"x": 1})
        signer.close()

    asyncio.run(exercise())


def test_discovery_and_request_rejection_conflict_and_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
        target = LocalTechnocore()
        store = StateStore(tmp_path / "state.sqlite3")
        gate = OperationalGate(store, tmp_path / "KILL_SWITCH")
        rosetta = AsyncSigner(tmp_path / "rosetta.sqlite3", "synthetic-service-rosetta-edge")
        peer = AsyncSigner(tmp_path / "peer.sqlite3", "synthetic-service-peer-edge")
        card, attestation = await build_service_card(
            rosetta.did, registry, rosetta, "https://reports.invalid", NOW, tmp_path / "service"
        )
        gateway = DiscoveryGateway(
            target,
            rosetta,
            registry,
            store,
            card,
            attestation,
            "https://reports.invalid",
            tmp_path / "KILL_SWITCH",
            gate,
        )
        await gateway.announce()
        reply = "mb-peer-edge"
        target.create_room(reply)

        unsigned = ProtocolRecord(1, "room", peer.did, 1, "{}", "bad")
        assert await gateway.handle_discovery(unsigned, NOW) is None
        assert await gateway.handle_request(unsigned, NOW, BUNDLE) == (None, None)

        expired_query = DiscoveryQuery(
            schema="rosetta.discover.v1",
            request_id="1" * 32,
            reply_room=reply,
            expires_at=NOW,
        )
        expired_record = await signed_post(target, peer, "peer", "discovery", expired_query.dict())
        assert await gateway.handle_discovery(expired_record, NOW) is None
        malformed = await signed_post(target, peer, "peer", "discovery", {"unknown": True})
        assert await gateway.handle_discovery(malformed, NOW) is None

        bad_request = _request("2" * 32, reply).copy(update={"expires_at": NOW})
        bad_record = await signed_post(
            target, peer, "peer", card.request_mailbox, bad_request.dict()
        )
        assert await gateway.handle_request(bad_record, NOW, BUNDLE) == (None, None)

        first = _request("3" * 32, reply)
        first_record = await signed_post(target, peer, "peer", card.request_mailbox, first.dict())
        accepted, result = await gateway.handle_request(first_record, NOW, BUNDLE)
        assert accepted is not None and accepted.status == "accepted" and result is not None

        conflict_request = _request("3" * 32, reply, consumer="raw-fetch")
        conflict_record = await signed_post(
            target, peer, "peer", card.request_mailbox, conflict_request.dict()
        )
        conflict, conflict_result = await gateway.handle_request(conflict_record, NOW, BUNDLE)
        assert conflict is not None and conflict.status == "rejected" and conflict_result is None

        second = _request("4" * 32, reply)
        second_record = await signed_post(target, peer, "peer", card.request_mailbox, second.dict())
        accepted_second, _ = await gateway.handle_request(second_record, NOW, BUNDLE)
        assert accepted_second is not None and accepted_second.status == "accepted"

        third = _request("5" * 32, reply)
        third_record = await signed_post(target, peer, "peer", card.request_mailbox, third.dict())
        quota, quota_result = await gateway.handle_request(third_record, NOW, BUNDLE)
        assert quota is not None and quota.status == "rejected" and quota_result is None

        monkeypatch.setattr(store, "reserve_request", lambda *args, **kwargs: "duplicate")
        monkeypatch.setattr(store, "request_status", lambda *args, **kwargs: None)
        missing_record = await signed_post(
            target,
            peer,
            "peer",
            card.request_mailbox,
            _request("6" * 32, reply).dict(),
        )
        with pytest.raises(RuntimeError, match="disappeared"):
            await gateway.handle_request(missing_record, NOW, BUNDLE)

        rosetta.close()
        peer.close()
        store.close()

    asyncio.run(exercise())
