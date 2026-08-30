import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rosetta.cli import _registry
from rosetta.contracts import SignRequest, SignResponse
from rosetta.observability import Metrics
from rosetta.operations import OperationalGate
from rosetta.persistence import StateStore
from rosetta.publishing import StaticPublisher
from rosetta.runners import RunnerSupervisor
from rosetta.scheduler import Scheduler
from rosetta.signer_client import GuardedSigner

NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


class StubSigner:
    async def sign(self, _request: SignRequest) -> SignResponse:
        return SignResponse(
            did="did:key:z6Mkon3Necd6NkkyfoGoHxid2znGc59LU3K7mubaRcFbLfLX",
            signature="A" * 86,
            signed_digest="sha256:" + "0" * 64,
        )


def test_kill_switch_blocks_scheduler_runner_and_signer(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    kill = tmp_path / "KILL_SWITCH"
    gate = OperationalGate(store, kill)
    kill.touch()
    with pytest.raises(RuntimeError, match="kill_switch_active"):
        Scheduler(store, _registry(), gate).observe("p", "s", "t", NOW)
    with pytest.raises(RuntimeError, match="kill_switch_active"):
        RunnerSupervisor(_registry(), gate=gate).compile("python-http")
    with pytest.raises(RuntimeError, match="kill_switch_active"):
        StaticPublisher(False, tmp_path / "spool", tmp_path / "public", store, gate).publish(
            tmp_path / "spool/bundle"
        )

    async def blocked_sign() -> None:
        with pytest.raises(RuntimeError, match="kill_switch_active"):
            await GuardedSigner(StubSigner(), gate).sign(
                SignRequest(action="artifact_root", scope="test", digest="sha256:" + "0" * 64)
            )

    asyncio.run(blocked_sign())
    store.close()


def test_budgets_quarantine_and_crash_recovery_persist(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    store = StateStore(path)
    gate = OperationalGate(
        store,
        tmp_path / "KILL_SWITCH",
        max_runs_per_day=2,
        monthly_budget_cents=5,
        quarantine_after=3,
    )
    gate.reserve_run(NOW, 2)
    gate.reserve_run(NOW, 3)
    with pytest.raises(RuntimeError, match="daily_run_quota_exceeded"):
        gate.reserve_run(NOW, 0)
    assert gate.record("runner", False, NOW) == (1, False)
    assert gate.record("runner", False, NOW) == (2, False)
    assert gate.record("runner", False, NOW) == (3, True)
    with pytest.raises(RuntimeError, match="component_quarantined"):
        gate.require("runner")
    store.close()

    reopened = StateStore(path)
    assert reopened.usage("2026-08-25", "runs") == 2
    assert reopened.usage("2026-08", "cost_cents") == 5
    assert reopened.component_quarantined("runner")
    reopened.record_component_result("runner", True, 3, NOW)
    assert not reopened.component_quarantined("runner")
    reopened.close()


def test_parallel_slots_are_bounded(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = StateStore(tmp_path / "state.sqlite3")
        gate = OperationalGate(store, tmp_path / "KILL_SWITCH", max_parallel=2)
        active = 0
        high_water = 0
        lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal active, high_water
            async with gate.slot("runner"):
                async with lock:
                    active += 1
                    high_water = max(high_water, active)
                await asyncio.sleep(0.01)
                async with lock:
                    active -= 1

        await asyncio.gather(*(worker() for _ in range(8)))
        assert high_water == 2
        store.close()

    asyncio.run(exercise())


def test_monthly_budget_and_invalid_metric_name_fail_closed(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    gate = OperationalGate(
        store,
        tmp_path / "KILL_SWITCH",
        max_runs_per_day=4,
        monthly_budget_cents=1,
    )
    with pytest.raises(RuntimeError, match="monthly_budget_exceeded"):
        gate.reserve_run(NOW, 2)
    metrics = Metrics()
    with pytest.raises(ValueError, match="closed identifiers"):
        metrics.increment("unsafe.metric")
    store.close()
