from pathlib import Path

import yaml

from rosetta.config import load_config
from rosetta.observer import WATCHED_PATHS

ROOT = Path(__file__).resolve().parents[2]


def test_staging_compose_has_no_ingress_secrets_or_worker_internet() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.staging.yaml").read_text())
    services = compose["services"]
    assert set(services) == {"observer", "egress-proxy"}
    assert compose["networks"]["observer-internal"]["internal"] is True

    for service in services.values():
        assert "ports" not in service
        assert "build" not in service
        assert service["read_only"] is True
        assert service["user"] == "65532:65532"
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "/var/run/docker.sock" not in str(service)
        assert "secret" not in str(service).lower()

    assert services["observer"]["networks"] == ["observer-internal"]
    assert set(services["egress-proxy"]["networks"]) == {"observer-internal", "egress"}
    assert "https://technocore.chat" in services["egress-proxy"]["command"]
    assert services["egress-proxy"]["healthcheck"]["retries"] == 12
    assert services["observer"]["depends_on"]["egress-proxy"]["condition"] == "service_healthy"
    assert services["observer"]["command"][0] == "rosetta.observer"
    assert "public_writes" in services["observer"]["healthcheck"]["test"][-1]


def test_staging_profile_is_strictly_read_only_and_closed() -> None:
    config = load_config(ROOT / "config/config.staging.example.yaml", {})
    assert config.mode == "dry_run"
    assert config.observer.enabled
    assert config.technocore.base_url == "https://technocore.chat"
    assert config.observer.fetch_base_url == "http://egress-proxy:8081"
    assert not config.discovery.enabled
    assert not config.service.enabled
    assert not config.publisher.enabled
    assert config.model.provider == "disabled"
    assert config.rosetta.max_parallel_runners == 1
    assert WATCHED_PATHS == (
        "/healthz",
        "/.well-known/agent.json",
        "/openapi.json",
    )


def test_systemd_supervises_the_whole_compose_boundary() -> None:
    unit = (ROOT / "deploy/rosetta-observer.service").read_text()
    assert "--abort-on-container-exit" in unit
    assert "Restart=on-failure" in unit
    assert "EnvironmentFile=/etc/rosetta/staging.env" in unit
    assert "deploy/compose.staging.yaml" in unit
