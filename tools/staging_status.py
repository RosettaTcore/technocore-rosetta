"""Fail-closed offline validation of read-only staging state."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_JSON_BYTES = 2 * 1024 * 1024


def _load_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not_regular_file:{path.name}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"oversized_json:{path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"not_an_object:{path.name}")
    return value


def check_status(
    state_directory: Path,
    evidence_directory: Path,
    *,
    expected_release: str,
    max_age_seconds: int,
    min_observations: int,
    max_evidence_bytes: int,
    now: datetime | None = None,
) -> dict[str, object]:
    checked_at = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    result: dict[str, object] = {
        "schema": "rosetta.staging-status.v2",
        "checked_at": checked_at.astimezone(timezone.utc).isoformat(),
        "status": "fail",
        "reasons": reasons,
    }
    warnings: list[str] = []
    result["warnings"] = warnings
    health_release: object = None
    protocol_digest: object = None

    if (state_directory / "KILL_SWITCH").exists():
        reasons.append("kill_switch_active")

    try:
        health = _load_object(state_directory / "health.json")
        if health.get("schema") != "rosetta.observer-health.v2":
            reasons.append("invalid_health_schema")
        if health.get("status") != "healthy":
            reasons.append("observer_not_healthy")
        if health.get("safety_status") != "safe":
            reasons.append("observer_safety_not_safe")
        if health.get("mode") != "dry_run":
            reasons.append("observer_not_dry_run")
        if health.get("public_writes") != 0:
            reasons.append("public_write_count_nonzero")
        health_release = health.get("release")
        compatibility_status = health.get("compatibility_status")
        if compatibility_status != "compatible":
            warnings.append(f"compatibility_{compatibility_status or 'unknown'}")
        if health_release is None:
            warnings.append("no_protocol_observation")
        elif health_release != expected_release.removeprefix("v"):
            warnings.append("release_drift")
        protocol_digest = health.get("protocol_digest")
        if protocol_digest is not None and (
            not isinstance(protocol_digest, str) or DIGEST.fullmatch(protocol_digest) is None
        ):
            reasons.append("invalid_protocol_digest")
            protocol_digest = None
        observed_at = datetime.fromisoformat(str(health["checked_at"]))
        if observed_at.tzinfo is None:
            raise ValueError("health_timestamp_not_aware")
        age = (
            checked_at.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
        ).total_seconds()
        result["health_age_seconds"] = round(age, 3)
        if age < -60:
            reasons.append("health_timestamp_in_future")
        if age > max_age_seconds:
            reasons.append("health_stale")
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        reasons.append(f"health_unreadable:{type(exc).__name__}")
        protocol_digest = None

    evidence_bytes = 0
    try:
        for path in evidence_directory.iterdir():
            if path.is_symlink() or not path.is_file():
                reasons.append("unexpected_evidence_entry")
                continue
            evidence_bytes += path.stat().st_size
        result["evidence_bytes"] = evidence_bytes
        if evidence_bytes > max_evidence_bytes:
            reasons.append("evidence_budget_exceeded")
    except FileNotFoundError:
        reasons.append("evidence_directory_missing")

    if protocol_digest is not None:
        evidence_path = evidence_directory / f"{protocol_digest.removeprefix('sha256:')}.json"
        try:
            evidence = _load_object(evidence_path)
            if evidence.get("schema") != "rosetta.protocol-observation.v1":
                reasons.append("invalid_evidence_schema")
            if evidence.get("protocol_digest") != protocol_digest:
                reasons.append("evidence_digest_mismatch")
            if evidence.get("release") != health_release:
                reasons.append("evidence_release_mismatch")
            if evidence.get("public_writes") != 0:
                reasons.append("evidence_public_write_count_nonzero")
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"evidence_unreadable:{type(exc).__name__}")

    database = state_directory / "observer.sqlite3"
    try:
        if database.is_symlink() or not database.is_file():
            raise OSError("observer database is not a regular file")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                reasons.append("database_integrity_failed")
            row = None
            if protocol_digest is not None:
                row = connection.execute(
                    "SELECT release, observation_count FROM protocol_observations "
                    "WHERE protocol_digest=?",
                    (protocol_digest,),
                ).fetchone()
            safety_row = connection.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN safety_status != 'safe' OR public_writes != 0 THEN 1 ELSE 0 END) "
                "FROM (SELECT safety_status, public_writes FROM observer_checks "
                "ORDER BY checked_at DESC LIMIT ?)",
                (min_observations,),
            ).fetchone()
        finally:
            connection.close()
        if protocol_digest is not None:
            if row is None:
                reasons.append("protocol_observation_missing")
            else:
                result["observation_count"] = int(row[1])
                if row[0] != health_release:
                    reasons.append("database_release_mismatch")
        safety_check_count = int(safety_row[0]) if safety_row is not None else 0
        unsafe_check_count = int(safety_row[1] or 0) if safety_row is not None else 0
        result["safety_check_count"] = safety_check_count
        result["unsafe_check_count"] = unsafe_check_count
        if safety_check_count < min_observations:
            reasons.append("safety_check_count_too_low")
        if unsafe_check_count:
            reasons.append("unsafe_check_recorded")
    except (sqlite3.Error, OSError) as exc:
        reasons.append(f"database_unreadable:{type(exc).__name__}")

    if not reasons:
        result["status"] = "pass_with_warnings" if warnings else "pass"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--expected-release", default="v0.10.0")
    parser.add_argument("--max-age-seconds", type=int, default=660)
    parser.add_argument("--min-observations", type=int, default=1)
    parser.add_argument("--max-evidence-bytes", type=int, default=104_857_600)
    args = parser.parse_args()
    result = check_status(
        args.state_dir,
        args.evidence_dir,
        expected_release=args.expected_release,
        max_age_seconds=args.max_age_seconds,
        min_observations=args.min_observations,
        max_evidence_bytes=args.max_evidence_bytes,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if str(result["status"]).startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
