"""Fail-closed configuration for the public request/result pilot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, root_validator, validator

from rosetta.service import service_names
from rosetta_signer.did import public_key_from_did


class _Closed(BaseModel):
    class Config:
        extra = "forbid"
        allow_population_by_field_name = True


def _absolute(value: str) -> str:
    if not Path(value).is_absolute():
        raise ValueError("pilot runtime paths must be absolute")
    return value


class PilotTechnocore(_Closed):
    authority_origin: str = "https://technocore.chat"
    fetch_origin: str = "http://technocore-egress:8082"
    pinned_release: Literal["v0.13.0"] = "v0.13.0"
    discovery_rooms: list[str] = ["lobby", "meta"]
    request_timeout_seconds: int = 20
    max_response_bytes: int = 1_048_576

    @validator("authority_origin")
    def public_tls_origin(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Technocore authority must be HTTPS")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Technocore authority must be an origin only")
        return value.rstrip("/")

    @validator("fetch_origin")
    def private_fetch_origin(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("invalid pilot fetch origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("pilot fetch endpoint must be an origin only")
        if parsed.scheme == "http" and parsed.hostname not in {
            "technocore-egress",
            "127.0.0.1",
            "localhost",
        }:
            raise ValueError("plain HTTP is limited to the local egress boundary")
        return value.rstrip("/")

    @validator("discovery_rooms")
    def closed_discovery_rooms(cls, value: list[str]) -> list[str]:
        if not value or len(value) > 4 or len(set(value)) != len(value):
            raise ValueError("pilot requires one to four unique discovery rooms")
        if any(room not in {"lobby", "meta"} for room in value):
            raise ValueError("unreviewed discovery room")
        return value

    @validator("request_timeout_seconds")
    def bounded_timeout(cls, value: int) -> int:
        if value < 2 or value > 30:
            raise ValueError("pilot timeout must be between 2 and 30 seconds")
        return value

    @validator("max_response_bytes")
    def bounded_response(cls, value: int) -> int:
        if value < 1_024 or value > 4_194_304:
            raise ValueError("invalid pilot response limit")
        return value


class PilotIdentity(_Closed):
    public_did: str
    signer_socket: str = "/run/rosetta-signer/signer.sock"

    _socket_path = validator("signer_socket", allow_reuse=True)(_absolute)

    @validator("public_did")
    def valid_did(cls, value: str) -> str:
        public_key_from_did(value)
        service_names(value)
        return value


class PilotService(_Closed):
    enabled: bool = False
    public_base_url: str
    state_directory: str = "/var/lib/rosetta/pilot"
    spool_directory: str = "/var/lib/rosetta/publish-spool"
    static_root: str = "/srv/rosetta-static"
    kill_switch_file: str = "/var/lib/rosetta/state/KILL_SWITCH"
    poll_seconds: int = 10
    max_requests_per_did_per_day: int = 2
    max_external_jobs_per_day: int = 8
    max_queue_depth: int = 16
    max_parallel_runners: Literal[1] = 1
    monthly_budget_cents: int = 4_000

    _state_path = validator(
        "state_directory",
        "spool_directory",
        "static_root",
        "kill_switch_file",
        allow_reuse=True,
    )(_absolute)

    @validator("public_base_url")
    def public_https_base(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("public base URL must be a fixed HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("public base URL cannot contain credentials")
        return value.rstrip("/")

    @validator("poll_seconds")
    def bounded_poll(cls, value: int) -> int:
        if value < 5 or value > 300:
            raise ValueError("pilot poll interval must be between 5 and 300 seconds")
        return value

    @validator("max_requests_per_did_per_day")
    def bounded_per_did(cls, value: int) -> int:
        if value < 1 or value > 2:
            raise ValueError("per-DID pilot limit cannot exceed 2")
        return value

    @validator("max_external_jobs_per_day")
    def bounded_global(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("global pilot limit cannot exceed 8")
        return value

    @validator("max_queue_depth")
    def bounded_queue(cls, value: int) -> int:
        if value < 1 or value > 16:
            raise ValueError("pilot queue depth cannot exceed 16")
        return value

    @validator("monthly_budget_cents")
    def bounded_budget(cls, value: int) -> int:
        if value < 0 or value > 4_000:
            raise ValueError("pilot monthly budget cannot exceed 4000 cents")
        return value


class PilotConfig(_Closed):
    schema_: Literal["rosetta.pilot-config.v1"] = Field(alias="schema")
    mode: Literal["pilot"]
    technocore: PilotTechnocore
    identity: PilotIdentity
    service: PilotService
    model_provider: Literal["disabled"] = "disabled"

    @root_validator
    def one_identity_and_no_llm(cls, values: dict[str, object]) -> dict[str, object]:
        identity = values.get("identity")
        service = values.get("service")
        if isinstance(identity, PilotIdentity) and isinstance(service, PilotService):
            room, mailbox = service_names(identity.public_did)
            if len(room) > 48 or len(mailbox) > 48:
                raise ValueError("derived Technocore service names exceed protocol limits")
        return values


def load_pilot_config(path: Path, environ: dict[str, str] | None = None) -> PilotConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("pilot configuration must be a mapping")
    config = PilotConfig.parse_obj(data)
    env = os.environ if environ is None else environ
    if config.service.enabled and env.get("ROSETTA_PILOT_ENABLE") != "PUBLIC_WRITES_APPROVED":
        raise ValueError("enabled pilot requires the explicit runtime activation token")
    return config
