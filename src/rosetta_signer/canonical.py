"""Deterministic JSON and Technocore single-line canonicalization."""

from __future__ import annotations

import json
import math
import unicodedata
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

_SWEPT_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}


def sweep_text(text: str, *, max_chars: int = 4096) -> str:
    """Apply the official single-line sweep and enforce post-sweep bounds."""
    swept = "".join(
        " " if unicodedata.category(char) in _SWEPT_CATEGORIES else char for char in text
    )
    swept = swept.strip()
    if not swept:
        raise ValueError("message is empty after Unicode sweep")
    if len(swept) > max_chars:
        raise ValueError("message exceeds post-sweep character limit")
    return swept


def signed_room_payload(room: str, nonce: int, text: str) -> bytes:
    if not room or "|" in room:
        raise ValueError("invalid room")
    if nonce < 1 or nonce > 9_999_999_999_999_999_999:
        raise ValueError("nonce must contain 1-19 ASCII digits")
    return f"{room}|{nonce}|{sweep_text(text)}".encode()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime is not canonical")
        utc = value.astimezone(timezone.utc)
        return utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported canonical JSON type: {type(value).__name__}")


def _reject_noncanonical_numbers(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number is not JSON")
        raise ValueError("floats are outside Rosetta's canonical JSON profile")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical object keys must be strings")
            _reject_noncanonical_numbers(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_noncanonical_numbers(item)


def canonical_json(value: Any) -> bytes:
    """Canonical JSON profile: UTF-8, sorted keys, integers, no insignificant space.

    Rosetta contracts intentionally exclude floating point values, so this is an
    explicitly specified RFC 8785-compatible subset rather than a broad JCS clone.
    """
    _reject_noncanonical_numbers(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
