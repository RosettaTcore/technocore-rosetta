import base64
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rosetta.evolution import (
    EvolutionCandidate,
    EvolutionMutation,
    load_evolution_policy,
    validate_candidate,
)
from rosetta.registry import AdapterRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _candidate(path: str, *, operation: str = "create", expected: str | None = None):
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    return EvolutionCandidate(
        schema="rosetta.evolution-candidate.v1",
        trigger="operator",
        objective="Adversarial boundary test",
        parent_bundle_root="sha256:" + "1" * 64,
        parent_registry_sha256=registry.digest,
        parent_source_sha256="sha256:" + "2" * 64,
        proposed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        mutations=[
            EvolutionMutation(
                path=path,
                operation=operation,
                expected_sha256=expected,
                content_base64=base64.b64encode(b"hostile\n").decode(),
            )
        ],
    )


@pytest.mark.parametrize(
    "path",
    [
        "src/rosetta/evolution.py",
        "src/rosetta/operations.py",
        "config/evolution.policy.yaml",
        "deploy/Dockerfile.evolution-evaluator",
        "src/rosetta_signer/protocol.py",
        "AGENTS.md",
    ],
)
def test_candidate_cannot_change_authority_boundary(path: str) -> None:
    with pytest.raises(ValueError, match="outside|protected"):
        validate_candidate(
            _candidate(path), load_evolution_policy(PROJECT_ROOT / "config/evolution.policy.yaml")
        )


@pytest.mark.parametrize(
    "path",
    ["/tmp/escape", "../escape", "docs/../../escape", "docs\\escape"],  # noqa: S108
)
def test_candidate_cannot_escape_project(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        validate_candidate(
            _candidate(path), load_evolution_policy(PROJECT_ROOT / "config/evolution.policy.yaml")
        )


def test_candidate_cannot_smuggle_binary_or_oversized_change() -> None:
    policy = load_evolution_policy(PROJECT_ROOT / "config/evolution.policy.yaml")
    binary = _candidate("docs/hostile.md")
    binary.mutations[0].content_base64 = base64.b64encode(b"x\0y").decode()
    with pytest.raises(ValueError, match="binary"):
        validate_candidate(binary, policy)

    oversized = _candidate("docs/huge.md")
    oversized.mutations[0].content_base64 = base64.b64encode(b"x" * 65537).decode()
    with pytest.raises(ValueError, match="byte limit"):
        validate_candidate(oversized, policy)
