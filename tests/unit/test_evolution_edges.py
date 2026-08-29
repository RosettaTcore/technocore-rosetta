from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from rosetta import evolution
from rosetta.contracts import SignRequest, SignResponse
from rosetta.evolution import (
    DockerEvolutionEvaluator,
    EvolutionCandidate,
    EvolutionEngine,
    EvolutionMutation,
    EvolutionPolicy,
    GateResult,
    source_tree_digest,
    validate_candidate,
    verify_evolution_package,
)
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.registry import AdapterRegistry
from rosetta_signer.did import SyntheticIdentity
from rosetta_signer.nonce_store import NonceStore
from rosetta_signer.protocol import SignerProtocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
GATE_NAMES = ("format", "lint", "types", "tests", "typescript", "secrets")


class ProtocolSigner:
    def __init__(self, path: Path) -> None:
        self.store = NonceStore(path)
        self.protocol = SignerProtocol(SyntheticIdentity("synthetic-edge-signer"), self.store)

    async def sign(self, request: SignRequest) -> SignResponse:
        return self.protocol.handle(request)

    def close(self) -> None:
        self.store.close()


class ResultEvaluator:
    def __init__(self, gates: list[GateResult]) -> None:
        self.gates = gates

    def evaluate(self, candidate_root: Path) -> list[GateResult]:
        assert (candidate_root / "local").is_dir()
        return self.gates


def _gate(name: str, passed: bool = True) -> GateResult:
    return GateResult(
        name=name,
        passed=passed,
        exit_code=0 if passed else 1,
        output_sha256=DIGEST,
        output_tail="passed" if passed else "failed",
    )


def _policy() -> EvolutionPolicy:
    raw = yaml.safe_load((PROJECT_ROOT / "config/evolution.policy.yaml").read_text())
    return EvolutionPolicy.parse_obj(raw)


def _candidate(project: Path, registry: AdapterRegistry) -> EvolutionCandidate:
    return EvolutionCandidate(
        schema="rosetta.evolution-candidate.v1",
        trigger="coverage_gap",
        objective="Exercise a security edge",
        parent_bundle_root=DIGEST,
        parent_registry_sha256=registry.digest,
        parent_source_sha256=source_tree_digest(project),
        proposed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        mutations=[
            EvolutionMutation(
                path="docs/generated-edge.md",
                operation="create",
                content_base64=base64.b64encode(b"edge\n").decode(),
            )
        ],
    )


def _engine(
    project: Path, evaluator: ResultEvaluator
) -> tuple[EvolutionEngine, StateStore, AdapterRegistry]:
    project.mkdir(parents=True)
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    store = StateStore(project / "local/state.sqlite3")
    gate = OperationalGate(store, project / "local/KILL_SWITCH")
    return EvolutionEngine(project, registry, _policy(), gate, evaluator), store, registry


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("evaluator_image_digest", "latest", "sha256"),
        ("allowed_prefixes", [], "non-empty"),
        ("protected_paths", ["docs", "docs"], "unique"),
        ("trusted_operator_dids", ["did:key:invalid"], "unsupported DID"),
        ("max_files", 0, "positive"),
        ("required_gates", ["format"], "fixed gate"),
    ],
)
def test_evolution_policy_rejects_weak_authority(field: str, value: object, match: str) -> None:
    raw = yaml.safe_load((PROJECT_ROOT / "config/evolution.policy.yaml").read_text())
    raw[field] = value
    with pytest.raises((ValidationError, ValueError), match=match):
        EvolutionPolicy.parse_obj(raw)


def test_evolution_contract_time_digest_and_payload_edges() -> None:
    raw = json.loads(
        (PROJECT_ROOT / "fixtures/evolution/candidate-add-domain-vector.json").read_text()
    )
    raw["objective"] = " "
    with pytest.raises(ValidationError, match="objective"):
        EvolutionCandidate.parse_obj(raw)
    raw["objective"] = "valid"
    raw["proposed_at"] = "2026-08-26T00:00:00"
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvolutionCandidate.parse_obj(raw)
    raw["proposed_at"] = "2026-08-26T00:00:00Z"
    raw["parent_bundle_root"] = "sha256:" + "G" * 64
    with pytest.raises(ValidationError, match="hexadecimal"):
        EvolutionCandidate.parse_obj(raw)
    with pytest.raises(ValidationError, match="sha256"):
        GateResult(name="x", passed=True, exit_code=0, output_sha256="bad", output_tail="")

    mutation = EvolutionMutation(path="docs/x", operation="create", content_base64="YQ")
    with pytest.raises(ValueError, match="canonical base64"):
        mutation.content()


def test_source_tree_and_path_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.txt").write_text("source", encoding="utf-8")
    first = source_tree_digest(root)
    (root / "local").mkdir()
    (root / "local/ignored.txt").write_text("runtime", encoding="utf-8")
    assert source_tree_digest(root) == first
    (root / "link").symlink_to(root / "source.txt")
    with pytest.raises(ValueError, match="symbolic"):
        source_tree_digest(root)
    with pytest.raises(ValueError, match="escapes"):
        evolution._under(root, tmp_path / "outside")


def test_candidate_limits_and_risk_classification(tmp_path: Path) -> None:
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    project = tmp_path / "project"
    project.mkdir()
    candidate = _candidate(project, registry)
    policy = _policy()
    assert validate_candidate(candidate, policy) == "documentation"
    candidate.mutations[0].path = "src/rosetta/generated.py"
    assert validate_candidate(candidate, policy) == "runtime_code"
    candidate.mutations[0].expected_sha256 = DIGEST
    with pytest.raises(ValueError, match="create mutation"):
        validate_candidate(candidate, policy)
    candidate.mutations = [
        EvolutionMutation(
            path=f"docs/{index}.md",
            operation="create",
            content_base64=base64.b64encode(b"x").decode(),
        )
        for index in range(policy.max_files + 1)
    ]
    with pytest.raises(ValueError, match="file limit"):
        validate_candidate(candidate, policy)


def test_docker_evaluator_contract_and_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluator = DockerEvolutionEvaluator(DIGEST, 10)
    monkeypatch.setattr(evolution.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="unavailable"):
        evaluator.evaluate(tmp_path)

    monkeypatch.setattr(evolution.shutil, "which", lambda name: "/usr/bin/docker")

    def completed(returncode: int, payload: object = None, stderr: str = "") -> SimpleNamespace:
        stdout = "" if payload is None else json.dumps(payload) + "\n"
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(
        evolution.subprocess,
        "run",
        lambda *args, **kwargs: completed(2, stderr="daemon failure"),
    )
    with pytest.raises(RuntimeError, match="infrastructure"):
        evaluator.evaluate(tmp_path)

    monkeypatch.setattr(
        evolution.subprocess,
        "run",
        lambda *args, **kwargs: completed(0, {"schema": "unknown", "gates": []}),
    )
    with pytest.raises(RuntimeError, match="unknown result schema"):
        evaluator.evaluate(tmp_path)

    failed_gate = _gate("tests", False).dict()
    payload = {"schema": "rosetta.evolution-gates.v1", "gates": [failed_gate]}
    monkeypatch.setattr(evolution.subprocess, "run", lambda *args, **kwargs: completed(0, payload))
    with pytest.raises(RuntimeError, match="disagrees"):
        evaluator.evaluate(tmp_path)

    passed_gate = _gate("tests").dict()
    payload = {"schema": "rosetta.evolution-gates.v1", "gates": [passed_gate]}
    monkeypatch.setattr(evolution.subprocess, "run", lambda *args, **kwargs: completed(0, payload))
    assert evaluator.evaluate(tmp_path)[0].name == "tests"


@pytest.mark.parametrize("variant", ["duplicate", "missing", "unexpected"])
def test_engine_rejects_evaluator_gate_set_drift(tmp_path: Path, variant: str) -> None:
    gates = [_gate(name) for name in GATE_NAMES]
    if variant == "duplicate":
        gates.append(_gate("tests"))
    elif variant == "missing":
        gates = gates[1:]
    else:
        gates.append(_gate("future-gate"))
    engine, store, registry = _engine(tmp_path / variant, ResultEvaluator(gates))
    candidate = _candidate(engine.project_root, registry)
    with pytest.raises(RuntimeError, match="duplicate|omitted|unexpected"):
        asyncio.run(
            engine.evaluate_and_package(
                candidate,
                engine.project_root / "local/workspaces",
                engine.project_root / "artifacts/proposal",
                ProtocolSigner(tmp_path / f"{variant}.sqlite3"),
            )
        )
    store.close()


def test_rejected_candidate_is_signed_and_verifiable(tmp_path: Path) -> None:
    gates = [_gate(name, passed=name != "tests") for name in GATE_NAMES]
    engine, store, registry = _engine(tmp_path / "rejected", ResultEvaluator(gates))
    candidate = _candidate(engine.project_root, registry)
    signer = ProtocolSigner(tmp_path / "signer.sqlite3")
    output = engine.project_root / "artifacts/proposal"
    root, evaluation = asyncio.run(
        engine.evaluate_and_package(
            candidate, engine.project_root / "local/workspaces", output, signer
        )
    )
    assert evaluation.state == "rejected"
    assert not evaluation.passed
    assert verify_evolution_package(output) == root
    signer.close()
    store.close()
