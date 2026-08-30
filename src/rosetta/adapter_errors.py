"""Deterministic normalization for bounded adapter HTTP failures."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, StrictInt, validator


class AdapterErrorKind(str, Enum):
    INVALID_REQUEST = "invalid_request"
    ACCESS_REFUSED = "access_refused"
    CONFLICT = "conflict"
    DUPLICATE_FILTERED = "duplicate_filtered"
    RATE_LIMITED = "rate_limited"
    UNEXPECTED_REDIRECT = "unexpected_redirect"
    UPSTREAM_FAILURE = "upstream_failure"
    HTTP_FAILURE = "http_failure"


class NormalizedAdapterError(BaseModel):
    kind: AdapterErrorKind
    status: StrictInt
    retryable: bool
    retry_after_seconds: StrictInt | None = None

    class Config:
        extra = "forbid"

    @validator("status")
    def status_is_error(cls, value: int) -> int:
        if value < 300 or value > 599:
            raise ValueError("normalized status must be an HTTP error")
        return value


def normalize_http_error(
    status: int, retry_after: str | int | None = None
) -> NormalizedAdapterError:
    """Map an HTTP failure to the closed Rosetta retry model.

    Only 429 is retryable, and only with a positive bounded integer delay. Technocore v0.10.0's
    duplicate filter uses 422 specifically to prevent automatic replay of identical content.
    """
    if status == 400:
        kind = AdapterErrorKind.INVALID_REQUEST
    elif status == 403:
        kind = AdapterErrorKind.ACCESS_REFUSED
    elif status == 409:
        kind = AdapterErrorKind.CONFLICT
    elif status == 422:
        kind = AdapterErrorKind.DUPLICATE_FILTERED
    elif status == 429:
        kind = AdapterErrorKind.RATE_LIMITED
    elif 300 <= status < 400:
        kind = AdapterErrorKind.UNEXPECTED_REDIRECT
    elif status >= 500:
        kind = AdapterErrorKind.UPSTREAM_FAILURE
    else:
        kind = AdapterErrorKind.HTTP_FAILURE

    delay: int | None = None
    if status == 429 and retry_after is not None:
        try:
            parsed = int(retry_after)
        except (TypeError, ValueError):
            parsed = 0
        if 0 < parsed <= 60:
            delay = parsed
    return NormalizedAdapterError(
        kind=kind,
        status=status,
        retryable=status == 429 and delay is not None,
        retry_after_seconds=delay,
    )
