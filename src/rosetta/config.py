"""Safe configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, validator


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

    @validator("technocore")
    def origin_is_allowlisted(cls, value: TechnocoreSettings) -> TechnocoreSettings:
        if value.base_url not in [origin.rstrip("/") for origin in value.allowed_origins]:
            raise ValueError("Technocore origin is not allowlisted")
        return value


def load_config(path: Path, environ: dict[str, str] | None = None) -> AppConfig:
    env = os.environ if environ is None else environ
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a mapping")
    if env.get("ROSETTA_MODE") not in {None, "dry_run"}:
        raise ValueError("local MVP permits dry_run only")
    return AppConfig.parse_obj(data)
