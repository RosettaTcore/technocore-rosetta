import json
from datetime import datetime, timezone
from pathlib import Path

from rosetta.persistence import StateStore
from tools.backup_rehearsal import digest_tree, rehearse
from tools.staging_backup import create_snapshot


def test_synthetic_backup_restore(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    store = StateStore(source / "state.sqlite3")
    store.close()
    (source / "evidence.json").write_text('{"synthetic":true}\n')
    destination = tmp_path / "rehearsal"
    rehearse(source, destination)
    assert (destination / "RESTORE_OK").read_text() == "synthetic restore verified\n"
    assert digest_tree(destination / "backup") == digest_tree(destination / "restored")


def test_staging_snapshot_uses_sqlite_backup_and_manifest(tmp_path: Path) -> None:
    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    state.mkdir()
    evidence.mkdir()
    store = StateStore(state / "observer.sqlite3")
    store.record_protocol_observation(
        "sha256:" + "b" * 64,
        "0.10.0",
        datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    store.close()
    (state / "health.json").write_text('{"status":"healthy"}\n', encoding="utf-8")
    (evidence / "observation.json").write_text('{"public_writes":0}\n', encoding="utf-8")

    destination = tmp_path / "snapshot"
    create_snapshot(
        state,
        evidence,
        destination,
        now=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "rosetta.staging-backup.v1"
    assert set(manifest["files"]) == {
        "evidence/observation.json",
        "state/health.json",
        "state/observer.sqlite3",
    }
