"""Minimal Ed25519 did:key support and domain-separated verification."""

from __future__ import annotations

import base64
import hashlib
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_ALPHABET: Final[str] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ED25519_MULTICODEC: Final[bytes] = bytes((0xED, 0x01))
ARTIFACT_DOMAIN: Final[bytes] = b"rosetta.artifact.v1\x00"
SERVICE_DOMAIN: Final[bytes] = b"rosetta.service-document.v1\x00"
EVOLUTION_DOMAIN: Final[bytes] = b"rosetta.evolution-proposal.v1\x00"


def b58encode(data: bytes) -> str:
    zeros = len(data) - len(data.lstrip(b"\0"))
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _ALPHABET[remainder] + encoded
    return "1" * zeros + (encoded or ("" if zeros else "1"))


def b58decode(value: str) -> bytes:
    number = 0
    for char in value:
        try:
            number = number * 58 + _ALPHABET.index(char)
        except ValueError as exc:
            raise ValueError("invalid base58btc") from exc
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + raw


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def base64url_decode(value: str) -> bytes:
    if "=" in value:
        raise ValueError("padding is forbidden")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def did_from_public_key(public_key: bytes) -> str:
    if len(public_key) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return "did:key:z" + b58encode(_ED25519_MULTICODEC + public_key)


def public_key_from_did(did: str) -> Ed25519PublicKey:
    prefix = "did:key:z"
    if not did.startswith(prefix):
        raise ValueError("unsupported DID")
    decoded = b58decode(did[len(prefix) :])
    if not decoded.startswith(_ED25519_MULTICODEC) or len(decoded) != 34:
        raise ValueError("DID is not an Ed25519 did:key")
    return Ed25519PublicKey.from_public_bytes(decoded[2:])


def did_fingerprint(did: str) -> str:
    return hashlib.sha256(did.encode("utf-8")).hexdigest()[:16]


class SyntheticIdentity:
    """Test-only identity derived inside the signer from a public fixture label."""

    def __init__(self, fixture_id: str) -> None:
        if not fixture_id.startswith("synthetic-"):
            raise ValueError("only explicitly synthetic fixture identities are allowed")
        private_bytes = hashlib.sha256(
            b"rosetta.synthetic.identity.v1\x00" + fixture_id.encode()
        ).digest()
        self._private = Ed25519PrivateKey.from_private_bytes(private_bytes)
        public = self._private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.did = did_from_public_key(public)

    def sign(self, payload: bytes) -> str:
        return base64url(self._private.sign(payload))


def verify_signature(did: str, payload: bytes, signature: str) -> bool:
    try:
        raw = base64url_decode(signature)
        if len(raw) != 64 or len(signature) != 86:
            return False
        public_key_from_did(did).verify(raw, payload)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def artifact_payload(digest: str) -> bytes:
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("artifact digest must be sha256:<64 lowercase hex>")
    raw = digest[7:]
    if any(char not in "0123456789abcdef" for char in raw):
        raise ValueError("artifact digest must be lowercase hexadecimal")
    return ARTIFACT_DOMAIN + digest.encode("ascii")


def service_document_payload(digest: str) -> bytes:
    artifact_payload(digest)
    return SERVICE_DOMAIN + digest.encode("ascii")


def evolution_proposal_payload(digest: str) -> bytes:
    artifact_payload(digest)
    return EVOLUTION_DOMAIN + digest.encode("ascii")
