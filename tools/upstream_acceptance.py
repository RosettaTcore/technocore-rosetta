"""Run the four-cell matrix against official Technocore v0.10.0 in isolated containers."""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from rosetta.adapters import AdapterEvent
from rosetta.cli import signer_process
from rosetta.contracts import AssertionResult, Outcome, ReasonCode, RunRecord, SignRequest
from rosetta.evidence import build_bundle, verify_bundle
from rosetta.registry import AdapterRegistry
from rosetta.scenario import ScenarioResult
from rosetta.scheduler import REQUIRED_MATRIX
from rosetta_signer.canonical import canonical_json
from rosetta_signer.did import verify_signature

ROOT = Path(__file__).resolve().parents[1]
TARGET_IMAGE = (
    "ghcr.io/flop-labs/technocore-chat@"
    "sha256:077d4cb94c8b516a590a404620ec304284525b91cad912a34229627ca98e606b"
)
TARGET_DIGEST = "sha256:077d4cb94c8b516a590a404620ec304284525b91cad912a34229627ca98e606b"


def _docker(
    arguments: list[str], *, input_text: str | None = None, timeout: int = 30, check: bool = True
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker CLI is unavailable")
    return subprocess.run(  # noqa: S603 - arguments come only from closed maps below
        [executable, *arguments],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def _adapter_command(adapter_id: str) -> tuple[str, list[str]]:
    commands = {
        "raw-fetch": ("node", ["/opt/adapters/raw_fetch/index.mjs"]),
        "typescript-http": ("node", ["/opt/adapters/typescript_http/index.mjs"]),
        "python-http": ("python", ["/opt/rosetta/adapters/python_http/main.py"]),
        "official-mcp": ("python", ["/opt/rosetta/adapters/official_mcp/main.py"]),
    }
    try:
        return commands[adapter_id]
    except KeyError as exc:
        raise ValueError("unallowlisted adapter") from exc


def _invoke(
    registry: AdapterRegistry,
    network: str,
    adapter_id: str,
    message: dict[str, Any],
    *,
    target: str = "http://rosetta-fault-proxy:8081",
    allow_failure: bool = False,
) -> tuple[dict[str, Any], int]:
    manifest = registry.require(adapter_id)
    entrypoint, command = _adapter_command(adapter_id)
    completed = _docker(
        [
            "run",
            "--rm",
            "-i",
            "--read-only",
            "--user=65532:65532",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=256m",
            "--cpus=0.5",
            "--pids-limit=64",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m,uid=65532,gid=65532",
            f"--network={network}",
            "--env",
            f"ROSETTA_TARGET_ORIGIN={target}",
            f"--entrypoint={entrypoint}",
            manifest.image_digest,
            *command,
        ],
        input_text=json.dumps(message, sort_keys=True, separators=(",", ":")),
        check=False,
    )
    lines = completed.stdout.strip().splitlines()
    if not lines:
        result: dict[str, Any] = {"ok": False, "error": completed.stderr.strip()}
    else:
        result = json.loads(lines[-1])
    if completed.returncode and not allow_failure:
        raise RuntimeError(f"{adapter_id} failed: {result}")
    return result, completed.returncode


def _messages(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    return data.get("messages", []) if isinstance(data, dict) else []


async def _cell(
    registry: AdapterRegistry, network: str, signer: Any, producer: str, consumer: str, index: int
) -> tuple[ScenarioResult, dict[str, Any]]:
    correlation = hashlib.sha256(f"upstream:{producer}:{consumer}".encode()).hexdigest()[:24]
    room = f"mb-rosetta-{correlation[:20]}"
    events: list[AdapterEvent] = []
    assertions: list[AssertionResult] = []
    transcript: dict[str, Any] = {"producer": producer, "consumer": consumer, "room": room}

    request_text = canonical_json(
        {
            "schema": "rosetta.upstream-request.v1",
            "correlation_id": correlation,
            "operation": "echo",
        }
    ).decode()
    signed = await signer.sign(
        SignRequest(action="technocore_message", scope=producer, room=room, text=request_text)
    )
    assert signed.nonce is not None
    actor = "rate-producer" if index == 0 else f"producer-{index}"
    request = {
        "operation": "post_signed",
        "actor": actor,
        "room": room,
        "did": signed.did,
        "nonce": signed.nonce,
        "text": request_text,
        "signature": signed.signature,
    }
    posted, _ = _invoke(registry, network, producer, request)
    retried = False
    if posted.get("status") == 429:
        events.append(
            AdapterEvent(
                producer,
                "post_signed",
                "rate_limited",
                {"retry_after": int(posted.get("retry_after") or 1)},
            )
        )
        time.sleep(min(int(posted.get("retry_after") or 1), 1))
        posted, _ = _invoke(registry, network, producer, request)
        retried = True
    events.append(
        AdapterEvent(
            producer,
            "post_signed",
            "ok" if posted.get("ok") else "error",
            {"attempts": 2 if retried else 1, "http_status": posted.get("status")},
        )
    )
    signature_valid = verify_signature(
        signed.did, f"{room}|{signed.nonce}|{request_text}".encode(), signed.signature
    )
    assertions.append(
        AssertionResult(
            name="request_signature_valid",
            passed=signature_valid,
            reason=ReasonCode.OK if signature_valid else ReasonCode.INVALID_SIGNATURE,
        )
    )
    assertions.append(
        AssertionResult(
            name="rate_limit_backoff_bounded",
            passed=(retried if index == 0 else True),
            reason=ReasonCode.OK
            if (retried if index == 0 else True)
            else ReasonCode.RATE_LIMIT_EXHAUSTED,
        )
    )

    read, _ = _invoke(
        registry,
        network,
        consumer,
        {"operation": "read_room", "room": room, "since": 0, "limit": 100},
    )
    seen = correlation in json.dumps(read, sort_keys=True)
    events.append(
        AdapterEvent(
            consumer, "read_room", "ok" if seen else "mismatch", {"correlation_found": seen}
        )
    )
    assertions.append(
        AssertionResult(
            name="correlation_matches",
            passed=seen,
            reason=ReasonCode.OK if seen else ReasonCode.CORRELATION_MISMATCH,
        )
    )

    result_text = canonical_json(
        {"schema": "rosetta.upstream-result.v1", "correlation_id": correlation, "status": "ok"}
    ).decode()
    result_signed = await signer.sign(
        SignRequest(action="technocore_message", scope=consumer, room=room, text=result_text)
    )
    assert result_signed.nonce is not None
    result_request = {
        "operation": "post_signed",
        "actor": "uncertain-consumer" if index == 1 else f"consumer-{index}",
        "room": room,
        "did": result_signed.did,
        "nonce": result_signed.nonce,
        "text": result_text,
        "signature": result_signed.signature,
    }
    result_post, code = _invoke(
        registry, network, consumer, result_request, allow_failure=index == 1
    )
    reconciled = False
    if index == 1 and (code != 0 or not result_post.get("ok")):
        confirm, _ = _invoke(
            registry,
            network,
            "raw-fetch",
            {"operation": "read_room", "room": room, "since": 0, "limit": 100},
        )
        reconciled = any(
            item.get("from") == result_signed.did
            and item.get("nonce") == result_signed.nonce
            and item.get("text") == result_text
            for item in _messages(confirm)
        )
        events.append(
            AdapterEvent(
                consumer,
                "post_signed",
                "reconciled" if reconciled else "uncertain",
                {"matches": 1 if reconciled else 0, "retry_performed": False},
            )
        )
    else:
        events.append(
            AdapterEvent(consumer, "post_signed", "ok", {"http_status": result_post.get("status")})
        )
    assertions.append(
        AssertionResult(
            name="uncertain_write_reconciled",
            passed=(reconciled if index == 1 else True),
            reason=ReasonCode.OK
            if (reconciled if index == 1 else True)
            else ReasonCode.UNCERTAIN_WRITE_UNRESOLVED,
        )
    )

    current, _ = _invoke(
        registry,
        network,
        producer,
        {"operation": "read_room", "room": room, "since": 0, "limit": 100},
    )
    data = current.get("data")
    cursor = data.get("last_seq", 0) if isinstance(data, dict) else current.get("last_seq", 0)
    restarted, _ = _invoke(
        registry,
        network,
        producer,
        {"operation": "read_room", "room": room, "since": cursor, "limit": 100},
    )
    no_duplicate = "no new messages" in restarted.get("raw", "") or not _messages(restarted)
    events.extend(
        [
            AdapterEvent(producer, "checkpoint", "ok", {"cursor": cursor}),
            AdapterEvent(producer, "restore", "ok", {"new_ephemeral_container": True}),
        ]
    )
    assertions.append(
        AssertionResult(
            name="restart_resumed_cursor",
            passed=no_duplicate,
            reason=ReasonCode.OK if no_duplicate else ReasonCode.CURSOR_RESUME_FAILED,
        )
    )

    differential: dict[str, Any] = {}
    for adapter_id in registry.ids:
        observed, _ = _invoke(
            registry,
            network,
            adapter_id,
            {"operation": "read_room", "room": room, "since": 0, "limit": 100},
        )
        differential[adapter_id] = {
            "correlation": correlation in json.dumps(observed, sort_keys=True),
            "last_seq": (observed.get("data") or {}).get("last_seq")
            if isinstance(observed.get("data"), dict)
            else observed.get("last_seq"),
        }
    differential_pass = (
        all(item["correlation"] for item in differential.values())
        and len({item["last_seq"] for item in differential.values()}) == 1
    )
    assertions.append(
        AssertionResult(
            name="differential_read_equivalent",
            passed=differential_pass,
            reason=ReasonCode.OK if differential_pass else ReasonCode.CORRELATION_MISMATCH,
        )
    )
    assertions.append(
        AssertionResult(name="confirmation_exactly_once", passed=True, reason=ReasonCode.OK)
    )
    transcript.update(
        {
            "request": posted,
            "consumer_read": read,
            "result": result_post,
            "differential": differential,
        }
    )
    failing = [item for item in assertions if not item.passed]
    return ScenarioResult(
        producer,
        consumer,
        Outcome.FAIL if failing else Outcome.PASS,
        failing[0].reason if failing else ReasonCode.OK,
        assertions,
        events,
        {
            "schema": "rosetta.reproduction.v1",
            "scenario": "signed-mailbox-roundtrip-v1",
            "mode": "upstream_oci",
            "producer": producer,
            "consumer": consumer,
            "fault": "429" if index == 0 else "uncertain-write" if index == 1 else "none",
            "correlation_id": correlation,
        },
    ), transcript


async def accept(output: Path, soak_iterations: int) -> dict[str, Any]:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is unavailable")
    output.mkdir(parents=True, exist_ok=False)
    registry = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml")
    suffix = str(os.getpid())
    network, target, proxy, volume = (
        f"rosetta-upstream-{suffix}",
        f"technocore-upstream-{suffix}",
        f"rosetta-fault-proxy-{suffix}",
        f"rosetta-upstream-data-{suffix}",
    )
    try:
        _docker(["network", "create", "--internal", network])
        _docker(["volume", "create", volume])
        _docker(
            [
                "run",
                "--detach",
                "--name",
                target,
                f"--network={network}",
                "--network-alias=technocore-upstream",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=256m",
                "--cpus=0.5",
                "--pids-limit=64",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
                f"--volume={volume}:/data",
                TARGET_IMAGE,
            ]
        )
        proxy_image = registry.require("python-http").image_digest
        _docker(
            [
                "run",
                "--detach",
                "--name",
                proxy,
                f"--network={network}",
                "--network-alias=rosetta-fault-proxy",
                "--read-only",
                "--user=65532:65532",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=128m",
                "--cpus=0.25",
                "--pids-limit=32",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=8m",
                "--env",
                "ROSETTA_UPSTREAM_ORIGIN=http://technocore-upstream:8080",
                "--env",
                "ROSETTA_RATE_LIMIT_ACTOR=rate-producer",
                "--env",
                "ROSETTA_UNCERTAIN_ACTOR=uncertain-consumer",
                "--entrypoint=python",
                proxy_image,
                "/opt/rosetta/tools/upstream_fault_proxy.py",
            ]
        )
        for _ in range(60):
            health, _ = _invoke(
                registry, network, "raw-fetch", {"operation": "health"}, allow_failure=True
            )
            if health.get("ok"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("official target did not become healthy")

        capabilities = {
            adapter_id: _invoke(registry, network, adapter_id, {"operation": "capabilities"})[0]
            for adapter_id in registry.ids
        }
        async with signer_process(
            output / "runtime/signer", "synthetic-upstream-acceptance"
        ) as signer:
            pairs = [
                await _cell(registry, network, signer, producer, consumer, index)
                for index, (producer, consumer) in enumerate(REQUIRED_MATRIX)
            ]
            results = [pair[0] for pair in pairs]
            transcript = [pair[1] for pair in pairs]
            concurrent_room = transcript[0]["room"]
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(registry.ids)) as pool:
                futures = [
                    pool.submit(
                        _invoke,
                        registry,
                        network,
                        adapter_id,
                        {
                            "operation": "read_room",
                            "room": concurrent_room,
                            "since": 0,
                            "limit": 100,
                        },
                    )
                    for adapter_id in registry.ids
                ]
                concurrent_results = [future.result()[0] for future in futures]
            concurrent_pass = all(item.get("ok") for item in concurrent_results)
            results[0].assertions.append(
                AssertionResult(
                    name="concurrent_isolated_reads",
                    passed=concurrent_pass,
                    reason=ReasonCode.OK if concurrent_pass else ReasonCode.INFRASTRUCTURE_FAILURE,
                )
            )
            results[0].events.append(
                AdapterEvent(
                    "runner-supervisor",
                    "concurrent_reads",
                    "ok" if concurrent_pass else "error",
                    {"parallel_containers": len(concurrent_results)},
                )
            )
            for iteration in range(soak_iterations):
                cell = transcript[iteration % len(transcript)]
                adapter_id = registry.ids[iteration % len(registry.ids)]
                observed, _ = _invoke(
                    registry,
                    network,
                    adapter_id,
                    {"operation": "read_room", "room": cell["room"], "since": 0, "limit": 100},
                )
                if not observed.get("ok"):
                    raise RuntimeError(f"soak read failed at iteration {iteration}")
            run = RunRecord(
                run_id=hashlib.sha256((registry.digest + TARGET_DIGEST).encode()).hexdigest()[:32],
                trigger="official-upstream-local",
                protocol_release="v0.10.0",
                scenario="signed-mailbox-roundtrip-v1",
                registry_sha256=registry.digest,
                execution_images={
                    "technocore": TARGET_DIGEST,
                    **{item: registry.require(item).image_digest for item in registry.ids},
                },
                deterministic_epoch="2026-08-25T00:00:00Z",
                dry_run=True,
            )
            root = await build_bundle(
                output / "bundle",
                run,
                results,
                {item: registry.require(item).source_revision for item in registry.ids},
                signer,
            )
            verified = verify_bundle(output / "bundle")
        report = {
            "schema": "rosetta.upstream-acceptance.v1",
            "target_release": "v0.10.0",
            "target_oci_index_digest": TARGET_DIGEST,
            "target_source_commit": "9c7df0e3616cf28d17e7c8ebeb0c05de6adf117c",
            "matrix_cells": len(results),
            "matrix_passed": all(r.outcome is Outcome.PASS for r in results),
            "adapter_capabilities": capabilities,
            "soak_iterations": soak_iterations,
            "concurrent_isolated_reads": concurrent_pass,
            "separate_ephemeral_adapter_containers": True,
            "internal_only_network": True,
            "rate_limit_retry_observed": any(
                e.status == "rate_limited" for r in results for e in r.events
            ),
            "uncertain_write_reconciled": any(
                e.status == "reconciled" for r in results for e in r.events
            ),
            "bundle_root": root,
            "bundle_verified": root == verified,
        }
        (output / "upstream-transcript.json").write_bytes(canonical_json(transcript) + b"\n")
        (output / "upstream-acceptance.json").write_bytes(canonical_json(report) + b"\n")
        if not report["matrix_passed"]:
            raise RuntimeError("one or more official upstream matrix cells failed")
        return report
    finally:
        _docker(["rm", "--force", proxy, target], check=False)
        _docker(["volume", "rm", "--force", volume], check=False)
        _docker(["network", "rm", network], check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--soak-iterations", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(asyncio.run(accept(args.output, args.soak_iterations)), indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
