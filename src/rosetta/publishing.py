"""Narrow, disabled-by-default static artifact publisher boundary."""

from __future__ import annotations

import shutil
from pathlib import Path

from rosetta.evidence import verify_bundle
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore


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
            raise ValueError("bundle root already published")
        self.approved_destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        if verify_bundle(destination) != root:
            shutil.rmtree(destination)
            raise RuntimeError("copied bundle failed verification")
        return destination
