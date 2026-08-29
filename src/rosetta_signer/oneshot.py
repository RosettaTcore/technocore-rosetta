"""Sandbox-compatible one-request signer process used only by the local harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rosetta.contracts import SignRequest
from rosetta_signer.did import SyntheticIdentity
from rosetta_signer.nonce_store import NonceStore
from rosetta_signer.protocol import SignerProtocol


def main() -> None:
    parser = argparse.ArgumentParser(description="Rosetta local one-shot synthetic signer")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--synthetic-key-id", required=True)
    args = parser.parse_args()
    request = SignRequest.parse_raw(sys.stdin.buffer.readline(16_385))
    store = NonceStore(args.state)
    try:
        response = SignerProtocol(SyntheticIdentity(args.synthetic_key_id), store).handle(request)
        sys.stdout.write(json.dumps(response.dict(), sort_keys=True, separators=(",", ":")) + "\n")
    finally:
        store.close()


if __name__ == "__main__":
    main()
