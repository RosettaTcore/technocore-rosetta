import importlib.util
import json
from pathlib import Path

from rosetta_signer.did import verify_signature

ROOT = Path(__file__).resolve().parents[2]


def test_official_v070_vector_verifies_byte_for_byte_in_both_implementations() -> None:
    vector = json.loads(
        (ROOT / "fixtures/upstream/technocore-v0.7.0-ed25519-vector.json").read_text()
    )
    did = vector["did"]
    message = vector["message_utf8"].encode()
    signature = vector["signature_base64url_unpadded"]
    assert len(signature) == 86 and "=" not in signature
    assert verify_signature(did, message, signature)

    spec = importlib.util.spec_from_file_location(
        "official_didkey", ROOT / "vendor/technocore-chat-v0.7.0/src/didkey.py"
    )
    assert spec is not None and spec.loader is not None
    official = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(official)
    assert official.verify(did, signature, message.decode()) is None

    mutated = ("B" if signature[0] != "B" else "C") + signature[1:]
    assert not verify_signature(did, message, mutated)
    try:
        official.verify(did, mutated, message.decode())
    except official.SignatureError:
        pass
    else:
        raise AssertionError("official verifier accepted a one-byte signature mutation")
