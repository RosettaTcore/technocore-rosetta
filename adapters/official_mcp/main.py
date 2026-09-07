"""Rosetta adapter over the exact official Technocore v0.13 MCP stdio server.

The adapter is an MCP client, not a second implementation of the protocol. It starts the
vendored official server over stdio, performs the MCP initialization handshake and invokes
only a closed set of tools. Private key material is never passed to MCP: signed tools
receive only the public DID, nonce and signature returned by Rosetta's isolated signer.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ADAPTER_ID = "official-mcp"
VERSION = "0.13.0"
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
vendored = root / "vendor" / "technocore-chat-v0.13.0" / "mcp" / "src"
if not vendored.exists():
    vendored = Path("/opt/rosetta/vendor/technocore-chat-v0.13.0/mcp/src")


def _server_parameters() -> StdioServerParameters:
    path = os.pathsep.join((str(vendored), os.environ.get("PYTHONPATH", ""))).rstrip(os.pathsep)
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", "from technocore_mcp.server import main; main()"],
        env={
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONPATH": path,
            "PYTHONUNBUFFERED": "1",
            "TECHNOCORE_URL": ORIGIN,
        },
    )


def _text(result: Any) -> str:
    parts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
    return "\n".join(parts)


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with stdio_client(_server_parameters()) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            if initialized.server_info.version != VERSION:
                raise RuntimeError("official MCP server version mismatch")
            result = await session.call_tool(name, arguments)
    raw = _text(result)
    failed = bool(getattr(result, "is_error", False))
    output: dict[str, Any] = {"ok": not failed, "raw": raw}
    if failed:
        retry = re.search(r"retry(?: in| after)?\s+(\d+)", raw, re.IGNORECASE)
        if retry:
            output.update(status=429, retry_after=retry.group(1))
    else:
        output["status"] = 200
    return output


async def _tools() -> list[str]:
    async with stdio_client(_server_parameters()) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            if initialized.server_info.version != VERSION:
                raise RuntimeError("official MCP server version mismatch")
            listed = await session.list_tools()
    return [tool.name for tool in listed.tools]


async def _invoke(message: dict[str, Any]) -> dict[str, Any]:
    operation = message.get("operation")
    base: dict[str, Any] = {
        "schema": "rosetta.adapter-result.v1",
        "id": ADAPTER_ID,
        "operation": operation,
    }
    if operation == "capabilities":
        tools = await _tools()
        required = {"read_room", "wait_for_message", "say_signed", "read_docs"}
        if not required.issubset(tools):
            raise RuntimeError("official MCP tool surface is incomplete")
        return {
            **base,
            "ok": True,
            "runtime": f"python-{sys.version_info.major}.{sys.version_info.minor}",
            "transport": "official-mcp-sdk-stdio-0.13.0",
            "upstream_version": VERSION,
            "tools": tools,
            "operations": ["health", "read_room", "wait_room", "post_signed"],
        }
    if operation == "health":
        result = await _call("read_docs", {"page": "manual"})
    elif operation in {"read_room", "wait_room"}:
        arguments = {"room": message["room"], "since": int(message.get("since", 0))}
        if operation == "read_room":
            arguments["limit"] = int(message.get("limit", 100))
            result = await _call("read_room", arguments)
        else:
            arguments["seconds"] = float(message.get("wait", 0))
            result = await _call("wait_for_message", arguments)
        match = re.search(r"next: /r/[^?]+\?since=(\d+)", result["raw"])
        result["last_seq"] = int(match.group(1)) if match else None
    elif operation == "post_signed":
        result = await _call(
            "say_signed",
            {
                "room": message["room"],
                "text": message["text"],
                "did": message["did"],
                "sig": message["signature"],
                "nonce": int(message["nonce"]),
            },
        )
    else:
        raise ValueError("unsupported closed adapter operation")
    return {**base, **result}


def invoke(message: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_invoke(message))


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
