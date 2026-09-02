"""Verify a deployed read-only observer without making network requests."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = "technocore-rosetta-staging"
MAX_HEALTH_AGE_SECONDS = 660
MAX_STATUS_OUTPUT_BYTES = 64 * 1024
Runner = Callable[..., subprocess.CompletedProcess[str]]


class VerificationError(RuntimeError):
    """A stable deployment verification failure."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise VerificationError(reason)


def command(*parts: str) -> str:
    try:
        # Every caller supplies a fixed executable and argument structure from this module.
        return subprocess.run(  # noqa: S603
            parts, check=True, capture_output=True, text=True
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise VerificationError(f"command_failed:{Path(parts[0]).name}") from exc
    except OSError as exc:
        raise VerificationError(f"command_unavailable:{Path(parts[0]).name}") from exc


def container_status(
    container_id: str,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    parts = [
        "docker",
        "exec",
        "--user",
        "65532:65532",
        container_id,
        "python",
        "/opt/rosetta/tools/staging_status.py",
        "--state-dir",
        "/var/lib/rosetta/state",
        "--evidence-dir",
        "/var/lib/rosetta/evidence",
        "--expected-release",
        "v0.10.0",
        "--max-age-seconds",
        str(MAX_HEALTH_AGE_SECONDS),
        "--min-observations",
        "1",
        "--max-evidence-bytes",
        "104857600",
    ]
    try:
        completed = runner(
            parts,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationError("offline_status_unavailable") from exc
    raw = completed.stdout.strip()
    if completed.returncode != 0 and not raw:
        raise VerificationError("offline_status_child_failed")
    if len(raw.encode("utf-8")) > MAX_STATUS_OUTPUT_BYTES:
        raise VerificationError("offline_status_output_oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError("offline_status_output_invalid") from exc
    if not isinstance(value, dict) or value.get("schema") != "rosetta.staging-status.v2":
        raise VerificationError("offline_status_output_invalid")
    if completed.returncode != 0:
        reasons = value.get("reasons")
        if isinstance(reasons, list) and reasons and all(isinstance(item, str) for item in reasons):
            detail = ",".join(reasons[:8])
            raise VerificationError(f"offline_status_failed:{detail}")
        raise VerificationError("offline_status_failed")
    return value


def verify(
    expected_image: str, expected_release_dir: Path, not_before: datetime
) -> dict[str, object]:
    require(
        command("systemctl", "is-active", "rosetta-observer.service") == "active",
        "service_inactive",
    )
    require(
        command("systemctl", "is-enabled", "rosetta-observer.service") == "enabled",
        "service_disabled",
    )
    require(Path("/opt/rosetta/current").resolve() == expected_release_dir, "release_link_mismatch")

    container_ids = command(
        "docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"
    ).splitlines()
    require(len(container_ids) == 2, "container_count_mismatch")
    containers = json.loads(command("docker", "inspect", *container_ids))
    by_service = {
        item["Config"]["Labels"]["com.docker.compose.service"]: item for item in containers
    }
    require(set(by_service) == {"observer", "egress-proxy"}, "container_set_mismatch")
    for item in by_service.values():
        require(item["Image"] == expected_image, "container_image_mismatch")
        require(item["Config"]["User"] == "65532:65532", "container_user_mismatch")
        require(item["HostConfig"]["ReadonlyRootfs"] is True, "writable_container_root")
        require(item["HostConfig"]["Privileged"] is False, "privileged_container")
        require(item["HostConfig"]["CapDrop"] == ["ALL"], "capabilities_not_dropped")
        require(
            "no-new-privileges:true" in item["HostConfig"]["SecurityOpt"],
            "new_privileges_allowed",
        )
        require(not item["HostConfig"].get("PortBindings"), "container_port_published")
        require(item["State"]["Running"] is True, "container_not_running")
        require(item["State"]["Health"]["Status"] == "healthy", "container_not_healthy")
        require(
            all("docker.sock" not in mount["Source"] for mount in item["Mounts"]),
            "docker_socket_mounted",
        )

    observer = by_service["observer"]
    egress = by_service["egress-proxy"]
    require(
        set(observer["NetworkSettings"]["Networks"]) == {f"{PROJECT}_observer-internal"},
        "observer_network_mismatch",
    )
    require(
        set(egress["NetworkSettings"]["Networks"])
        == {f"{PROJECT}_observer-internal", f"{PROJECT}_egress"},
        "egress_network_mismatch",
    )
    require(
        {mount["Destination"] for mount in observer["Mounts"]}
        == {"/etc/rosetta/config.yaml", "/var/lib/rosetta/state", "/var/lib/rosetta/evidence"},
        "observer_mount_mismatch",
    )
    require(egress["Mounts"] == [], "egress_mount_present")

    for line in command("ss", "-H", "-lnt").splitlines():
        local_address = line.split()[3]
        require(
            local_address.endswith(":22") or local_address.startswith("127.0.0.1:"),
            f"unexpected_listener:{local_address}",
        )

    health = json.loads(Path("/var/lib/rosetta/state/health.json").read_text())
    require(health.get("schema") == "rosetta.observer-health.v2", "invalid_health_schema")
    require(health.get("status") == "healthy", "observer_unhealthy")
    require(health.get("safety_status") == "safe", "observer_safety_unsafe")
    require(health.get("mode") == "dry_run", "observer_not_dry_run")
    require(health.get("public_writes") == 0, "public_write_detected")
    checked_at = datetime.fromisoformat(str(health["checked_at"]))
    require(checked_at.tzinfo is not None, "health_timestamp_not_aware")
    checked_at = checked_at.astimezone(timezone.utc)
    require(checked_at >= not_before.astimezone(timezone.utc), "health_predates_activation")
    require(
        (datetime.now(timezone.utc) - checked_at).total_seconds() < MAX_HEALTH_AGE_SECONDS,
        "health_stale",
    )

    status = container_status(str(observer["Id"]))
    require(status["status"] in {"pass", "pass_with_warnings"}, "offline_status_failed")
    require(status["unsafe_check_count"] == 0, "unsafe_check_recorded")
    return {
        "schema": "rosetta.staging-live-verification.v3",
        "status": "pass",
        "containers": sorted(by_service),
        "image": expected_image,
        "safety_status": health["safety_status"],
        "compatibility_status": health["compatibility_status"],
        "observation_current": health.get("observation_current"),
        "public_writes": health["public_writes"],
        "safety_check_count": status["safety_check_count"],
        "warnings": status["warnings"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--expected-release-dir", type=Path, required=True)
    parser.add_argument("--not-before", required=True)
    args = parser.parse_args()
    try:
        not_before = datetime.fromisoformat(args.not_before)
        require(not_before.tzinfo is not None, "activation_timestamp_not_aware")
        result = verify(args.expected_image, args.expected_release_dir, not_before)
    except (KeyError, OSError, ValueError, json.JSONDecodeError, VerificationError) as exc:
        reason = str(exc) if isinstance(exc, VerificationError) else type(exc).__name__
        print(
            json.dumps(
                {
                    "schema": "rosetta.staging-live-verification.v3",
                    "status": "fail",
                    "reason": reason,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
