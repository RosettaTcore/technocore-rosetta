import asyncio
from pathlib import Path

import pytest

from rosetta.cli import _registry, _run_record, _versions, signer_process
from rosetta.contracts import Outcome, ReasonCode
from rosetta.evidence import build_bundle, verify_bundle
from rosetta.scenario import run_roundtrip
from rosetta.scheduler import REQUIRED_MATRIX


def test_all_required_cells_faults_and_reproducible_bundle(tmp_path: Path) -> None:
    async def exercise() -> None:
        registry = _registry()
        async with signer_process(tmp_path / "signer", "synthetic-integration-matrix") as signer:
            results = [
                await run_roundtrip(producer, consumer, registry, signer)
                for producer, consumer in REQUIRED_MATRIX
            ]
            assert all(result.outcome is Outcome.PASS for result in results)
            names = {assertion.name for result in results for assertion in result.assertions}
            assert "rate_limit_backoff_bounded" in names
            assert "uncertain_write_reconciled" in names
            assert "restart_resumed_cursor" in names
            first = await build_bundle(
                tmp_path / "a", _run_record(registry), results, _versions(registry), signer
            )
            second = await build_bundle(
                tmp_path / "b", _run_record(registry), results, _versions(registry), signer
            )
            assert first == second
            assert verify_bundle(tmp_path / "a") == first

    asyncio.run(exercise())


def test_injected_regression_has_stable_reason_and_minimal_reproduction(tmp_path: Path) -> None:
    async def exercise() -> None:
        registry = _registry()
        async with signer_process(tmp_path / "signer", "synthetic-regression") as signer:
            result = await run_roundtrip(
                "python-http", "typescript-http", registry, signer, inject_regression=True
            )
        assert result.outcome is Outcome.FAIL
        assert result.reason is ReasonCode.CANONICAL_PAYLOAD_MISMATCH
        assert result.reproduction["fault"] == "broken-canonicalizer"
        assert set(result.reproduction) == {
            "schema",
            "scenario",
            "producer",
            "consumer",
            "fault",
            "correlation_id",
        }

    asyncio.run(exercise())


def test_bundle_mutation_breaks_verification(tmp_path: Path) -> None:
    async def exercise() -> None:
        registry = _registry()
        async with signer_process(tmp_path / "signer", "synthetic-mutation") as signer:
            result = await run_roundtrip("python-http", "typescript-http", registry, signer)
            await build_bundle(
                tmp_path / "bundle", _run_record(registry), [result], _versions(registry), signer
            )
        (tmp_path / "bundle/run.json").write_text("{}\n")
        with pytest.raises(ValueError, match="checksum mismatch"):
            verify_bundle(tmp_path / "bundle")

    asyncio.run(exercise())
