from pathlib import Path

from rosetta.persistence import StateStore
from tools.backup_rehearsal import digest_tree, rehearse


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
