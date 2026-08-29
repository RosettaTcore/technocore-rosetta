"""Worker-facing client for the narrow Unix-socket signer boundary."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Protocol

from rosetta.contracts import SignRequest, SignResponse
from rosetta.operations import OperationalGate


class Signer(Protocol):
    async def sign(self, request: SignRequest) -> SignResponse: ...


class SignerClient:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    async def sign(self, request: SignRequest) -> SignResponse:
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        writer.write(request.json(sort_keys=True, separators=(",", ":")).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        writer.close()
        await writer.wait_closed()
        response = SignResponse.parse_raw(line)
        return response


class ProcessSignerClient:
    """Separate-process local fallback when the host sandbox forbids socket binding."""

    def __init__(
        self, state_path: Path, fixture_id: str, environ: dict[str, str] | None = None
    ) -> None:
        self.state_path = state_path
        self.fixture_id = fixture_id
        self.environ = dict(os.environ if environ is None else environ)

    async def sign(self, request: SignRequest) -> SignResponse:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "rosetta_signer.oneshot",
            "--state",
            str(self.state_path),
            "--synthetic-key-id",
            self.fixture_id,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.environ,
        )
        stdout, stderr = await process.communicate(
            request.json(by_alias=True, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        if process.returncode != 0:
            raise RuntimeError("signer child rejected request: " + stderr.decode()[:200])
        return SignResponse.parse_raw(stdout)


class GuardedSigner:
    """Apply the shared operational gate before every private-key boundary call."""

    def __init__(self, signer: Signer, gate: OperationalGate) -> None:
        self.signer = signer
        self.gate = gate

    async def sign(self, request: SignRequest) -> SignResponse:
        self.gate.require("signer")
        return await self.signer.sign(request)
