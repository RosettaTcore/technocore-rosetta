from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import yaml

from rosetta.delivery import ReliableMessenger
from rosetta.local_protocol import LocalTechnocore, RateLimited
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.pilot_config import load_pilot_config
from rosetta.pilot_egress import PilotEgress
from rosetta.technocore_client import (
    TechnocoreHttpClient,
    TechnocoreRefusal,
    validate_room_name,
)
from rosetta_signer.canonical import signed_note_payload, signed_room_payload
from rosetta_signer.did import SyntheticIdentity
from tests.unit.test_service_edges import AsyncSigner

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def _metadata(path: str) -> httpx.Response:
    if path == "/healthz":
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok\n")
    if path == "/.well-known/agent.json":
        value = {
            "name": "technocore-chat",
            "version": "0.13.0",
            "documentation": {
                "openapi": "https://technocore.chat/openapi.json",
                "manual": "https://technocore.chat/llms.txt",
            },
        }
    else:
        value = {
            "openapi": "3.1.0",
            "info": {"version": "0.13.0"},
            "paths": {
                "/healthz": {},
                "/.well-known/agent.json": {},
                "/openapi.json": {},
            },
        }
    return httpx.Response(
        200, headers={"content-type": "application/json"}, content=json.dumps(value).encode()
    )


def test_production_client_has_fixed_bounded_protocol_surface() -> None:
    identity = SyntheticIdentity("synthetic-client")
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path in {"/healthz", "/.well-known/agent.json", "/openapi.json"}:
            return _metadata(request.url.path)
        if request.method == "GET" and request.url.path == "/r/mb-peer":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "room": "mb-peer",
                    "generation": 1,
                    "last_seq": 4,
                    "messages": [
                        {
                            "seq": 4,
                            "from": identity.did,
                            "nonce": 1,
                            "text": "hello",
                            "sig": identity.sign(signed_room_payload("mb-peer", 1, "hello")),
                        }
                    ],
                },
            )
        if request.method == "POST" and request.url.path == "/r/mb-peer":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "posted": {
                        "seq": 5,
                        "from": body["did"],
                        "nonce": int(body["nonce"]),
                        "text": body["text"],
                        "sig": body["sig"],
                    }
                },
            )
        if request.method == "GET" and request.url.path.startswith("/kv/room-owners/"):
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=("warning\n\n" + identity.did + "\n").encode(),
            )
        if request.method == "POST" and request.url.path.startswith("/kv/room-owners/"):
            return httpx.Response(
                200, headers={"content-type": "application/json"}, json={"stored": True}
            )
        raise AssertionError(str(request.url))

    client = TechnocoreHttpClient(
        "http://127.0.0.1:8082",
        "https://technocore.chat",
        "v0.13.0",
        transport=httpx.MockTransport(upstream),
    )
    try:
        assert client.capabilities()["release"] == "v0.13.0"
        records = client.read_room("mb-peer", since=3, limit=2)
        assert len(records) == 1 and records[0].signed and records[0].sequence == 4
        posted = client.post_signed(
            "actor",
            "mb-peer",
            identity.did,
            2,
            "result",
            identity.sign(signed_room_payload("mb-peer", 2, "result")),
        )
        assert posted.sequence == 5
        assert client.read_note("room-owners", "d-rosetta-test") == identity.did
        assert client.post_signed_note(
            "room-owners",
            "d-rosetta-test",
            identity.did,
            3,
            identity.did,
            identity.sign(signed_note_payload("room-owners", "d-rosetta-test", 3, identity.did)),
            if_absent=True,
        ) == {"stored": True}
    finally:
        client.close()
    assert all(request.url.host == "127.0.0.1" for request in requests)
    with pytest.raises(ValueError, match="room"):
        validate_room_name("Bad Room")
    with pytest.raises(ValueError, match="reviewed"):
        TechnocoreHttpClient("https://fetch.invalid", "https://technocore.chat", "v0.11.0")


def test_production_client_normalizes_refusal_and_rate_limit() -> None:
    limited = TechnocoreHttpClient(
        "https://fetch.invalid",
        "https://technocore.chat",
        "v0.13.0",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, headers={"retry-after": "999"})
        ),
    )
    with pytest.raises(RateLimited) as caught:
        limited.read_room("lobby")
    assert caught.value.retry_after_seconds == 60
    limited.close()
    invalid = TechnocoreHttpClient(
        "https://fetch.invalid",
        "https://technocore.chat",
        "v0.13.0",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"[]"
            )
        ),
    )
    with pytest.raises(TechnocoreRefusal, match="shape"):
        invalid.read_room("lobby")
    invalid.close()


def test_reliable_delivery_survives_rate_limit_uncertainty_and_restart(tmp_path: Path) -> None:
    async def exercise() -> None:
        target = LocalTechnocore()
        target.create_room("mb-peer")
        store = StateStore(tmp_path / "state.sqlite3")
        signer = AsyncSigner(tmp_path / "nonce.sqlite3", "synthetic-delivery")
        gate = OperationalGate(store, tmp_path / "KILL_SWITCH")
        slept: list[float] = []

        async def sleeper(seconds: float) -> None:
            slept.append(seconds)

        messenger = ReliableMessenger(target, signer, store, gate, sleeper=sleeper)
        target.inject_rate_limit_once("actor", "mb-peer")
        first = await messenger.send("one", "actor", "mb-peer", {"value": 1})
        assert slept == [1.0]
        again = await messenger.send("one", "actor", "mb-peer", {"value": 1})
        assert again.sequence == first.sequence
        target.inject_uncertain_write_once("actor", "mb-peer")
        uncertain = await messenger.send("two", "actor", "mb-peer", {"value": 2})
        assert uncertain.sequence > first.sequence
        with pytest.raises(RuntimeError, match="conflict"):
            await messenger.send("one", "actor", "mb-peer", {"value": 9})
        signer.close()
        store.close()

    asyncio.run(exercise())


def test_pilot_egress_rejects_open_proxy_behavior() -> None:
    identity = SyntheticIdentity("synthetic-egress")
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    egress = PilotEgress(
        "https://technocore.chat",
        identity.did,
        "d-rosetta-test",
        "mb-rosetta-test",
        ["lobby"],
        2,
        1024,
        transport=httpx.MockTransport(upstream),
    )
    try:
        assert egress.forward("GET", "/r/lobby?format=json&since=0&limit=2")[0] == 200
        assert egress.forward("GET", "/r/private?format=json")[0] == 403
        assert egress.forward("GET", "/r/lobby?bad=query")[0] == 403
        assert egress.forward("GET", "https://evil.invalid/r/lobby?format=json")[0] == 400
        body = json.dumps(
            {
                "did": identity.did,
                "sig": identity.sign(signed_room_payload("mb-peer", 1, "ok")),
                "nonce": "1",
                "text": "ok",
            }
        ).encode()
        assert egress.forward("POST", "/r/mb-peer?format=json", body)[0] == 200
        bad = json.dumps(
            {
                "did": SyntheticIdentity("synthetic-other").did,
                "sig": SyntheticIdentity("synthetic-other").sign(
                    signed_room_payload("mb-peer", 1, "x")
                ),
                "nonce": "1",
                "text": "x",
            }
        ).encode()
        assert egress.forward("POST", "/r/mb-peer?format=json", bad)[0] == 403
    finally:
        egress.close()
    assert len(seen) == 2


def test_pilot_config_is_closed_disabled_by_default_and_requires_activation(tmp_path: Path) -> None:
    did = SyntheticIdentity("synthetic-config").did
    config = {
        "schema": "rosetta.pilot-config.v1",
        "mode": "pilot",
        "technocore": {},
        "identity": {"public_did": did, "signer_socket": str(tmp_path / "signer.sock")},
        "service": {
            "enabled": False,
            "public_base_url": "https://reports.invalid",
            "state_directory": str(tmp_path / "state"),
            "spool_directory": str(tmp_path / "spool"),
            "static_root": str(tmp_path / "public"),
            "kill_switch_file": str(tmp_path / "KILL_SWITCH"),
        },
    }
    path = tmp_path / "pilot.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert not load_pilot_config(path, {}).service.enabled
    config["service"]["enabled"] = True
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="activation token"):
        load_pilot_config(path, {})
    assert load_pilot_config(
        path, {"ROSETTA_PILOT_ENABLE": "PUBLIC_WRITES_APPROVED"}
    ).service.enabled
    config["identity"]["public_did"] = "did:key:not-valid"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        load_pilot_config(path, {"ROSETTA_PILOT_ENABLE": "PUBLIC_WRITES_APPROVED"})
