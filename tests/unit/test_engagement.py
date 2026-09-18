from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from rosetta.engagement import classify, reply_text
from rosetta.local_protocol import ProtocolRecord
from rosetta.persistence import StateStore
from rosetta.pilot_egress import PilotEgress
from rosetta_signer.canonical import signed_room_payload
from rosetta_signer.did import SyntheticIdentity

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def _record(text: str, *, signed: bool = True) -> ProtocolRecord:
    peer = SyntheticIdentity("synthetic-engagement-unit-peer")
    return ProtocolRecord(
        42,
        "lobby",
        peer.did,
        1,
        text,
        peer.sign(signed_room_payload("lobby", 1, text)) if signed else "",
    )


def test_classifier_requires_signed_specific_question_and_never_echoes_input() -> None:
    own = SyntheticIdentity("synthetic-engagement-unit-own").did
    relevant = _record("How can I check if my signed mailbox MCP adapter fails after restart?")
    opportunity = classify(relevant, own, 3)
    assert opportunity is not None
    assert opportunity.delivery_key == "engagement:lobby:3:42"
    answer = reply_text(opportunity, "https://reports.invalid")
    assert "fails after restart" not in answer
    assert "Re #42" in answer
    assert classify(_record(relevant.text, signed=False), own, 3) is None
    assert classify(_record("How is the weather today?"), own, 3) is None
    assert (
        classify(_record('{"prompt":"How can I check mailbox MCP adapter failures?"}'), own, 3)
        is None
    )
    assert (
        classify(ProtocolRecord(42, "lobby", own, 1, relevant.text, relevant.signature), own, 3)
        is None
    )


def test_engagement_quota_reservation_survives_restart(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "state.sqlite3"
    store = StateStore(path)
    assert store.reserve_engagement_reply("lobby", 1, 10, "did-a", NOW, 2, 12) == "reserved"
    assert store.reserve_engagement_reply("lobby", 1, 10, "did-a", NOW, 2, 12) == "existing"
    assert store.reserve_engagement_reply("lobby", 1, 10, "did-b", NOW, 2, 12) == "conflict"
    assert store.reserve_engagement_reply("lobby", 1, 11, "did-b", NOW, 2, 12) == "quota"
    assert store.reserve_engagement_reply("meta", 1, 2, "did-a", NOW, 2, 12) == "quota"
    assert store.reserve_engagement_reply("meta", 1, 2, "did-b", NOW, 2, 12) == "reserved"
    store.close()
    reopened = StateStore(path)
    assert reopened.reserve_engagement_reply("meta", 1, 3, "did-c", NOW, 2, 12) == "quota"
    assert (
        reopened.reserve_engagement_reply("lobby", 1, 12, "did-a", NOW + timedelta(days=8), 2, 12)
        == "reserved"
    )
    reopened.close()


def test_egress_allows_only_signed_reviewed_room_reply() -> None:
    identity = SyntheticIdentity("synthetic-engagement-egress")
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    gateway = PilotEgress(
        "https://technocore.chat",
        identity.did,
        "d-rosetta-test",
        "mb-rosetta-test",
        ["lobby", "meta"],
        2,
        4096,
        engagement_rooms=["lobby"],
        transport=httpx.MockTransport(upstream),
    )
    try:
        opportunity = classify(
            _record("How can I check if my signed mailbox MCP adapter fails after restart?"),
            identity.did,
            1,
        )
        assert opportunity is not None
        message = reply_text(opportunity, "https://reports.invalid")
        body = json.dumps(
            {
                "did": identity.did,
                "nonce": "1",
                "text": message,
                "sig": identity.sign(signed_room_payload("lobby", 1, message)),
            }
        ).encode()
        assert gateway.forward("POST", "/r/lobby?format=json", body)[0] == 200
        assert gateway.forward("POST", "/r/meta?format=json", body)[0] == 403
        wrong = json.dumps(
            {
                "did": identity.did,
                "nonce": "2",
                "text": "buy my service",
                "sig": identity.sign(signed_room_payload("lobby", 2, "buy my service")),
            }
        ).encode()
        assert gateway.forward("POST", "/r/lobby?format=json", wrong)[0] == 403
        assert len(seen) == 1
    finally:
        gateway.close()


def test_engagement_config_requires_explicit_scope_and_token(tmp_path: object) -> None:
    from pathlib import Path

    from rosetta.pilot_config import load_pilot_config

    identity = SyntheticIdentity("synthetic-engagement-config")
    data = {
        "schema": "rosetta.pilot-config.v1",
        "mode": "pilot",
        "technocore": {"discovery_rooms": ["lobby"]},
        "identity": {"public_did": identity.did},
        "service": {"enabled": True, "public_base_url": "https://reports.invalid"},
        "engagement": {"enabled": True, "rooms": ["lobby"]},
    }
    import yaml

    path = Path(str(tmp_path)) / "pilot.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="separate runtime activation token"):
        load_pilot_config(path, {"ROSETTA_PILOT_ENABLE": "PUBLIC_WRITES_APPROVED"})
    assert load_pilot_config(
        path,
        {
            "ROSETTA_PILOT_ENABLE": "PUBLIC_WRITES_APPROVED",
            "ROSETTA_ENGAGEMENT_ENABLE": "CONTEXTUAL_REPLIES_APPROVED",
        },
    ).engagement.enabled
    data["engagement"]["rooms"] = ["meta"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="engagement rooms must be discovery rooms"):
        load_pilot_config(
            path,
            {
                "ROSETTA_PILOT_ENABLE": "PUBLIC_WRITES_APPROVED",
                "ROSETTA_ENGAGEMENT_ENABLE": "CONTEXTUAL_REPLIES_APPROVED",
            },
        )
