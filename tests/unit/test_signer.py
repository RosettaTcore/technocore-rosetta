import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rosetta.contracts import SignRequest
from rosetta.signer_client import ProcessSignerClient, SignerClient
from rosetta_signer.canonical import signed_room_payload
from rosetta_signer.did import (
    SeedFileIdentity,
    SyntheticIdentity,
    artifact_payload,
    b58decode,
    b58encode,
    base64url_decode,
    did_from_public_key,
    evolution_proposal_payload,
    public_key_from_did,
    service_document_payload,
    verify_signature,
)
from rosetta_signer.nonce_store import NonceStore
from rosetta_signer.protocol import SignerProtocol

EXPECTED_DID = "did:key:z6MkqF736S32saPTuLDZueAyZnU6KdsKpRJZJVojJgBQEE11"
EXPECTED_SIGNATURE = (
    "go_vURio7JKeS9uu9i9LKSt2ITZanGdJlIXQUotF9LgjfaiuHZV62fWhxvmRt4irl_6JF5MxwsgtgLhkZMQ4CQ"
)


def test_synthetic_official_compatibility_vector() -> None:
    identity = SyntheticIdentity("synthetic-official-vector")
    payload = signed_room_payload("mb-vector", 1, "hello world")
    assert identity.did == EXPECTED_DID
    assert identity.sign(payload) == EXPECTED_SIGNATURE
    assert verify_signature(EXPECTED_DID, payload, EXPECTED_SIGNATURE)
    assert len(EXPECTED_SIGNATURE) == 86
    assert "=" not in EXPECTED_SIGNATURE


def test_signature_domains_cannot_cross_verify(tmp_path: Path) -> None:
    store = NonceStore(tmp_path / "nonce.sqlite3")
    protocol = SignerProtocol(SyntheticIdentity("synthetic-domain-test"), store)
    digest = "sha256:" + "a" * 64
    artifact = protocol.handle(SignRequest(action="artifact_root", scope="test", digest=digest))
    service = protocol.handle(SignRequest(action="service_document", scope="test", digest=digest))
    evolution = protocol.handle(
        SignRequest(action="evolution_proposal", scope="test", digest=digest)
    )
    assert verify_signature(artifact.did, artifact_payload(digest), artifact.signature)
    assert not verify_signature(artifact.did, service_document_payload(digest), artifact.signature)
    assert not verify_signature(service.did, artifact_payload(digest), service.signature)
    assert verify_signature(evolution.did, evolution_proposal_payload(digest), evolution.signature)
    assert not verify_signature(evolution.did, artifact_payload(digest), evolution.signature)
    assert not verify_signature(
        artifact.did, evolution_proposal_payload(digest), artifact.signature
    )
    store.close()


def test_nonce_regression_rejected_after_restart(tmp_path: Path) -> None:
    state = tmp_path / "nonce.sqlite3"
    first = NonceStore(state)
    assert first.next("message:room", 5) == 5
    first.close()
    second = NonceStore(state)
    with pytest.raises(ValueError):
        second.next("message:room", 5)
    assert second.next("message:room") == 6
    second.close()


def test_unknown_signer_action_and_fields_fail_closed() -> None:
    with pytest.raises(ValidationError):
        SignRequest.parse_obj({"action": "wallet", "scope": "x"})
    with pytest.raises(ValidationError):
        SignRequest.parse_obj(
            {"action": "artifact_root", "scope": "x", "digest": "x", "seed": "no"}
        )


@pytest.mark.parametrize(
    "sign_request",
    [
        SignRequest(action="technocore_message", scope="x", text="text"),
        SignRequest(
            action="technocore_message",
            scope="x",
            room="room",
            text="text",
            digest="sha256:" + "a" * 64,
        ),
        SignRequest(action="artifact_root", scope="x", digest="sha256:" + "a" * 64, room="room"),
        SignRequest(action="service_document", scope="x", digest="sha256:" + "a" * 64, text="text"),
        SignRequest(
            action="evolution_proposal", scope="x", digest="sha256:" + "a" * 64, room="room"
        ),
    ],
)
def test_signer_protocol_rejects_cross_action_fields(
    tmp_path: Path, sign_request: SignRequest
) -> None:
    store = NonceStore(tmp_path / "nonce.sqlite3")
    protocol = SignerProtocol(SyntheticIdentity("synthetic-invalid-request"), store)
    with pytest.raises(ValueError):
        protocol.handle(sign_request)
    store.close()


def test_unix_signer_client_roundtrip_is_framed(monkeypatch: pytest.MonkeyPatch) -> None:
    response = {
        "schema": "rosetta.sign-response.v1",
        "did": EXPECTED_DID,
        "signature": EXPECTED_SIGNATURE,
        "nonce": None,
        "signed_digest": "sha256:" + "a" * 64,
    }

    class Reader:
        async def readline(self) -> bytes:
            return json.dumps(response).encode() + b"\n"

    class Writer:
        def __init__(self) -> None:
            self.data = b""
            self.closed = False

        def write(self, data: bytes) -> None:
            self.data += data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    writer = Writer()

    async def connect(path: str):  # type: ignore[no-untyped-def]
        assert path == "/tmp/signer.sock"  # noqa: S108 - inert test path
        return Reader(), writer

    monkeypatch.setattr(asyncio, "open_unix_connection", connect)
    result = asyncio.run(
        SignerClient("/tmp/signer.sock").sign(  # noqa: S108 - inert test path
            SignRequest(action="artifact_root", scope="x", digest="sha256:" + "a" * 64)
        )
    )
    assert result.did == EXPECTED_DID
    assert writer.data.endswith(b"\n")
    assert writer.closed


def test_process_signer_client_surfaces_child_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Process:
        returncode = 1

        async def communicate(self, data: bytes):  # type: ignore[no-untyped-def]
            assert data.endswith(b"\n")
            return b"", b"rejected fixture"

    async def create(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    client = ProcessSignerClient(tmp_path / "nonce.sqlite3", "synthetic-failing")
    with pytest.raises(RuntimeError, match="rejected fixture"):
        asyncio.run(
            client.sign(SignRequest(action="artifact_root", scope="x", digest="sha256:" + "a" * 64))
        )


def test_did_encoding_and_digest_validation_edges() -> None:
    assert b58decode(b58encode(b"\0\0hello")) == b"\0\0hello"
    with pytest.raises(ValueError, match="base58"):
        b58decode("0")
    with pytest.raises(ValueError, match="padding"):
        base64url_decode("abc=")
    with pytest.raises(ValueError, match="32 bytes"):
        did_from_public_key(b"short")
    with pytest.raises(ValueError, match="unsupported"):
        public_key_from_did("did:web:example.invalid")
    with pytest.raises(ValueError, match="Ed25519"):
        public_key_from_did("did:key:z" + b58encode(b"wrong"))
    with pytest.raises(ValueError, match="synthetic"):
        SyntheticIdentity("production-key")
    with pytest.raises(ValueError, match="sha256"):
        artifact_payload("latest")
    with pytest.raises(ValueError, match="hexadecimal"):
        artifact_payload("sha256:" + "G" * 64)
    assert not verify_signature(EXPECTED_DID, b"payload", "short")


def test_seed_file_identity_requires_exact_private_regular_file(tmp_path: Path) -> None:
    seed_path = tmp_path / "seed"
    seed_path.write_bytes(bytes(range(32)))
    seed_path.chmod(0o600)
    identity = SeedFileIdentity(seed_path)
    signature = identity.sign(b"bounded payload")
    assert verify_signature(identity.did, b"bounded payload", signature)

    seed_path.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        SeedFileIdentity(seed_path)
    seed_path.chmod(0o600)
    seed_path.write_bytes(b"short")
    with pytest.raises(ValueError, match="exactly 32"):
        SeedFileIdentity(seed_path)


def test_seed_file_identity_rejects_symlink(tmp_path: Path) -> None:
    seed_path = tmp_path / "seed"
    seed_path.write_bytes(bytes(range(32)))
    seed_path.chmod(0o600)
    link = tmp_path / "seed-link"
    link.symlink_to(seed_path)
    with pytest.raises(OSError):
        SeedFileIdentity(link)


def test_seed_file_identity_rejects_non_regular_and_wrong_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="regular"):
        SeedFileIdentity(tmp_path)

    seed_path = tmp_path / "seed"
    seed_path.write_bytes(bytes(range(32)))
    seed_path.chmod(0o600)
    actual_fstat = os.fstat

    def wrong_owner(descriptor: int) -> SimpleNamespace:
        metadata = actual_fstat(descriptor)
        return SimpleNamespace(st_mode=metadata.st_mode, st_uid=os.geteuid() + 1)

    monkeypatch.setattr(os, "fstat", wrong_owner)
    with pytest.raises(ValueError, match="owned"):
        SeedFileIdentity(seed_path)
