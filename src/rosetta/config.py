"""Safe configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, root_validator, validator


class ClosedSettings(BaseModel):
    class Config:
        extra = "forbid"


class TechnocoreSettings(ClosedSettings):
    base_url: str
    pinned_release: str
    allowed_origins: list[str]
    long_poll_seconds: int = 10
    request_timeout_seconds: int = 20

    @validator("pinned_release")
    def pinned_release_only(cls, value: str) -> str:
        if value in {"main", "master", "latest"} or not value.startswith("v"):
            raise ValueError("Technocore release must be an explicit version")
        return value

    @validator("base_url")
    def fixed_origin(cls, value: str, values: dict[str, object]) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must have a fixed HTTP(S) origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an origin only")
        return value.rstrip("/")


class RosettaSettings(ClosedSettings):
    scenario_allowlist: list[str]
    max_runs_per_day: int = 4
    max_parallel_runners: int = 2


class AdapterSettings(ClosedSettings):
    registry_file: str
    required_mvp_adapters: list[str]


class RunnerSettings(ClosedSettings):
    backend: Literal["container"]
    network_policy: Literal["local_technocore_only"]
    read_only_root: Literal[True]
    run_as_non_root: Literal[True]
    memory_mb: int
    cpu_quota: float
    timeout_seconds: int
    allow_host_mounts: Literal[False]
    allow_docker_socket: Literal[False]
    allow_secrets: Literal[False]


class DiscoverySettings(ClosedSettings):
    enabled: bool = False


class ServiceSettings(ClosedSettings):
    enabled: bool = False
    max_requests_per_did_per_day: int = 2
    max_external_jobs_per_day: int = 8
    max_queue_depth: int = 16
    max_request_expiry_hours: int = 24


class ModelSettings(ClosedSettings):
    provider: Literal["disabled"] = "disabled"


class PublisherSettings(ClosedSettings):
    enabled: Literal[False] = False


class OperationsSettings(ClosedSettings):
    kill_switch_file: str
    fail_read_only_after_errors: int = 3
    monthly_total_budget_eur: int = 40


class ObserverSettings(ClosedSettings):
    enabled: bool = False
    fetch_base_url: str = "http://egress-proxy:8081"
    interval_seconds: int = 300
    max_response_bytes: int = 1_048_576
    state_directory: str = "/var/lib/rosetta/state"
    evidence_directory: str = "/var/lib/rosetta/evidence"

    @validator("interval_seconds")
    def bounded_interval(cls, value: int) -> int:
        if value < 60 or value > 86_400:
            raise ValueError("observer interval must be between 60 and 86400 seconds")
        return value

    @validator("max_response_bytes")
    def bounded_response(cls, value: int) -> int:
        if value < 1_024 or value > 4_194_304:
            raise ValueError("observer response limit must be between 1 KiB and 4 MiB")
        return value

    @validator("fetch_base_url")
    def fixed_fetch_origin(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("observer fetch_base_url must be a fixed HTTP(S) origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("observer fetch_base_url must be an origin only")
        if parsed.scheme == "http" and parsed.hostname not in {
            "egress-proxy",
            "localhost",
            "127.0.0.1",
        }:
            raise ValueError("plain HTTP observer fetches are limited to the local egress boundary")
        return value.rstrip("/")

    @validator("state_directory", "evidence_directory")
    def absolute_runtime_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("observer runtime directories must be absolute")
        return value


class AppConfig(ClosedSettings):
    mode: Literal["dry_run"] = "dry_run"
    technocore: TechnocoreSettings
    rosetta: RosettaSettings
    adapters: AdapterSettings
    runners: RunnerSettings
    discovery: DiscoverySettings
    service: ServiceSettings
    model: ModelSettings
    publisher: PublisherSettings
    operations: OperationsSettings
    observer: ObserverSettings = Field(default_factory=ObserverSettings)

    @validator("technocore")
    def origin_is_allowlisted(cls, value: TechnocoreSettings) -> TechnocoreSettings:
        if value.base_url not in [origin.rstrip("/") for origin in value.allowed_origins]:
            raise ValueError("Technocore origin is not allowlisted")
        return value

    @root_validator
    def observer_is_read_only(cls, values: dict[str, object]) -> dict[str, object]:
        observer = values.get("observer")
        technocore = values.get("technocore")
        if isinstance(observer, ObserverSettings) and observer.enabled:
            if not isinstance(technocore, TechnocoreSettings):
                return values
            if not technocore.base_url.startswith("https://"):
                raise ValueError("enabled observer requires an HTTPS Technocore authority")
            for section in ("discovery", "service"):
                configured = values.get(section)
                if configured is not None and getattr(configured, "enabled", False):
                    raise ValueError(
                        "observer requires discovery and service writes to be disabled"
                    )
        return values


def load_config(path: Path, environ: dict[str, str] | None = None) -> AppConfig:
    env = os.environ if environ is None else environ
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a mapping")
    if env.get("ROSETTA_MODE") not in {None, "dry_run"}:
        raise ValueError("local MVP permits dry_run only")
    return AppConfig.parse_obj(data)
