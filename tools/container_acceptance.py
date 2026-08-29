"""Reproducible live OCI isolation and Unix-socket signer acceptance checks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def run(
    docker: str, arguments: list[str], *, timeout: int = 30, input_text: str | None = None
) -> str:
    completed = subprocess.run(  # noqa: S603 - Docker arguments are assembled from closed values
        [docker, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )
    return completed.stdout.strip()


def hardened_arguments() -> list[str]:
    return [
        "--network=none",
        "--read-only",
        "--user=65532:65532",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=256m",
        "--cpus=0.5",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=16m,uid=65532,gid=65532",
    ]


def accept(image: str, node_image: str, output: Path) -> dict[str, Any]:
    if not image.startswith("sha256:") or len(image) != 71:
        raise ValueError("image must be an immutable sha256 image ID")
    if not node_image.startswith("sha256:") or len(node_image) != 71:
        raise ValueError("node image must be an immutable sha256 image ID")
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI is unavailable")
    suffix = str(os.getpid())
    policy_container = f"rosetta-policy-{suffix}"
    hostile_container = f"rosetta-hostile-{suffix}"
    signer_container = f"rosetta-signer-{suffix}"
    socket_volume = f"rosetta-signer-socket-{suffix}"
    state_volume = f"rosetta-signer-state-{suffix}"
    report: dict[str, Any] = {
        "schema": "rosetta.container-acceptance.v1",
        "image_id": image,
        "node_image_id": node_image,
        "checks": {},
    }
    checks = report["checks"]
    assert isinstance(checks, dict)
    try:
        run(
            docker,
            [
                "create",
                "--name",
                policy_container,
                *hardened_arguments(),
                image,
                "rosetta.cli",
                "--help",
            ],
        )
        inspected = json.loads(run(docker, ["inspect", policy_container]))[0]
        host = inspected["HostConfig"]
        config = inspected["Config"]
        checks.update(
            {
                "non_root_user": config["User"] == "65532:65532",
                "read_only_root": host["ReadonlyRootfs"] is True,
                "network_none": host["NetworkMode"] == "none",
                "capabilities_dropped": host["CapDrop"] == ["ALL"],
                "no_new_privileges": "no-new-privileges" in host["SecurityOpt"],
                "memory_limit_256m": host["Memory"] == 256 * 1024 * 1024,
                "cpu_limit_half_core": host["NanoCpus"] == 500_000_000,
                "pids_limit_64": host["PidsLimit"] == 64,
                "bounded_tmpfs": host["Tmpfs"].get("/tmp")  # noqa: S108 - container tmpfs
                == "rw,noexec,nosuid,size=16m,uid=65532,gid=65532",
                "no_host_binds": not host["Binds"] and not inspected["Mounts"],
                "ephemeral_auto_remove": host["AutoRemove"] is False,
            }
        )

        adapter_probes = [
            (
                "adapter_python_http",
                image,
                "python",
                ["/opt/rosetta/adapters/python_http/main.py"],
                "python-http",
            ),
            (
                "adapter_raw_fetch_fixture",
                node_image,
                "node",
                ["/opt/adapters/raw_fetch/index.mjs"],
                "raw-fetch",
            ),
            (
                "adapter_official_mcp",
                image,
                "python",
                ["/opt/rosetta/adapters/official_mcp/main.py"],
                "official-mcp",
            ),
            (
                "adapter_typescript_http",
                node_image,
                "node",
                ["/opt/adapters/typescript_http/index.mjs"],
                "typescript-http",
            ),
        ]
        for check_name, adapter_image, entrypoint, arguments, expected_id in adapter_probes:
            capability = json.loads(
                run(
                    docker,
                    [
                        "run",
                        "--rm",
                        "-i",
                        *hardened_arguments(),
                        f"--entrypoint={entrypoint}",
                        adapter_image,
                        *arguments,
                    ],
                    input_text='{"operation":"capabilities"}',
                )
            )
            checks[check_name] = capability.get("id") == expected_id
        run(docker, ["rm", policy_container])

        probe = (
            "import json,os,pathlib,socket;"
            "blocked=False;"
            "\ntry:pathlib.Path('/blocked').write_text('x')"
            "\nexcept OSError:blocked=True"
            "\ncap=next(x.split(':',1)[1].strip() for x in "
            "pathlib.Path('/proc/self/status').read_text().splitlines() "
            "if x.startswith('CapEff:'));"
            "\ns=socket.socket();s.settimeout(0.2);net=False"
            "\ntry:s.connect(('169.254.169.254',80));net=True"
            "\nexcept OSError:pass"
            "\nprint(json.dumps({'uid':os.getuid(),'root_write_blocked':blocked,'cap_eff':cap,"
            "'metadata_connected':net,'docker_socket':pathlib.Path('/var/run/docker.sock').exists(),"
            "'host_users':pathlib.Path('/Users').exists(),"
            "'evidence':pathlib.Path('/var/lib/rosetta/evidence').exists()}))"
        )
        runtime = json.loads(
            run(
                docker,
                [
                    "run",
                    "--rm",
                    *hardened_arguments(),
                    "--entrypoint=python",
                    image,
                    "-c",
                    probe,
                ],
            )
        )
        checks.update(
            {
                "runtime_uid_non_root": runtime["uid"] == 65532,
                "runtime_root_write_denied": runtime["root_write_blocked"] is True,
                "runtime_zero_effective_capabilities": runtime["cap_eff"] == "0000000000000000",
                "cloud_metadata_unreachable": runtime["metadata_connected"] is False,
                "container_socket_unreachable": runtime["docker_socket"] is False,
                "host_paths_unreachable": runtime["host_users"] is False,
                "persisted_evidence_unreachable": runtime["evidence"] is False,
            }
        )

        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 - fixed hostile CPU fixture
            [
                docker,
                "run",
                "--name",
                hostile_container,
                *hardened_arguments(),
                "--entrypoint=python",
                image,
                "-c",
                "while True: pass",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            process.wait(timeout=1)
            checks["hostile_timeout_terminated"] = False
        except subprocess.TimeoutExpired:
            run(docker, ["kill", hostile_container])
            process.wait(timeout=5)
            checks["hostile_timeout_terminated"] = time.monotonic() - started < 7
        run(docker, ["rm", hostile_container])

        run(docker, ["volume", "create", socket_volume])
        run(docker, ["volume", "create", state_volume])
        for volume, mount in [
            (socket_volume, "/run/rosetta-signer"),
            (state_volume, "/var/lib/rosetta-signer"),
        ]:
            run(
                docker,
                [
                    "run",
                    "--rm",
                    "--network=none",
                    "--user=0:0",
                    "--cap-drop=ALL",
                    "--cap-add=CHOWN",
                    f"--volume={volume}:{mount}",
                    "--entrypoint=/bin/chown",
                    image,
                    "65532:65532",
                    mount,
                ],
            )
        run(
            docker,
            [
                "run",
                "--detach",
                "--name",
                signer_container,
                "--network=none",
                "--read-only",
                "--user=65532:65532",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=128m",
                "--cpus=0.25",
                "--pids-limit=32",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=8m,uid=65532,gid=65532",
                f"--volume={socket_volume}:/run/rosetta-signer",
                f"--volume={state_volume}:/var/lib/rosetta-signer",
                image,
                "rosetta_signer.service",
                "--socket",
                "/run/rosetta-signer/signer.sock",
                "--state",
                "/var/lib/rosetta-signer/nonce.sqlite3",
                "--synthetic-key-id",
                "synthetic-container-acceptance",
            ],
        )
        signer_inspect = json.loads(run(docker, ["inspect", signer_container]))[0]
        checks["signer_network_none"] = signer_inspect["HostConfig"]["NetworkMode"] == "none"
        checks["signer_read_only_non_root"] = (
            signer_inspect["HostConfig"]["ReadonlyRootfs"] is True
            and signer_inspect["Config"]["User"] == "65532:65532"
        )
        client_probe = (
            "import asyncio,json;from rosetta.contracts import SignRequest;"
            "from rosetta.signer_client import SignerClient;"
            "\nasync def f():"
            "\n c=SignerClient('/run/rosetta-signer/signer.sock')"
            "\n for _ in range(50):"
            "\n  try:"
            "\n   r=await c.sign(SignRequest(action='artifact_root',scope='container',"
            "digest='sha256:'+'0'*64));print(json.dumps({'did':r.did,'signature_len':len(r.signature)}));return"
            "\n  except (FileNotFoundError,ConnectionRefusedError):await asyncio.sleep(.05)"
            "\n raise RuntimeError('signer socket unavailable')"
            "\nasyncio.run(f())"
        )
        signer_result = json.loads(
            run(
                docker,
                [
                    "run",
                    "--rm",
                    "--network=none",
                    "--read-only",
                    "--user=65532:65532",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--tmpfs=/tmp:rw,noexec,nosuid,size=8m,uid=65532,gid=65532",
                    f"--volume={socket_volume}:/run/rosetta-signer",
                    "--entrypoint=python",
                    image,
                    "-c",
                    client_probe,
                ],
            )
        )
        checks["unix_socket_signing_verified"] = (
            signer_result["did"].startswith("did:key:z6Mk") and signer_result["signature_len"] == 86
        )
        checks["runner_peer_network_isolation"] = checks["network_none"] is True
    finally:
        subprocess.run(  # noqa: S603 - cleanup is limited to generated names
            [docker, "rm", "--force", policy_container, hostile_container, signer_container],
            capture_output=True,
            text=True,
        )
        subprocess.run(  # noqa: S603 - cleanup is limited to generated names
            [docker, "volume", "rm", "--force", socket_volume, state_volume],
            capture_output=True,
            text=True,
        )
    report["passed"] = all(value is True for value in checks.values())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["passed"]:
        failed = sorted(name for name, passed in checks.items() if passed is not True)
        raise RuntimeError("container acceptance failed: " + ", ".join(failed))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--node-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = accept(args.image, args.node_image, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
