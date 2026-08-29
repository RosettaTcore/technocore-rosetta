"""Newline-delimited JSON Unix-socket signer service; intentionally no network APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rosetta.contracts import SignRequest
from rosetta_signer.did import SyntheticIdentity
from rosetta_signer.nonce_store import NonceStore
from rosetta_signer.protocol import SignerProtocol


class UnixSignerService:
    def __init__(self, protocol: SignerProtocol, socket_path: Path) -> None:
        self.protocol = protocol
        self.socket_path = socket_path

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if len(line) > 16_384:
                raise ValueError("sign request too large")
            request = SignRequest.parse_raw(line)
            response: dict[str, Any] = self.protocol.handle(request).dict()
        except (ValueError, ValidationError, asyncio.TimeoutError) as exc:
            response = {"schema": "rosetta.sign-error.v1", "error": type(exc).__name__}
        writer.write(json.dumps(response, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def run(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        async with server:
            await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rosetta networkless synthetic signer")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--synthetic-key-id", required=True)
    args = parser.parse_args()
    identity = SyntheticIdentity(args.synthetic_key_id)
    store = NonceStore(args.state)
    asyncio.run(UnixSignerService(SignerProtocol(identity, store), args.socket).run())


if __name__ == "__main__":
    main()
