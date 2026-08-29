import unicodedata
from datetime import date, datetime, timezone
from enum import Enum

import pytest

from rosetta_signer.canonical import canonical_json, signed_room_payload, sweep_text


@pytest.mark.parametrize("category", ["Cc", "Cf", "Cs", "Co", "Zl", "Zp"])
def test_every_required_unicode_category_is_swept(category: str) -> None:
    sample = next(
        chr(codepoint)
        for codepoint in range(0x110000)
        if unicodedata.category(chr(codepoint)) == category
    )
    assert sweep_text(f"a{sample}b") == "a b"


def test_sweep_rejects_empty_and_oversized() -> None:
    with pytest.raises(ValueError):
        sweep_text("\x00\u2028")
    with pytest.raises(ValueError):
        sweep_text("x" * 4097)


def test_room_payload_and_canonical_json_are_stable() -> None:
    assert signed_room_payload("room", 7, "  hi\nthere  ") == b"room|7|hi there"
    assert canonical_json({"z": 1, "a": "é"}) == b'{"a":"\xc3\xa9","z":1}'
    with pytest.raises(ValueError):
        canonical_json({"float": 1.5})


@pytest.mark.parametrize("room,nonce", [("", 1), ("bad|room", 1), ("room", 0), ("room", 10**19)])
def test_signed_payload_rejects_ambiguous_room_and_nonce(room: str, nonce: int) -> None:
    with pytest.raises(ValueError):
        signed_room_payload(room, nonce, "text")


def test_canonical_json_supported_types_and_nested_validation() -> None:
    class Choice(Enum):
        VALUE = "value"

    value = {
        "date": date(2026, 8, 26),
        "datetime": datetime(2026, 8, 26, 2, 0, tzinfo=timezone.utc),
        "enum": Choice.VALUE,
        "nested": [1, (2, 3)],
    }
    assert canonical_json(value) == (
        b'{"date":"2026-08-26","datetime":"2026-08-26T02:00:00Z",'
        b'"enum":"value","nested":[1,[2,3]]}'
    )
    with pytest.raises(ValueError, match="naive"):
        canonical_json({"time": datetime(2026, 8, 26)})
    with pytest.raises(ValueError, match="keys"):
        canonical_json({1: "not canonical"})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"nested": [float("inf")]})
    with pytest.raises(TypeError, match="unsupported"):
        canonical_json({"object": object()})
