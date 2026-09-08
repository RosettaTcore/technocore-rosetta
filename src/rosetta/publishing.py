"""Narrow, disabled-by-default static artifact publisher boundary."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from rosetta.contracts import ServiceCard
from rosetta.evidence import verify_bundle
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.service import verify_service_card


class StaticPublisher:
    def __init__(
        self,
        enabled: bool,
        approved_spool: Path,
        approved_destination: Path,
        state: StateStore,
        gate: OperationalGate,
    ) -> None:
        self.enabled = enabled
        self.approved_spool = approved_spool.resolve()
        self.approved_destination = approved_destination.resolve()
        self.state = state
        self.gate = gate

    def publish(self, bundle: Path) -> Path:
        self.gate.require("publisher")
        if not self.enabled:
            raise RuntimeError("publisher_disabled")
        source = bundle.resolve()
        if self.approved_spool not in source.parents:
            raise ValueError("bundle is outside the approved spool")
        root = verify_bundle(source)
        destination = self.approved_destination / root.removeprefix("sha256:")
        if destination.exists():
            raise ValueError("bundle already published")
        self.approved_destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        if verify_bundle(destination) != root:
            shutil.rmtree(destination)
            raise RuntimeError("copied bundle failed verification")
        self.state.register_bundle(root, destination, datetime.now().astimezone())
        return destination


class ServiceDocumentPublisher:
    """Publish only the reviewed service document set, with the attestation last."""

    FILES = (
        "service-card.json",
        "schemas/rosetta-request-v1.json",
        "schemas/rosetta-result-v1.json",
        "skill.md",
        ".well-known/agent.json",
        "service-card.attestation.json",
    )

    def __init__(
        self,
        enabled: bool,
        approved_spool: Path,
        approved_destination: Path,
        gate: OperationalGate,
    ) -> None:
        self.enabled = enabled
        self.approved_spool = approved_spool.resolve()
        self.approved_destination = approved_destination.resolve()
        self.gate = gate

    def publish(self, source: Path, now: datetime) -> None:
        self.gate.require("publisher")
        if not self.enabled:
            raise RuntimeError("publisher_disabled")
        resolved = source.resolve()
        if self.approved_spool not in resolved.parents:
            raise ValueError("service documents are outside the approved spool")
        actual = tuple(
            path.relative_to(resolved).as_posix()
            for path in sorted(resolved.rglob("*"))
            if path.is_file()
        )
        if set(actual) != set(self.FILES):
            raise ValueError("service document set is not closed")
        card = ServiceCard.parse_raw((resolved / "service-card.json").read_bytes())
        attestation = json.loads((resolved / "service-card.attestation.json").read_bytes())
        if not verify_service_card(card, attestation, now):
            raise ValueError("service card attestation is invalid or expired")
        self.approved_destination.mkdir(parents=True, exist_ok=True)
        for relative in self.FILES:
            source_file = resolved / relative
            target = self.approved_destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(source_file.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                Path(temporary).chmod(0o644)
                Path(temporary).replace(target)
            except Exception:
                Path(temporary).unlink(missing_ok=True)
                raise
