from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from rosetta.contracts import Outcome, ServiceRequest

NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def valid_request() -> dict[str, object]:
    return {
        "schema": "rosetta.request.v1",
        "request_id": "a" * 32,
        "scenario": "signed-mailbox-roundtrip-v1",
        "producer": "python-http",
        "consumer": "official-mcp",
        "target_profile": "current",
        "reply_room": "mb-requester-public",
        "expires_at": NOW + timedelta(hours=1),
    }


@pytest.mark.parametrize("field", ["code", "prompt", "url", "commit", "image", "credentials"])
def test_request_cannot_expand_execution_authority(field: str) -> None:
    data = valid_request()
    data[field] = "untrusted"
    with pytest.raises(ValidationError):
        ServiceRequest.parse_obj(data)


def test_private_reply_unknown_profile_and_schema_fail_closed() -> None:
    for key, value in [
        ("reply_room", "mb-p-secret"),
        ("target_profile", "main"),
        ("schema", "rosetta.request.v2"),
    ]:
        data = valid_request()
        data[key] = value
        with pytest.raises(ValidationError):
            ServiceRequest.parse_obj(data)


def test_expiry_is_bounded() -> None:
    request = ServiceRequest.parse_obj(valid_request())
    request.validate_expiry(NOW)
    data = valid_request()
    data["expires_at"] = NOW + timedelta(hours=25)
    with pytest.raises(ValueError):
        ServiceRequest.parse_obj(data).validate_expiry(NOW)
    data["expires_at"] = NOW
    with pytest.raises(ValueError):
        ServiceRequest.parse_obj(data).validate_expiry(NOW)


def test_outcome_is_closed() -> None:
    assert {item.value for item in Outcome} == {"pass", "fail", "skip", "error"}
