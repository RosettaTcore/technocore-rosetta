import tarfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from rosetta.adapter_errors import AdapterErrorKind, NormalizedAdapterError, normalize_http_error

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "status,kind",
    [
        (400, AdapterErrorKind.INVALID_REQUEST),
        (403, AdapterErrorKind.ACCESS_REFUSED),
        (409, AdapterErrorKind.CONFLICT),
        (422, AdapterErrorKind.DUPLICATE_FILTERED),
        (429, AdapterErrorKind.RATE_LIMITED),
        (302, AdapterErrorKind.UNEXPECTED_REDIRECT),
        (503, AdapterErrorKind.UPSTREAM_FAILURE),
        (418, AdapterErrorKind.HTTP_FAILURE),
    ],
)
def test_http_errors_have_stable_closed_kinds(status: int, kind: AdapterErrorKind) -> None:
    normalized = normalize_http_error(status)
    assert normalized.kind is kind
    assert not normalized.retryable
    assert normalized.retry_after_seconds is None


def test_only_bounded_429_is_retryable() -> None:
    accepted = normalize_http_error(429, "2")
    assert accepted.retryable and accepted.retry_after_seconds == 2
    for value in (None, "invalid", "0", "61"):
        refused = normalize_http_error(429, value)
        assert not refused.retryable and refused.retry_after_seconds is None
    assert not normalize_http_error(422, "1").retryable


def test_success_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ValidationError, match="HTTP error"):
        NormalizedAdapterError(kind="http_failure", status=200, retryable=False)
    with pytest.raises(ValidationError):
        NormalizedAdapterError(
            kind="http_failure", status=418, retryable=False, unexpected="authority"
        )


def test_v010_source_declares_422_on_every_write_lane() -> None:
    archive = ROOT / "work/upstream/technocore-chat-v0.10.0.tar.gz"
    with tarfile.open(archive, "r:gz") as source:
        stream = source.extractfile("technocore-chat-0.10.0/src/manifest.py")
        assert stream is not None
        manifest = stream.read().decode()
    assert manifest.count('"422": _DUPLICATE_TEXT') == 3
    assert "Retry-After semantics resends the same bytes" in manifest
