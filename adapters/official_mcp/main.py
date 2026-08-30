"""Adapter that calls the exact vendored Technocore MCP 0.10.0 implementation.

The upstream MCP intentionally excludes the signed lane so private keys never enter model
context. Rosetta therefore uses MCP for discovery/read/wait and its isolated signer output
with a direct HTTP POST only for signed writes.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ADAPTER_ID = "official-mcp"
ORIGIN = os.environ.get("ROSETTA_TARGET_ORIGIN", "http://technocore-upstream:8080").rstrip("/")
_parsed = urlparse(ORIGIN)
if _parsed.scheme not in {"http", "https"} or _parsed.hostname not in {
    "technocore-upstream",
    "rosetta-fault-proxy",
    "127.0.0.1",
    "localhost",
}:
    raise RuntimeError("target origin is not an approved local Technocore endpoint")

root = Path(__file__).resolve().parents[2]
upstream = root / "vendor" / "technocore-chat-v0.10.0" / "mcp" / "src"
if not upstream.exists():
    upstream = Path("/opt/rosetta/vendor/technocore-chat-v0.10.0/mcp/src")
sys.path.insert(0, str(upstream))
os.environ["TECHNOCORE_URL"] = ORIGIN

from technocore_mcp.server import VERSION, server  # noqa: E402


def _mcp(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    reply = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    if reply is None or "result" not in reply:
        raise RuntimeError(f"MCP protocol failure: {reply}")
    result = reply["result"]
    content = result.get("content", [])
    raw = content[0].get("text", "") if content else ""
    return {"ok": not result.get("isError", False), "raw": raw, "mcp_reply": reply}


def _signed_post(message: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(
        {
            "did": message["did"],
            "sig": message["signature"],
            "nonce": str(message["nonce"]),
            "text": message["text"],
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 - ORIGIN scheme/host checked above
        f"{ORIGIN}/r/{message['room']}?format=json",
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"rosetta-mcp/{VERSION}",
            "X-Rosetta-Actor": str(message.get("actor", ADAPTER_ID)),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            raw = response.read().decode()
            return {"ok": True, "status": response.status, "raw": raw, "data": json.loads(raw)}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "raw": exc.read().decode("utf-8", "replace"),
            "retry_after": exc.headers.get("Retry-After"),
        }


def invoke(message: dict[str, Any]) -> dict[str, Any]:
    operation = message.get("operation")
    base: dict[str, Any] = {
        "schema": "rosetta.adapter-result.v1",
        "id": ADAPTER_ID,
        "operation": operation,
    }
    if operation == "capabilities":
        listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return {
            **base,
            "ok": True,
            "runtime": f"python-{sys.version_info.major}.{sys.version_info.minor}",
            "transport": "official-mcp-0.10.0+signed-http-boundary",
            "upstream_version": VERSION,
            "tools": [item["name"] for item in listed["result"]["tools"]],  # type: ignore[index]
            "operations": ["health", "read_room", "wait_room", "post_signed"],
        }
    if operation == "health":
        result = _mcp("read_docs", {"page": "manual"})
    elif operation in {"read_room", "wait_room"}:
        arguments = {"room": message["room"], "since": int(message.get("since", 0))}
        if operation == "read_room":
            arguments["limit"] = int(message.get("limit", 100))
            result = _mcp("read_room", arguments)
        else:
            arguments["seconds"] = float(message.get("wait", 0))
            result = _mcp("wait_for_message", arguments)
        match = re.search(r"next: /r/[^?]+\?since=(\d+)", result["raw"])
        result["last_seq"] = int(match.group(1)) if match else None
    elif operation == "post_signed":
        result = _signed_post(message)
    else:
        raise ValueError("unsupported closed adapter operation")
    return {**base, **result}


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
