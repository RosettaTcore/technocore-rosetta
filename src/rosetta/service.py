"""Closed discovery and autonomous local service protocol."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import ValidationError

from rosetta.contracts import (
    Acknowledgement,
    DiscoveryOffer,
    DiscoveryQuery,
    Outcome,
    ReasonCode,
    ServiceCard,
    ServiceLimits,
    ServiceRequest,
    ServiceResult,
    SignRequest,
    validate_public_mailbox,
)
from rosetta.local_protocol import LocalTechnocore, ProtocolRecord
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.registry import AdapterRegistry
from rosetta.signer_client import Signer
from rosetta_signer.canonical import canonical_json
from rosetta_signer.did import did_fingerprint, service_document_payload, verify_signature


def service_names(did: str) -> tuple[str, str]:
    fingerprint = did_fingerprint(did)
    return f"d-rosetta-{fingerprint}", f"mb-rosetta-{fingerprint}"


def _require_origin(url: str, allowed_origin: str) -> None:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin != allowed_origin.rstrip("/") or parsed.username or parsed.password:
        raise ValueError("URL origin is not the configured publisher origin")


async def build_service_card(
    did: str,
    registry: AdapterRegistry,
    signer: Signer,
    base_url: str,
    protocol_baseline: Literal["v0.7.0", "v0.10.0"],
    now: datetime,
    output_dir: Path,
) -> tuple[ServiceCard, dict[str, Any]]:
    service_room, request_mailbox = service_names(did)
    request_url = base_url.rstrip("/") + "/schemas/rosetta-request-v1.json"
    report_url = base_url.rstrip("/") + "/reports"
    _require_origin(request_url, base_url)
    _require_origin(report_url, base_url)
    card = ServiceCard.parse_obj(
        {
            "did": did,
            "service_room": service_room,
            "request_mailbox": request_mailbox,
            "protocol_baseline": protocol_baseline,
            "scenarios": ["signed-mailbox-roundtrip-v1"],
            "adapter_profiles": registry.ids,
            "request_schema_url": request_url,
            "report_base_url": report_url,
            "limits": ServiceLimits(per_did_per_day=2, global_per_day=8).dict(),
            "status": "available",
            "updated_at": now,
            "valid_until": now + timedelta(days=7),
        }
    )
    card_bytes = canonical_json(card.dict())
    digest = "sha256:" + hashlib.sha256(card_bytes).hexdigest()
    signed = await signer.sign(
        SignRequest(action="service_document", scope="service-card", digest=digest)
    )
    attestation = {
        "schema": "rosetta.service-card-attestation.v1",
        "domain": "rosetta.service-document.v1",
        "did": signed.did,
        "service_card_sha256": digest,
        "signature": signed.signature,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "service-card.json").write_bytes(card_bytes + b"\n")
    (output_dir / "service-card.attestation.json").write_bytes(canonical_json(attestation) + b"\n")
    schemas = output_dir / "schemas"
    schemas.mkdir(exist_ok=True)
    request_schema = (
        ServiceRequest.schema_json(indent=2, sort_keys=True, by_alias=True).encode() + b"\n"
    )
    result_schema = (
        ServiceResult.schema_json(indent=2, sort_keys=True, by_alias=True).encode() + b"\n"
    )
    (schemas / "rosetta-request-v1.json").write_bytes(request_schema)
    (schemas / "rosetta-result-v1.json").write_bytes(result_schema)
    agent = {
        "schema": "rosetta.agent-manifest.v1",
        "name": "Technocore Rosetta",
        "did": did,
        "service_card": base_url.rstrip("/") + "/service-card.json",
    }
    well_known = output_dir / ".well-known"
    well_known.mkdir(exist_ok=True)
    (well_known / "agent.json").write_bytes(canonical_json(agent) + b"\n")
    skill = (
        "# Technocore Rosetta\n\n"
        "Submit only a DID-signed `rosetta.request.v1` to the public request mailbox. "
        "Requests cannot contain code, prompts, URLs, credentials, commits, images, "
        "or private mailboxes.\n"
    )
    (output_dir / "skill.md").write_text(skill, encoding="utf-8")
    return card, attestation


def verify_service_card(card: ServiceCard, attestation: dict[str, Any], now: datetime) -> bool:
    card_bytes = canonical_json(card.dict())
    digest = "sha256:" + hashlib.sha256(card_bytes).hexdigest()
    if digest != attestation.get("service_card_sha256") or card.did != attestation.get("did"):
        return False
    if card.valid_until.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
        return False
    return verify_signature(
        card.did, service_document_payload(digest), str(attestation.get("signature"))
    )


async def signed_post(
    target: LocalTechnocore,
    signer: Signer,
    actor: str,
    room: str,
    body: dict[str, Any],
) -> ProtocolRecord:
    text = canonical_json(body).decode()
    signed = await signer.sign(
        SignRequest(action="technocore_message", scope=actor, room=room, text=text)
    )
    if signed.nonce is None:
        raise RuntimeError("signer omitted message nonce")
    return target.post_signed(actor, room, signed.did, signed.nonce, text, signed.signature)


class DiscoveryGateway:
    def __init__(
        self,
        target: LocalTechnocore,
        signer: Signer,
        registry: AdapterRegistry,
        store: StateStore,
        card: ServiceCard,
        card_attestation: dict[str, Any],
        base_url: str,
        kill_switch: Path,
        gate: OperationalGate,
    ) -> None:
        self.target = target
        self.signer = signer
        self.registry = registry
        self.store = store
        self.card = card
        self.card_attestation = card_attestation
        self.base_url = base_url.rstrip("/")
        self.kill_switch = kill_switch
        self.gate = gate
        self.runner_starts = 0

    def _require_operational(self) -> None:
        self.gate.require("service")

    async def announce(self) -> ProtocolRecord:
        self._require_operational()
        self.target.create_room(self.card.service_room)
        self.target.create_room(self.card.request_mailbox)
        announcement = {
            "schema": "rosetta.service-announcement.v1",
            "did": self.card.did,
            "request_mailbox": self.card.request_mailbox,
            "service_card_url": self.base_url + "/service-card.json",
            "service_card_sha256": self.card_attestation["service_card_sha256"],
        }
        return await signed_post(
            self.target, self.signer, "rosetta-discovery", self.card.service_room, announcement
        )

    async def handle_discovery(
        self, record: ProtocolRecord, now: datetime
    ) -> DiscoveryOffer | None:
        self._require_operational()
        if not record.signed:
            return None
        try:
            query = DiscoveryQuery.parse_raw(record.text)
            if query.expires_at.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                return None
            validate_public_mailbox(query.reply_room)
        except (ValidationError, ValueError, KeyError):
            return None
        offer = DiscoveryOffer.parse_obj(
            {
                "request_id": query.request_id,
                "did": self.card.did,
                "service_card_url": self.base_url + "/service-card.json",
                "service_card_sha256": self.card_attestation["service_card_sha256"],
                "request_mailbox": self.card.request_mailbox,
                "valid_until": self.card.valid_until,
            }
        )
        await signed_post(
            self.target, self.signer, "rosetta-discovery", query.reply_room, offer.dict()
        )
        return offer

    async def handle_request(
        self,
        record: ProtocolRecord,
        now: datetime,
        bundle_root: str,
        outcome: Outcome = Outcome.PASS,
    ) -> tuple[Acknowledgement | None, ServiceResult | None]:
        self._require_operational()
        if not record.signed:
            return None, None
        try:
            request = ServiceRequest.parse_raw(record.text)
            request.validate_expiry(now)
            self.registry.require(request.producer)
            self.registry.require(request.consumer)
        except (ValidationError, ValueError):
            return None, None
        canonical = canonical_json(request.dict())
        content_hash = hashlib.sha256(canonical).hexdigest()
        job_id = hashlib.sha256((record.did + request.request_id).encode()).hexdigest()[:24]
        ack = Acknowledgement(
            request_id=request.request_id,
            status="accepted",
            job_id=job_id,
            position=1,
        )
        status = self.store.reserve_request(
            record.did,
            request.request_id,
            content_hash,
            canonical_json(ack.dict()).decode(),
            now,
            2,
            8,
        )
        if status == "duplicate":
            prior = self.store.request_status(record.did, request.request_id)
            if prior is None:
                raise RuntimeError("idempotency state disappeared")
            prior_ack = Acknowledgement.parse_raw(prior[1])
            prior_result = ServiceResult.parse_raw(prior[2]) if prior[2] else None
            return prior_ack, prior_result
        if status == "conflict":
            conflict = Acknowledgement(
                request_id=request.request_id,
                status="rejected",
                reason=ReasonCode.DUPLICATE_CONFLICT,
            )
            await signed_post(
                self.target, self.signer, "rosetta-service", request.reply_room, conflict.dict()
            )
            return conflict, None
        if status == "quota":
            quota = Acknowledgement(
                request_id=request.request_id,
                status="rejected",
                reason=ReasonCode.QUOTA_EXCEEDED,
            )
            await signed_post(
                self.target, self.signer, "rosetta-service", request.reply_room, quota.dict()
            )
            return quota, None
        self.runner_starts += 1
        await signed_post(
            self.target, self.signer, "rosetta-service", request.reply_room, ack.dict()
        )
        result = ServiceResult.parse_obj(
            {
                "request_id": request.request_id,
                "job_id": job_id,
                "outcome": outcome,
                "bundle_root": bundle_root,
                "report_url": (f"{self.base_url}/reports/{bundle_root.removeprefix('sha256:')}/"),
                "completed_at": now,
            }
        )
        await signed_post(
            self.target, self.signer, "rosetta-service", request.reply_room, result.dict()
        )
        self.store.store_result(
            record.did, request.request_id, canonical_json(result.dict()).decode()
        )
        return ack, result
