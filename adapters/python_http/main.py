"""Independent HTTPX implementation of the closed Rosetta adapter protocol."""

from __future__ import annotations

import json
import os
import platform
import sys
from typing import Any
from urllib.parse import urlparse

import httpx

ADAPTER_ID = "python-http"
ORIGIN = os.environ.get("ROSETTA_TARGET_ORIGIN", "http://technocore-upstream:8080").rstrip("/")
_parsed = urlparse(ORIGIN)
if _parsed.scheme not in {"http", "https"} or _parsed.hostname not in {
    "technocore-upstream",
    "rosetta-fault-proxy",
    "127.0.0.1",
    "localhost",
}:
    raise RuntimeError("target origin is not an approved local Technocore endpoint")


def _result(operation: str, response: httpx.Response, *, json_body: bool = False) -> dict[str, Any]:
    return {
        "schema": "rosetta.adapter-result.v1",
        "id": ADAPTER_ID,
        "operation": operation,
        "ok": response.is_success,
        "status": response.status_code,
        "retry_after": response.headers.get("retry-after"),
        "data": response.json() if response.is_success and json_body else None,
        "raw": response.text,
    }


def invoke(message: dict[str, Any]) -> dict[str, Any]:
    operation = message.get("operation")
    if operation == "capabilities":
        return {
            "schema": "rosetta.adapter-result.v1",
            "id": ADAPTER_ID,
            "operation": operation,
            "ok": True,
            "runtime": f"python-{platform.python_version()}",
            "transport": "httpx",
            "operations": ["health", "read_room", "wait_room", "post_signed"],
        }
    with httpx.Client(
        base_url=ORIGIN, timeout=5, follow_redirects=False, trust_env=False
    ) as client:
        if operation == "health":
            return _result(operation, client.get("/healthz"))
        if operation in {"read_room", "wait_room"}:
            params = {
                "format": "json",
                "since": int(message.get("since", 0)),
                "limit": int(message.get("limit", 100)),
            }
            if operation == "wait_room":
                params["wait"] = int(message.get("wait", 0))
            response = client.get(f"/r/{message['room']}", params=params)
            return _result(operation, response, json_body=True)
        if operation == "post_signed":
            response = client.post(
                f"/r/{message['room']}",
                params={"format": "json"},
                json={
                    "did": message["did"],
                    "sig": message["signature"],
                    "nonce": str(message["nonce"]),
                    "text": message["text"],
                },
                headers={"X-Rosetta-Actor": str(message.get("actor", ADAPTER_ID))},
            )
            return _result(operation, response, json_body=True)
    raise ValueError("unsupported closed adapter operation")


def main() -> None:
    try:
        message = json.loads(sys.stdin.read() or "{}")
        if not isinstance(message, dict):
            raise ValueError("adapter input must be an object")
        print(json.dumps(invoke(message), sort_keys=True, separators=(",", ":")))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "rosetta.adapter-result.v1",
                    "id": ADAPTER_ID,
                    "operation": "error",
                    "ok": False,
                    "error": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
