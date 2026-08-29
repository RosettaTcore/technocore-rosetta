"""Kill switches, bounded budgets, decision traces, and redaction."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rosetta.persistence import StateStore

_SENSITIVE_KEY = re.compile(r"(authorization|cookie|token|secret|password|seed|credential)", re.I)


def kill_switch_active(path: Path) -> bool:
    return path.exists()


def require_operational(path: Path) -> None:
    if kill_switch_active(path):
        raise RuntimeError("kill_switch_active")


class OperationalGate:
    """One fail-closed policy shared by scheduling, execution, signing and publishing."""

    def __init__(
        self,
        store: StateStore,
        kill_switch: Path,
        *,
        max_runs_per_day: int = 4,
        monthly_budget_cents: int = 4_000,
        quarantine_after: int = 3,
        max_parallel: int = 2,
    ) -> None:
        self.store = store
        self.kill_switch = kill_switch
        self.max_runs_per_day = max_runs_per_day
        self.monthly_budget_cents = monthly_budget_cents
        self.quarantine_after = quarantine_after
        self._slots = asyncio.Semaphore(max_parallel)

    def require(self, component: str) -> None:
        require_operational(self.kill_switch)
        if self.store.component_quarantined(component):
            raise RuntimeError(f"component_quarantined:{component}")

    def reserve_run(self, now: datetime, estimated_cost_cents: int = 0) -> None:
        self.require("scheduler")
        current = now.astimezone(timezone.utc)
        if not self.store.reserve_usage(
            current.date().isoformat(), "runs", 1, self.max_runs_per_day
        ):
            raise RuntimeError("daily_run_quota_exceeded")
        if not self.store.reserve_usage(
            current.strftime("%Y-%m"),
            "cost_cents",
            estimated_cost_cents,
            self.monthly_budget_cents,
        ):
            raise RuntimeError("monthly_budget_exceeded")

    def record(self, component: str, success: bool, now: datetime) -> tuple[int, bool]:
        return self.store.record_component_result(component, success, self.quarantine_after, now)

    @asynccontextmanager
    async def slot(self, component: str) -> AsyncIterator[None]:
        self.require(component)
        async with self._slots:
            self.require(component)
            yield


def redact(value: Any, *, max_string: int = 512) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [redact(item) for item in value[:100]]
    if isinstance(value, str):
        text = value[:max_string]
        text = re.sub(r"https?://[^\s\"']+", "[REDACTED_URL]", text)
        text = re.sub(r"Bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", text, flags=re.I)
        return text
    return value


@dataclass(frozen=True)
class DecisionTrace:
    mode: str
    kill_switch: bool
    public_write: bool
    publisher_enabled: bool
    model_provider: str

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "kill_switch": self.kill_switch,
            "public_write": self.public_write,
            "publisher_enabled": self.publisher_enabled,
            "model_provider": self.model_provider,
        }
