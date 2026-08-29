"""Operator CLI for evaluate-only evolution proposals and approved recovery actions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from rosetta.evolution import (
    DockerEvolutionEvaluator,
    EvolutionCandidate,
    EvolutionEngine,
    load_evolution_policy,
    verify_evolution_package,
)
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.registry import AdapterRegistry
from rosetta.signer_client import GuardedSigner, ProcessSignerClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _inside_project(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents:
        raise ValueError(f"{label} must remain under the Rosetta project directory")
    return resolved


def _engine() -> tuple[EvolutionEngine, StateStore]:
    policy = load_evolution_policy(PROJECT_ROOT / "config/evolution.policy.yaml")
    registry = AdapterRegistry.load(PROJECT_ROOT / "config/adapters.lock.yaml")
    store = StateStore(PROJECT_ROOT / "local/evolution/state.sqlite3")
    gate = OperationalGate(store, PROJECT_ROOT / "local/KILL_SWITCH")
    evaluator = DockerEvolutionEvaluator(
        policy.evaluator_image_digest, policy.evaluator_timeout_seconds
    )
    return EvolutionEngine(PROJECT_ROOT, registry, policy, gate, evaluator), store


async def _evaluate(candidate_path: Path, output: Path, workspace: Path) -> dict[str, object]:
    candidate = EvolutionCandidate.parse_raw(
        _inside_project(candidate_path, "candidate").read_bytes()
    )
    engine, store = _engine()
    now = datetime.now(timezone.utc)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    signer_state = PROJECT_ROOT / "local/evolution/signer/nonce.sqlite3"
    signer_state.parent.mkdir(parents=True, exist_ok=True)
    signer = GuardedSigner(
        ProcessSignerClient(
            signer_state,
            "synthetic-rosetta-evolution-local",
            environment,
        ),
        engine.gate,
    )
    try:
        engine.gate.reserve_run(now)
        root, evaluation = await engine.evaluate_and_package(
            candidate,
            _inside_project(workspace, "workspace"),
            _inside_project(output, "output"),
            signer,
        )
        engine.gate.record("evolution", True, now)
        return {
            "schema": "rosetta.evolution-cli-result.v1",
            "candidate_id": evaluation.candidate_id,
            "evolution_root": root,
            "passed": evaluation.passed,
            "state": evaluation.state,
            "project_mutated": False,
            "automatic_promotion": False,
        }
    except Exception:
        engine.gate.record("evolution", False, now)
        raise
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rosetta controlled evolution pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate", help="stage, test, and sign a candidate")
    evaluate.add_argument("candidate", type=Path)
    evaluate.add_argument("output", type=Path)
    evaluate.add_argument(
        "--workspace", type=Path, default=PROJECT_ROOT / "local/evolution/workspaces"
    )
    verify = subparsers.add_parser("verify", help="verify a signed evolution package")
    verify.add_argument("package", type=Path)
    promote = subparsers.add_parser("promote", help="apply an exactly approved passing candidate")
    promote.add_argument("package", type=Path)
    promote.add_argument("approval", type=Path)
    promote.add_argument(
        "--rollback-root", type=Path, default=PROJECT_ROOT / "local/evolution/rollbacks"
    )
    rollback = subparsers.add_parser("rollback", help="reverse an exactly approved promotion")
    rollback.add_argument("record", type=Path)
    rollback.add_argument("approval", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "evaluate":
        result = asyncio.run(_evaluate(args.candidate, args.output, args.workspace))
    elif args.command == "verify":
        result = {
            "schema": "rosetta.evolution-verification.v1",
            "evolution_root": verify_evolution_package(_inside_project(args.package, "package")),
            "verified": True,
        }
    else:
        engine, store = _engine()
        try:
            if args.command == "promote":
                record = engine.promote(
                    _inside_project(args.package, "package"),
                    _inside_project(args.approval, "approval"),
                    _inside_project(args.rollback_root, "rollback root"),
                )
                result = {
                    "schema": "rosetta.evolution-promotion-result.v1",
                    "promoted": True,
                    "rollback_record": str(record),
                }
            else:
                engine.rollback(
                    _inside_project(args.record, "record"),
                    _inside_project(args.approval, "approval"),
                )
                result = {"schema": "rosetta.evolution-rollback-result.v1", "rolled_back": True}
        finally:
            store.close()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
