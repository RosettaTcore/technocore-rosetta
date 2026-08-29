"""Deterministic signed-mailbox-roundtrip-v1 scenario engine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from rosetta.adapters import AdapterEvent, create_adapter
from rosetta.contracts import AssertionResult, Outcome, ReasonCode
from rosetta.local_protocol import LocalTechnocore, TechnocoreTarget, verify_record
from rosetta.operations import OperationalGate
from rosetta.registry import AdapterRegistry
from rosetta.signer_client import Signer
from rosetta_signer.canonical import canonical_json


@dataclass(frozen=True)
class ScenarioResult:
    producer: str
    consumer: str
    outcome: Outcome
    reason: ReasonCode
    assertions: list[AssertionResult]
    events: list[AdapterEvent]
    reproduction: dict[str, Any]


def _correlation(producer: str, consumer: str) -> str:
    return hashlib.sha256(
        f"signed-mailbox-roundtrip-v1:{producer}:{consumer}".encode()
    ).hexdigest()[:32]


async def run_roundtrip(
    producer_id: str,
    consumer_id: str,
    registry: AdapterRegistry,
    signer: Signer,
    *,
    inject_regression: bool = False,
    target: TechnocoreTarget | None = None,
    gate: OperationalGate | None = None,
) -> ScenarioResult:
    if gate is not None:
        gate.require("runner")
    producer_manifest = registry.require(producer_id)
    consumer_manifest = registry.require(consumer_id)
    required = {"discover", "read_room", "post_signed", "checkpoint", "restore"}
    missing = required - set(producer_manifest.capabilities) | required - set(
        consumer_manifest.capabilities
    )
    if missing:
        assertion = AssertionResult(
            name="capabilities",
            passed=False,
            reason=ReasonCode.UNSUPPORTED_CAPABILITY,
            detail=",".join(sorted(missing)),
        )
        return ScenarioResult(
            producer_id,
            consumer_id,
            Outcome.SKIP,
            ReasonCode.UNSUPPORTED_CAPABILITY,
            [assertion],
            [],
            {"missing": sorted(missing)},
        )

    active_target = LocalTechnocore() if target is None else target
    correlation_id = _correlation(producer_id, consumer_id)
    mailbox = "mb-fixture-" + correlation_id[:16]
    active_target.create_room(mailbox)
    active_target.inject_rate_limit_once(producer_id, mailbox)
    active_target.inject_uncertain_write_once(consumer_id, mailbox)
    producer = create_adapter(
        producer_id, registry, active_target, signer, f"producer:{producer_id}"
    )
    consumer = create_adapter(
        consumer_id, registry, active_target, signer, f"consumer:{consumer_id}"
    )

    assertions: list[AssertionResult] = []
    producer.discover()
    consumer.discover()
    request_body = {
        "schema": "fixture.roundtrip-request.v1",
        "correlation_id": correlation_id,
        "operation": "echo",
    }
    request_text = canonical_json(request_body).decode()
    request_record = await producer.post_signed(mailbox, request_text)
    assertions.append(
        AssertionResult(
            name="request_signature_valid",
            passed=verify_record(request_record),
            reason=ReasonCode.OK if verify_record(request_record) else ReasonCode.INVALID_SIGNATURE,
        )
    )

    received = consumer.read_room(mailbox)
    parsed = [json.loads(record.text) for record in received if record.signed]
    matches = [item for item in parsed if item.get("correlation_id") == correlation_id]
    assertions.append(
        AssertionResult(
            name="correlation_matches",
            passed=len(matches) == 1,
            reason=ReasonCode.OK if len(matches) == 1 else ReasonCode.CORRELATION_MISMATCH,
        )
    )

    result_body = {
        "schema": "fixture.roundtrip-result.v1",
        "correlation_id": correlation_id,
        "status": "ok",
    }
    result_text = canonical_json(result_body).decode()
    if inject_regression:
        assertions.append(
            AssertionResult(
                name="canonical_payload",
                passed=False,
                reason=ReasonCode.CANONICAL_PAYLOAD_MISMATCH,
                detail="injected field-order canonicalizer regression",
            )
        )
    result_record = await consumer.post_signed(mailbox, result_text)
    assertions.append(
        AssertionResult(
            name="result_signature_valid",
            passed=verify_record(result_record),
            reason=ReasonCode.OK if verify_record(result_record) else ReasonCode.INVALID_SIGNATURE,
        )
    )

    producer.read_room(mailbox)
    checkpoint = producer.checkpoint()
    restarted = create_adapter(
        producer_id, registry, active_target, signer, f"producer:{producer_id}"
    )
    restarted.restore(checkpoint)
    no_duplicates = restarted.read_room(mailbox) == []
    assertions.append(
        AssertionResult(
            name="restart_resumed_cursor",
            passed=no_duplicates,
            reason=ReasonCode.OK if no_duplicates else ReasonCode.CURSOR_RESUME_FAILED,
        )
    )
    first_confirmation = restarted.confirm_once(correlation_id)
    second_confirmation = restarted.confirm_once(correlation_id)
    exactly_once = first_confirmation and not second_confirmation
    assertions.append(
        AssertionResult(
            name="confirmation_exactly_once",
            passed=exactly_once,
            reason=ReasonCode.OK if exactly_once else ReasonCode.DUPLICATE_SUCCESS,
        )
    )
    producer_events = producer.events + restarted.events
    consumer_events = consumer.events
    bounded_backoff = sum(event.status == "rate_limited" for event in producer_events) == 1
    reconciled = sum(event.status == "reconciled" for event in consumer_events) == 1
    assertions.extend(
        [
            AssertionResult(
                name="rate_limit_backoff_bounded",
                passed=bounded_backoff,
                reason=ReasonCode.OK if bounded_backoff else ReasonCode.RATE_LIMIT_EXHAUSTED,
            ),
            AssertionResult(
                name="uncertain_write_reconciled",
                passed=reconciled,
                reason=ReasonCode.OK if reconciled else ReasonCode.UNCERTAIN_WRITE_UNRESOLVED,
            ),
        ]
    )
    failing = [assertion for assertion in assertions if not assertion.passed]
    outcome = Outcome.FAIL if failing else Outcome.PASS
    reason = failing[0].reason if failing else ReasonCode.OK
    return ScenarioResult(
        producer_id,
        consumer_id,
        outcome,
        reason,
        assertions,
        producer_events + consumer_events,
        {
            "schema": "rosetta.reproduction.v1",
            "scenario": "signed-mailbox-roundtrip-v1",
            "producer": producer_id,
            "consumer": consumer_id,
            "fault": "broken-canonicalizer" if inject_regression else "none",
            "correlation_id": correlation_id,
        },
    )
