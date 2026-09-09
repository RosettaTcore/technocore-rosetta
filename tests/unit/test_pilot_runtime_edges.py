from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import rosetta.pilot as pilot_module
import rosetta.publishing as publishing_module
from rosetta.contracts import Acknowledgement, Outcome, ServiceRequest
from rosetta.local_protocol import ProtocolRecord, UncertainWrite
from rosetta.pilot import PilotRuntime, _atomic_json, _run
from rosetta.pilot_config import PilotConfig
from rosetta.publishing import ServiceDocumentPublisher
from rosetta.service import service_names
from rosetta_signer.did import SyntheticIdentity
from tests.integration.test_pilot_service import PilotFixtureTarget
from tests.unit.test_service_edges import AsyncSigner

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _config(tmp_path: Path, did: str, *, enabled: bool) -> PilotConfig:
    return PilotConfig.parse_obj(
        {
            "schema": "rosetta.pilot-config.v1",
            "mode": "pilot",
            "technocore": {
                "authority_origin": "https://technocore.chat/",
                "fetch_origin": "http://localhost:8082/",
                "pinned_release": "v0.13.0",
                "discovery_rooms": ["lobby", "meta"],
                "request_timeout_seconds": 30,
                "max_response_bytes": 4_194_304,
            },
            "identity": {"public_did": did, "signer_socket": str(tmp_path / "signer.sock")},
            "service": {
                "enabled": enabled,
                "public_base_url": "https://reports.invalid/",
                "state_directory": str(tmp_path / "state"),
                "spool_directory": str(tmp_path / "spool"),
                "static_root": str(tmp_path / "public"),
                "kill_switch_file": str(tmp_path / "KILL_SWITCH"),
                "poll_seconds": 300,
                "max_requests_per_did_per_day": 2,
                "max_external_jobs_per_day": 8,
                "max_queue_depth": 16,
                "max_parallel_runners": 1,
                "monthly_budget_cents": 4_000,
            },
            "model_provider": "disabled",
        }
    )


def test_pilot_config_valid_boundaries_are_normalized(tmp_path: Path) -> None:
    config = _config(tmp_path, SyntheticIdentity("synthetic-config-valid-edges").did, enabled=False)
    assert config.technocore.authority_origin == "https://technocore.chat"
    assert config.technocore.fetch_origin == "http://localhost:8082"
    assert config.service.public_base_url == "https://reports.invalid"
    assert config.service.poll_seconds == 300


def test_atomic_json_removes_temporary_file_after_failed_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_source: str, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(pilot_module.os, "replace", fail)
    with pytest.raises(OSError, match="synthetic"):
        _atomic_json(tmp_path / "value.json", {"safe": True})
    assert list(tmp_path.iterdir()) == []


def test_runtime_identity_disabled_activation_and_corrupt_preview(tmp_path: Path) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-runtime-edge")
        other = SyntheticIdentity("synthetic-runtime-other").did
        target = PilotFixtureTarget()
        mismatch = PilotRuntime(
            _config(tmp_path / "mismatch", other, enabled=False), signer=signer, target=target
        )
        with pytest.raises(RuntimeError, match="configured DID"):
            await mismatch.prepare(NOW)
        mismatch.request_stop()
        assert mismatch.stop_requested
        mismatch.close()

        signer2 = AsyncSigner(tmp_path / "signer2.sqlite3", "synthetic-runtime-edge-2")
        runtime = PilotRuntime(
            _config(tmp_path / "disabled", signer2.did, enabled=False),
            signer=signer2,
            target=PilotFixtureTarget(),
            clock=lambda: NOW,
        )
        _, digest = await runtime.prepare(NOW)
        with pytest.raises(RuntimeError, match="pilot_disabled"):
            await runtime.activate(digest, NOW)
        with pytest.raises(RuntimeError, match="not_activated"):
            await runtime.poll_once(NOW)
        runtime.preview_path.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="activation preview"):
            runtime._load_prepared()
        runtime.stop_requested = True
        await runtime.serve()
        runtime.close()
        signer.close()
        signer2.close()

    asyncio.run(exercise())


def test_runtime_activation_digest_card_and_write_set_fail_closed(tmp_path: Path) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-activation-edge")
        runtime = PilotRuntime(
            _config(tmp_path, signer.did, enabled=True),
            signer=signer,
            target=PilotFixtureTarget(),
            clock=lambda: NOW,
        )
        _, digest = await runtime.prepare(NOW)
        with pytest.raises(RuntimeError, match="approval digest"):
            await runtime.activate("sha256:" + "0" * 64, NOW)

        attestation_path = runtime.service_documents / "service-card.attestation.json"
        attestation = json.loads(attestation_path.read_bytes())
        original = dict(attestation)
        attestation["service_card_sha256"] = "sha256:" + "0" * 64
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
        with pytest.raises(RuntimeError, match="invalid or expired"):
            runtime._load_card(NOW)
        attestation_path.write_text(json.dumps(original), encoding="utf-8")

        configured_did = runtime.config.identity.public_did
        runtime.config.identity.public_did = SyntheticIdentity("synthetic-changed-identity").did
        with pytest.raises(RuntimeError, match="identity mismatch"):
            runtime._load_card(NOW)
        runtime.config.identity.public_did = configured_did

        preview, _ = runtime._load_prepared()
        preview["writes"] = []
        _atomic_json(runtime.preview_path, preview)
        changed_digest = pilot_module._digest(preview)
        with pytest.raises(ValueError, match="write set"):
            await runtime.activate(changed_digest, NOW)

        preview["writes"] = ["bad", {}, {}]
        _atomic_json(runtime.preview_path, preview)
        changed_digest = pilot_module._digest(preview)
        with pytest.raises(ValueError, match="claim_service_room preview"):
            await runtime.activate(changed_digest, NOW)

        preview, _ = await runtime.prepare(NOW)
        writes = preview["writes"]
        assert isinstance(writes, list)
        writes[1] = "bad"
        _atomic_json(runtime.preview_path, preview)
        changed_digest = pilot_module._digest(preview)
        with pytest.raises(ValueError, match="allow_service_identity preview"):
            await runtime.activate(changed_digest, NOW)

        preview, _ = await runtime.prepare(NOW)
        writes = preview["writes"]
        assert isinstance(writes, list)
        writes[2] = "bad"
        _atomic_json(runtime.preview_path, preview)
        changed_digest = pilot_module._digest(preview)
        with pytest.raises(ValueError, match="announcement preview"):
            await runtime.activate(changed_digest, NOW)

        preview, _ = await runtime.prepare(NOW)
        preview["service_room"] = "d-rosetta-wrong"
        _atomic_json(runtime.preview_path, preview)
        with pytest.raises(ValueError, match="metadata changed"):
            await runtime.activate(pilot_module._digest(preview), NOW)
        runtime.close()
        signer.close()

    asyncio.run(exercise())


class _UncertainClaimTarget(PilotFixtureTarget):
    def __init__(self, owner: str | None) -> None:
        super().__init__()
        self.owner = owner

    def post_signed_note(self, *args: object, **kwargs: object) -> dict[str, bool]:
        if args[0] == "room-owners":
            raise UncertainWrite("synthetic uncertain room claim")
        return super().post_signed_note(*args, **kwargs)

    def read_note(self, namespace: str, key: str) -> str | None:
        if namespace == "room-owners":
            return self.owner
        return super().read_note(namespace, key)


def test_activation_reconciles_only_the_exact_room_owner(tmp_path: Path) -> None:
    async def exercise() -> None:
        for suffix, exact_owner in [("recover", True), ("wrong", False)]:
            root = tmp_path / suffix
            root.mkdir()
            signer = AsyncSigner(root / "signer.sqlite3", f"synthetic-claim-{suffix}")
            target = _UncertainClaimTarget(signer.did if exact_owner else "not-the-owner")
            runtime = PilotRuntime(
                _config(root, signer.did, enabled=True),
                signer=signer,
                target=target,
                clock=lambda: NOW,
            )
            _, digest = await runtime.prepare(NOW)
            if exact_owner:
                activated = await runtime.activate(digest, NOW)
                assert activated["schema"] == "rosetta.pilot-activation.v1"
            else:
                with pytest.raises(UncertainWrite, match="uncertain room claim"):
                    await runtime.activate(digest, NOW)
            runtime.close()
            signer.close()

    asyncio.run(exercise())


class _UncertainAllowTarget(PilotFixtureTarget):
    def __init__(self, allowed: str | None) -> None:
        super().__init__()
        self.allowed = allowed

    def post_signed_note(self, *args: object, **kwargs: object) -> dict[str, bool]:
        if args[0] == "room-allow":
            if self.allowed is not None:
                self.notes[("room-allow", str(args[1]))] = self.allowed
            raise UncertainWrite("synthetic uncertain allow-list")
        return super().post_signed_note(*args, **kwargs)

    def read_note(self, namespace: str, key: str) -> str | None:
        if namespace == "room-allow":
            return self.allowed
        return super().read_note(namespace, key)


def test_activation_reconciles_only_the_exact_room_allow_list(tmp_path: Path) -> None:
    async def exercise() -> None:
        for suffix, exact_value in [("recover", True), ("wrong", False)]:
            root = tmp_path / suffix
            root.mkdir()
            signer = AsyncSigner(root / "signer.sqlite3", f"synthetic-allow-{suffix}")
            target = _UncertainAllowTarget(signer.did if exact_value else "not-allowed")
            runtime = PilotRuntime(
                _config(root, signer.did, enabled=True),
                signer=signer,
                target=target,
                clock=lambda: NOW,
            )
            _, digest = await runtime.prepare(NOW)
            if exact_value:
                activated = await runtime.activate(digest, NOW)
                assert activated["schema"] == "rosetta.pilot-activation.v1"
            else:
                with pytest.raises(UncertainWrite, match="uncertain allow-list"):
                    await runtime.activate(digest, NOW)
            runtime.close()
            signer.close()

    asyncio.run(exercise())


def _request() -> ServiceRequest:
    return ServiceRequest(
        schema="rosetta.request.v1",
        request_id="a" * 32,
        scenario="signed-mailbox-roundtrip-v1",
        producer="python-http",
        consumer="official-mcp",
        target_profile="current",
        reply_room="mb-synthetic-requester",
        expires_at=NOW + timedelta(hours=1),
    )


def test_request_bundle_is_recovered_and_runner_failure_is_evidence(tmp_path: Path) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-bundle-recovery")
        runtime = PilotRuntime(
            _config(tmp_path, signer.did, enabled=True),
            signer=signer,
            target=PilotFixtureTarget(),
            clock=lambda: NOW,
        )

        async def fail_roundtrip(*_args: object, **_kwargs: object) -> object:
            raise OSError("synthetic runner failure")

        original = pilot_module.run_roundtrip
        pilot_module.run_roundtrip = fail_roundtrip  # type: ignore[assignment]
        try:
            root, outcome, bundle = await runtime._build_request_bundle(
                "did:requester", _request(), "job-edge", NOW
            )
        finally:
            pilot_module.run_roundtrip = original
        assert outcome == Outcome.ERROR and bundle.is_dir()
        recovered_root, recovered_outcome, recovered_bundle = await runtime._build_request_bundle(
            "did:requester", _request(), "job-edge", NOW
        )
        assert (recovered_root, recovered_outcome, recovered_bundle) == (root, outcome, bundle)
        runtime.close()
        signer.close()

    asyncio.run(exercise())


def test_execute_marks_failed_job_and_recovery_replays_pending_job(tmp_path: Path) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-job-recovery")
        runtime = PilotRuntime(
            _config(tmp_path, signer.did, enabled=True),
            signer=signer,
            target=PilotFixtureTarget(),
            clock=lambda: NOW,
        )
        request = _request()
        ack = Acknowledgement(request_id=request.request_id, status="accepted", job_id="job-1")
        assert (
            runtime.store.reserve_request(
                "did:requester",
                request.request_id,
                "hash",
                ack.json(),
                NOW,
                2,
                8,
                request.json(by_alias=True),
                max_queue_depth=16,
            )
            == "accepted"
        )

        async def fail_bundle(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("synthetic build failure")

        runtime._build_request_bundle = fail_bundle  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="synthetic build"):
            await runtime._execute(object(), "did:requester", request, "job-1", NOW)  # type: ignore[arg-type]
        assert runtime.store.pending_jobs() == []

        runtime.store.mark_job("did:requester", request.request_id, "accepted", NOW)
        replayed: list[tuple[str, str]] = []

        async def record_execute(
            _gateway: object,
            requester: str,
            recovered: ServiceRequest,
            job_id: str,
            _now: datetime,
        ) -> None:
            replayed.append((requester, job_id))
            assert recovered == request

        runtime._execute = record_execute  # type: ignore[method-assign]
        await runtime._recover(object(), NOW)  # type: ignore[arg-type]
        assert replayed == [("did:requester", "job-1")]

        missing_job_ack = Acknowledgement(request_id="b" * 32, status="accepted")
        second = request.copy(update={"request_id": "b" * 32})
        assert (
            runtime.store.reserve_request(
                "did:second",
                second.request_id,
                "hash-2",
                missing_job_ack.json(),
                NOW,
                2,
                8,
                second.json(by_alias=True),
            )
            == "accepted"
        )
        with pytest.raises(RuntimeError, match="no job id"):
            await runtime._recover(object(), NOW)  # type: ignore[arg-type]
        runtime.store.mark_job("did:second", second.request_id, "failed", NOW)

        third = request.copy(update={"request_id": "c" * 32})
        assert (
            runtime.store.reserve_request(
                "did:third",
                third.request_id,
                "hash-3",
                ack.copy(update={"request_id": third.request_id}).json(),
                NOW,
                2,
                8,
                third.json(by_alias=True),
            )
            == "accepted"
        )
        runtime.store.connection.execute(
            "DELETE FROM service_requests WHERE requester_did='did:third'"
        )
        with pytest.raises(RuntimeError, match="orphan"):
            await runtime._recover(object(), NOW)  # type: ignore[arg-type]
        runtime.close()
        signer.close()

    asyncio.run(exercise())


class _PollingGateway:
    def __init__(self, request: ServiceRequest, *, no_job_id: bool = False) -> None:
        self.request = request
        self.no_job_id = no_job_id

    async def handle_discovery(self, record: ProtocolRecord, _now: datetime) -> object | None:
        return object() if record.text == "offer" else None

    async def accept_request(
        self, record: ProtocolRecord, _now: datetime
    ) -> tuple[ServiceRequest | None, Acknowledgement | None, str]:
        if self.no_job_id:
            return (
                self.request,
                Acknowledgement(request_id=self.request.request_id, status="accepted"),
                "accepted",
            )
        if record.text == "duplicate":
            return (
                self.request,
                Acknowledgement(
                    request_id=self.request.request_id, status="accepted", job_id="job"
                ),
                "duplicate",
            )
        if record.text == "quota":
            return None, None, "quota"
        return None, None, "unsigned"


def test_poll_counts_discovery_rejections_and_requires_job_id(tmp_path: Path) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-poll-edges")
        target = PilotFixtureTarget()
        runtime = PilotRuntime(
            _config(tmp_path, signer.did, enabled=True),
            signer=signer,
            target=target,
            clock=lambda: NOW,
        )
        await runtime.prepare(NOW)
        runtime.activation_path.write_text("{}", encoding="utf-8")
        _, mailbox = service_names(signer.did)
        target.create_room("lobby")
        target.create_room("meta")
        target.create_room(mailbox)
        target._rooms["lobby"].append(  # noqa: SLF001 - deterministic fixture injection
            ProtocolRecord(1, "lobby", "did", 0, "offer", "")
        )
        target._rooms[mailbox].extend(  # noqa: SLF001 - deterministic fixture injection
            [
                ProtocolRecord(1, mailbox, "did", 0, "duplicate", ""),
                ProtocolRecord(2, mailbox, "did", 0, "quota", ""),
                ProtocolRecord(3, mailbox, "did", 0, "unsigned", ""),
            ]
        )
        gateway = _PollingGateway(_request())
        runtime._gateway = lambda _card: gateway  # type: ignore[method-assign]
        assert await runtime.poll_once(NOW) == {"discovery": 1, "requests": 0, "rejected": 1}
        assert runtime.store.room_cursor("lobby") == 1
        assert runtime.store.room_cursor(mailbox) == 3

        target._rooms[mailbox].append(  # noqa: SLF001 - deterministic fixture injection
            ProtocolRecord(4, mailbox, "did", 0, "accepted", "")
        )
        runtime._gateway = lambda _card: _PollingGateway(  # type: ignore[method-assign]
            _request(), no_job_id=True
        )
        with pytest.raises(RuntimeError, match="no job id"):
            await runtime.poll_once(NOW)

        async def stop_after_poll(_now: datetime | None = None) -> dict[str, int]:
            runtime.stop_requested = True
            return {}

        runtime.stop_requested = False
        runtime.poll_once = stop_after_poll  # type: ignore[method-assign]
        await runtime.serve()
        runtime.close()
        signer.close()

    asyncio.run(exercise())


def test_serve_survives_poll_failure_with_fail_closed_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-poll-recovery")
        runtime = PilotRuntime(
            _config(tmp_path, signer.did, enabled=True),
            signer=signer,
            target=PilotFixtureTarget(),
            clock=lambda: NOW,
        )
        calls = 0
        health_transitions: list[str] = []
        write_health = runtime._write_health

        def record_health(status: str, *args: object, **kwargs: object) -> None:
            health_transitions.append(status)
            write_health(status, *args, **kwargs)  # type: ignore[arg-type]

        runtime._write_health = record_health  # type: ignore[method-assign]

        async def poll() -> dict[str, int]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("untrusted public value must not be logged")
            runtime._write_health(
                "healthy",
                NOW,
                {"discovery": 0, "requests": 0, "rejected": 0},
            )
            runtime.stop_requested = True
            return {}

        async def no_wait(_seconds: float) -> None:
            return None

        runtime.poll_once = poll  # type: ignore[method-assign]
        monkeypatch.setattr(pilot_module.asyncio, "sleep", no_wait)
        await runtime.serve()
        assert calls == 2
        assert health_transitions == ["degraded", "healthy"]
        health = json.loads((tmp_path / "state/health.json").read_bytes())
        assert health["status"] == "healthy"
        assert "error_code" not in health
        assert "error_type" not in health
        runtime.close()
        signer.close()

    asyncio.run(exercise())
    error_output = capsys.readouterr().err
    assert '"event": "poll_failed"' in error_output
    assert "untrusted public value" not in error_output


def test_generation_change_resets_cursor_before_processing_recreated_room(
    tmp_path: Path,
) -> None:
    signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-generation-reset")
    target = PilotFixtureTarget()
    runtime = PilotRuntime(
        _config(tmp_path, signer.did, enabled=True),
        signer=signer,
        target=target,
        clock=lambda: NOW,
    )
    runtime.store.advance_room_cursor("lobby", 9)
    runtime.store.set_room_generation("lobby", 1)
    calls: list[int] = []

    def read_room(room: str, *, since: int = 0, limit: int = 100) -> list[ProtocolRecord]:
        assert room == "lobby" and limit == 100
        calls.append(since)
        return []

    target.read_room = read_room  # type: ignore[method-assign]
    target.room_generation = lambda _room: 2  # type: ignore[attr-defined]
    assert runtime._read_generation_safe("lobby") == []
    assert calls == [9, 0]
    assert runtime.store.room_checkpoint("lobby") == (0, 2)
    runtime.close()
    signer.close()


class _CommandRuntime:
    def __init__(self) -> None:
        self.closed = False
        self.stopped = False

    async def prepare(self) -> tuple[dict[str, object], str]:
        return {"safe": True}, "sha256:test"

    async def activate(self, digest: str) -> dict[str, str]:
        return {"activated": digest}

    async def poll_once(self) -> dict[str, int]:
        return {"requests": 0}

    async def serve(self) -> None:
        self.stopped = True

    def request_stop(self, *_args: object) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("command", ["prepare", "activate", "once", "serve", "unknown"])
def test_pilot_command_dispatch_closes_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    runtime = _CommandRuntime()
    monkeypatch.setattr(pilot_module, "load_pilot_config", lambda _path: object())
    monkeypatch.setattr(pilot_module, "PilotRuntime", lambda _config: runtime)
    monkeypatch.setattr(pilot_module.signal, "signal", lambda *_args: None)
    args = argparse.Namespace(
        config=tmp_path / "config.yaml", command=command, approved_digest="ok"
    )
    if command == "unknown":
        with pytest.raises(RuntimeError, match="unknown"):
            asyncio.run(_run(args))
    else:
        result = asyncio.run(_run(args))
        assert result is not None
    assert runtime.closed


def test_pilot_main_prints_machine_readable_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def result(_args: argparse.Namespace) -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(pilot_module, "_run", result)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rosetta-pilot", "--config", str(tmp_path / "pilot.yaml"), "once"],
    )
    pilot_module.main()
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_service_names_remain_protocol_bounded() -> None:
    did = SyntheticIdentity("synthetic-service-name-boundary").did
    room, mailbox = service_names(did)
    assert len(room) <= 48 and len(mailbox) <= 48


def test_service_document_publisher_rejects_every_unapproved_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        signer = AsyncSigner(tmp_path / "signer.sqlite3", "synthetic-publisher-edges")
        runtime = PilotRuntime(
            _config(tmp_path, signer.did, enabled=True),
            signer=signer,
            target=PilotFixtureTarget(),
            clock=lambda: NOW,
        )
        await runtime.prepare(NOW)
        disabled = ServiceDocumentPublisher(
            False, runtime.spool_dir, runtime.static_root, runtime.gate
        )
        with pytest.raises(RuntimeError, match="disabled"):
            disabled.publish(runtime.service_documents, NOW)

        outside = tmp_path / "outside"
        outside.mkdir()
        enabled = ServiceDocumentPublisher(
            True, runtime.spool_dir, runtime.static_root, runtime.gate
        )
        with pytest.raises(ValueError, match="outside"):
            enabled.publish(outside, NOW)

        extra = runtime.service_documents / "unreviewed.txt"
        extra.write_text("not approved", encoding="utf-8")
        with pytest.raises(ValueError, match="not closed"):
            enabled.publish(runtime.service_documents, NOW)
        extra.unlink()

        attestation_path = runtime.service_documents / "service-card.attestation.json"
        original = attestation_path.read_bytes()
        attestation = json.loads(original)
        attestation["service_card_sha256"] = "sha256:" + "0" * 64
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid or expired"):
            enabled.publish(runtime.service_documents, NOW)
        attestation_path.write_bytes(original)

        def fail_fsync(_descriptor: int) -> None:
            raise OSError("synthetic fsync failure")

        monkeypatch.setattr(publishing_module.os, "fsync", fail_fsync)
        with pytest.raises(OSError, match="synthetic fsync"):
            enabled.publish(runtime.service_documents, NOW)
        assert not list(runtime.static_root.glob(".*"))
        runtime.close()
        signer.close()

    asyncio.run(exercise())
