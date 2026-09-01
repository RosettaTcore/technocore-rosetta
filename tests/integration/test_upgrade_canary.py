from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from rosetta import observer as observer_module
from rosetta.config import load_config
from rosetta.observer import EndpointEvidence, ObserverService, ProtocolObservation
from tools.upgrade_canary import run_canary

ROOT = Path(__file__).resolve().parents[2]


def test_next_upstream_release_does_not_stop_observer(tmp_path: Path) -> None:
    output = tmp_path / "upgrade-canary"
    report = run_canary(output)

    assert report["status"] == "pass"
    assert report["observer_remained_running"] is True
    assert report["recovered_without_restart"] is True
    assert report["safety_check_count"] == 6
    assert report["unsafe_check_count"] == 0
    assert report["public_writes"] == 0
    assert report["request_methods"] == ["GET"]
    assert report["request_paths"] == [
        "/.well-known/agent.json",
        "/healthz",
        "/openapi.json",
    ]
    assert [step["compatibility_status"] for step in report["sequence"]] == [
        "compatible",
        "release_drift",
        "unavailable",
        "unavailable",
        "rejected",
        "compatible",
    ]
    assert json.loads((output / "report.json").read_text()) == report


def test_observer_process_recovers_from_unexpected_probe_fault_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = yaml.safe_load((ROOT / "config/config.staging.example.yaml").read_text())
    data["observer"]["state_directory"] = str(tmp_path / "state")
    data["observer"]["evidence_directory"] = str(tmp_path / "evidence")
    data["operations"]["kill_switch_file"] = str(tmp_path / "state/KILL_SWITCH")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(config_path, {})

    endpoint = EndpointEvidence("/healthz", "sha256:" + "1" * 64, 3, "text/plain")
    recovered = ProtocolObservation(
        "0.10.0",
        "sha256:" + "2" * 64,
        (endpoint,),
        "0.10.0",
        "compatible",
    )

    class RecoveringClient:
        def __init__(self) -> None:
            self.calls = 0
            self.service: ObserverService | None = None

        def probe(self) -> ProtocolObservation:
            self.calls += 1
            if self.calls == 1:
                raise TypeError("synthetic unexpected parser fault")
            assert self.service is not None
            self.service.request_stop()
            return recovered

        def close(self) -> None:
            return None

    client = RecoveringClient()
    times = iter(
        (
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 2, tzinfo=timezone.utc) + timedelta(minutes=5),
        )
    )
    service = ObserverService(config, client=client, clock=lambda: next(times))  # type: ignore[arg-type]
    client.service = service
    monotonic = iter((0.0, 301.0, 302.0))
    monkeypatch.setattr(observer_module.time, "monotonic", lambda: next(monotonic))

    service.run()
    checks = service.store.connection.execute(
        "SELECT safety_status, compatibility_status, reason FROM observer_checks "
        "ORDER BY checked_at"
    ).fetchall()
    health = json.loads((tmp_path / "state/health.json").read_text())
    service.close()

    assert client.calls == 2
    assert service.stop_requested is True
    assert checks == [
        ("unsafe", "unknown", "observer_internal_error"),
        ("safe", "compatible", None),
    ]
    assert health["status"] == "healthy"
    assert health["safety_status"] == "safe"
    assert health["compatibility_status"] == "compatible"
    assert health["public_writes"] == 0
