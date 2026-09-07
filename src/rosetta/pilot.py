"""Closed public Technocore request/result pilot.

No network-selected code, URL, repository, image, prompt, assertion, or command reaches
the runner. A request selects only one reviewed scenario and two IDs from the immutable
adapter registry. The actual scenario runs against Rosetta's pinned local target; public
Technocore is coordination transport only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any

from rosetta.adapters import AdapterEvent
from rosetta.contracts import (
    Acknowledgement,
    AssertionResult,
    Outcome,
    ReasonCode,
    RunRecord,
    ServiceCard,
    ServiceRequest,
    SignRequest,
)
from rosetta.delivery import ReliableMessenger
from rosetta.evidence import build_bundle, verify_bundle
from rosetta.local_protocol import LocalTechnocore, ProtocolRecord
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.pilot_config import PilotConfig, load_pilot_config
from rosetta.publishing import ServiceDocumentPublisher, StaticPublisher
from rosetta.registry import AdapterRegistry
from rosetta.scenario import ScenarioResult, run_roundtrip
from rosetta.service import DiscoveryGateway, build_service_card, verify_service_card
from rosetta.signer_client import GuardedSigner, Signer, SignerClient
from rosetta.technocore_client import TechnocoreHttpClient
from rosetta_signer.canonical import canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_json(path: Path, value: dict[str, object], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


class PilotRuntime:
    def __init__(
        self,
        config: PilotConfig,
        *,
        signer: Signer | None = None,
        target: TechnocoreHttpClient | None = None,
        store: StateStore | None = None,
        clock: Any = None,
    ) -> None:
        self.config = config
        self.clock = clock or _now
        self.state_dir = Path(config.service.state_directory)
        self.spool_dir = Path(config.service.spool_directory)
        self.static_root = Path(config.service.static_root)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.store = store or StateStore(self.state_dir / "pilot.sqlite3")
        self.gate = OperationalGate(
            self.store,
            Path(config.service.kill_switch_file),
            max_runs_per_day=config.service.max_external_jobs_per_day,
            monthly_budget_cents=config.service.monthly_budget_cents,
            max_parallel=1,
        )
        raw_signer = signer or SignerClient(config.identity.signer_socket)
        self.signer = GuardedSigner(raw_signer, self.gate)
        self.target = target or TechnocoreHttpClient(
            config.technocore.fetch_origin,
            config.technocore.authority_origin,
            config.technocore.pinned_release,
            timeout_seconds=config.technocore.request_timeout_seconds,
            max_response_bytes=config.technocore.max_response_bytes,
        )
        self.registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
        self.stop_requested = False

    @property
    def service_documents(self) -> Path:
        return self.spool_dir / "service-documents"

    @property
    def preview_path(self) -> Path:
        return self.state_dir / "activation-preview.json"

    @property
    def activation_path(self) -> Path:
        return self.state_dir / "activation.json"

    def close(self) -> None:
        self.target.close()
        self.store.close()

    def request_stop(self, _signum: int | None = None, _frame: FrameType | None = None) -> None:
        self.stop_requested = True

    async def _assert_identity(self) -> None:
        check = await self.signer.sign(
            SignRequest(
                action="service_document",
                scope="pilot-identity-check",
                digest="sha256:" + "0" * 64,
            )
        )
        if check.did != self.config.identity.public_did:
            raise RuntimeError("configured DID does not match isolated signer")

    async def prepare(self, now: datetime | None = None) -> tuple[dict[str, object], str]:
        current = now or self.clock()
        await self._assert_identity()
        card, attestation = await build_service_card(
            self.config.identity.public_did,
            self.registry,
            self.signer,
            self.config.service.public_base_url,
            "v0.13.0",
            current,
            self.service_documents,
        )
        if card.did != self.config.identity.public_did:
            raise RuntimeError("service card DID mismatch")
        claim = await self.signer.sign(
            SignRequest(
                action="technocore_note",
                scope="service-room-claim",
                namespace="room-owners",
                key=card.service_room,
                value=card.did,
            )
        )
        if claim.did != card.did or claim.nonce is None:
            raise RuntimeError("signer returned an invalid ownership claim")
        announcement = {
            "schema": "rosetta.service-announcement.v1",
            "did": card.did,
            "request_mailbox": card.request_mailbox,
            "service_card_url": self.config.service.public_base_url + "/service-card.json",
            "service_card_sha256": attestation["service_card_sha256"],
        }
        announcement_text = canonical_json(announcement).decode()
        announcement_key = "announcement:" + str(attestation["service_card_sha256"])
        prepared = self.store.delivery(announcement_key)
        if prepared is None:
            signed = await self.signer.sign(
                SignRequest(
                    action="technocore_message",
                    scope="rosetta-discovery",
                    room=card.service_room,
                    text=announcement_text,
                )
            )
            if signed.did != card.did or signed.nonce is None:
                raise RuntimeError("signer returned an invalid announcement")
            self.store.prepare_delivery(
                announcement_key,
                "rosetta-discovery",
                card.service_room,
                signed.did,
                signed.nonce,
                announcement_text,
                signed.signature,
            )
            prepared = self.store.delivery(announcement_key)
        if prepared is None:
            raise RuntimeError("announcement preparation disappeared")
        preview: dict[str, object] = {
            "schema": "rosetta.pilot-activation-preview.v1",
            "authority": self.config.technocore.authority_origin,
            "public_base_url": self.config.service.public_base_url,
            "service_card_sha256": attestation["service_card_sha256"],
            "service_room": card.service_room,
            "request_mailbox": card.request_mailbox,
            "limits": card.limits.dict(),
            "writes": [
                {
                    "purpose": "claim_service_room",
                    "method": "POST",
                    "path": f"/kv/room-owners/{card.service_room}?format=json",
                    "body": {
                        "did": claim.did,
                        "sig": claim.signature,
                        "nonce": str(claim.nonce),
                        "value": card.did,
                        "if_absent": True,
                    },
                },
                {
                    "purpose": "announce_service",
                    "method": "POST",
                    "path": f"/r/{card.service_room}?format=json",
                    "body": {
                        "did": prepared[2],
                        "sig": prepared[5],
                        "nonce": str(prepared[3]),
                        "text": prepared[4],
                    },
                },
            ],
            "automatic_behavior_after_activation": {
                "poll_rooms": [card.request_mailbox, *self.config.technocore.discovery_rooms],
                "accept_only": "rosetta.request.v1",
                "max_requests_per_did_per_day": card.limits.per_did_per_day,
                "max_global_requests_per_day": card.limits.global_per_day,
                "cold_outreach": False,
                "natural_language_replies": False,
                "llm_verdicts": False,
            },
        }
        preview_digest = _digest(preview)
        _atomic_json(self.preview_path, preview)
        (self.state_dir / "activation-preview.sha256").write_text(
            preview_digest + "\n", encoding="ascii"
        )
        return preview, preview_digest

    def _load_prepared(self) -> tuple[dict[str, object], str]:
        value = json.loads(self.preview_path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("invalid activation preview")
        return value, _digest(value)

    def _load_card(self, now: datetime) -> tuple[ServiceCard, dict[str, Any]]:
        card = ServiceCard.parse_raw((self.service_documents / "service-card.json").read_bytes())
        attestation = json.loads(
            (self.service_documents / "service-card.attestation.json").read_bytes()
        )
        if not verify_service_card(card, attestation, now):
            raise RuntimeError("service card is invalid or expired")
        if card.did != self.config.identity.public_did:
            raise RuntimeError("service card identity mismatch")
        return card, attestation

    async def activate(
        self, approved_digest: str, now: datetime | None = None
    ) -> dict[str, object]:
        if not self.config.service.enabled:
            raise RuntimeError("pilot_disabled")
        current = now or self.clock()
        await self._assert_identity()
        preview, preview_digest = self._load_prepared()
        if approved_digest != preview_digest:
            raise RuntimeError("activation approval digest mismatch")
        card, _ = self._load_card(current)
        self.target.capabilities()
        ServiceDocumentPublisher(True, self.spool_dir, self.static_root, self.gate).publish(
            self.service_documents, current
        )
        writes = preview.get("writes")
        if not isinstance(writes, list) or len(writes) != 2:
            raise ValueError("activation preview write set changed")
        claim = writes[0]
        if not isinstance(claim, dict) or not isinstance(claim.get("body"), dict):
            raise ValueError("invalid claim preview")
        body = claim["body"]
        try:
            self.target.post_signed_note(
                "room-owners",
                card.service_room,
                str(body["did"]),
                int(str(body["nonce"])),
                str(body["value"]),
                str(body["sig"]),
                if_absent=True,
            )
        except Exception as exc:
            # The only safe uncertain/restart reconciliation is the exact claimed owner.
            try:
                owner = self.target.read_note("room-owners", card.service_room)
            except Exception as reconciliation_error:
                raise exc from reconciliation_error
            if owner != card.did:
                raise exc
        gateway = self._gateway(card)
        announcement_record = await gateway.announce()
        activated = {
            "schema": "rosetta.pilot-activation.v1",
            "preview_sha256": preview_digest,
            "activated_at": current,
            "service_room": card.service_room,
            "request_mailbox": card.request_mailbox,
            "announcement_sequence": announcement_record.sequence,
        }
        _atomic_json(self.activation_path, activated)
        return activated

    def _gateway(self, card: ServiceCard) -> DiscoveryGateway:
        attestation = json.loads(
            (self.service_documents / "service-card.attestation.json").read_bytes()
        )
        messenger = ReliableMessenger(self.target, self.signer, self.store, self.gate)
        return DiscoveryGateway(
            self.target,
            self.signer,
            self.registry,
            self.store,
            card,
            attestation,
            self.config.service.public_base_url,
            Path(self.config.service.kill_switch_file),
            self.gate,
            max_queue_depth=self.config.service.max_queue_depth,
            messenger=messenger,
        )

    async def _build_request_bundle(
        self,
        requester: str,
        request: ServiceRequest,
        job_id: str,
        now: datetime,
    ) -> tuple[str, Outcome, Path]:
        final = self.spool_dir / "jobs" / job_id / "bundle"
        if final.exists():
            root = verify_bundle(final)
            matrix = json.loads((final / "matrix.json").read_bytes())
            return root, Outcome(matrix["cells"][0]["outcome"]), final
        self.gate.reserve_run(now)
        try:
            result = await run_roundtrip(
                request.producer,
                request.consumer,
                self.registry,
                self.signer,
                target=LocalTechnocore(),
                gate=self.gate,
            )
        except Exception as exc:
            result = ScenarioResult(
                request.producer,
                request.consumer,
                Outcome.ERROR,
                ReasonCode.INFRASTRUCTURE_FAILURE,
                [
                    AssertionResult(
                        name="runner_completed",
                        passed=False,
                        reason=ReasonCode.INFRASTRUCTURE_FAILURE,
                        detail=type(exc).__name__,
                    )
                ],
                [
                    AdapterEvent(
                        "rosetta-pilot",
                        "service-run",
                        "error",
                        {"error_type": type(exc).__name__},
                    )
                ],
                {
                    "schema": "rosetta.reproduction.v1",
                    "scenario": request.scenario,
                    "producer": request.producer,
                    "consumer": request.consumer,
                    "fault": "infrastructure-failure",
                    "correlation_id": request.request_id,
                },
            )
        run = RunRecord(
            run_id=hashlib.sha256(
                f"{requester}|{request.request_id}|{job_id}".encode()
            ).hexdigest()[:32],
            # Public requests run the deterministic local conformance model. The
            # independently gated OCI matrix is never implied by this bundle.
            trigger="signed-service-request-local-diagnostic",
            protocol_release="v0.13.0",
            scenario=request.scenario,
            registry_sha256=self.registry.digest,
            deterministic_epoch=request.expires_at.astimezone(timezone.utc).isoformat(),
            dry_run=True,
        )
        versions = {
            adapter_id: self.registry.require(adapter_id).source_revision
            for adapter_id in self.registry.ids
        }
        work = Path(tempfile.mkdtemp(prefix=f"job-{job_id}-", dir=self.spool_dir))
        try:
            bundle = work / "bundle"
            root = await build_bundle(bundle, run, [result], versions, self.signer)
            verify_bundle(bundle)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(bundle, final)
        finally:
            try:
                work.rmdir()
            except OSError:
                pass
        return root, result.outcome, final

    async def _execute(
        self,
        gateway: DiscoveryGateway,
        requester: str,
        request: ServiceRequest,
        job_id: str,
        now: datetime,
    ) -> None:
        self.store.mark_job(requester, request.request_id, "running", now)
        try:
            root, outcome, bundle = await self._build_request_bundle(
                requester, request, job_id, now
            )
            report_destination = self.static_root / "reports" / root.removeprefix("sha256:")
            if report_destination.exists():
                if verify_bundle(report_destination) != root:
                    raise RuntimeError("published report conflicts with recovered job")
            else:
                StaticPublisher(
                    True,
                    self.spool_dir,
                    self.static_root / "reports",
                    self.store,
                    self.gate,
                ).publish(bundle)
            status = self.store.request_status(requester, request.request_id)
            if status is None:
                raise RuntimeError("service request state disappeared")
            ack = Acknowledgement.parse_raw(status[1])
            await gateway.complete_request(requester, request, ack, self.clock(), root, outcome)
            self.gate.record("pilot_runner", True, self.clock())
        except Exception:
            self.store.mark_job(requester, request.request_id, "failed", self.clock())
            self.gate.record("pilot_runner", False, self.clock())
            raise

    async def _recover(self, gateway: DiscoveryGateway, now: datetime) -> None:
        for requester, request_id, request_json, _status in self.store.pending_jobs():
            request = ServiceRequest.parse_raw(request_json)
            state = self.store.request_status(requester, request_id)
            if state is None:
                raise RuntimeError("orphan service job")
            ack = Acknowledgement.parse_raw(state[1])
            if ack.job_id is None:
                raise RuntimeError("pending job has no job id")
            await self._execute(gateway, requester, request, ack.job_id, now)

    async def poll_once(self, now: datetime | None = None) -> dict[str, int]:
        if not self.config.service.enabled or not self.activation_path.is_file():
            raise RuntimeError("pilot_not_activated")
        current = now or self.clock()
        card, _ = self._load_card(current)
        gateway = self._gateway(card)
        await self._recover(gateway, current)
        counts = {"discovery": 0, "requests": 0, "rejected": 0}
        for room in self.config.technocore.discovery_rooms:
            records = self._read_generation_safe(room)
            for record in records:
                offer = await gateway.handle_discovery(record, current)
                counts["discovery"] += int(offer is not None)
                self.store.advance_room_cursor(room, record.sequence)
        room = card.request_mailbox
        records = self._read_generation_safe(room)
        for record in records:
            request, ack, status = await gateway.accept_request(record, current)
            if request is not None and ack is not None and ack.status == "accepted":
                counts["requests"] += int(status == "accepted")
                if status in {"accepted", "duplicate_pending"}:
                    if ack.job_id is None:
                        raise RuntimeError("accepted request has no job id")
                    await self._execute(gateway, record.did, request, ack.job_id, current)
            elif status not in {"unsigned", "invalid"}:
                counts["rejected"] += 1
            self.store.advance_room_cursor(room, record.sequence)
        _atomic_json(
            self.state_dir / "health.json",
            {
                "schema": "rosetta.pilot-health.v1",
                "status": "healthy",
                "checked_at": current,
                "public_writes_enabled": True,
                "service_room": card.service_room,
                "request_mailbox": card.request_mailbox,
                "counts": counts,
            },
        )
        return counts

    def _read_generation_safe(self, room: str) -> list[ProtocolRecord]:
        """Read without silently carrying a cursor into a recreated v0.13 room."""
        cursor, stored_generation = self.store.room_checkpoint(room)
        records = self.target.read_room(room, since=cursor, limit=100)
        generation_reader = getattr(self.target, "room_generation", None)
        observed_generation = generation_reader(room) if callable(generation_reader) else None
        if observed_generation is None:
            return records
        if stored_generation is not None and observed_generation != stored_generation:
            self.store.set_room_generation(room, observed_generation, reset=True)
            return self.target.read_room(room, since=0, limit=100)
        if stored_generation is None:
            self.store.set_room_generation(room, observed_generation)
        return records

    async def serve(self) -> None:
        self.target.capabilities()
        while not self.stop_requested:
            await self.poll_once()
            for _ in range(self.config.service.poll_seconds * 10):
                if self.stop_requested:
                    return
                await asyncio.sleep(0.1)


async def _run(args: argparse.Namespace) -> object:
    config = load_pilot_config(args.config)
    runtime = PilotRuntime(config)
    try:
        if args.command == "prepare":
            preview, digest = await runtime.prepare()
            return {"preview_sha256": digest, "preview": preview}
        if args.command == "activate":
            return await runtime.activate(args.approved_digest)
        if args.command == "once":
            return await runtime.poll_once()
        if args.command == "serve":
            signal.signal(signal.SIGTERM, runtime.request_stop)
            signal.signal(signal.SIGINT, runtime.request_stop)
            await runtime.serve()
            return {"status": "stopped"}
        raise RuntimeError("unknown pilot command")
    finally:
        runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="rosetta-pilot")
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    activate = commands.add_parser("activate")
    activate.add_argument("--approved-digest", required=True)
    commands.add_parser("once")
    commands.add_parser("serve")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
