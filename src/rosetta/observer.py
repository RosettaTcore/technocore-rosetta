"""Fail-closed, read-only observation of the public Technocore protocol metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any
from urllib.parse import urlparse

import httpx

from rosetta.config import AppConfig, load_config
from rosetta.operations import kill_switch_active
from rosetta.persistence import StateStore
from rosetta_signer.canonical import canonical_json

WATCHED_PATHS = ("/healthz", "/.well-known/agent.json", "/openapi.json")
SAFE_ERROR_REASONS = frozenset(
    {
        "authority_origin_mismatch",
        "authority_path_mismatch",
        "invalid_authority_url",
        "invalid_document_shape",
        "invalid_health_response",
        "invalid_json",
        "manifest_release_mismatch",
        "missing_documentation_links",
        "openapi_release_mismatch",
        "redirect_rejected",
        "required_metadata_path_missing",
        "response_too_large",
        "unexpected_content_type",
        "unexpected_service_identity",
        "unexpected_status",
        "unsupported_openapi_version",
    }
)


@dataclass(frozen=True)
class EndpointEvidence:
    path: str
    sha256: str
    size_bytes: int
    content_type: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
        }


@dataclass(frozen=True)
class ProtocolObservation:
    release: str
    protocol_digest: str
    endpoints: tuple[EndpointEvidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "rosetta.protocol-observation.v1",
            "release": self.release,
            "protocol_digest": self.protocol_digest,
            "endpoints": [endpoint.as_dict() for endpoint in self.endpoints],
        }


class ReadOnlyProbeClient:
    """A closed GET-only client for three reviewed metadata paths."""

    def __init__(
        self,
        fetch_base_url: str,
        authority_origin: str,
        pinned_release: str,
        timeout_seconds: int,
        max_response_bytes: int,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.fetch_base_url = fetch_base_url.rstrip("/")
        self.authority_origin = authority_origin.rstrip("/")
        self.expected_release = pinned_release.removeprefix("v")
        self.max_response_bytes = max_response_bytes
        self.client = httpx.Client(
            base_url=self.fetch_base_url,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={
                "Accept": "application/json, text/plain;q=0.9",
                "User-Agent": "rosetta-observer/0.1",
            },
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str) -> tuple[bytes, str]:
        if path not in WATCHED_PATHS:
            raise ValueError("observer_path_not_allowlisted")
        with self.client.stream("GET", path) as response:
            if response.is_redirect:
                raise RuntimeError(f"redirect_rejected:{path}")
            if response.status_code != 200:
                raise RuntimeError(f"unexpected_status:{path}:{response.status_code}")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise RuntimeError(f"response_too_large:{path}")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        return bytes(body), content_type

    @staticmethod
    def _json_document(path: str, body: bytes, content_type: str) -> dict[str, Any]:
        if content_type != "application/json":
            raise RuntimeError(f"unexpected_content_type:{path}")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid_json:{path}") from exc
        if not isinstance(document, dict):
            raise RuntimeError(f"invalid_document_shape:{path}")
        return document

    def _validate_authority_url(self, value: object, expected_path: str) -> None:
        if not isinstance(value, str):
            raise RuntimeError("invalid_authority_url")
        parsed = urlparse(value)
        if parsed.scheme or parsed.netloc:
            if f"{parsed.scheme}://{parsed.netloc}" != self.authority_origin:
                raise RuntimeError("authority_origin_mismatch")
        if parsed.path != expected_path or parsed.query or parsed.fragment:
            raise RuntimeError("authority_path_mismatch")

    def probe(self) -> ProtocolObservation:
        evidence: list[EndpointEvidence] = []
        documents: dict[str, dict[str, Any]] = {}
        for path in WATCHED_PATHS:
            body, content_type = self._get(path)
            if path == "/healthz":
                if content_type != "text/plain" or body.strip() != b"ok":
                    raise RuntimeError("invalid_health_response")
            else:
                documents[path] = self._json_document(path, body, content_type)
            evidence.append(
                EndpointEvidence(
                    path=path,
                    sha256="sha256:" + hashlib.sha256(body).hexdigest(),
                    size_bytes=len(body),
                    content_type=content_type,
                )
            )

        manifest = documents["/.well-known/agent.json"]
        openapi = documents["/openapi.json"]
        if manifest.get("name") != "technocore-chat":
            raise RuntimeError("unexpected_service_identity")
        if manifest.get("version") != self.expected_release:
            raise RuntimeError("manifest_release_mismatch")
        info = openapi.get("info")
        if not isinstance(info, dict) or info.get("version") != self.expected_release:
            raise RuntimeError("openapi_release_mismatch")
        if not str(openapi.get("openapi", "")).startswith("3.1"):
            raise RuntimeError("unsupported_openapi_version")
        paths = openapi.get("paths")
        if not isinstance(paths, dict) or not all(path in paths for path in WATCHED_PATHS):
            raise RuntimeError("required_metadata_path_missing")
        documentation = manifest.get("documentation")
        if not isinstance(documentation, dict):
            raise RuntimeError("missing_documentation_links")
        self._validate_authority_url(documentation.get("openapi"), "/openapi.json")
        self._validate_authority_url(documentation.get("manual"), "/llms.txt")

        digest_input = {
            "release": self.expected_release,
            "endpoints": {item.path: item.sha256 for item in evidence},
        }
        protocol_digest = "sha256:" + hashlib.sha256(canonical_json(digest_input)).hexdigest()
        return ProtocolObservation(self.expected_release, protocol_digest, tuple(evidence))


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _error_reason(exc: Exception) -> str:
    if isinstance(exc, RuntimeError):
        reason = str(exc).split(":", 1)[0]
        if reason in SAFE_ERROR_REASONS:
            return reason
    return type(exc).__name__


class ObserverService:
    def __init__(
        self,
        config: AppConfig,
        *,
        store: StateStore | None = None,
        client: ReadOnlyProbeClient | None = None,
        clock: Any = None,
    ) -> None:
        if not config.observer.enabled:
            raise ValueError("observer_disabled")
        self.config = config
        self.state_directory = Path(config.observer.state_directory)
        self.evidence_directory = Path(config.observer.evidence_directory)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self.evidence_directory.mkdir(parents=True, exist_ok=True)
        self.store = store or StateStore(self.state_directory / "observer.sqlite3")
        self.client = client or ReadOnlyProbeClient(
            config.observer.fetch_base_url,
            config.technocore.base_url,
            config.technocore.pinned_release,
            config.technocore.request_timeout_seconds,
            config.observer.max_response_bytes,
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stop_requested = False

    @property
    def kill_switch(self) -> Path:
        return Path(self.config.operations.kill_switch_file)

    def request_stop(self, _signum: int | None = None, _frame: FrameType | None = None) -> None:
        self.stop_requested = True

    def _health(self, **fields: object) -> None:
        _atomic_json(
            self.state_directory / "health.json",
            {
                "schema": "rosetta.observer-health.v1",
                "mode": "dry_run",
                "public_writes": 0,
                **fields,
            },
        )

    def observe_once(self) -> dict[str, object]:
        now = self.clock()
        if kill_switch_active(self.kill_switch):
            self._health(status="stopped", reason="kill_switch_active", checked_at=now.isoformat())
            raise RuntimeError("kill_switch_active")
        try:
            observation = self.client.probe()
            changed = self.store.record_protocol_observation(
                observation.protocol_digest, observation.release, now
            )
            self.store.record_component_result(
                "read_only_observer", True, self.config.operations.fail_read_only_after_errors, now
            )
            if changed:
                evidence = {
                    **observation.as_dict(),
                    "observed_at": now.astimezone(timezone.utc).isoformat(),
                    "changed": True,
                    "public_writes": 0,
                }
                digest_name = observation.protocol_digest.removeprefix("sha256:")
                _atomic_json(self.evidence_directory / f"{digest_name}.json", evidence)
            result: dict[str, object] = {
                "status": "healthy",
                "checked_at": now.astimezone(timezone.utc).isoformat(),
                "release": observation.release,
                "protocol_digest": observation.protocol_digest,
                "changed": changed,
                "public_writes": 0,
            }
            self._health(**result)
            return result
        except Exception as exc:
            errors, degraded = self.store.record_component_result(
                "read_only_observer", False, self.config.operations.fail_read_only_after_errors, now
            )
            self._health(
                status="degraded" if degraded else "retrying",
                reason=_error_reason(exc),
                consecutive_errors=errors,
                checked_at=now.astimezone(timezone.utc).isoformat(),
            )
            raise

    def run(self, *, once: bool = False) -> None:
        while not self.stop_requested:
            try:
                self.observe_once()
            except RuntimeError as exc:
                if str(exc) == "kill_switch_active":
                    return
                if once:
                    raise
            except Exception:
                if once:
                    raise
            if once:
                return
            deadline = time.monotonic() + self.config.observer.interval_seconds
            while not self.stop_requested and time.monotonic() < deadline:
                if kill_switch_active(self.kill_switch):
                    self.request_stop()
                    break
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    def close(self) -> None:
        self.client.close()
        self.store.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="rosetta-observer")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    service = ObserverService(load_config(args.config))
    signal.signal(signal.SIGTERM, service.request_stop)
    signal.signal(signal.SIGINT, service.request_stop)
    try:
        service.run(once=args.once)
    finally:
        service.close()


if __name__ == "__main__":
    main()
