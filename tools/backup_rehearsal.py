"""Synthetic local backup/restore rehearsal with byte-level verification."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
from pathlib import Path


def digest_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def rehearse(source: Path, destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("backup rehearsal destination must be empty")
    backup = destination / "backup"
    restored = destination / "restored"
    backup.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name.endswith(("-wal", "-shm")):
            continue
        relative = path.relative_to(source)
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".sqlite3":
            original = sqlite3.connect(str(path))
            copy = sqlite3.connect(str(target))
            try:
                original.backup(copy)
            finally:
                copy.close()
                original.close()
        else:
            shutil.copy2(path, target)
    shutil.copytree(backup, restored)
    if digest_tree(backup) != digest_tree(restored):
        raise RuntimeError("backup restore digest mismatch")
    (destination / "RESTORE_OK").write_text("synthetic restore verified\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    rehearse(args.source, args.destination)


if __name__ == "__main__":
    main()
