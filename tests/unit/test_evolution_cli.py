from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rosetta import evolution_cli

DIGEST = "sha256:" + "d" * 64


class FakeStore:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    def promote(self, package: Path, approval: Path, rollback: Path) -> Path:
        assert package.name == "package"
        assert approval.name == "approval.json"
        return rollback / "candidate/promotion.json"

    def rollback(self, record: Path, approval: Path) -> None:
        assert record.name == "promotion.json"
        assert approval.name == "approval.json"


def test_project_path_guard_and_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evolution_cli, "PROJECT_ROOT", tmp_path / "project")
    inside = evolution_cli.PROJECT_ROOT / "artifacts/proposal"
    assert evolution_cli._inside_project(inside, "test") == inside.resolve()
    with pytest.raises(ValueError, match="must remain"):
        evolution_cli._inside_project(tmp_path / "outside", "test")
    parsed = evolution_cli._parser().parse_args(["verify", str(inside)])
    assert parsed.command == "verify"


def test_verify_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    package = evolution_cli.PROJECT_ROOT / "artifacts/package"
    monkeypatch.setattr(evolution_cli, "verify_evolution_package", lambda path: DIGEST)
    monkeypatch.setattr(sys, "argv", ["rosetta-evolution", "verify", str(package)])
    evolution_cli.main()
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "schema": "rosetta.evolution-verification.v1",
        "evolution_root": DIGEST,
        "verified": True,
    }


def test_evaluate_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_evaluate(candidate: Path, output: Path, workspace: Path):  # type: ignore[no-untyped-def]
        assert candidate.name == "candidate.json"
        assert output.name == "package"
        assert workspace.name == "workspaces"
        return {"state": "awaiting_human_approval", "project_mutated": False}

    root = evolution_cli.PROJECT_ROOT
    monkeypatch.setattr(evolution_cli, "_evaluate", fake_evaluate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rosetta-evolution",
            "evaluate",
            str(root / "fixtures/candidate.json"),
            str(root / "artifacts/package"),
            "--workspace",
            str(root / "local/workspaces"),
        ],
    )
    evolution_cli.main()
    assert json.loads(capsys.readouterr().out)["project_mutated"] is False


@pytest.mark.parametrize("command", ["promote", "rollback"])
def test_approved_mutation_commands(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = evolution_cli.PROJECT_ROOT
    store = FakeStore()
    monkeypatch.setattr(evolution_cli, "_engine", lambda: (FakeEngine(), store))
    if command == "promote":
        argv = [
            "rosetta-evolution",
            "promote",
            str(root / "artifacts/package"),
            str(root / "local/approval.json"),
            "--rollback-root",
            str(root / "local/rollbacks"),
        ]
    else:
        argv = [
            "rosetta-evolution",
            "rollback",
            str(root / "local/promotion.json"),
            str(root / "local/approval.json"),
        ]
    monkeypatch.setattr(sys, "argv", argv)
    evolution_cli.main()
    output = json.loads(capsys.readouterr().out)
    assert output["promoted" if command == "promote" else "rolled_back"] is True
    assert store.closed
