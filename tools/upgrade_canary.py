"""Deterministic no-network canary for upstream release churn and recovery."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from rosetta.config import load_config
from rosetta.observer import WATCHED_PATHS, ObserverService, ReadOnlyProbeClient
from rosetta_signer.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
BASE_TIME = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Phase:
    name: str
    release: str | None = None
    status_code: int | None = None
    invalid_authority: bool = False


PHASES = (
    Phase("reviewed_baseline", release="0.10.0"),
    Phase("additive_next_release", release="0.11.0"),
    Phase("rate_limited", status_code=429),
    Phase("temporarily_unavailable", status_code=503),
    Phase("rejected_authority", release="0.11.0", invalid_authority=True),
    Phase("reviewed_baseline_recovered", release="0.10.0"),
)


def _documents(phase: Phase) -> dict[str, tuple[str, bytes]]:
    if phase.release is None:
        raise ValueError("release_required")
    openapi_url = (
        "https://unexpected.invalid/openapi.json"
        if phase.invalid_authority
        else "https://technocore.chat/openapi.json"
    )
    manifest = {
        "name": "technocore-chat",
        "version": phase.release,
        "documentation": {
            "openapi": openapi_url,
            "manual": "https://technocore.chat/llms.txt",
        },
        "capabilities": {"future_additive_field": True},
    }
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "Technocore", "version": phase.release},
        "paths": {path: {"get": {"x-future-additive-field": True}} for path in WATCHED_PATHS},
        "x-future-additive-field": {"safe_to_ignore": True},
    }
    return {
        "/healthz": ("text/plain; charset=utf-8", b"ok\n"),
        "/.well-known/agent.json": ("application/json", canonical_json(manifest)),
        "/openapi.json": ("application/json", canonical_json(openapi)),
    }


class SequencedTransport:
    def __init__(self) -> None:
        self.index = 0
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.index >= len(PHASES):
            raise AssertionError("unexpected_extra_probe")
        phase = PHASES[self.index]
        self.requests.append((request.method, request.url.path))
        if phase.status_code is not None:
            self.index += 1
            headers = {"Retry-After": "2"} if phase.status_code == 429 else {}
            return httpx.Response(phase.status_code, headers=headers)
        content_type, body = _documents(phase)[request.url.path]
        if request.url.path == "/openapi.json":
            self.index += 1
        return httpx.Response(200, headers={"content-type": content_type}, content=body)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def run_canary(output: Path) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runtime = output / "runtime"
    state = runtime / "state"
    evidence = runtime / "evidence"
    config_data = yaml.safe_load((ROOT / "config/config.staging.example.yaml").read_text())
    config_data["observer"]["state_directory"] = str(state)
    config_data["observer"]["evidence_directory"] = str(evidence)
    config_data["operations"]["kill_switch_file"] = str(state / "KILL_SWITCH")
    config_path = runtime / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=True), encoding="utf-8")
    config = load_config(config_path, {})

    sequence = SequencedTransport()
    client = ReadOnlyProbeClient(
        "https://canary.invalid",
        config.technocore.base_url,
        config.technocore.pinned_release,
        config.technocore.request_timeout_seconds,
        config.observer.max_response_bytes,
        transport=httpx.MockTransport(sequence),
    )
    timestamps = iter(BASE_TIME + timedelta(minutes=5 * index) for index in range(len(PHASES)))
    service = ObserverService(config, client=client, clock=lambda: next(timestamps))
    results: list[dict[str, object]] = []
    try:
        for phase in PHASES:
            result = service.observe_once()
            _require(result.get("safety_status") == "safe", f"unsafe:{phase.name}")
            _require(result.get("public_writes") == 0, f"public_write:{phase.name}")
            _require(not service.stop_requested, f"observer_stopped:{phase.name}")
            results.append(
                {
                    "phase": phase.name,
                    "safety_status": result["safety_status"],
                    "compatibility_status": result["compatibility_status"],
                    "observation_current": result.get("observation_current"),
                    "public_writes": result["public_writes"],
                }
            )
    finally:
        service.close()

    expected_compatibility = [
        "compatible",
        "release_drift",
        "unavailable",
        "unavailable",
        "rejected",
        "compatible",
    ]
    _require(
        [item["compatibility_status"] for item in results] == expected_compatibility,
        "unexpected_compatibility_sequence",
    )
    _require(sequence.index == len(PHASES), "scenario_not_completed")
    _require(all(method == "GET" for method, _path in sequence.requests), "non_get_request")
    _require(
        all(path in WATCHED_PATHS for _method, path in sequence.requests),
        "non_allowlisted_path",
    )

    connection = sqlite3.connect(f"file:{state / 'observer.sqlite3'}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        safety_check_count, unsafe_check_count, write_count = connection.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN safety_status != 'safe' THEN 1 ELSE 0 END), "
            "SUM(public_writes) FROM observer_checks"
        ).fetchone()
    finally:
        connection.close()
    _require(integrity == ("ok",), "database_integrity_failed")
    _require(safety_check_count == len(PHASES), "missing_safety_check")
    _require(int(unsafe_check_count or 0) == 0, "unsafe_check_recorded")
    _require(int(write_count or 0) == 0, "public_write_recorded")

    evidence_files = sorted(evidence.glob("*.json"))
    _require(len(evidence_files) == 2, "unexpected_evidence_count")
    health = json.loads((state / "health.json").read_text(encoding="utf-8"))
    _require(health.get("schema") == "rosetta.observer-health.v2", "invalid_health_schema")
    _require(health.get("safety_status") == "safe", "final_safety_not_safe")
    _require(health.get("compatibility_status") == "compatible", "recovery_failed")

    report: dict[str, Any] = {
        "schema": "rosetta.upstream-upgrade-canary.v1",
        "status": "pass",
        "pinned_release": config.technocore.pinned_release,
        "synthetic_next_release": "v0.11.0",
        "sequence": results,
        "observer_remained_running": True,
        "recovered_without_restart": True,
        "safety_check_count": safety_check_count,
        "unsafe_check_count": int(unsafe_check_count or 0),
        "public_writes": int(write_count or 0),
        "request_methods": sorted({method for method, _path in sequence.requests}),
        "request_paths": sorted({path for _method, path in sequence.requests}),
        "evidence_files": len(evidence_files),
        "final_safety_status": health["safety_status"],
        "final_compatibility_status": health["compatibility_status"],
    }
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="upgrade_canary")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_canary(args.output)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
