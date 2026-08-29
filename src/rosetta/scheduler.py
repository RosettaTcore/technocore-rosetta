"""Deterministic matrix compilation and restart-safe trigger deduplication."""

from __future__ import annotations

from datetime import datetime

from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore, trigger_key
from rosetta.registry import AdapterRegistry

REQUIRED_MATRIX: list[tuple[str, str]] = [
    ("raw-fetch", "official-mcp"),
    ("official-mcp", "python-http"),
    ("python-http", "typescript-http"),
    ("typescript-http", "raw-fetch"),
]


class Scheduler:
    def __init__(self, store: StateStore, registry: AdapterRegistry, gate: OperationalGate) -> None:
        self.store = store
        self.registry = registry
        self.gate = gate

    def compile_matrix(self) -> list[tuple[str, str]]:
        for producer, consumer in REQUIRED_MATRIX:
            self.registry.require(producer)
            self.registry.require(consumer)
        return list(REQUIRED_MATRIX)

    def observe(
        self,
        protocol_digest: str,
        scenario: str,
        trigger: str,
        now: datetime,
    ) -> bool:
        key = trigger_key(protocol_digest, self.registry.digest, scenario, trigger)
        self.gate.require("scheduler")
        accepted = self.store.register_trigger(key, now)
        if accepted:
            self.gate.reserve_run(now)
        return accepted
