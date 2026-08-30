"""Create a consistent plaintext staging snapshot for immediate external encryption."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _copy_regular(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"not_regular_file:{source.name}")
    destination.write_bytes(source.read_bytes())
    os.chmod(destination, 0o600)


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def create_snapshot(
    state_directory: Path,
    evidence_directory: Path,
    destination: Path,
    *,
    now: datetime | None = None,
) -> Path:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    os.chmod(temporary, 0o700)
    try:
        snapshot_state = temporary / "state"
        snapshot_evidence = temporary / "evidence"
        snapshot_state.mkdir(mode=0o700)
        snapshot_evidence.mkdir(mode=0o700)

        source_db = state_directory / "observer.sqlite3"
        if source_db.is_symlink() or not source_db.is_file():
            raise ValueError("observer_database_missing_or_unsafe")
        source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot_state / "observer.sqlite3")
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("snapshot_integrity_failed")
        finally:
            target.close()
            source.close()
        os.chmod(snapshot_state / "observer.sqlite3", 0o600)

        _copy_regular(state_directory / "health.json", snapshot_state / "health.json")
        for source_path in sorted(evidence_directory.iterdir()):
            if source_path.suffix != ".json":
                raise ValueError(f"unexpected_evidence_file:{source_path.name}")
            _copy_regular(source_path, snapshot_evidence / source_path.name)

        files = {}
        for path in sorted(temporary.rglob("*")):
            if path.is_file():
                files[path.relative_to(temporary).as_posix()] = _digest(path)
        manifest = {
            "schema": "rosetta.staging-backup.v1",
            "created_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            "files": files,
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_path, 0o600)
        temporary.replace(destination)
        return destination
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_snapshot(args.state_dir, args.evidence_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
