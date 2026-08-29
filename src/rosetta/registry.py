"""Reviewed immutable adapter registry."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from rosetta.contracts import AdapterManifest, AdapterRegistryContract
from rosetta_signer.canonical import canonical_json


class AdapterRegistry:
    def __init__(self, contract: AdapterRegistryContract) -> None:
        ids = [adapter.id for adapter in contract.adapters]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate adapter id")
        self.contract = contract
        self._by_id: dict[str, AdapterManifest] = {item.id: item for item in contract.adapters}

    @classmethod
    def load(cls, path: Path) -> AdapterRegistry:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(AdapterRegistryContract.parse_obj(raw))

    @property
    def digest(self) -> str:
        raw = canonical_json(self.contract.dict())
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def require(self, adapter_id: str) -> AdapterManifest:
        try:
            return self._by_id[adapter_id]
        except KeyError as exc:
            raise ValueError("unallowlisted adapter") from exc

    def contains_exact(self, manifest: AdapterManifest) -> bool:
        known = self._by_id.get(manifest.id)
        return known is not None and known == manifest

    @property
    def ids(self) -> list[str]:
        return sorted(self._by_id)
