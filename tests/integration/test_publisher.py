import asyncio
from pathlib import Path

import pytest

from rosetta.cli import _registry, _run_record, _versions, signer_process
from rosetta.evidence import build_bundle
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.publishing import StaticPublisher
from rosetta.scenario import run_roundtrip


def test_publisher_is_disabled_and_requires_valid_approved_bundle(tmp_path: Path) -> None:
    async def exercise() -> None:
        registry = _registry()
        spool = tmp_path / "spool"
        state = StateStore(tmp_path / "state.sqlite3")
        gate = OperationalGate(state, tmp_path / "KILL_SWITCH")
        async with signer_process(tmp_path / "signer", "synthetic-publisher") as signer:
            result = await run_roundtrip("python-http", "official-mcp", registry, signer)
            await build_bundle(
                spool / "bundle", _run_record(registry), [result], _versions(registry), signer
            )
        disabled = StaticPublisher(False, spool, tmp_path / "public", state, gate)
        with pytest.raises(RuntimeError, match="publisher_disabled"):
            disabled.publish(spool / "bundle")
        enabled = StaticPublisher(True, spool, tmp_path / "public", state, gate)
        published = enabled.publish(spool / "bundle")
        assert (published / "attestation.json").is_file()
        with pytest.raises(ValueError, match="already published"):
            enabled.publish(spool / "bundle")
        with pytest.raises(ValueError, match="approved spool"):
            enabled.publish(tmp_path / "outside")
        state.close()

    asyncio.run(exercise())
