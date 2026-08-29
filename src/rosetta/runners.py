"""OCI execution policy. Local fixtures use the same reviewed identities."""

from __future__ import annotations

from dataclasses import dataclass

from rosetta.contracts import AdapterManifest
from rosetta.operations import OperationalGate
from rosetta.registry import AdapterRegistry


@dataclass(frozen=True)
class RunnerPolicy:
    read_only_root: bool = True
    run_as_user: str = "65532:65532"
    memory_mb: int = 256
    cpu_quota: float = 0.5
    pids_limit: int = 64
    timeout_seconds: int = 120
    network: str = "rosetta-target-only"

    def docker_arguments(self, manifest: AdapterManifest) -> list[str]:
        return [
            "run",
            "--rm",
            "--read-only",
            "--user",
            self.run_as_user,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={self.memory_mb}m",
            f"--cpus={self.cpu_quota}",
            f"--pids-limit={self.pids_limit}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            f"--network={self.network}",
            manifest.image_digest,
        ]

    def validate(self, args: list[str]) -> None:
        joined = " ".join(args)
        required = ["--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges"]
        if any(item not in joined for item in required):
            raise ValueError("runner isolation flag missing")
        forbidden = ["--privileged", "/var/run/docker.sock", "--network=host", "-v ", "--mount"]
        if any(item in joined for item in forbidden):
            raise ValueError("forbidden runner authority")


class RunnerSupervisor:
    def __init__(
        self,
        registry: AdapterRegistry,
        policy: RunnerPolicy | None = None,
        gate: OperationalGate | None = None,
        *,
        allow_ungated_fixture: bool = False,
    ) -> None:
        if gate is None and not allow_ungated_fixture:
            raise ValueError("operational gate required outside explicit fixture validation")
        self.registry = registry
        self.policy = policy or RunnerPolicy()
        self.gate = gate

    def compile(self, adapter_id: str) -> dict[str, object]:
        if self.gate is not None:
            self.gate.require("runner")
        manifest = self.registry.require(adapter_id)
        args = self.policy.docker_arguments(manifest)
        self.policy.validate(args)
        return {
            "adapter_id": adapter_id,
            "image": manifest.image_digest,
            "command": args,
            "host_mounts": [],
            "secrets": [],
            "network": self.policy.network,
            "ephemeral": True,
        }
