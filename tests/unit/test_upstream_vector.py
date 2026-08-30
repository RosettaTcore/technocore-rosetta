import importlib.util
import json
import sys
from pathlib import Path

from rosetta_signer.did import verify_signature

ROOT = Path(__file__).resolve().parents[2]


def _verify_vector(release: str) -> dict[str, str]:
    vector = json.loads(
        (ROOT / f"fixtures/upstream/technocore-{release}-ed25519-vector.json").read_text()
    )
    did = vector["did"]
    message = vector["message_utf8"].encode()
    signature = vector["signature_base64url_unpadded"]
    assert len(signature) == 86 and "=" not in signature
    assert verify_signature(did, message, signature)

    spec = importlib.util.spec_from_file_location(
        "official_didkey", ROOT / f"vendor/technocore-chat-{release}/src/didkey.py"
    )
    assert spec is not None and spec.loader is not None
    official = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(official)
    finally:
        sys.dont_write_bytecode = prior
    assert official.verify(did, signature, message.decode()) is None

    mutated = ("B" if signature[0] != "B" else "C") + signature[1:]
    assert not verify_signature(did, message, mutated)
    try:
        official.verify(did, mutated, message.decode())
    except official.SignatureError:
        pass
    else:
        raise AssertionError("official verifier accepted a one-byte signature mutation")
    return vector


def test_official_v070_and_v010_vectors_verify_across_backend_change() -> None:
    old = _verify_vector("v0.7.0")
    current = _verify_vector("v0.10.0")
    assert old["did"] == current["did"]
    assert old["message_utf8"] == current["message_utf8"]
    assert old["signature_base64url_unpadded"] == current["signature_base64url_unpadded"]
