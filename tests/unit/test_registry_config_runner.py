from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rosetta.config import load_config
from rosetta.contracts import AdapterManifest, AdapterRegistryContract
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.registry import AdapterRegistry
from rosetta.runners import RunnerPolicy, RunnerSupervisor
from rosetta.scheduler import REQUIRED_MATRIX, Scheduler

ROOT = Path(__file__).resolve().parents[2]


def test_registry_is_immutable_and_complete() -> None:
    registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
    assert registry.ids == ["official-mcp", "python-http", "raw-fetch", "typescript-http"]
    assert registry.digest.startswith("sha256:")
    with pytest.raises(ValueError):
        registry.require("public-message-selected")
    assert registry.contains_exact(registry.contract.adapters[0])
    changed = registry.contract.adapters[0].copy(update={"runtime": "changed"})
    assert not registry.contains_exact(changed)


def test_mutable_manifest_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AdapterManifest(
            id="bad",
            runtime="python",
            source_repository="https://example.invalid/repo",
            source_revision_kind="git_commit",
            source_revision="main",
            dependency_lock_sha256="a" * 64,
            image="bad:latest",
            image_digest="latest",
            transport="http",
            capabilities=[],
        )


def test_config_has_safe_defaults_and_rejects_drift(tmp_path: Path) -> None:
    config = load_config(ROOT / "config/config.local.yaml", {})
    assert config.mode == "dry_run"
    assert not config.publisher.enabled
    assert config.model.provider == "disabled"
    assert config.runners.read_only_root
    data = yaml.safe_load((ROOT / "config/config.local.yaml").read_text())
    data["publisher"]["enabled"] = True
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError):
        load_config(bad, {})


def test_runner_spec_is_non_root_read_only_and_has_no_authority() -> None:
    registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
    spec = RunnerSupervisor(registry, allow_ungated_fixture=True).compile("python-http")
    command = " ".join(spec["command"])
    assert "--read-only" in command
    assert "--user 65532:65532" in command
    assert "--cap-drop=ALL" in command
    assert spec["host_mounts"] == []
    assert spec["secrets"] == []
    assert str(spec["image"]).startswith("sha256:")
    with pytest.raises(ValueError):
        RunnerPolicy().validate(["run", "--privileged"])
    valid = RunnerPolicy().docker_arguments(registry.contract.adapters[0])
    with pytest.raises(ValueError, match="forbidden"):
        RunnerPolicy().validate([*valid, "--network=host"])
    with pytest.raises(ValueError, match="operational gate"):
        RunnerSupervisor(registry)


@pytest.mark.parametrize(
    "mutation,error",
    [
        (("technocore", "pinned_release", "main"), "explicit version"),
        (("technocore", "base_url", "ftp://localhost"), "HTTP"),
        (("technocore", "base_url", "http://technocore-local/path"), "origin only"),
        (("technocore", "allowed_origins", ["http://other"]), "allowlisted"),
    ],
)
def test_config_rejects_origin_and_release_authority(
    tmp_path: Path, mutation: tuple[str, str, object], error: str
) -> None:
    data = yaml.safe_load((ROOT / "config/config.local.yaml").read_text())
    section, key, value = mutation
    data[section][key] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match=error):
        load_config(path, {})


def test_config_rejects_nonmapping_and_environment_override(tmp_path: Path) -> None:
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("disabled\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_config(scalar, {})
    with pytest.raises(ValueError, match="dry_run"):
        load_config(ROOT / "config/config.local.yaml", {"ROSETTA_MODE": "production"})


@pytest.mark.parametrize(
    "section,key,value,error",
    [
        ("observer", "interval_seconds", 1, "interval"),
        ("observer", "max_response_bytes", 100, "response limit"),
        ("observer", "fetch_base_url", "http://public.invalid", "local egress"),
        ("observer", "fetch_base_url", "not-a-url", "fixed HTTP"),
        ("observer", "fetch_base_url", "https://fetch.invalid/path", "origin only"),
        ("observer", "state_directory", "relative/state", "absolute"),
        ("technocore", "base_url", "http://technocore-local:8080", "HTTPS"),
    ],
)
def test_enabled_observer_rejects_unsafe_configuration(
    tmp_path: Path, section: str, key: str, value: object, error: str
) -> None:
    data = yaml.safe_load((ROOT / "config/config.staging.example.yaml").read_text())
    data[section][key] = value
    if section == "technocore":
        data["technocore"]["allowed_origins"] = [value]
    path = tmp_path / "observer.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match=error):
        load_config(path, {})


@pytest.mark.parametrize("section", ["discovery", "service"])
def test_enabled_observer_rejects_write_services(tmp_path: Path, section: str) -> None:
    data = yaml.safe_load((ROOT / "config/config.staging.example.yaml").read_text())
    data[section]["enabled"] = True
    path = tmp_path / "observer.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="writes.*disabled"):
        load_config(path, {})


def test_duplicate_registry_and_scheduler_matrix_fail_closed(tmp_path: Path) -> None:
    registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
    duplicate = AdapterRegistryContract(
        schema="rosetta.adapter-registry.v1",
        adapters=[registry.contract.adapters[0], registry.contract.adapters[0]],
    )
    with pytest.raises(ValueError, match="duplicate"):
        AdapterRegistry(duplicate)

    store = StateStore(tmp_path / "state.sqlite3")
    gate = OperationalGate(store, tmp_path / "KILL_SWITCH")
    scheduler = Scheduler(store, registry, gate)
    assert scheduler.compile_matrix() == REQUIRED_MATRIX
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    digest = "sha256:" + "f" * 64
    assert scheduler.observe(digest, "scenario", "manual", now)
    assert not scheduler.observe(digest, "scenario", "manual", now)
    store.close()
