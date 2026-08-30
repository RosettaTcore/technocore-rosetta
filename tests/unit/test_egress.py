from __future__ import annotations

import http.client
import sys
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest

from rosetta import egress as egress_module
from rosetta.egress import ReadOnlyEgress, handler_for


def test_egress_allows_only_fixed_https_origin_and_paths() -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    gateway = ReadOnlyEgress(
        "https://technocore.chat", 2, 1_024, transport=httpx.MockTransport(upstream)
    )
    try:
        assert gateway.fetch("/healthz") == (200, "text/plain", b"ok")
        assert gateway.fetch("/r/lobby/say/x/y")[0] == 404
    finally:
        gateway.close()
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.host == "technocore.chat"
    with pytest.raises(ValueError, match="HTTPS"):
        ReadOnlyEgress("http://technocore.chat", 2, 1_024)
    with pytest.raises(ValueError, match="path"):
        ReadOnlyEgress("https://technocore.chat/path", 2, 1_024)


def test_egress_rejects_redirect_errors_and_oversize() -> None:
    redirect = ReadOnlyEgress(
        "https://technocore.chat",
        2,
        1_024,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "/x"})
        ),
    )
    assert redirect.fetch("/healthz")[0] == 502
    redirect.close()

    oversized = ReadOnlyEgress(
        "https://technocore.chat",
        2,
        1_024,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 1_025)),
    )
    assert oversized.fetch("/healthz")[0] == 502
    oversized.close()

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no", request=request)

    failed = ReadOnlyEgress(
        "https://technocore.chat", 2, 1_024, transport=httpx.MockTransport(unavailable)
    )
    assert failed.fetch("/healthz")[0] == 502
    failed.close()


def test_http_boundary_refuses_queries_and_every_write_method() -> None:
    gateway = ReadOnlyEgress(
        "https://technocore.chat",
        2,
        1_024,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": "text/plain"}, content=b"ok"
            )
        ),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.request("GET", "/healthz?write=true")
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"):
            connection.request(method, "/healthz")
            response = connection.getresponse()
            assert response.status == 405
            response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        gateway.close()
        thread.join(timeout=2)


def test_egress_cli_starts_and_closes_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    class FakeGateway:
        def __init__(self, origin: str, timeout: int, limit: int) -> None:
            calls.append((origin, timeout, limit))

        def close(self) -> None:
            calls.append("gateway-closed")

    class FakeServer:
        def __init__(self, address: tuple[str, int], handler: object) -> None:
            calls.append((address, handler))

        def serve_forever(self, poll_interval: float) -> None:
            calls.append(poll_interval)

        def server_close(self) -> None:
            calls.append("server-closed")

    monkeypatch.setattr(egress_module, "ReadOnlyEgress", FakeGateway)
    monkeypatch.setattr(egress_module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(egress_module, "handler_for", lambda gateway: gateway)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rosetta-egress",
            "--origin",
            "https://technocore.chat",
            "--listen",
            "127.0.0.1",
            "--port",
            "9000",
        ],
    )
    egress_module.main()
    assert "server-closed" in calls and "gateway-closed" in calls
