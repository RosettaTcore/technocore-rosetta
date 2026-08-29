from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from rosetta import cli, evolution_cli

DIGEST = "sha256:" + "e" * 64


class FakeStore:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeGate:
    def __init__(self) -> None:
        self.reserved = 0
        self.records: list[tuple[str, bool]] = []

    def reserve_run(self, now: object) -> None:
        self.reserved += 1

    def record(self, component: str, success: bool, now: object) -> tuple[int, bool]:
        self.records.append((component, success))
        return 0, False


class FakeEvolutionEngine:
    def __init__(self, *, fail: bool = False) -> None:
        self.gate = FakeGate()
        self.fail = fail

    async def evaluate_and_package(
        self, candidate: object, workspace: Path, output: Path, signer: object
    ) -> tuple[str, SimpleNamespace]:
        assert workspace.name == "workspaces"
        assert output.name == "proposal"
        if self.fail:
            raise RuntimeError("evaluator unavailable")
        return DIGEST, SimpleNamespace(
            candidate_id="candidate", passed=True, state="awaiting_human_approval"
        )


def test_evolution_engine_factory_loads_protected_local_policy() -> None:
    engine, store = evolution_cli._engine()
    try:
        assert engine.policy.mode == "propose_only"
        assert engine.policy.trusted_operator_dids == []
    finally:
        store.close()


@pytest.mark.parametrize("fails", [False, True])
def test_evolution_evaluate_orchestration_records_health(
    fails: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = FakeEvolutionEngine(fail=fails)
    store = FakeStore()
    monkeypatch.setattr(evolution_cli, "_engine", lambda: (engine, store))
    candidate = evolution_cli.PROJECT_ROOT / "fixtures/evolution/candidate-add-domain-vector.json"
    coroutine = evolution_cli._evaluate(
        candidate,
        evolution_cli.PROJECT_ROOT / "artifacts/proposal",
        evolution_cli.PROJECT_ROOT / "local/workspaces",
    )
    if fails:
        with pytest.raises(RuntimeError, match="unavailable"):
            asyncio.run(coroutine)
        assert engine.gate.records == [("evolution", False)]
    else:
        result = asyncio.run(coroutine)
        assert result["state"] == "awaiting_human_approval"
        assert result["project_mutated"] is False
        assert engine.gate.records == [("evolution", True)]
    assert engine.gate.reserved == 1
    assert store.closed


def test_main_cli_demo_verify_and_cell_branches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_demo(output: Path, target_url: str | None, target_image: str):
        return {"mode": "demo", "output": output.name, "target": target_url}

    async def fake_cell(producer: str, consumer: str):
        return {"producer": producer, "consumer": consumer}

    monkeypatch.setattr(cli, "demo", fake_demo)
    monkeypatch.setattr(cli, "cell", fake_cell)
    monkeypatch.setattr(cli, "verify_bundle", lambda path: DIGEST)

    monkeypatch.setattr(
        sys,
        "argv",
        ["rosetta", "demo", "--output", "artifacts/x", "--target-url", "http://localhost"],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["mode"] == "demo"

    monkeypatch.setattr(sys, "argv", ["rosetta", "verify", "artifacts/x/bundle"])
    cli.main()
    assert capsys.readouterr().out.strip() == DIGEST

    monkeypatch.setattr(
        sys,
        "argv",
        ["rosetta", "cell", "--producer", "raw-fetch", "--consumer", "official-mcp"],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["consumer"] == "official-mcp"


def test_demo_output_guard_rejects_escape_and_nonempty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path / "project")
    with pytest.raises(ValueError, match="remain"):
        cli._prepare_output(tmp_path / "outside")
    output = cli.PROJECT_ROOT / "artifacts/output"
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "marker"
    marker.write_text("occupied", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        cli._prepare_output(output)
