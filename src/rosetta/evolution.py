"""Closed, signed and reversible self-evolution proposal pipeline."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, TypeAlias

import yaml
from pydantic import Field, StrictInt, StrictStr, validator

from rosetta.contracts import ClosedModel, SignRequest
from rosetta.operations import OperationalGate
from rosetta.registry import AdapterRegistry
from rosetta.signer_client import Signer
from rosetta_signer.canonical import canonical_json
from rosetta_signer.did import evolution_proposal_payload, public_key_from_did, verify_signature

EvolutionRisk: TypeAlias = Literal["test_only", "documentation", "runtime_code"]
EVOLUTION_APPROVAL_DOMAIN = b"rosetta.evolution-approval.v1\x00"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(data: bytes) -> str:
    return "sha256:" + _sha256(data)


def _require_digest(value: str, label: str) -> str:
    raw = value.removeprefix("sha256:")
    if not value.startswith("sha256:") or len(raw) != 64:
        raise ValueError(f"{label} must be sha256:<64 lowercase hex>")
    if any(char not in "0123456789abcdef" for char in raw):
        raise ValueError(f"{label} must be lowercase hexadecimal")
    return value


class EvolutionMutation(ClosedModel):
    path: StrictStr
    operation: Literal["create", "replace"]
    expected_sha256: StrictStr | None = None
    content_base64: StrictStr

    @validator("expected_sha256")
    def expected_digest_is_valid(cls, value: str | None) -> str | None:
        return None if value is None else _require_digest(value, "expected_sha256")

    def content(self) -> bytes:
        try:
            decoded = base64.b64decode(self.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("mutation content must be canonical base64") from exc
        if base64.b64encode(decoded).decode("ascii") != self.content_base64:
            raise ValueError("mutation content must be canonical base64")
        return decoded


class EvolutionCandidate(ClosedModel):
    schema_: Literal["rosetta.evolution-candidate.v1"] = Field(alias="schema")
    trigger: Literal["protocol_release", "regression", "coverage_gap", "operator"]
    objective: StrictStr
    parent_bundle_root: StrictStr
    parent_registry_sha256: StrictStr
    parent_source_sha256: StrictStr
    proposed_at: datetime
    mutations: list[EvolutionMutation]

    @validator("parent_bundle_root", "parent_registry_sha256", "parent_source_sha256")
    def parent_digest_is_valid(cls, value: str, field: Any) -> str:
        return _require_digest(value, field.name)

    @validator("objective")
    def objective_is_bounded(cls, value: str) -> str:
        if not value.strip() or len(value) > 512:
            raise ValueError("objective must contain 1-512 characters")
        return value.strip()

    @validator("mutations")
    def mutations_are_bounded(cls, value: list[EvolutionMutation]) -> list[EvolutionMutation]:
        if not value:
            raise ValueError("candidate needs at least one mutation")
        paths = [item.path for item in value]
        if len(paths) != len(set(paths)):
            raise ValueError("candidate contains duplicate mutation paths")
        return value

    @validator("proposed_at")
    def proposed_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("proposed_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class EvolutionPolicy(ClosedModel):
    schema_: Literal["rosetta.evolution-policy.v1"] = Field(alias="schema")
    enabled: Literal[True]
    mode: Literal["propose_only"]
    evaluator_image_digest: StrictStr
    allowed_prefixes: list[StrictStr]
    protected_paths: list[StrictStr]
    trusted_operator_dids: list[StrictStr]
    max_files: StrictInt
    max_total_bytes: StrictInt
    evaluator_timeout_seconds: StrictInt
    required_gates: list[Literal["format", "lint", "types", "tests", "typescript", "secrets"]]

    @validator("evaluator_image_digest")
    def evaluator_is_immutable(cls, value: str) -> str:
        return _require_digest(value, "evaluator image")

    @validator("allowed_prefixes", "protected_paths")
    def policy_paths_are_canonical(cls, value: list[str], field: Any) -> list[str]:
        if not value or len(value) != len(set(value)):
            raise ValueError(f"{field.name} must be non-empty and unique")
        for path in value:
            _safe_relative(path)
        return value

    @validator("trusted_operator_dids")
    def trusted_operators_are_valid(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("trusted_operator_dids must be unique")
        for did in value:
            public_key_from_did(did)
        return value

    @validator("max_files", "max_total_bytes", "evaluator_timeout_seconds")
    def policy_limits_are_positive(cls, value: int, field: Any) -> int:
        if value < 1:
            raise ValueError(f"{field.name} must be positive")
        return value

    @validator("required_gates")
    def all_fixed_gates_are_required(cls, value: list[str]) -> list[str]:
        required = {"format", "lint", "types", "tests", "typescript", "secrets"}
        if len(value) != len(set(value)) or set(value) != required:
            raise ValueError("required_gates must contain every fixed gate exactly once")
        return value


class GateResult(ClosedModel):
    name: StrictStr
    passed: bool
    exit_code: StrictInt
    output_sha256: StrictStr
    output_tail: StrictStr

    @validator("output_sha256")
    def output_digest_is_valid(cls, value: str) -> str:
        return _require_digest(value, "gate output digest")


class EvolutionEvaluation(ClosedModel):
    schema_: Literal["rosetta.evolution-evaluation.v1"] = Field(alias="schema")
    candidate_id: StrictStr
    evaluator_image_digest: StrictStr
    policy_sha256: StrictStr
    passed: bool
    gates: list[GateResult]
    risk: Literal["test_only", "documentation", "runtime_code"]
    automatic_promotion: Literal[False] = False
    state: Literal["awaiting_human_approval", "rejected"]

    @validator("evaluator_image_digest", "policy_sha256")
    def evaluation_digest_is_valid(cls, value: str, field: Any) -> str:
        return _require_digest(value, field.name)


class EvolutionApproval(ClosedModel):
    schema_: Literal["rosetta.evolution-approval.v1"] = Field(alias="schema")
    action: Literal["promote_candidate", "rollback_candidate"]
    candidate_id: StrictStr
    evolution_root: StrictStr
    approved_by: StrictStr
    approved_at: datetime
    operator_did: StrictStr
    signature: StrictStr

    @validator("evolution_root")
    def root_is_valid(cls, value: str) -> str:
        return _require_digest(value, "evolution_root")

    @validator("approved_by")
    def approver_is_named(cls, value: str) -> str:
        if not value.strip() or len(value) > 128:
            raise ValueError("approved_by must contain 1-128 characters")
        return value.strip()

    @validator("approved_at")
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class EvolutionAttestation(ClosedModel):
    schema_: Literal["rosetta.evolution-attestation.v1"] = Field(
        "rosetta.evolution-attestation.v1", alias="schema"
    )
    domain: Literal["rosetta.evolution-proposal.v1"] = "rosetta.evolution-proposal.v1"
    did: StrictStr
    evolution_root: StrictStr
    signature: StrictStr


class EvolutionLineage(ClosedModel):
    schema_: Literal["rosetta.evolution-lineage.v1"] = Field(alias="schema")
    candidate_id: StrictStr
    parent_bundle_root: StrictStr
    parent_registry_sha256: StrictStr
    parent_source_sha256: StrictStr
    policy_sha256: StrictStr
    risk: EvolutionRisk
    state: Literal["awaiting_human_approval", "rejected"]
    automatic_promotion: Literal[False]
    human_approval_required: Literal[True]


def load_evolution_policy(path: Path) -> EvolutionPolicy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EvolutionPolicy.parse_obj(raw)


def policy_digest(policy: EvolutionPolicy) -> str:
    return _digest(canonical_json(policy.dict()))


def evolution_approval_payload(approval: EvolutionApproval) -> bytes:
    unsigned = approval.dict(exclude={"signature"})
    return EVOLUTION_APPROVAL_DOMAIN + canonical_json(unsigned)


def verify_evolution_approval(
    approval: EvolutionApproval, policy: EvolutionPolicy, action: str, ident: str, root: str
) -> None:
    if (
        approval.action != action
        or approval.candidate_id != ident
        or approval.evolution_root != root
    ):
        raise ValueError("approval does not authorize this exact evolution action")
    if approval.operator_did not in policy.trusted_operator_dids:
        raise ValueError("approval operator DID is not trusted by evolution policy")
    if not verify_signature(
        approval.operator_did, evolution_approval_payload(approval), approval.signature
    ):
        raise ValueError("invalid evolution operator signature")


def candidate_id(candidate: EvolutionCandidate) -> str:
    return _sha256(canonical_json(candidate.dict()))


def source_tree_digest(project_root: Path) -> str:
    ignored_names = {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".coverage",
        "artifacts",
        "local",
        "node_modules",
        "work",
        "__pycache__",
    }
    entries: list[dict[str, str]] = []
    for path in sorted(project_root.rglob("*")):
        relative = path.relative_to(project_root)
        if any(part in ignored_names for part in relative.parts):
            continue
        if relative.parts[:2] == ("fixtures", "evolution"):
            continue
        if path.is_symlink():
            raise ValueError("symbolic links are forbidden in the evolution source tree")
        if path.is_file():
            entries.append({"path": relative.as_posix(), "sha256": _sha256(path.read_bytes())})
    return _digest(canonical_json(entries))


def _safe_relative(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or "\\" in path
        or candidate.as_posix() != path
    ):
        raise ValueError(f"unsafe mutation path: {path!r}")
    return candidate


def _is_path_or_child(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def validate_candidate(candidate: EvolutionCandidate, policy: EvolutionPolicy) -> EvolutionRisk:
    if len(candidate.mutations) > policy.max_files:
        raise ValueError("candidate exceeds mutation file limit")
    total = 0
    risk: EvolutionRisk = "test_only"
    for mutation in candidate.mutations:
        path = _safe_relative(mutation.path).as_posix()
        if not any(_is_path_or_child(path, prefix) for prefix in policy.allowed_prefixes):
            raise ValueError(f"mutation path is outside the evolution allowlist: {path}")
        if any(_is_path_or_child(path, protected) for protected in policy.protected_paths):
            raise ValueError(f"mutation path is protected from self-modification: {path}")
        content = mutation.content()
        if b"\0" in content:
            raise ValueError("binary mutation content is forbidden")
        total += len(content)
        if path.startswith("docs/") and risk == "test_only":
            risk = "documentation"
        elif not path.startswith(("tests/generated/", "fixtures/evolution/", "docs/")):
            risk = "runtime_code"
        if mutation.operation == "create" and mutation.expected_sha256 is not None:
            raise ValueError("create mutation cannot carry expected_sha256")
        if mutation.operation == "replace" and mutation.expected_sha256 is None:
            raise ValueError("replace mutation requires expected_sha256")
    if total > policy.max_total_bytes:
        raise ValueError("candidate exceeds total byte limit")
    return risk


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".coverage",
        "artifacts",
        "local",
        "node_modules",
        "work",
        "__pycache__",
    }
    return set(names) & ignored


def _under(root: Path, target: Path) -> Path:
    resolved_root = root.resolve()
    resolved = target.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("path escapes approved evolution root")
    return resolved


class DockerEvolutionEvaluator:
    """Execute candidate code only in a networkless, resource-bounded container."""

    def __init__(self, image_digest: str, timeout_seconds: int) -> None:
        self.image_digest = _require_digest(image_digest, "evaluator image")
        self.timeout_seconds = timeout_seconds

    def evaluate(self, candidate_root: Path) -> list[GateResult]:
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("Docker CLI is unavailable")
        mount = f"type=bind,src={candidate_root.resolve()},dst=/candidate,readonly"
        completed = subprocess.run(  # noqa: S603 - command and image are policy-controlled
            [
                docker,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--user=65532:65532",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=768m",
                "--cpus=1.0",
                "--pids-limit=128",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=128m,uid=65532,gid=65532",
                "--tmpfs=/candidate/local:rw,noexec,nosuid,size=128m,uid=65532,gid=65532",
                "--mount",
                mount,
                self.image_digest,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
        )
        lines = completed.stdout.strip().splitlines()
        if completed.returncode not in {0, 1} or not lines:
            detail = (completed.stdout + completed.stderr)[-1024:]
            raise RuntimeError(f"evaluator infrastructure failure: {detail}")
        payload = json.loads(lines[-1])
        if payload.get("schema") != "rosetta.evolution-gates.v1":
            raise RuntimeError("evaluator returned an unknown result schema")
        gates = [GateResult.parse_obj(item) for item in payload["gates"]]
        if (completed.returncode == 0) != all(item.passed for item in gates):
            raise RuntimeError("evaluator exit status disagrees with gate results")
        return gates


class EvolutionEvaluator(Protocol):
    def evaluate(self, candidate_root: Path) -> list[GateResult]: ...


class EvolutionEngine:
    def __init__(
        self,
        project_root: Path,
        registry: AdapterRegistry,
        policy: EvolutionPolicy,
        gate: OperationalGate,
        evaluator: EvolutionEvaluator,
    ) -> None:
        self.project_root = project_root.resolve()
        self.registry = registry
        self.policy = policy
        self.gate = gate
        self.evaluator = evaluator

    def stage(
        self, candidate: EvolutionCandidate, workspace: Path
    ) -> tuple[str, Path, EvolutionRisk]:
        self.gate.require("evolution")
        if candidate.parent_registry_sha256 != self.registry.digest:
            raise ValueError("candidate parent registry does not match current registry")
        if candidate.parent_source_sha256 != source_tree_digest(self.project_root):
            raise ValueError("candidate parent source tree does not match current project")
        risk = validate_candidate(candidate, self.policy)
        ident = candidate_id(candidate)
        workspace_root = _under(self.project_root, workspace)
        relative_workspace = workspace_root.relative_to(self.project_root)
        if not relative_workspace.parts or relative_workspace.parts[0] != "local":
            raise ValueError("candidate workspace must be under the ignored local directory")
        root = _under(self.project_root, workspace_root / ident)
        if root.exists():
            raise ValueError("candidate workspace already exists")
        candidate_root = root / "candidate"
        candidate_root.parent.mkdir(parents=True, exist_ok=False)
        shutil.copytree(self.project_root, candidate_root, symlinks=True, ignore=_copy_ignore)
        if any(path.is_symlink() for path in candidate_root.rglob("*")):
            raise ValueError("symbolic links are forbidden in evolution candidate sources")
        # The evaluator overlays this empty mount point with a bounded tmpfs while
        # the surrounding candidate bind remains read-only.
        (candidate_root / "local").mkdir()
        for mutation in candidate.mutations:
            relative = _safe_relative(mutation.path)
            destination = _under(candidate_root, candidate_root.joinpath(*relative.parts))
            if destination.is_symlink():
                raise ValueError("mutation target cannot be a symlink")
            content = mutation.content()
            if mutation.operation == "create":
                if destination.exists():
                    raise ValueError(f"create target already exists: {mutation.path}")
            else:
                if not destination.is_file():
                    raise ValueError(f"replace target is not a file: {mutation.path}")
                current = _digest(destination.read_bytes())
                if current != mutation.expected_sha256:
                    raise ValueError(f"stale replace base: {mutation.path}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return ident, candidate_root, risk

    async def evaluate_and_package(
        self,
        candidate: EvolutionCandidate,
        workspace: Path,
        output: Path,
        signer: Signer,
    ) -> tuple[str, EvolutionEvaluation]:
        ident, candidate_root, risk = self.stage(candidate, workspace)
        gates = self.evaluator.evaluate(candidate_root)
        by_name = {item.name: item for item in gates}
        if len(by_name) != len(gates):
            raise RuntimeError("evaluator returned duplicate gate names")
        missing = [name for name in self.policy.required_gates if name not in by_name]
        if missing:
            raise RuntimeError("evaluator omitted required gates: " + ", ".join(sorted(missing)))
        unexpected = set(by_name) - set(self.policy.required_gates)
        if unexpected:
            raise RuntimeError(
                "evaluator returned unexpected gates: " + ", ".join(sorted(unexpected))
            )
        passed = all(by_name[name].passed for name in self.policy.required_gates)
        evaluation = EvolutionEvaluation(
            schema_="rosetta.evolution-evaluation.v1",
            candidate_id=ident,
            evaluator_image_digest=self.policy.evaluator_image_digest,
            policy_sha256=policy_digest(self.policy),
            passed=passed,
            gates=gates,
            risk=risk,
            state="awaiting_human_approval" if passed else "rejected",
        )
        output = _under(self.project_root, output)
        if output.exists() and any(output.iterdir()):
            raise ValueError("evolution package destination must be empty")
        output.mkdir(parents=True, exist_ok=True)
        (output / "candidate.json").write_bytes(canonical_json(candidate.dict()) + b"\n")
        (output / "evaluation.json").write_bytes(canonical_json(evaluation.dict()) + b"\n")
        lineage = EvolutionLineage(
            schema_="rosetta.evolution-lineage.v1",
            candidate_id=ident,
            parent_bundle_root=candidate.parent_bundle_root,
            parent_registry_sha256=candidate.parent_registry_sha256,
            parent_source_sha256=candidate.parent_source_sha256,
            policy_sha256=policy_digest(self.policy),
            risk=risk,
            state=evaluation.state,
            automatic_promotion=False,
            human_approval_required=True,
        )
        (output / "lineage.json").write_bytes(canonical_json(lineage.dict()) + b"\n")
        for mutation in candidate.mutations:
            relative = _safe_relative(mutation.path)
            change = output / "changes" / Path(*relative.parts)
            change.parent.mkdir(parents=True, exist_ok=True)
            change.write_bytes(mutation.content())
        entries = _package_entries(output)
        (output / "checksums.txt").write_text(
            "".join(f"{digest}  {path}\n" for path, digest in entries), encoding="utf-8"
        )
        root = _package_root(entries)
        signed = await signer.sign(
            SignRequest(action="evolution_proposal", scope=ident, digest=root)
        )
        attestation = EvolutionAttestation(
            did=signed.did, evolution_root=root, signature=signed.signature
        )
        (output / "attestation.json").write_bytes(canonical_json(attestation.dict()) + b"\n")
        return root, evaluation

    def promote(
        self,
        package: Path,
        approval_file: Path,
        rollback_root: Path,
    ) -> Path:
        self.gate.require("evolution")
        root = verify_evolution_package(package)
        approval = EvolutionApproval.parse_raw(approval_file.read_bytes())
        candidate = EvolutionCandidate.parse_raw((package / "candidate.json").read_bytes())
        ident = candidate_id(candidate)
        verify_evolution_approval(approval, self.policy, "promote_candidate", ident, root)
        evaluation = EvolutionEvaluation.parse_raw((package / "evaluation.json").read_bytes())
        if not evaluation.passed or evaluation.state != "awaiting_human_approval":
            raise ValueError("only a passing candidate can be promoted")
        if evaluation.evaluator_image_digest != self.policy.evaluator_image_digest:
            raise ValueError("candidate was not evaluated by the currently pinned evaluator")
        if evaluation.policy_sha256 != policy_digest(self.policy):
            raise ValueError("candidate was not evaluated under the current evolution policy")
        if candidate.parent_registry_sha256 != self.registry.digest:
            raise ValueError("candidate parent registry is no longer current")
        if candidate.parent_source_sha256 != source_tree_digest(self.project_root):
            raise ValueError("candidate parent source tree is no longer current")
        validate_candidate(candidate, self.policy)
        rollback = _under(self.project_root, rollback_root / ident)
        if rollback.exists():
            raise ValueError("rollback record already exists")
        prepared: list[tuple[EvolutionMutation, Path, bytes, bytes | None]] = []
        for mutation in candidate.mutations:
            relative = _safe_relative(mutation.path)
            destination = _under(self.project_root, self.project_root.joinpath(*relative.parts))
            promoted = (package / "changes" / Path(*relative.parts)).read_bytes()
            if mutation.operation == "create":
                if destination.exists():
                    raise ValueError(f"promotion create target exists: {mutation.path}")
                previous = None
            else:
                if not destination.is_file():
                    raise ValueError(f"promotion base is not a file: {mutation.path}")
                previous = destination.read_bytes()
                if _digest(previous) != mutation.expected_sha256:
                    raise ValueError(f"promotion base changed after evaluation: {mutation.path}")
            prepared.append((mutation, destination, promoted, previous))

        rollback.mkdir(parents=True)
        record: dict[str, Any] = {
            "schema": "rosetta.evolution-promotion.v1",
            "state": "prepared",
            "candidate_id": ident,
            "evolution_root": root,
            "approved_by": approval.approved_by,
            "approved_at": approval.approved_at,
            "files": [],
        }
        for mutation, _destination, promoted, previous in prepared:
            relative = _safe_relative(mutation.path)
            item: dict[str, Any] = {
                "path": mutation.path,
                "operation": mutation.operation,
                "promoted_sha256": _digest(promoted),
            }
            if mutation.operation == "create":
                item["previous_sha256"] = None
            else:
                assert previous is not None
                backup = rollback / "files" / Path(*relative.parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(previous)
                item["previous_sha256"] = _digest(previous)
            record["files"].append(item)
        record_path = rollback / "promotion.json"
        record_path.write_bytes(canonical_json(record) + b"\n")
        for _mutation, destination, promoted, _previous in prepared:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(promoted)
        record["state"] = "applied"
        record_path.write_bytes(canonical_json(record) + b"\n")
        return record_path

    def rollback(self, record_path: Path, approval_file: Path) -> None:
        self.gate.require("evolution")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        approval = EvolutionApproval.parse_raw(approval_file.read_bytes())
        verify_evolution_approval(
            approval,
            self.policy,
            "rollback_candidate",
            str(record.get("candidate_id")),
            str(record.get("evolution_root")),
        )
        rollback = record_path.parent
        for item in record["files"]:
            relative = _safe_relative(item["path"])
            destination = _under(self.project_root, self.project_root.joinpath(*relative.parts))
            if item["operation"] == "create":
                if destination.exists():
                    if (
                        not destination.is_file()
                        or _digest(destination.read_bytes()) != item["promoted_sha256"]
                    ):
                        raise ValueError(f"promoted file drifted before rollback: {item['path']}")
                    destination.unlink()
            else:
                backup = rollback / "files" / Path(*relative.parts)
                previous = backup.read_bytes()
                if not destination.is_file():
                    raise ValueError(f"promoted file drifted before rollback: {item['path']}")
                current = _digest(destination.read_bytes())
                if current == item["promoted_sha256"]:
                    destination.write_bytes(previous)
                elif current != item["previous_sha256"]:
                    raise ValueError(f"promoted file drifted before rollback: {item['path']}")
        record["state"] = "rolled_back"
        record_path.write_bytes(canonical_json(record) + b"\n")


def _package_entries(package: Path) -> list[tuple[str, str]]:
    entries = []
    for path in sorted(package.rglob("*")):
        if path.is_symlink():
            raise ValueError("symbolic links are forbidden in evolution packages")
        if path.is_file() and path.name not in {"checksums.txt", "attestation.json"}:
            entries.append((path.relative_to(package).as_posix(), _sha256(path.read_bytes())))
    return entries


def _package_root(entries: list[tuple[str, str]]) -> str:
    manifest = [{"path": path, "sha256": digest} for path, digest in sorted(entries)]
    return _digest(canonical_json(manifest))


def verify_evolution_package(package: Path) -> str:
    expected: list[tuple[str, str]] = []
    for line in (package / "checksums.txt").read_text(encoding="utf-8").splitlines():
        try:
            digest, raw_relative = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError("invalid evolution checksum line") from exc
        relative = _safe_relative(raw_relative).as_posix()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid evolution checksum digest")
        path = _under(package, package / Path(*PurePosixPath(relative).parts))
        if path.is_symlink() or not path.is_file() or _sha256(path.read_bytes()) != digest:
            raise ValueError(f"evolution checksum mismatch: {relative}")
        expected.append((relative, digest))
    if len(expected) != len(set(expected)):
        raise ValueError("duplicate evolution checksum entry")
    actual = _package_entries(package)
    if actual != sorted(expected):
        raise ValueError("evolution package file set differs from checksums")
    root = _package_root(actual)
    attestation = EvolutionAttestation.parse_raw((package / "attestation.json").read_bytes())
    if attestation.evolution_root != root:
        raise ValueError("evolution root mismatch")
    if not verify_signature(
        attestation.did, evolution_proposal_payload(root), attestation.signature
    ):
        raise ValueError("invalid evolution proposal attestation")
    candidate = EvolutionCandidate.parse_raw((package / "candidate.json").read_bytes())
    evaluation = EvolutionEvaluation.parse_raw((package / "evaluation.json").read_bytes())
    lineage = EvolutionLineage.parse_raw((package / "lineage.json").read_bytes())
    ident = candidate_id(candidate)
    expected_state = "awaiting_human_approval" if evaluation.passed else "rejected"
    if evaluation.candidate_id != ident:
        raise ValueError("candidate identity mismatch")
    if evaluation.state != expected_state:
        raise ValueError("evaluation result and state disagree")
    if (
        lineage.candidate_id != ident
        or lineage.parent_bundle_root != candidate.parent_bundle_root
        or lineage.parent_registry_sha256 != candidate.parent_registry_sha256
        or lineage.parent_source_sha256 != candidate.parent_source_sha256
        or lineage.policy_sha256 != evaluation.policy_sha256
        or lineage.risk != evaluation.risk
        or lineage.state != evaluation.state
    ):
        raise ValueError("evolution lineage mismatch")
    expected_changes = sorted(mutation.path for mutation in candidate.mutations)
    actual_changes = sorted(
        path.relative_to(package / "changes").as_posix()
        for path in (package / "changes").rglob("*")
        if path.is_file()
    )
    if actual_changes != expected_changes:
        raise ValueError("evolution package changes do not match candidate")
    for mutation in candidate.mutations:
        change = package / "changes" / Path(*_safe_relative(mutation.path).parts)
        if change.read_bytes() != mutation.content():
            raise ValueError(f"evolution change content mismatch: {mutation.path}")
    return root
