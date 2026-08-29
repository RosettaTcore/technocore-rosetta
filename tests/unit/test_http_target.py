from __future__ import annotations

from typing import Any

import httpx
import pytest

from rosetta import http_target
from rosetta.http_target import HttpTechnocore
from rosetta.local_protocol import RateLimited, UncertainWrite


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://localhost/test")
            raise httpx.HTTPStatusError(
                "fixture error", request=request, response=httpx.Response(self.status_code)
            )


class FakeClient:
    def __init__(self, *args: object, health: Any = None, **kwargs: object) -> None:
        self.health = health or {"release": "v0.7.0", "status": "ok"}
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.closed = False
        self.next_get: FakeResponse | None = None
        self.next_post: FakeResponse | None = None

    def get(self, path: str, **kwargs: object) -> FakeResponse:
        if path == "/health":
            return FakeResponse(self.health)
        assert self.next_get is not None
        response, self.next_get = self.next_get, None
        return response

    def post(self, path: str, json: dict[str, object]) -> FakeResponse:
        self.posts.append((path, json))
        if self.next_post is not None:
            response, self.next_post = self.next_post, None
            return response
        return FakeResponse({})

    def close(self) -> None:
        self.closed = True


def _target(monkeypatch: pytest.MonkeyPatch, health: Any = None) -> HttpTechnocore:
    client = FakeClient(health=health)
    monkeypatch.setattr(http_target.httpx, "Client", lambda **kwargs: client)
    return HttpTechnocore("http://127.0.0.1:8080", "sha256:" + "a" * 64)


@pytest.mark.parametrize(
    "origin",
    [
        "https://technocore.chat",
        "http://evil.invalid",
        "http://127.0.0.1/path",
        "http://user:pass@127.0.0.1",
    ],
)
def test_container_target_rejects_nonlocal_or_nonorigin_urls(origin: str) -> None:
    with pytest.raises(ValueError):
        HttpTechnocore(origin, "sha256:" + "a" * 64)


def test_container_target_rejects_mutable_image_and_wrong_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="immutable"):
        HttpTechnocore("http://localhost", "latest")
    with pytest.raises(ValueError, match="identity"):
        _target(monkeypatch, {"release": "v0.8.0", "status": "ok"})


def test_http_target_complete_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _target(monkeypatch)
    client = target.client
    target.inject_rate_limit_once("actor", "room")
    target.inject_uncertain_write_once("actor", "room")
    target.create_room("room")
    assert len(client.posts) == 3

    client.next_get = FakeResponse({"release": "v0.7.0", "operations": ["read_room"]})
    assert target.capabilities()["release"] == "v0.7.0"
    record = {
        "sequence": 1,
        "room": "room",
        "did": "did:key:test",
        "nonce": 1,
        "text": "hello",
        "signature": "x",
    }
    client.next_get = FakeResponse({"records": [record]})
    assert target.read_room("room", since=0, limit=1)[0].sequence == 1
    client.next_post = FakeResponse(record)
    assert target.post_signed("actor", "room", "did:key:test", 1, "hello", "x").room == "room"
    target.close()
    assert client.closed


def test_http_target_normalizes_faults_and_invalid_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _target(monkeypatch)
    client = target.client
    client.next_get = FakeResponse([])
    with pytest.raises(ValueError, match="capability"):
        target.capabilities()
    client.next_get = FakeResponse({"records": {}})
    with pytest.raises(ValueError, match="record"):
        target.read_room("room")

    client.next_post = FakeResponse({}, 429, {"Retry-After": "7"})
    with pytest.raises(RateLimited) as limited:
        target.post_signed("actor", "room", "did", 1, "text", "sig")
    assert limited.value.retry_after_seconds == 7
    client.next_post = FakeResponse({}, 599)
    with pytest.raises(UncertainWrite):
        target.post_signed("actor", "room", "did", 1, "text", "sig")
