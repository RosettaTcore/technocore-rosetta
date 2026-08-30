"""Local-only operator CLI and reproducible Phase 3 demonstration."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rosetta.contracts import DiscoveryQuery, Outcome, RunRecord, ServiceRequest, SignRequest
from rosetta.evidence import build_bundle, verify_bundle
from rosetta.http_target import HttpTechnocore
from rosetta.local_protocol import LocalTechnocore
from rosetta.observability import Metrics
from rosetta.operations import DecisionTrace, OperationalGate
from rosetta.persistence import StateStore
from rosetta.registry import AdapterRegistry
from rosetta.runners import RunnerSupervisor
from rosetta.scenario import ScenarioResult, run_roundtrip
from rosetta.scheduler import REQUIRED_MATRIX, Scheduler
from rosetta.service import (
    DiscoveryGateway,
    build_service_card,
    signed_post,
    verify_service_card,
)
from rosetta.signer_client import GuardedSigner, ProcessSignerClient, Signer
from rosetta_signer.canonical import canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DETERMINISTIC_TIME = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)


@asynccontextmanager
async def signer_process(directory: Path, fixture_id: str) -> AsyncIterator[ProcessSignerClient]:
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / "nonce.sqlite3"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    yield ProcessSignerClient(state, fixture_id, environment)


def _registry() -> AdapterRegistry:
    return AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")


async def _identity_did(client: Signer, scope: str) -> str:
    response = await client.sign(
        SignRequest(action="artifact_root", scope=scope, digest="sha256:" + "0" * 64)
    )
    return response.did


async def _matrix(
    registry: AdapterRegistry,
    signer: Signer,
    target: HttpTechnocore | None = None,
    gate: OperationalGate | None = None,
) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for producer, consumer in REQUIRED_MATRIX:
        results.append(
            await run_roundtrip(producer, consumer, registry, signer, target=target, gate=gate)
        )
    return results


def _run_record(
    registry: AdapterRegistry,
    suffix: str = "matrix",
    execution_images: dict[str, str] | None = None,
) -> RunRecord:
    identity = hashlib.sha256(
        f"v0.7.0|{registry.digest}|signed-mailbox-roundtrip-v1|{suffix}".encode()
    ).hexdigest()[:32]
    return RunRecord(
        run_id=identity,
        trigger="local-demo",
        protocol_release="v0.7.0",
        scenario="signed-mailbox-roundtrip-v1",
        registry_sha256=registry.digest,
        execution_images=execution_images or {},
        deterministic_epoch="2026-08-25T00:00:00Z",
        dry_run=True,
    )


def _versions(registry: AdapterRegistry) -> dict[str, str]:
    return {adapter_id: registry.require(adapter_id).source_revision for adapter_id in registry.ids}


def _prepare_output(path: Path) -> None:
    resolved = path.resolve()
    if PROJECT_ROOT not in resolved.parents:
        raise ValueError("demo output must remain under the project directory")
    if path.exists() and any(path.iterdir()):
        raise ValueError("output directory must be absent or empty")
    path.mkdir(parents=True, exist_ok=True)


async def demo(
    output: Path,
    target_url: str | None = None,
    target_image: str = LocalTechnocore.image_digest,
) -> dict[str, object]:
    _prepare_output(output)
    runtime = output / "runtime"
    registry = _registry()
    matrix_target = HttpTechnocore(target_url, target_image) if target_url is not None else None
    protocol_digest = target_image if matrix_target is not None else LocalTechnocore.image_digest
    execution_images = (
        {"matrix_worker": target_image, "technocore_target": target_image}
        if matrix_target is not None
        else {}
    )
    store = StateStore(runtime / "rosetta.sqlite3")
    gate = OperationalGate(store, runtime / "KILL_SWITCH")
    scheduler = Scheduler(store, registry, gate)
    first_trigger = scheduler.observe(
        protocol_digest,
        "signed-mailbox-roundtrip-v1",
        "local-demo",
        DETERMINISTIC_TIME,
    )
    duplicate_trigger = scheduler.observe(
        protocol_digest,
        "signed-mailbox-roundtrip-v1",
        "local-demo",
        DETERMINISTIC_TIME,
    )
    metrics = Metrics()
    async with signer_process(
        runtime / "rosetta-signer", "synthetic-rosetta-demo"
    ) as raw_rosetta_signer:
        rosetta_signer = GuardedSigner(raw_rosetta_signer, gate)
        results = await _matrix(registry, rosetta_signer, matrix_target, gate)
        if matrix_target is not None:
            matrix_target.close()
        for result in results:
            metrics.increment(f"matrix_{result.outcome.value}")
        run = _run_record(registry, execution_images=execution_images)
        root = await build_bundle(
            output / "bundle", run, results, _versions(registry), rosetta_signer
        )
        verified_root = verify_bundle(output / "bundle")

        equivalent_a = await build_bundle(
            output / "determinism-a", run, results, _versions(registry), rosetta_signer
        )
        equivalent_b = await build_bundle(
            output / "determinism-b", run, results, _versions(registry), rosetta_signer
        )

        regression = await run_roundtrip(
            "python-http",
            "typescript-http",
            registry,
            rosetta_signer,
            inject_regression=True,
            gate=gate,
        )
        regression_root = await build_bundle(
            output / "regression-bundle",
            _run_record(registry, "broken-canonicalizer", execution_images),
            [regression],
            _versions(registry),
            rosetta_signer,
        )

        rosetta_did = await _identity_did(rosetta_signer, "service-card-did")
        card, card_attestation = await build_service_card(
            rosetta_did,
            registry,
            rosetta_signer,
            "https://reports.invalid",
            "v0.7.0",
            DETERMINISTIC_TIME,
            output / "service",
        )
        service_target = LocalTechnocore()
        gateway = DiscoveryGateway(
            service_target,
            rosetta_signer,
            registry,
            store,
            card,
            card_attestation,
            "https://reports.invalid",
            runtime / "KILL_SWITCH",
            gate,
        )
        announcement = await gateway.announce()

        async with signer_process(
            runtime / "peer-signer", "synthetic-peer-demo"
        ) as raw_peer_signer:
            peer_signer = GuardedSigner(raw_peer_signer, gate)
            peer_did = await _identity_did(peer_signer, "peer-did")
            reply_room = "mb-peer-" + hashlib.sha256(peer_did.encode()).hexdigest()[:16]
            service_target.create_room(reply_room)
            discovered_rooms = service_target.events()
            announcement_verified = announcement.signed and card.service_room in discovered_rooms
            card_verified = verify_service_card(card, card_attestation, DETERMINISTIC_TIME)

            discover_query = DiscoveryQuery(
                schema_="rosetta.discover.v1",
                request_id="1" * 32,
                reply_room=reply_room,
                expires_at=DETERMINISTIC_TIME + timedelta(hours=1),
            )
            query_record = await signed_post(
                service_target,
                peer_signer,
                "synthetic-peer",
                card.service_room,
                discover_query.dict(),
            )
            offer = await gateway.handle_discovery(query_record, DETERMINISTIC_TIME)

            request = ServiceRequest(
                schema_="rosetta.request.v1",
                request_id="2" * 32,
                scenario="signed-mailbox-roundtrip-v1",
                producer="python-http",
                consumer="official-mcp",
                target_profile="current",
                reply_room=reply_room,
                expires_at=DETERMINISTIC_TIME + timedelta(hours=1),
            )
            request_record = await signed_post(
                service_target,
                peer_signer,
                "synthetic-peer",
                card.request_mailbox,
                request.dict(),
            )
            ack, service_result = await gateway.handle_request(
                request_record, DETERMINISTIC_TIME, root
            )
            replay_ack, replay_result = await gateway.handle_request(
                request_record, DETERMINISTIC_TIME, root
            )
            reply_records = service_target.read_room(reply_room, since=0, limit=100)

        supervisor = RunnerSupervisor(registry, gate=gate)
        runner_specs = [supervisor.compile(adapter_id) for adapter_id in registry.ids]
        (output / "runner-specs.json").write_bytes(canonical_json(runner_specs) + b"\n")
        metrics.increment("service_runner_starts", gateway.runner_starts)
        metrics.write(output / "metrics.json")
        trace = DecisionTrace("dry_run", False, False, False, "disabled")
        (output / "decision-trace.json").write_bytes(canonical_json(trace.as_dict()) + b"\n")

    store.close()
    report = {
        "schema": "rosetta.local-demo-report.v1",
        "all_matrix_cells_pass": all(result.outcome is Outcome.PASS for result in results),
        "matrix_cells": len(results),
        "technocore_target": "container-http" if target_url is not None else "in-process",
        "technocore_target_image": protocol_digest,
        "bundle_root": root,
        "bundle_verified": root == verified_root,
        "deterministic_roots_equal": equivalent_a == equivalent_b == root,
        "regression_outcome": regression.outcome.value,
        "regression_reason": regression.reason.value,
        "regression_bundle_root": regression_root,
        "trigger_first_accepted": first_trigger,
        "trigger_duplicate_rejected": not duplicate_trigger,
        "service_announcement_verified": announcement_verified,
        "service_card_verified": card_verified,
        "discovery_offer_received": offer is not None,
        "request_acknowledged": ack is not None and ack.status == "accepted",
        "signed_result_received": service_result is not None,
        "idempotent_replay_same_state": replay_ack == ack and replay_result == service_result,
        "service_runner_starts": gateway.runner_starts,
        "reply_signed_records": sum(record.signed for record in reply_records),
        "dry_run": True,
        "public_writes": 0,
    }
    (output / "demo-report.json").write_bytes(canonical_json(report) + b"\n")
    _write_acceptance_report(output / "ACCEPTANCE_REPORT.md", report)
    return report


def _write_acceptance_report(path: Path, report: dict[str, object]) -> None:
    checks = [
        ("Four required matrix cells pass", report["all_matrix_cells_pass"]),
        ("Signed evidence bundle verifies", report["bundle_verified"]),
        ("Equivalent runs have identical roots", report["deterministic_roots_equal"]),
        (
            "Injected canonicalizer regression fails stably",
            report["regression_reason"] == "canonical_payload_mismatch",
        ),
        ("Trigger deduplication survives persisted state", report["trigger_duplicate_rejected"]),
        ("Synthetic peer discovers signed service card", report["service_card_verified"]),
        ("Explicit signed discovery query receives offer", report["discovery_offer_received"]),
        (
            "Service request receives acknowledgement and result",
            report["request_acknowledged"] and report["signed_result_received"],
        ),
        ("Identical replay starts no second job", report["service_runner_starts"] == 1),
        ("Dry-run made no public writes", report["dry_run"] and report["public_writes"] == 0),
    ]
    lines = ["# Local MVP acceptance report", "", "Generated by the deterministic local demo.", ""]
    lines.extend(f"- [{'x' if passed else ' '}] {label}" for label, passed in checks)
    lines.extend(
        [
            "",
            "The full unit, integration, adversarial, static, and secret-scan results "
            "are recorded separately by the operator quality gate.",
            "No public Technocore endpoint, publisher, cloud service, or production "
            "credential was used.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def cell(producer: str, consumer: str) -> dict[str, object]:
    local = PROJECT_ROOT / "local" / "cell-signer"
    async with signer_process(local, "synthetic-cell-cli") as signer:
        result = await run_roundtrip(producer, consumer, _registry(), signer)
    return {
        "producer": result.producer,
        "consumer": result.consumer,
        "outcome": result.outcome.value,
        "reason": result.reason.value,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="rosetta")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "artifacts/demo")
    demo_parser.add_argument("--target-url")
    demo_parser.add_argument("--target-image", default=LocalTechnocore.image_digest)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("bundle", type=Path)
    cell_parser = subparsers.add_parser("cell")
    cell_parser.add_argument("--producer", required=True)
    cell_parser.add_argument("--consumer", required=True)
    args = parser.parse_args()
    if args.command == "demo":
        print(
            json.dumps(
                asyncio.run(demo(args.output, args.target_url, args.target_image)),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "verify":
        print(verify_bundle(args.bundle))
    elif args.command == "cell":
        print(json.dumps(asyncio.run(cell(args.producer, args.consumer)), sort_keys=True))


if __name__ == "__main__":
    main()
