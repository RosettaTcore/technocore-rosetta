"""Closed, versioned data contracts used at every trust boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, StrictInt, StrictStr, validator


class ClosedModel(BaseModel):
    class Config:
        extra = "forbid"
        validate_assignment = True
        allow_population_by_field_name = True

    def dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().dict(*args, **kwargs)


class Outcome(str, Enum):
    PASS = "pass"  # noqa: S105 - protocol verdict, not a credential
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


class ReasonCode(str, Enum):
    OK = "ok"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_SIGNATURE = "invalid_signature"
    CANONICAL_PAYLOAD_MISMATCH = "canonical_payload_mismatch"
    CORRELATION_MISMATCH = "correlation_mismatch"
    DUPLICATE_SUCCESS = "duplicate_success"
    CURSOR_RESUME_FAILED = "cursor_resume_failed"
    RATE_LIMIT_EXHAUSTED = "rate_limit_exhausted"
    UNCERTAIN_WRITE_UNRESOLVED = "uncertain_write_unresolved"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    UNALLOWLISTED_ADAPTER = "unallowlisted_adapter"
    UNSUPPORTED_PROFILE = "unsupported_profile"
    EXPIRED = "expired"
    QUOTA_EXCEEDED = "quota_exceeded"
    BUSY = "busy"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    INVALID_REPLY_ROOM = "invalid_reply_room"
    UNSIGNED = "unsigned"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"


class AdapterManifest(ClosedModel):
    id: StrictStr
    runtime: StrictStr
    source_repository: StrictStr
    source_revision_kind: Literal["git_commit", "tree_sha256"]
    source_revision: StrictStr
    wrapper_revision_sha256: StrictStr | None = None
    dependency_lock_sha256: StrictStr
    image: StrictStr
    image_digest: StrictStr
    transport: StrictStr
    capabilities: list[StrictStr]

    @validator("source_revision")
    def revision_is_immutable(cls, value: str, values: dict[str, Any]) -> str:
        expected = 40 if values.get("source_revision_kind") == "git_commit" else 64
        if len(value) != expected or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"source_revision must be {expected} lowercase hexadecimal characters")
        return value

    @validator("dependency_lock_sha256")
    def dependency_lock_is_hash(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("dependency lock must be a lowercase sha256")
        return value

    @validator("wrapper_revision_sha256")
    def wrapper_revision_is_hash(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("wrapper revision must be a lowercase sha256")
        return value

    @validator("image_digest")
    def image_is_pinned(cls, value: str) -> str:
        raw = value.removeprefix("sha256:")
        if not value.startswith("sha256:") or len(raw) != 64:
            raise ValueError("image must use an immutable sha256 digest")
        if any(c not in "0123456789abcdef" for c in raw):
            raise ValueError("image digest must be lowercase hexadecimal")
        return value


class AdapterRegistryContract(ClosedModel):
    schema_: Literal["rosetta.adapter-registry.v1"] = Field(alias="schema")
    adapters: list[AdapterManifest]


class ScenarioContract(ClosedModel):
    schema_: Literal["rosetta.scenario.v1"] = Field(alias="schema")
    id: Literal["signed-mailbox-roundtrip-v1"]
    version: StrictInt
    required_capabilities: list[StrictStr]
    assertions: list[StrictStr]
    faults: dict[StrictStr, bool]


class AssertionResult(ClosedModel):
    name: StrictStr
    passed: bool
    reason: ReasonCode
    detail: StrictStr = ""


class MatrixCell(ClosedModel):
    schema_: Literal["rosetta.matrix-cell.v1"] = Field("rosetta.matrix-cell.v1", alias="schema")
    producer: StrictStr
    consumer: StrictStr
    outcome: Outcome
    reason: ReasonCode
    protocol_release: StrictStr
    scenario: StrictStr
    adapter_versions: dict[StrictStr, StrictStr]
    assertions: list[AssertionResult]
    evidence_file: StrictStr


class RunRecord(ClosedModel):
    schema_: Literal["rosetta.run.v1"] = Field("rosetta.run.v1", alias="schema")
    run_id: StrictStr
    trigger: StrictStr
    protocol_release: StrictStr
    scenario: StrictStr
    registry_sha256: StrictStr
    execution_images: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    deterministic_epoch: StrictStr
    dry_run: bool

    @validator("execution_images")
    def execution_images_are_immutable(cls, value: dict[str, str]) -> dict[str, str]:
        for digest in value.values():
            raw = digest.removeprefix("sha256:")
            if not digest.startswith("sha256:") or len(raw) != 64:
                raise ValueError("execution image must be an immutable sha256 digest")
            if any(char not in "0123456789abcdef" for char in raw):
                raise ValueError("execution image digest must be lowercase hexadecimal")
        return value


class EvidenceEvent(ClosedModel):
    schema_: Literal["rosetta.evidence-event.v1"] = Field(
        "rosetta.evidence-event.v1", alias="schema"
    )
    sequence: StrictInt
    actor: StrictStr
    operation: StrictStr
    status: StrictStr
    correlation_id: StrictStr
    detail: dict[StrictStr, Any] = Field(default_factory=dict)
    previous_hash: StrictStr
    event_hash: StrictStr


class SignRequest(ClosedModel):
    schema_: Literal["rosetta.sign-request.v1"] = Field("rosetta.sign-request.v1", alias="schema")
    action: Literal["technocore_message", "artifact_root", "service_document", "evolution_proposal"]
    scope: StrictStr
    nonce: StrictInt | None = None
    room: StrictStr | None = None
    text: StrictStr | None = None
    digest: StrictStr | None = None


class SignResponse(ClosedModel):
    schema_: Literal["rosetta.sign-response.v1"] = Field("rosetta.sign-response.v1", alias="schema")
    did: StrictStr
    signature: StrictStr
    nonce: StrictInt | None = None
    signed_digest: StrictStr


class Price(ClosedModel):
    kind: Literal["free"] = "free"
    currency: None = None
    amount: Literal[0] = 0


class ServiceLimits(ClosedModel):
    per_did_per_day: StrictInt
    global_per_day: StrictInt


class ServiceCard(ClosedModel):
    schema_: Literal["rosetta.service-card.v1"] = Field("rosetta.service-card.v1", alias="schema")
    service_id: Literal["technocore-rosetta"] = "technocore-rosetta"
    did: StrictStr
    service_room: StrictStr
    request_mailbox: StrictStr
    protocol_baseline: Literal["v0.7.0"] = "v0.7.0"
    scenarios: list[Literal["signed-mailbox-roundtrip-v1"]]
    adapter_profiles: list[StrictStr]
    request_schema_url: AnyHttpUrl
    report_base_url: AnyHttpUrl
    price: Price = Field(default_factory=Price)
    limits: ServiceLimits
    status: Literal["available", "unavailable"]
    updated_at: datetime
    valid_until: datetime

    @validator("valid_until")
    def expiry_after_update(cls, value: datetime, values: dict[str, Any]) -> datetime:
        updated = values.get("updated_at")
        if updated is not None and value <= updated:
            raise ValueError("valid_until must be after updated_at")
        return value


class DiscoveryQuery(ClosedModel):
    schema_: Literal["rosetta.discover.v1"] = Field(alias="schema")
    request_id: StrictStr
    reply_room: StrictStr
    expires_at: datetime


class DiscoveryOffer(ClosedModel):
    schema_: Literal["rosetta.offer.v1"] = Field("rosetta.offer.v1", alias="schema")
    request_id: StrictStr
    did: StrictStr
    service_card_url: AnyHttpUrl
    service_card_sha256: StrictStr
    request_mailbox: StrictStr
    valid_until: datetime


class ServiceRequest(ClosedModel):
    schema_: Literal["rosetta.request.v1"] = Field(alias="schema")
    request_id: StrictStr
    scenario: Literal["signed-mailbox-roundtrip-v1"]
    producer: StrictStr
    consumer: StrictStr
    target_profile: Literal["current"]
    reply_room: StrictStr
    expires_at: datetime

    @validator("request_id")
    def request_id_is_closed(cls, value: str) -> str:
        if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("request_id must be 32 lowercase hexadecimal characters")
        return value

    @validator("reply_room")
    def reply_is_public_mailbox(cls, value: str) -> str:
        return validate_public_mailbox(value)

    def validate_expiry(self, now: datetime, max_hours: int = 24) -> None:
        current = now.astimezone(timezone.utc)
        expiry = self.expires_at.astimezone(timezone.utc)
        if expiry <= current or (expiry - current).total_seconds() > max_hours * 3600:
            raise ValueError("expired or overlong request")


class Acknowledgement(ClosedModel):
    schema_: Literal["rosetta.ack.v1"] = Field("rosetta.ack.v1", alias="schema")
    request_id: StrictStr
    status: Literal["accepted", "rejected"]
    job_id: StrictStr | None = None
    position: StrictInt | None = None
    reason: ReasonCode | None = None


class ServiceResult(ClosedModel):
    schema_: Literal["rosetta.result.v1"] = Field("rosetta.result.v1", alias="schema")
    request_id: StrictStr
    job_id: StrictStr
    outcome: Outcome
    bundle_root: StrictStr
    report_url: AnyHttpUrl
    completed_at: datetime


class Attestation(ClosedModel):
    schema_: Literal["rosetta.attestation.v1"] = Field("rosetta.attestation.v1", alias="schema")
    domain: Literal["rosetta.artifact.v1"] = "rosetta.artifact.v1"
    did: StrictStr
    bundle_root: StrictStr
    signature: StrictStr
    algorithm: Literal["Ed25519"] = "Ed25519"


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    """Pydantic v1/v2-compatible JSON-ready dictionary."""
    return model.dict()


def validate_public_mailbox(value: str) -> str:
    if not value.startswith("mb-") or value.startswith("mb-p-"):
        raise ValueError("reply room must be a public signed mailbox")
    if len(value) > 64 or not all(c.islower() or c.isdigit() or c == "-" for c in value):
        raise ValueError("invalid reply room")
    return value
