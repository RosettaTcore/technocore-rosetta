from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

import rosetta.pilot_egress as pilot_egress_module
from rosetta.contracts import SignRequest, SignResponse
from rosetta.delivery import ReliableMessenger
from rosetta.local_protocol import ProtocolRecord, RateLimited, UncertainWrite
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.pilot_config import PilotConfig, load_pilot_config
from rosetta.pilot_egress import PilotEgress, handler_for
from rosetta.technocore_client import TechnocoreHttpClient, TechnocoreRefusal
from rosetta_signer.canonical import signed_note_payload, signed_room_payload
from rosetta_signer.did import SyntheticIdentity


def _config(tmp_path: Path) -> dict[str, Any]:
    return {
        "schema": "rosetta.pilot-config.v1",
        "mode": "pilot",
        "technocore": {},
        "identity": {
            "public_did": SyntheticIdentity("synthetic-pilot-config-edges").did,
            "signer_socket": str(tmp_path / "signer.sock"),
        },
        "service": {
            "enabled": False,
            "public_base_url": "https://reports.invalid",
            "state_directory": str(tmp_path / "state"),
            "spool_directory": str(tmp_path / "spool"),
            "static_root": str(tmp_path / "public"),
            "kill_switch_file": str(tmp_path / "KILL_SWITCH"),
        },
    }


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("technocore", "authority_origin", "http://technocore.chat", "HTTPS"),
        ("technocore", "authority_origin", "https://technocore.chat/path", "origin only"),
        ("technocore", "authority_origin", "https://u@technocore.chat", "origin only"),
        ("technocore", "fetch_origin", "ftp://localhost", "invalid pilot fetch"),
        ("technocore", "fetch_origin", "http://remote.invalid", "local egress"),
        ("technocore", "fetch_origin", "https://fetch.invalid/path", "origin only"),
        ("technocore", "discovery_rooms", [], "one to four"),
        ("technocore", "discovery_rooms", ["lobby", "lobby"], "unique"),
        ("technocore", "discovery_rooms", ["private"], "unreviewed"),
        ("technocore", "request_timeout_seconds", 1, "between 2 and 30"),
        ("technocore", "request_timeout_seconds", 31, "between 2 and 30"),
        ("technocore", "max_response_bytes", 100, "response limit"),
        ("technocore", "max_response_bytes", 5_000_000, "response limit"),
        ("identity", "signer_socket", "relative.sock", "absolute"),
        ("service", "public_base_url", "http://reports.invalid", "fixed HTTPS"),
        ("service", "public_base_url", "https://reports.invalid/path", "fixed HTTPS"),
        ("service", "public_base_url", "https://u:p@reports.invalid", "credentials"),
        ("service", "poll_seconds", 4, "between 5 and 300"),
        ("service", "poll_seconds", 301, "between 5 and 300"),
        ("service", "max_requests_per_did_per_day", 3, "cannot exceed 2"),
        ("service", "max_requests_per_did_per_day", 0, "cannot exceed 2"),
        ("service", "max_external_jobs_per_day", 9, "cannot exceed 8"),
        ("service", "max_external_jobs_per_day", 0, "cannot exceed 8"),
        ("service", "max_queue_depth", 17, "cannot exceed 16"),
        ("service", "max_queue_depth", 0, "cannot exceed 16"),
        ("service", "monthly_budget_cents", -1, "cannot exceed 4000"),
        ("service", "monthly_budget_cents", 4001, "cannot exceed 4000"),
        ("service", "state_directory", "relative", "absolute"),
    ],
)
def test_pilot_config_rejects_every_open_boundary(
    tmp_path: Path, section: str, field: str, value: object, message: str
) -> None:
    config = _config(tmp_path)
    config[section][field] = value
    with pytest.raises(ValueError, match=message):
        PilotConfig.parse_obj(config)


def test_pilot_config_loader_rejects_non_mapping_and_wrong_activation(tmp_path: Path) -> None:
    path = tmp_path / "pilot.yaml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_pilot_config(path, {})
    config = _config(tmp_path)
    config["service"]["enabled"] = True
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="activation token"):
        load_pilot_config(path, {"ROSETTA_PILOT_ENABLE": "wrong"})


def _client(
    handler: Any, *, maximum: int = 1_048_576, fetch_origin: str = "https://fetch.invalid"
) -> TechnocoreHttpClient:
    return TechnocoreHttpClient(
        fetch_origin,
        "https://technocore.chat",
        "v0.13.0",
        max_response_bytes=maximum,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://fetch.invalid",
        "http://fetch.invalid",
        "https://u:p@fetch.invalid",
        "https://fetch.invalid/path",
        "https://fetch.invalid?q=1",
        "https://fetch.invalid#fragment",
    ],
)
def test_client_rejects_non_fixed_origins(origin: str) -> None:
    with pytest.raises(ValueError):
        _client(lambda _request: httpx.Response(200), fetch_origin=origin)


def test_client_constructor_and_helpers_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        _client(lambda _request: httpx.Response(200), maximum=100)
    client = _client(lambda _request: httpx.Response(200))
    client.inject_rate_limit_once("a", "b")
    client.inject_uncertain_write_once("a", "b")
    client.create_room("valid-room")
    with pytest.raises(ValueError, match="room"):
        client.create_room("INVALID")
    client.close()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(302, headers={"location": "https://evil.invalid"}), "redirect"),
        (httpx.Response(500, headers={"content-type": "application/json"}), "upstream"),
        (httpx.Response(200, headers={"content-type": "text/plain"}, content=b"{}"), "content"),
        (httpx.Response(200, headers={"content-type": "application/json"}, content=b"{"), "json"),
        (httpx.Response(200, headers={"content-type": "application/json"}, json=[]), "shape"),
    ],
)
def test_client_normalizes_bad_http_responses(response: httpx.Response, message: str) -> None:
    client = _client(lambda _request: response)
    with pytest.raises(TechnocoreRefusal, match=message):
        client.read_room("lobby")
    client.close()


def test_client_rejects_oversized_response_and_non_numeric_rate_limit() -> None:
    large = _client(
        lambda _request: httpx.Response(
            200, headers={"content-type": "application/json"}, content=b"x" * 1025
        ),
        maximum=1024,
    )
    with pytest.raises(TechnocoreRefusal, match="too_large"):
        large.read_room("lobby")
    large.close()
    limited = _client(lambda _request: httpx.Response(429, headers={"retry-after": "later"}))
    with pytest.raises(RateLimited) as caught:
        limited.read_room("lobby")
    assert caught.value.retry_after_seconds == 3
    limited.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"room": "wrong", "messages": []},
        {"room": "lobby", "messages": {}},
        {"room": "lobby", "messages": ["bad"]},
        {"room": "lobby", "messages": [{"seq": 0, "from": "did", "text": "x"}]},
        {"room": "lobby", "messages": [{"seq": 1, "from": 1, "text": "x"}]},
        {"room": "lobby", "messages": [{"seq": 1, "from": "did", "text": 1}]},
        {"room": "lobby", "messages": [{"seq": 1, "from": "did", "text": "x", "nonce": "1"}]},
        {"room": "lobby", "messages": [{"seq": 1, "from": "did", "text": "x" * 4097}]},
        {
            "room": "lobby",
            "messages": [
                {"seq": 2, "from": "did", "text": "a"},
                {"seq": 1, "from": "did", "text": "b"},
            ],
        },
    ],
)
def test_client_rejects_malformed_room_views(payload: dict[str, object]) -> None:
    client = _client(
        lambda _request: httpx.Response(
            200, headers={"content-type": "application/json"}, json=payload
        )
    )
    with pytest.raises(TechnocoreRefusal):
        client.read_room("lobby")
    client.close()


@pytest.mark.parametrize(("since", "limit"), [(-1, 1), (0, 0), (0, 201)])
def test_client_rejects_unbounded_room_cursors(since: int, limit: int) -> None:
    client = _client(lambda _request: httpx.Response(500))
    with pytest.raises(ValueError, match="cursor"):
        client.read_room("lobby", since=since, limit=limit)
    client.close()


def test_client_reconcile_detects_duplicate_delivery() -> None:
    identity = SyntheticIdentity("synthetic-duplicate-client")
    did = identity.did
    signature = identity.sign(signed_room_payload("lobby", 1, "same"))
    payload = {
        "room": "lobby",
        "generation": 1,
        "last_seq": 2,
        "messages": [
            {"seq": 1, "from": did, "nonce": 1, "text": "same", "sig": signature},
            {"seq": 2, "from": did, "nonce": 1, "text": "same", "sig": signature},
        ],
    }
    client = _client(
        lambda _request: httpx.Response(
            200, headers={"content-type": "application/json"}, json=payload
        )
    )
    with pytest.raises(RuntimeError, match="duplicate"):
        client.reconcile("lobby", did, 1, "same")
    client.close()


def test_client_verifies_signed_records_and_tracks_room_generation() -> None:
    identity = SyntheticIdentity("synthetic-v013-read-signature")
    signature = identity.sign(signed_room_payload("lobby", 7, "verified"))

    def response(sig: str) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "room": "lobby",
                "generation": 3,
                "last_seq": 4,
                "messages": [
                    {
                        "seq": 4,
                        "from": identity.did,
                        "nonce": 7,
                        "text": "verified",
                        "sig": sig,
                    }
                ],
            },
        )

    valid = _client(lambda _request: response(signature))
    assert valid.read_room("lobby")[0].signed
    assert valid.room_generation("lobby") == 3
    assert valid.room_generation("unread") is None
    valid.close()

    invalid = _client(lambda _request: response("A" * 86))
    with pytest.raises(TechnocoreRefusal, match="signature"):
        invalid.read_room("lobby")
    invalid.close()


@pytest.mark.parametrize(
    "view",
    [
        {"room": "lobby", "generation": -1, "last_seq": 0, "messages": []},
        {"room": "lobby", "generation": "1", "last_seq": 0, "messages": []},
        {"room": "lobby", "generation": 1, "last_seq": -1, "messages": []},
    ],
)
def test_client_rejects_invalid_v013_room_metadata(view: dict[str, object]) -> None:
    client = _client(
        lambda _request: httpx.Response(
            200, headers={"content-type": "application/json"}, json=view
        )
    )
    with pytest.raises(TechnocoreRefusal, match="room_view"):
        client.read_room("lobby")
    client.close()


@pytest.mark.parametrize(
    ("posted", "message"),
    [
        (None, "missing"),
        ({"seq": 1, "from": "wrong", "nonce": 1, "text": "hello"}, "mismatch"),
        ({"seq": "1", "from": "DID", "nonce": 1, "text": "hello"}, "mismatch"),
    ],
)
def test_client_rejects_invalid_post_confirmation(posted: object, message: str) -> None:
    identity = SyntheticIdentity("synthetic-post-client")
    signature = identity.sign(signed_room_payload("lobby", 1, "hello"))
    body = {} if posted is None else {"posted": posted}
    if isinstance(posted, dict) and posted.get("from") == "DID":
        posted["from"] = identity.did
    if isinstance(posted, dict):
        posted["sig"] = signature
    client = _client(
        lambda _request: httpx.Response(
            200, headers={"content-type": "application/json"}, json=body
        )
    )
    with pytest.raises(TechnocoreRefusal, match=message):
        client.post_signed("actor", "lobby", identity.did, 1, "hello", signature)
    client.close()


@pytest.mark.parametrize(
    ("did", "nonce", "text", "signature"),
    [
        ("bad", 1, "x", "sig"),
        (SyntheticIdentity("synthetic-valid-post").did, 0, "x", "sig"),
        (SyntheticIdentity("synthetic-valid-post-2").did, 1, "x" * 4097, "sig"),
        (SyntheticIdentity("synthetic-valid-post-3").did, 1, "x", ""),
    ],
)
def test_client_rejects_invalid_signed_post(
    did: str, nonce: int, text: str, signature: str
) -> None:
    client = _client(lambda _request: httpx.Response(500))
    with pytest.raises(ValueError, match="signed"):
        client.post_signed("actor", "lobby", did, nonce, text, signature)
    client.close()


def test_client_reconciles_transport_failure_without_resigning() -> None:
    identity = SyntheticIdentity("synthetic-uncertain-client")
    signature = identity.sign(signed_room_payload("lobby", 2, "hello"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            raise httpx.ConnectError("lost", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "room": "lobby",
                "generation": 1,
                "last_seq": 9,
                "messages": [
                    {
                        "seq": 9,
                        "from": identity.did,
                        "nonce": 2,
                        "text": "hello",
                        "sig": signature,
                    }
                ],
            },
        )

    client = _client(handler)
    record = client.post_signed("actor", "lobby", identity.did, 2, "hello", signature)
    assert record.sequence == 9 and record.signature == signature
    client.close()


@pytest.mark.parametrize("reconcile_error", [False, True])
def test_client_fails_closed_when_uncertain_write_cannot_reconcile(
    reconcile_error: bool,
) -> None:
    identity = SyntheticIdentity("synthetic-unresolved-client")
    signature = identity.sign(signed_room_payload("lobby", 2, "hello"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" or reconcile_error:
            raise httpx.ConnectError("lost", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"room": "lobby", "generation": 0, "last_seq": 0, "messages": []},
        )

    client = _client(handler)
    with pytest.raises(UncertainWrite):
        client.post_signed("actor", "lobby", identity.did, 2, "hello", signature)
    client.close()


def test_client_note_paths_are_closed_and_normalized() -> None:
    identity = SyntheticIdentity("synthetic-note-client")
    with pytest.raises(ValueError, match="namespace"):
        _client(lambda _request: httpx.Response(500)).read_note("other", "key")
    for response, expected in [
        (httpx.Response(404), None),
        (httpx.Response(503), TechnocoreRefusal),
        (httpx.Response(200, headers={"content-type": "application/json"}), TechnocoreRefusal),
        (
            httpx.Response(200, headers={"content-type": "text/plain"}, content=b"missing"),
            TechnocoreRefusal,
        ),
        (
            httpx.Response(200, headers={"content-type": "text/plain"}, content=b"\xff"),
            UnicodeDecodeError,
        ),
    ]:
        client = _client(lambda _request, response=response: response)
        if expected is None:
            assert client.read_note("room-owners", "key") is None
        else:
            with pytest.raises(expected):
                client.read_note("room-owners", "key")
        client.close()

    client = _client(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("lost", request=request))
    )
    note_signature = identity.sign(signed_note_payload("room-owners", "key", 1, identity.did))
    with pytest.raises(UncertainWrite):
        client.post_signed_note("room-owners", "key", identity.did, 1, identity.did, note_signature)
    client.close()
    with pytest.raises(ValueError, match="namespace"):
        _client(lambda _request: httpx.Response(500)).post_signed_note(
            "other", "key", identity.did, 1, identity.did, "x" * 86
        )
    for nonce, signature, value in [
        (0, "sig", identity.did),
        (1, "", identity.did),
        (1, "sig", "x" * 8193),
    ]:
        client = _client(lambda _request: httpx.Response(500))
        with pytest.raises(ValueError, match="signed"):
            client.post_signed_note("room-owners", "key", identity.did, nonce, value, signature)
        client.close()


def _egress(handler: Any | None = None, *, maximum: int = 1024) -> tuple[PilotEgress, str]:
    did = SyntheticIdentity("synthetic-egress-edges").did
    transport = httpx.MockTransport(handler) if handler is not None else None
    return (
        PilotEgress(
            "https://technocore.chat",
            did,
            "d-rosetta-edge",
            "mb-rosetta-edge",
            ["lobby"],
            2,
            maximum,
            transport=transport,
        ),
        did,
    )


@pytest.mark.parametrize(
    "origin",
    ["http://technocore.chat", "https://technocore.chat/path", "https://u@technocore.chat"],
)
def test_egress_rejects_invalid_origin(origin: str) -> None:
    did = SyntheticIdentity("synthetic-egress-origin").did
    with pytest.raises(ValueError):
        PilotEgress(origin, did, "room", "mb-room", ["lobby"], 2, 1024)


def test_egress_rejects_invalid_identity_and_room() -> None:
    with pytest.raises(ValueError, match="DID"):
        PilotEgress("https://technocore.chat", "bad", "room", "mb-room", [], 2, 1024)
    did = SyntheticIdentity("synthetic-egress-room").did
    with pytest.raises(ValueError, match="room"):
        PilotEgress("https://technocore.chat", did, "BAD", "mb-room", [], 2, 1024)


@pytest.mark.parametrize(
    "target",
    [
        "/healthz?x=1",
        "/kv/room-owners/d-rosetta-edge?x=1",
        "/r/lobby?format=json&broken",
        "/r/lobby?format=html",
        "/r/lobby?format=json&extra=1",
        "/r/lobby?format=json&since=-1",
        "/r/lobby?format=json&limit=201",
        "/r/lobby?format=json&wait=21",
        "/r/lobby?format=json&limit=1&limit=2",
        "/r/not-allowed?format=json",
        "/r/BAD?format=json",
        "/not-a-room?format=json",
    ],
)
def test_egress_rejects_unreviewed_reads(target: str) -> None:
    egress, _ = _egress(lambda _request: httpx.Response(200))
    assert egress.forward("GET", target)[0] == 403
    egress.close()


def _signed_body(writer_did: str, **updates: object) -> bytes:
    identity = SyntheticIdentity("synthetic-egress-edges")
    assert identity.did == writer_did
    payload: dict[str, object] = {
        "did": writer_did,
        "sig": identity.sign(signed_room_payload("d-rosetta-edge", 1, "ok")),
        "nonce": "1",
        "text": "ok",
    }
    payload.update(updates)
    return json.dumps(payload).encode()


@pytest.mark.parametrize(
    "target,body",
    [
        ("/r/d-rosetta-edge", b"{"),
        ("/r/d-rosetta-edge", b"[]"),
        ("/r/private", b"{}"),
        ("/not-room", b"{}"),
    ],
)
def test_egress_rejects_malformed_write_targets(target: str, body: bytes) -> None:
    egress, _ = _egress(lambda _request: httpx.Response(200))
    assert egress.forward("POST", target + "?format=json", body)[0] == 403
    egress.close()


@pytest.mark.parametrize(
    "updates",
    [
        {"did": "bad"},
        {"extra": True},
        {"sig": "short"},
        {"sig": 1},
        {"nonce": 1},
        {"nonce": "x"},
        {"nonce": "1" * 20},
        {"text": ""},
        {"text": 1},
        {"text": "x" * 4097},
        {"if_absent": True},
    ],
)
def test_egress_rejects_mutated_signed_messages(updates: dict[str, object]) -> None:
    egress, did = _egress(lambda _request: httpx.Response(200))
    assert (
        egress.forward("POST", "/r/d-rosetta-edge?format=json", _signed_body(did, **updates))[0]
        == 403
    )
    egress.close()


def test_egress_note_policy_and_upstream_failures() -> None:
    egress, did = _egress(
        lambda _request: httpx.Response(200, headers={"retry-after": "2"}, content=b"ok")
    )
    identity = SyntheticIdentity("synthetic-egress-edges")
    note = json.dumps(
        {
            "did": did,
            "sig": identity.sign(signed_note_payload("room-owners", "d-rosetta-edge", 1, did)),
            "nonce": "1",
            "value": did,
            "if_absent": True,
        }
    ).encode()
    assert egress.forward("POST", "/kv/room-owners/d-rosetta-edge?format=json", note) == (
        200,
        "application/octet-stream",
        b"ok",
        "2",
    )
    wrong = json.loads(note)
    wrong["value"] = "other"
    assert (
        egress.forward(
            "POST", "/kv/room-owners/d-rosetta-edge?format=json", json.dumps(wrong).encode()
        )[0]
        == 403
    )
    wrong["value"] = did
    wrong["if_absent"] = False
    assert (
        egress.forward(
            "POST", "/kv/room-owners/d-rosetta-edge?format=json", json.dumps(wrong).encode()
        )[0]
        == 403
    )
    assert egress.forward("PUT", "/r/d-rosetta-edge?format=json", note)[0] == 403
    egress.close()

    redirect, _ = _egress(lambda _request: httpx.Response(302))
    assert redirect.forward("GET", "/healthz")[0] == 502
    redirect.close()
    large, _ = _egress(lambda _request: httpx.Response(200, content=b"x" * 1025))
    assert large.forward("GET", "/healthz")[0] == 502
    large.close()
    broken, _ = _egress(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("lost", request=request))
    )
    assert broken.forward("GET", "/healthz")[0] == 502
    broken.close()


def test_egress_http_handler_enforces_lengths_methods_and_headers() -> None:
    egress, did = _egress(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/json", "retry-after": "2"},
            content=b"{}",
        )
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(egress))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        connection = HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        assert (response.status, response.read(), response.getheader("Cache-Control")) == (
            200,
            b"{}",
            "no-store",
        )
        assert response.getheader("Retry-After") == "2"
        connection.request(
            "POST",
            "/r/d-rosetta-edge?format=json",
            body=_signed_body(did),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.request("PUT", "/healthz")
        response = connection.getresponse()
        assert response.status == 405
        response.read()
        connection.close()

        for header, expected in [("", 411), ("Content-Length: 20001\r\n", 413)]:
            with socket.create_connection((host, port), timeout=2) as raw:
                raw.sendall(
                    (
                        "POST /r/d-rosetta-edge?format=json HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        f"{header}"
                        "Connection: close\r\n\r\n"
                    ).encode()
                )
                status_line = raw.recv(128).split(b"\r\n", 1)[0]
                assert f" {expected} ".encode() in status_line
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        egress.close()


def test_egress_main_closes_server_and_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[str] = []

    class Gateway:
        def close(self) -> None:
            closed.append("gateway")

    class Server:
        def serve_forever(self, poll_interval: float) -> None:
            assert poll_interval == 0.5

        def server_close(self) -> None:
            closed.append("server")

    monkeypatch.setattr(pilot_egress_module, "PilotEgress", lambda *_args, **_kwargs: Gateway())
    monkeypatch.setattr(
        pilot_egress_module,
        "ThreadingHTTPServer",
        lambda _address, _handler: Server(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rosetta-pilot-egress",
            "--writer-did",
            SyntheticIdentity("synthetic-egress-main").did,
            "--service-room",
            "d-rosetta-main",
            "--request-mailbox",
            "mb-rosetta-main",
            "--discovery-room",
            "lobby",
        ],
    )
    pilot_egress_module.main()
    assert closed == ["server", "gateway"]


class _NoNonce:
    async def sign(self, _request: SignRequest) -> SignResponse:
        return SignResponse(
            did=SyntheticIdentity("synthetic-no-nonce-delivery").did,
            signature="x" * 86,
            signed_digest="sha256:" + "a" * 64,
            nonce=None,
        )


class _Target:
    def __init__(self, failures: list[Exception], reconcile: ProtocolRecord | None = None) -> None:
        self.failures = failures
        self.reconciled = reconcile

    def post_signed(self, *args: object) -> ProtocolRecord:
        if self.failures:
            raise self.failures.pop(0)
        return ProtocolRecord(
            7, str(args[1]), str(args[2]), int(args[3]), str(args[4]), str(args[5])
        )

    def reconcile(self, *_args: object) -> ProtocolRecord | None:
        return self.reconciled

    def read_room(self, room: str, *, since: int = 0, limit: int = 100) -> list[ProtocolRecord]:
        del room, since, limit
        return []


def test_delivery_fails_closed_on_nonce_rate_limit_and_refusal(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = StateStore(tmp_path / "state.sqlite3")
        gate = OperationalGate(store, tmp_path / "KILL_SWITCH")
        no_nonce = ReliableMessenger(_Target([]), _NoNonce(), store, gate)
        with pytest.raises(RuntimeError, match="nonce"):
            await no_nonce.send("nonce", "actor", "room", {"x": 1})

        from tests.unit.test_service_edges import AsyncSigner

        signer = AsyncSigner(tmp_path / "nonce.sqlite3", "synthetic-delivery-edges")
        limited = ReliableMessenger(_Target([RateLimited(3)]), signer, store, gate)
        with pytest.raises(RateLimited):
            await limited.send("slow", "actor", "room", {"x": 2})
        refused = ReliableMessenger(_Target([TechnocoreRefusal(500, "bad")]), signer, store, gate)
        with pytest.raises(TechnocoreRefusal):
            await refused.send("refused", "actor", "room", {"x": 3})
        missing = ReliableMessenger(_Target([UncertainWrite("lost")]), signer, store, gate)
        with pytest.raises(UncertainWrite, match="not found"):
            await missing.send("missing", "actor", "room", {"x": 4})
        signer.close()
        store.close()

    asyncio.run(exercise())


def test_delivery_reconciles_refusal_and_detects_corrupt_confirmation(tmp_path: Path) -> None:
    async def exercise() -> None:
        from tests.unit.test_service_edges import AsyncSigner

        store = StateStore(tmp_path / "state.sqlite3")
        gate = OperationalGate(store, tmp_path / "KILL_SWITCH")
        signer = AsyncSigner(tmp_path / "nonce.sqlite3", "synthetic-delivery-reconcile")
        did = signer.did
        reconciled = ProtocolRecord(9, "room", did, 1, "ignored", "sig")
        target = _Target([TechnocoreRefusal(409, "duplicate")], reconciled)
        messenger = ReliableMessenger(target, signer, store, gate)
        record = await messenger.send("reconciled", "actor", "room", {"x": 1})
        assert record.sequence == 9

        store.prepare_delivery("corrupt", "actor", "room", did, 4, "{}", "sig")
        store.connection.execute(
            "UPDATE outbound_deliveries SET status='confirmed', sequence=NULL "
            "WHERE delivery_key='corrupt'"
        )
        with pytest.raises(RuntimeError, match="missing_sequence"):
            await messenger.send("corrupt", "actor", "room", {})
        signer.close()
        store.close()

    asyncio.run(exercise())
