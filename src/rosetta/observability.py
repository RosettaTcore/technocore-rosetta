"""Structured local metrics without sensitive payloads."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


class Metrics:
    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()

    def increment(self, name: str, value: int = 1) -> None:
        if not name.replace("_", "").isalnum():
            raise ValueError("metric names are closed identifiers")
        self._counter[name] += value

    def snapshot(self) -> dict[str, int]:
        return dict(sorted(self._counter.items()))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.snapshot(), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
