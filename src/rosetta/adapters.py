"""Narrow adapter protocol and the four reviewed local harness profiles."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rosetta.contracts import SignRequest
from rosetta.local_protocol import ProtocolRecord, RateLimited, TechnocoreTarget, UncertainWrite
from rosetta.registry import AdapterRegistry
from rosetta.signer_client import Signer

_RUNTIME_PROBE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class AdapterEvent:
    actor: str
    operation: str
    status: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class Checkpoint:
    cursors: dict[str, int]
    confirmations: list[str]


class FixtureAdapter:
    """Same semantic contract exposed through profile-specific transports."""

    def __init__(
        self,
        adapter_id: str,
        registry: AdapterRegistry,
        target: TechnocoreTarget,
        signer: Signer,
        role_scope: str,
    ) -> None:
        self.manifest = registry.require(adapter_id)
        self.target = target
        self.signer = signer
        self.role_scope = role_scope
        self.cursors: dict[str, int] = {}
        self.confirmations: list[str] = []
        self.events: list[AdapterEvent] = []

    def discover(self) -> dict[str, object]:
        capabilities = self.target.capabilities()
        runtime = _runtime_probe(self.manifest.id)
        self.events.append(
            AdapterEvent(
                self.manifest.id,
                "discover",
                "ok",
                {
                    "release": "v0.7.0",
                    "runtime": runtime["runtime"],
                    "transport": runtime["transport"],
                },
            )
        )
        return capabilities

    def read_room(self, room: str) -> list[ProtocolRecord]:
        since = self.cursors.get(room, 0)
        records = self.target.read_room(room, since=since, limit=100)
        if records:
            self.cursors[room] = max(record.sequence for record in records)
        self.events.append(
            AdapterEvent(
                self.manifest.id, "read_room", "ok", {"count": len(records), "since": since}
            )
        )
        return records

    async def post_signed(self, room: str, text: str) -> ProtocolRecord:
        response = await self.signer.sign(
            SignRequest(
                action="technocore_message",
                scope=self.role_scope,
                room=room,
                text=text,
            )
        )
        if response.nonce is None:
            raise RuntimeError("message signature did not include nonce")
        attempts = 0
        while attempts < 2:
            attempts += 1
            try:
                record = self.target.post_signed(
                    self.manifest.id,
                    room,
                    response.did,
                    response.nonce,
                    text,
                    response.signature,
                )
                self.events.append(
                    AdapterEvent(self.manifest.id, "post_signed", "ok", {"attempts": attempts})
                )
                return record
            except RateLimited as exc:
                self.events.append(
                    AdapterEvent(
                        self.manifest.id,
                        "post_signed",
                        "rate_limited",
                        {"retry_after": exc.retry_after_seconds, "attempt": attempts},
                    )
                )
                if exc.retry_after_seconds > 2 or attempts >= 2:
                    raise
            except UncertainWrite:
                matches = [
                    record
                    for record in self.target.read_room(room, since=0, limit=100)
                    if record.did == response.did and record.nonce == response.nonce
                ]
                if len(matches) != 1:
                    raise
                self.events.append(
                    AdapterEvent(
                        self.manifest.id,
                        "post_signed",
                        "reconciled",
                        {"matches": 1, "retry_performed": False},
                    )
                )
                return matches[0]
        raise RuntimeError("bounded retry exhausted")

    def checkpoint(self) -> Checkpoint:
        checkpoint = Checkpoint(dict(self.cursors), list(self.confirmations))
        self.events.append(AdapterEvent(self.manifest.id, "checkpoint", "ok", {}))
        return checkpoint

    def restore(self, checkpoint: Checkpoint) -> None:
        self.cursors = dict(checkpoint.cursors)
        self.confirmations = list(checkpoint.confirmations)
        self.events.append(AdapterEvent(self.manifest.id, "restore", "ok", {}))

    def confirm_once(self, correlation_id: str) -> bool:
        if correlation_id in self.confirmations:
            return False
        self.confirmations.append(correlation_id)
        self.events.append(AdapterEvent(self.manifest.id, "confirm", "ok", {"count": 1}))
        return True


def create_adapter(
    adapter_id: str,
    registry: AdapterRegistry,
    target: TechnocoreTarget,
    signer: Signer,
    role_scope: str,
) -> FixtureAdapter:
    return FixtureAdapter(adapter_id, registry, target, signer, role_scope)


def _runtime_probe(adapter_id: str) -> dict[str, Any]:
    """Execute only the reviewed local harness selected by a closed identifier."""
    root = Path(__file__).resolve().parents[2]
    commands = {
        "raw-fetch": ["node", str(root / "adapters/raw_fetch/index.mjs")],
        "official-mcp": ["node", str(root / "adapters/official_mcp/index.mjs")],
        "python-http": [sys.executable, str(root / "adapters/python_http/main.py")],
        "typescript-http": [
            "node",
            str(root / "adapters/typescript_http/index.mjs"),
        ],
    }
    try:
        command = commands[adapter_id]
    except KeyError as exc:
        raise ValueError("unallowlisted adapter runtime") from exc
    environment = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
    completed = subprocess.run(  # noqa: S603 - command is selected only from the closed map
        command,
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        # A cold Node.js process can exceed two seconds on a contended CI runner.
        # Keep the probe bounded while allowing deterministic cold starts.
        timeout=_RUNTIME_PROBE_TIMEOUT_SECONDS,
        text=True,
        input='{"operation":"capabilities"}',
    )
    if len(completed.stdout) > 4096:
        raise ValueError("adapter capability response is oversized")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict) or result.get("id") != adapter_id:
        raise ValueError("adapter returned a mismatched identity")
    return result
