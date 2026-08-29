"""Reproducible, checksummed, domain-attested evidence bundles."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rosetta.contracts import Attestation, MatrixCell, RunRecord, SignRequest
from rosetta.operations import redact
from rosetta.scenario import ScenarioResult
from rosetta.signer_client import Signer
from rosetta_signer.canonical import canonical_json
from rosetta_signer.did import artifact_payload, verify_signature

PAYLOAD_FILES = ("run.json", "matrix.json", "summary.md")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _event_chain(result: ScenarioResult) -> list[dict[str, Any]]:
    previous = "sha256:" + "0" * 64
    output: list[dict[str, Any]] = []
    for sequence, event in enumerate(result.events, 1):
        base = {
            "schema": "rosetta.evidence-event.v1",
            "sequence": sequence,
            "actor": event.actor,
            "operation": event.operation,
            "status": event.status,
            "correlation_id": result.reproduction.get("correlation_id", ""),
            "detail": redact(event.detail),
            "previous_hash": previous,
        }
        current = "sha256:" + _sha256(canonical_json(base))
        output.append({**base, "event_hash": current})
        previous = current
    return output


def _bundle_entries(bundle_dir: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file() or path.name in {"checksums.txt", "attestation.json"}:
            continue
        relative = path.relative_to(bundle_dir).as_posix()
        entries.append((relative, _sha256(path.read_bytes())))
    return entries


def compute_bundle_root(entries: Iterable[tuple[str, str]]) -> str:
    manifest = [{"path": path, "sha256": digest} for path, digest in sorted(entries)]
    return "sha256:" + _sha256(canonical_json(manifest))


async def build_bundle(
    bundle_dir: Path,
    run: RunRecord,
    results: list[ScenarioResult],
    registry_versions: dict[str, str],
    signer: Signer,
) -> str:
    if bundle_dir.exists() and any(bundle_dir.iterdir()):
        raise ValueError("bundle destination must be empty")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _write(bundle_dir / "run.json", canonical_json(run.dict()) + b"\n")
    cells: list[dict[str, Any]] = []
    for result in results:
        cell_name = f"{result.producer}--{result.consumer}"
        evidence_name = f"evidence/{cell_name}.json"
        cell = MatrixCell(
            producer=result.producer,
            consumer=result.consumer,
            outcome=result.outcome,
            reason=result.reason,
            protocol_release=run.protocol_release,
            scenario=run.scenario,
            adapter_versions={
                result.producer: registry_versions[result.producer],
                result.consumer: registry_versions[result.consumer],
            },
            assertions=result.assertions,
            evidence_file=evidence_name,
        )
        cells.append(cell.dict())
        _write(bundle_dir / evidence_name, canonical_json(_event_chain(result)) + b"\n")
        reproduction = canonical_json(result.reproduction) + b"\n"
        _write(bundle_dir / f"reproduce/{cell_name}.json", reproduction)
        if result.reproduction.get("mode") == "upstream_oci":
            command = "make upstream-acceptance\n"
        else:
            command = (
                "PYTHONPATH=src python3 -m rosetta.cli cell "
                f"--producer {result.producer} --consumer {result.consumer}\n"
            )
        _write(bundle_dir / f"reproduce/{cell_name}.txt", command.encode())
    _write(
        bundle_dir / "matrix.json",
        canonical_json({"schema": "rosetta.matrix.v1", "cells": cells}) + b"\n",
    )
    passed = sum(result.outcome.value == "pass" for result in results)
    failed = sum(result.outcome.value == "fail" for result in results)
    summary = (
        "# Rosetta local observation\n\n"
        f"Scenario: `{run.scenario}`\n\n"
        f"Observed cells: {len(results)}; pass: {passed}; fail: {failed}.\n\n"
        "This artifact reports bounded observed behavior. It is not a claim of trust, "
        "safety, endorsement, official status, or eligibility.\n"
    )
    _write(bundle_dir / "summary.md", summary.encode())
    entries = _bundle_entries(bundle_dir)
    checksums = "".join(f"{digest}  {path}\n" for path, digest in entries)
    _write(bundle_dir / "checksums.txt", checksums.encode())
    root = compute_bundle_root(entries)
    signed = await signer.sign(SignRequest(action="artifact_root", scope="bundle", digest=root))
    attestation = Attestation(did=signed.did, bundle_root=root, signature=signed.signature)
    _write(bundle_dir / "attestation.json", canonical_json(attestation.dict()) + b"\n")
    return root


def verify_bundle(bundle_dir: Path) -> str:
    checksum_lines = (bundle_dir / "checksums.txt").read_text(encoding="utf-8").splitlines()
    expected: list[tuple[str, str]] = []
    for line in checksum_lines:
        digest, relative = line.split("  ", 1)
        path = bundle_dir / relative
        if not path.is_file() or _sha256(path.read_bytes()) != digest:
            raise ValueError(f"checksum mismatch: {relative}")
        expected.append((relative, digest))
    actual = _bundle_entries(bundle_dir)
    if actual != sorted(expected):
        raise ValueError("bundle file set differs from checksums")
    root = compute_bundle_root(actual)
    attestation = Attestation.parse_raw((bundle_dir / "attestation.json").read_bytes())
    if attestation.bundle_root != root:
        raise ValueError("bundle root mismatch")
    if not verify_signature(attestation.did, artifact_payload(root), attestation.signature):
        raise ValueError("invalid bundle attestation")
    return root
