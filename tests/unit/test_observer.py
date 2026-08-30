from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import yaml

from rosetta import observer as observer_module
from rosetta.config import AppConfig, load_config
from rosetta.observer import (
    WATCHED_PATHS,
    EndpointEvidence,
    ObserverService,
    ProtocolObservation,
    ReadOnlyProbeClient,
    _atomic_json,
    _error_reason,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _documents() -> dict[str, tuple[str, bytes]]:
    manifest = {
        "name": "technocore-chat",
        "version": "0.7.0",
        "documentation": {
            "openapi": "https://technocore.chat/openapi.json",
            "manual": "https://technocore.chat/llms.txt",
        },
    }
    openapi = {
        "openapi": "3.1.0",
        "info": {"version": "0.7.0"},
        "paths": {path: {"get": {}} for path in WATCHED_PATHS},
    }
    return {
        "/healthz": ("text/plain; charset=utf-8", b"ok\n"),
        "/.well-known/agent.json": ("application/json", json.dumps(manifest).encode()),
        "/openapi.json": ("application/json", json.dumps(openapi).encode()),
    }


def _transport(
    documents: dict[str, tuple[str, bytes]] | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    payloads = documents or _documents()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        content_type, body = payloads[request.url.path]
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return httpx.MockTransport(handler), requests


def _client(transport: httpx.BaseTransport, limit: int = 1_048_576) -> ReadOnlyProbeClient:
    return ReadOnlyProbeClient(
        "https://fetch.invalid",
        "https://technocore.chat",
        "v0.7.0",
        2,
        limit,
        transport=transport,
    )


def _config(tmp_path: Path) -> AppConfig:
    data = yaml.safe_load((ROOT / "config/config.staging.example.yaml").read_text())
    data["observer"]["state_directory"] = str(tmp_path / "state")
    data["observer"]["evidence_directory"] = str(tmp_path / "evidence")
    data["operations"]["kill_switch_file"] = str(tmp_path / "state/KILL_SWITCH")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_config(path, {})


def test_probe_uses_only_closed_get_surface_and_is_deterministic() -> None:
    transport, requests = _transport()
    client = _client(transport)
    try:
        first = client.probe()
        second = client.probe()
        with pytest.raises(ValueError, match="allowlisted"):
            client._get("/r/lobby/say/rosetta/no")
    finally:
        client.close()
    assert first == second
    assert first.release == "0.7.0"
    assert first.protocol_digest.startswith("sha256:")
    assert [request.method for request in requests] == ["GET"] * 6
    assert [request.url.path for request in requests[:3]] == list(WATCHED_PATHS)
    assert all(request.url.host == "fetch.invalid" for request in requests)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ({"name": "other"}, "identity"),
        ({"version": "9.9.9"}, "release"),
        (
            {
                "documentation": {
                    "openapi": "https://evil.invalid/openapi.json",
                    "manual": "/llms.txt",
                }
            },
            "origin",
        ),
    ],
)
def test_probe_rejects_untrusted_manifest_authority(
    mutation: dict[str, object], error: str
) -> None:
    documents = _documents()
    manifest = json.loads(documents["/.well-known/agent.json"][1])
    manifest.update(mutation)
    documents["/.well-known/agent.json"] = ("application/json", json.dumps(manifest).encode())
    client = _client(_transport(documents)[0])
    try:
        with pytest.raises(RuntimeError, match=error):
            client.probe()
    finally:
        client.close()


def test_probe_rejects_redirect_wrong_type_and_size() -> None:
    redirect = httpx.MockTransport(lambda _request: httpx.Response(302, headers={"location": "/x"}))
    client = _client(redirect)
    with pytest.raises(RuntimeError, match="redirect"):
        client.probe()
    client.close()


@pytest.mark.parametrize(
    "path,content_type,body,error",
    [
        ("/.well-known/agent.json", "text/plain", b"{}", "content_type"),
        ("/.well-known/agent.json", "application/json", b"{", "invalid_json"),
        ("/.well-known/agent.json", "application/json", b"[]", "shape"),
    ],
)
def test_probe_rejects_invalid_json_documents(
    path: str, content_type: str, body: bytes, error: str
) -> None:
    documents = _documents()
    documents[path] = (content_type, body)
    client = _client(_transport(documents)[0])
    with pytest.raises(RuntimeError, match=error):
        client.probe()
    client.close()


@pytest.mark.parametrize(
    "mutation,error",
    [
        ({"info": {"version": "9.0.0"}}, "openapi_release"),
        ({"openapi": "2.0"}, "openapi_version"),
        ({"paths": {}}, "metadata_path"),
    ],
)
def test_probe_rejects_incompatible_openapi(mutation: dict[str, object], error: str) -> None:
    documents = _documents()
    openapi = json.loads(documents["/openapi.json"][1])
    openapi.update(mutation)
    documents["/openapi.json"] = ("application/json", json.dumps(openapi).encode())
    client = _client(_transport(documents)[0])
    with pytest.raises(RuntimeError, match=error):
        client.probe()
    client.close()


def test_probe_rejects_status_and_invalid_document_links() -> None:
    client = _client(httpx.MockTransport(lambda _request: httpx.Response(503)))
    with pytest.raises(RuntimeError, match="unexpected_status"):
        client.probe()
    client.close()

    for documentation, error in (
        (None, "documentation"),
        ({"openapi": 7, "manual": "/llms.txt"}, "authority_url"),
        ({"openapi": "/wrong", "manual": "/llms.txt"}, "authority_path"),
    ):
        documents = _documents()
        manifest = json.loads(documents["/.well-known/agent.json"][1])
        manifest["documentation"] = documentation
        documents["/.well-known/agent.json"] = (
            "application/json",
            json.dumps(manifest).encode(),
        )
        client = _client(_transport(documents)[0])
        with pytest.raises(RuntimeError, match=error):
            client.probe()
        client.close()

    documents = _documents()
    documents["/healthz"] = ("text/html", b"ok")
    client = _client(_transport(documents)[0])
    with pytest.raises(RuntimeError, match="health"):
        client.probe()
    client.close()

    documents = _documents()
    documents["/healthz"] = ("text/plain", b"x" * 1_025)
    client = _client(_transport(documents)[0], 1_024)
    with pytest.raises(RuntimeError, match="too_large"):
        client.probe()
    client.close()


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False
        endpoint = EndpointEvidence("/healthz", "sha256:" + "1" * 64, 3, "text/plain")
        self.observation = ProtocolObservation("0.7.0", "sha256:" + "2" * 64, (endpoint,))

    def probe(self) -> ProtocolObservation:
        if self.fail:
            raise httpx.ConnectError("sensitive upstream details")
        return self.observation

    def close(self) -> None:
        self.closed = True


def test_observer_persists_change_once_and_deduplicates_across_restart(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first_client = FakeClient()
    first = ObserverService(config, client=first_client, clock=lambda: NOW)  # type: ignore[arg-type]
    assert first.observe_once()["changed"] is True
    first.close()
    assert first_client.closed

    second_client = FakeClient()
    second = ObserverService(config, client=second_client, clock=lambda: NOW)  # type: ignore[arg-type]
    result = second.observe_once()
    latest = second.store.latest_protocol_observation()
    second.close()
    assert result["changed"] is False
    assert latest is not None and latest[3] == 2
    assert len(list((tmp_path / "evidence").glob("*.json"))) == 1
    health = json.loads((tmp_path / "state/health.json").read_text())
    assert health["status"] == "healthy" and health["public_writes"] == 0


def test_observer_kill_switch_and_failure_are_fail_closed_and_redacted(tmp_path: Path) -> None:
    config = _config(tmp_path)
    switch = Path(config.operations.kill_switch_file)
    switch.parent.mkdir(parents=True, exist_ok=True)
    switch.write_text("stop", encoding="utf-8")
    service = ObserverService(config, client=FakeClient(), clock=lambda: NOW)  # type: ignore[arg-type]
    service.run(once=True)
    service.close()
    assert json.loads((tmp_path / "state/health.json").read_text())["status"] == "stopped"

    switch.unlink()
    failing = ObserverService(config, client=FakeClient(fail=True), clock=lambda: NOW)  # type: ignore[arg-type]
    with pytest.raises(httpx.ConnectError):
        failing.observe_once()
    failing.close()
    raw_health = (tmp_path / "state/health.json").read_text()
    assert "sensitive upstream details" not in raw_health
    assert json.loads(raw_health)["reason"] == "ConnectError"
    assert _error_reason(RuntimeError("unexpected_status:/healthz:503")) == "unexpected_status"
    assert _error_reason(RuntimeError("external secret detail")) == "RuntimeError"


def test_observer_run_modes_stop_cleanly(tmp_path: Path) -> None:
    config = _config(tmp_path)
    successful = ObserverService(config, client=FakeClient(), clock=lambda: NOW)  # type: ignore[arg-type]
    successful.run(once=True)
    successful.request_stop()
    assert successful.stop_requested
    successful.close()

    class StopThenFail(FakeClient):
        def __init__(self, service_holder: list[ObserverService], error: Exception) -> None:
            super().__init__()
            self.service_holder = service_holder
            self.error = error

        def probe(self) -> ProtocolObservation:
            self.service_holder[0].request_stop()
            raise self.error

    for error in (RuntimeError("transient"), httpx.ConnectError("down")):
        holder: list[ObserverService] = []
        service = ObserverService(  # type: ignore[arg-type]
            config, client=StopThenFail(holder, error), clock=lambda: NOW
        )
        holder.append(service)
        service.run()
        service.close()

    for error in (RuntimeError("transient"), httpx.ConnectError("down")):
        failing_once = ObserverService(  # type: ignore[arg-type]
            config, client=FakeClient(fail=True), clock=lambda: NOW
        )
        failing_once.client.probe = (  # type: ignore[method-assign]
            lambda selected=error: (_ for _ in ()).throw(selected)
        )
        with pytest.raises(type(error)):
            failing_once.run(once=True)
        failing_once.close()


def test_observer_continuous_wait_honors_switch_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    service = ObserverService(config, client=FakeClient(), clock=lambda: NOW)  # type: ignore[arg-type]
    switch_checks = iter((False, True))
    monkeypatch.setattr(observer_module, "kill_switch_active", lambda _path: next(switch_checks))
    service.run()
    assert service.stop_requested
    service.close()

    service = ObserverService(config, client=FakeClient(), clock=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(observer_module, "kill_switch_active", lambda _path: False)
    monotonic = iter((0.0, 0.0, 0.0))
    monkeypatch.setattr(observer_module.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(observer_module.time, "sleep", lambda _seconds: service.request_stop())
    service.run()
    assert service.stop_requested
    service.close()


def test_observer_constructor_and_cli_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disabled = load_config(ROOT / "config/config.local.yaml", {})
    with pytest.raises(ValueError, match="disabled"):
        ObserverService(disabled)

    config = _config(tmp_path)
    real_client_service = ObserverService(config)
    real_client_service.close()

    calls: list[object] = []

    class FakeService:
        def __init__(self, loaded: AppConfig) -> None:
            assert loaded is config

        def request_stop(self, *args: object) -> None:
            calls.append(args)

        def run(self, *, once: bool = False) -> None:
            calls.append(once)

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(observer_module, "load_config", lambda _path: config)
    monkeypatch.setattr(observer_module, "ObserverService", FakeService)
    monkeypatch.setattr(observer_module.signal, "signal", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["rosetta-observer", "--config", "x", "--once"])
    observer_module.main()
    assert True in calls and "closed" in calls


def test_atomic_json_replaces_and_cleans_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "nested/value.json"
    _atomic_json(path, {"b": 2})
    _atomic_json(path, {"a": 1})
    assert path.read_bytes() == b'{"a":1}\n'
    assert list(path.parent.iterdir()) == [path]


def test_atomic_json_removes_temporary_file_after_failed_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "value.json"
    monkeypatch.setattr(
        observer_module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("full"))
    )
    with pytest.raises(OSError, match="full"):
        _atomic_json(path, {"a": 1})
    assert list(tmp_path.iterdir()) == []
