import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rosetta.persistence import StateStore
from tools.staging_status import check_status

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 30, 21, 0, tzinfo=timezone.utc)


def _write_state(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    state.mkdir()
    evidence.mkdir()
    health = {
        "schema": "rosetta.observer-health.v1",
        "mode": "dry_run",
        "public_writes": 0,
        "status": "healthy",
        "checked_at": NOW.isoformat(),
        "release": "0.10.0",
        "protocol_digest": DIGEST,
    }
    (state / "health.json").write_text(json.dumps(health), encoding="utf-8")
    observation = {
        "schema": "rosetta.protocol-observation.v1",
        "release": "0.10.0",
        "protocol_digest": DIGEST,
        "public_writes": 0,
    }
    (evidence / f"{'a' * 64}.json").write_text(json.dumps(observation), encoding="utf-8")
    store = StateStore(state / "observer.sqlite3")
    store.record_protocol_observation(DIGEST, "0.10.0", NOW)
    store.close()
    return state, evidence


def _check(state: Path, evidence: Path, now: datetime = NOW) -> dict[str, object]:
    return check_status(
        state,
        evidence,
        expected_release="v0.10.0",
        max_age_seconds=660,
        min_observations=1,
        max_evidence_bytes=1024 * 1024,
        now=now,
    )


def test_staging_status_passes_for_consistent_fresh_read_only_state(tmp_path: Path) -> None:
    state, evidence = _write_state(tmp_path)
    result = _check(state, evidence)
    assert result["status"] == "pass"
    assert result["reasons"] == []
    assert result["observation_count"] == 1


def test_staging_status_fails_closed_on_stale_or_writable_health(tmp_path: Path) -> None:
    state, evidence = _write_state(tmp_path)
    health = json.loads((state / "health.json").read_text(encoding="utf-8"))
    health["public_writes"] = 1
    (state / "health.json").write_text(json.dumps(health), encoding="utf-8")
    result = _check(state, evidence, NOW + timedelta(seconds=661))
    assert result["status"] == "fail"
    assert "public_write_count_nonzero" in result["reasons"]
    assert "health_stale" in result["reasons"]


def test_staging_status_fails_closed_on_kill_switch_and_missing_evidence(tmp_path: Path) -> None:
    state, evidence = _write_state(tmp_path)
    (state / "KILL_SWITCH").touch()
    (evidence / f"{'a' * 64}.json").unlink()
    result = _check(state, evidence)
    assert result["status"] == "fail"
    assert "kill_switch_active" in result["reasons"]
    assert "evidence_unreadable:FileNotFoundError" in result["reasons"]


def test_staging_status_rejects_symlinked_state_files(tmp_path: Path) -> None:
    state, evidence = _write_state(tmp_path)
    real_health = tmp_path / "real-health.json"
    (state / "health.json").replace(real_health)
    (state / "health.json").symlink_to(real_health)
    result = _check(state, evidence)
    assert result["status"] == "fail"
    assert "health_unreadable:ValueError" in result["reasons"]

    (state / "health.json").unlink()
    real_health.replace(state / "health.json")
    real_database = tmp_path / "real.sqlite3"
    (state / "observer.sqlite3").replace(real_database)
    (state / "observer.sqlite3").symlink_to(real_database)
    result = _check(state, evidence)
    assert result["status"] == "fail"
    assert "database_unreadable:OSError" in result["reasons"]
