from datetime import datetime, timezone
from pathlib import Path

import pytest

from rosetta.operations import redact, require_operational
from rosetta.persistence import StateStore, trigger_key

NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def test_trigger_deduplication_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    first = StateStore(path)
    assert first.register_trigger("same", NOW)
    first.close()
    second = StateStore(path)
    assert not second.register_trigger("same", NOW)
    second.close()


def test_transactional_request_idempotency_conflict_and_quota(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    assert store.reserve_request("did:a", "1", "hash-a", "ack", NOW, 1, 2) == "accepted"
    assert store.reserve_request("did:a", "1", "hash-a", "ack", NOW, 1, 2) == "duplicate"
    assert store.reserve_request("did:a", "1", "hash-b", "ack", NOW, 1, 2) == "conflict"
    assert store.reserve_request("did:a", "2", "hash-c", "ack", NOW, 1, 2) == "quota"
    assert store.reserve_request("did:b", "1", "hash-b", "ack", NOW, 1, 2) == "accepted"
    assert store.reserve_request("did:c", "1", "hash-c", "ack", NOW, 1, 2) == "quota"
    store.close()


def test_kill_switch_and_redaction(tmp_path: Path) -> None:
    switch = tmp_path / "KILL_SWITCH"
    require_operational(switch)
    switch.write_text("stop")
    try:
        require_operational(switch)
        raise AssertionError("kill switch did not stop operation")
    except RuntimeError as exc:
        assert str(exc) == "kill_switch_active"
    redacted = redact({"Authorization": "Bearer abc", "url": "https://evil.invalid/a", "ok": "x"})
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["url"] == "[REDACTED_URL]"


def test_persistence_indexes_health_and_usage_edges(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    assert store.request_status("did:a", "missing") is None
    assert store.reserve_request("did:a", "1", "hash", "ack", NOW, 2, 2) == "accepted"
    assert store.request_status("did:a", "1") == ("hash", "ack", None)
    store.store_result("did:a", "1", "result")
    assert store.request_status("did:a", "1") == ("hash", "ack", "result")

    store.record_infrastructure_error("network", NOW)
    store.record_infrastructure_error("network", NOW)
    assert store.consecutive_errors("network") == 2
    store.record_infrastructure_error("other", NOW)
    assert store.consecutive_errors("network") == 0

    assert store.register_bundle("sha256:one", tmp_path / "bundle", NOW)
    assert not store.register_bundle("sha256:one", tmp_path / "bundle", NOW)
    assert store.usage("2026-08", "cost") == 0
    assert store.reserve_usage("2026-08", "cost", 2, 3)
    assert store.usage("2026-08", "cost") == 2
    assert not store.reserve_usage("2026-08", "cost", 2, 3)
    with pytest.raises(ValueError, match="non-negative"):
        store.reserve_usage("2026-08", "cost", -1, 3)

    with pytest.raises(ValueError, match="positive"):
        store.record_component_result("runner", False, 0, NOW)
    assert store.record_component_result("runner", False, 2, NOW) == (1, False)
    assert store.record_component_result("runner", False, 2, NOW) == (2, True)
    assert store.component_quarantined("runner")
    assert store.record_component_result("runner", True, 2, NOW) == (0, False)
    assert not store.component_quarantined("runner")
    assert not store.component_quarantined("missing")
    store.close()


def test_trigger_key_is_stable_and_input_sensitive() -> None:
    first = trigger_key("protocol", "registry", "scenario", "release")
    assert first == trigger_key("protocol", "registry", "scenario", "release")
    assert first != trigger_key("protocol-2", "registry", "scenario", "release")
