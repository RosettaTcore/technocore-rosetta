from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rosetta.contracts import SignRequest, SignResponse
from rosetta.evolution import (
    EvolutionApproval,
    EvolutionCandidate,
    EvolutionEngine,
    EvolutionMutation,
    EvolutionPolicy,
    GateResult,
    candidate_id,
    evolution_approval_payload,
    source_tree_digest,
    validate_candidate,
    verify_evolution_approval,
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
OPERATOR = SyntheticIdentity("synthetic-evolution-operator")


class PassingEvaluator:
    image_digest = DIGEST

    def evaluate(self, candidate_root: Path) -> list[GateResult]:
        assert candidate_root.is_dir()
        return [
            GateResult(
                name=name,
                passed=True,
                exit_code=0,
                output_sha256=DIGEST,
                output_tail="passed",
            )
            for name in ("format", "lint", "types", "tests", "typescript", "secrets")
        ]


class AsyncProtocolSigner:
    def __init__(self, state: Path) -> None:
        self.store = NonceStore(state)
        self.protocol = SignerProtocol(SyntheticIdentity("synthetic-evolution-test"), self.store)

    async def sign(self, request: SignRequest) -> SignResponse:
        return self.protocol.handle(request)

    def close(self) -> None:
        self.store.close()


def _policy() -> EvolutionPolicy:
    return EvolutionPolicy(
        schema="rosetta.evolution-policy.v1",
        enabled=True,
        mode="propose_only",
        evaluator_image_digest=DIGEST,
        allowed_prefixes=["tests/generated", "docs", "src/rosetta"],
        protected_paths=["src/rosetta/evolution.py", "src/rosetta/operations.py"],
        trusted_operator_dids=[OPERATOR.did],
        max_files=4,
        max_total_bytes=4096,
        evaluator_timeout_seconds=30,
        required_gates=["format", "lint", "types", "tests", "typescript", "secrets"],
    )


def _candidate(
    registry: AdapterRegistry,
    mutations: list[EvolutionMutation],
    project: Path | None = None,
) -> EvolutionCandidate:
    return EvolutionCandidate(
        schema="rosetta.evolution-candidate.v1",
        trigger="regression",
        objective="Repair a locally reproduced deterministic regression",
        parent_bundle_root="sha256:" + "b" * 64,
        parent_registry_sha256=registry.digest,
        parent_source_sha256=(source_tree_digest(project) if project is not None else DIGEST),
        proposed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        mutations=mutations,
    )


def _mutation(path: str, content: bytes, operation: str = "create", expected: str | None = None):
    return EvolutionMutation(
        path=path,
        operation=operation,
        expected_sha256=expected,
        content_base64=base64.b64encode(content).decode(),
    )


def _engine(root: Path) -> tuple[EvolutionEngine, StateStore, AdapterRegistry]:
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    store = StateStore(root / "local/state.sqlite3")
    gate = OperationalGate(store, root / "local/KILL_SWITCH")
    engine = EvolutionEngine(root, registry, _policy(), gate, PassingEvaluator())
    return engine, store, registry


def _approval(path: Path, action: str, ident: str, root: str) -> None:
    approval = EvolutionApproval(
        schema="rosetta.evolution-approval.v1",
        action=action,
        candidate_id=ident,
        evolution_root=root,
        approved_by="local-test-operator",
        approved_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        operator_did=OPERATOR.did,
        signature="",
    )
    approval.signature = OPERATOR.sign(evolution_approval_payload(approval))
    path.write_text(approval.json(by_alias=True), encoding="utf-8")


def test_candidate_identity_and_closed_policy_validation() -> None:
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    candidate = _candidate(
        registry, [_mutation("tests/generated/test_new.py", b"def test_x():\n    assert True\n")]
    )
    assert candidate_id(candidate) == candidate_id(EvolutionCandidate.parse_raw(candidate.json()))
    assert validate_candidate(candidate, _policy()) == "test_only"

    with pytest.raises(ValueError, match="unsafe mutation path"):
        validate_candidate(_candidate(registry, [_mutation("../escape.py", b"x")]), _policy())
    with pytest.raises(ValueError, match="protected"):
        validate_candidate(
            _candidate(registry, [_mutation("src/rosetta/evolution.py", b"pass\n")]), _policy()
        )
    with pytest.raises(ValueError, match="requires expected"):
        validate_candidate(
            _candidate(registry, [_mutation("src/rosetta/value.py", b"x", "replace")]),
            _policy(),
        )


def test_signed_package_promotion_and_explicit_rollback(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / "src/rosetta/value.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"VALUE = 1\n")
    engine, store, registry = _engine(project)
    signer = AsyncProtocolSigner(tmp_path / "nonce.sqlite3")
    replacement = b"VALUE = 2\n"
    candidate = _candidate(
        registry,
        [
            _mutation(
                "src/rosetta/value.py",
                replacement,
                "replace",
                "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
            ),
            _mutation("tests/generated/test_value.py", b"def test_value():\n    assert True\n"),
        ],
        project,
    )
    package = project / "artifacts/proposal"
    root, evaluation = asyncio.run(
        engine.evaluate_and_package(candidate, project / "local/workspaces", package, signer)
    )
    assert evaluation.state == "awaiting_human_approval"
    assert verify_evolution_package(package) == root
    assert target.read_bytes() == b"VALUE = 1\n"

    approval = project / "local/promote.json"
    _approval(approval, "promote_candidate", candidate_id(candidate), root)
    record = engine.promote(package, approval, project / "local/rollbacks")
    assert target.read_bytes() == replacement
    created = project / "tests/generated/test_value.py"
    assert created.is_file()

    rollback_approval = project / "local/rollback.json"
    _approval(rollback_approval, "rollback_candidate", candidate_id(candidate), root)
    engine.rollback(record, rollback_approval)
    assert target.read_bytes() == b"VALUE = 1\n"
    assert not created.exists()
    signer.close()
    store.close()


def test_promotion_preflight_is_atomic_and_package_tampering_fails(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / "src/rosetta/value.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"VALUE = 1\n")
    engine, store, registry = _engine(project)
    signer = AsyncProtocolSigner(tmp_path / "nonce.sqlite3")
    original_digest = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    candidate = _candidate(
        registry,
        [
            _mutation("tests/generated/first.py", b"SAFE = True\n"),
            _mutation("src/rosetta/value.py", b"VALUE = 2\n", "replace", original_digest),
        ],
        project,
    )
    package = project / "artifacts/proposal"
    root, _ = asyncio.run(
        engine.evaluate_and_package(candidate, project / "local/workspaces", package, signer)
    )
    approval = project / "local/promote.json"
    _approval(approval, "promote_candidate", candidate_id(candidate), root)
    target.write_bytes(b"OPERATOR_CHANGE = True\n")
    with pytest.raises(ValueError, match="source tree|base changed"):
        engine.promote(package, approval, project / "local/rollbacks")
    assert not (project / "tests/generated/first.py").exists()

    evaluation = package / "evaluation.json"
    evaluation.write_bytes(evaluation.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_evolution_package(package)
    signer.close()
    store.close()


def test_candidate_rejects_duplicate_and_noncanonical_content() -> None:
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    mutation = _mutation("docs/a.md", b"a")
    with pytest.raises(ValueError, match="duplicate"):
        _candidate(registry, [mutation, mutation])
    invalid = EvolutionMutation(path="docs/a.md", operation="create", content_base64="***")
    with pytest.raises(ValueError, match="canonical base64"):
        invalid.content()


def test_operator_approval_requires_trusted_did_and_exact_signature() -> None:
    approval = EvolutionApproval(
        schema="rosetta.evolution-approval.v1",
        action="promote_candidate",
        candidate_id="c" * 64,
        evolution_root=DIGEST,
        approved_by="operator",
        approved_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        operator_did=OPERATOR.did,
        signature="",
    )
    approval.signature = OPERATOR.sign(evolution_approval_payload(approval))
    verify_evolution_approval(approval, _policy(), "promote_candidate", "c" * 64, DIGEST)

    untrusted = _policy()
    untrusted.trusted_operator_dids = []
    with pytest.raises(ValueError, match="not trusted"):
        verify_evolution_approval(approval.copy(), untrusted, "promote_candidate", "c" * 64, DIGEST)

    tampered = approval.copy()
    tampered.signature = "x" * 86
    with pytest.raises(ValueError, match="invalid evolution operator"):
        verify_evolution_approval(tampered, _policy(), "promote_candidate", "c" * 64, DIGEST)
