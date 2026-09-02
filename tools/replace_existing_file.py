#!/usr/bin/env python3
"""Replace the contents of one pre-existing protected regular file."""

from __future__ import annotations

import argparse
import os
import stat
from collections.abc import Sequence
from pathlib import Path

MAX_SOURCE_BYTES = 64 * 1024


def _open_flags(access: int) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise RuntimeError("nofollow_open_unavailable")
    return access | no_follow | getattr(os, "O_CLOEXEC", 0)


def _validate_file(
    metadata: os.stat_result,
    *,
    expected_uid: int,
    expected_gid: int,
    label: str,
) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise RuntimeError(f"unsafe_{label}")


def replace_existing_file(
    source: Path,
    destination: Path,
    *,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> None:
    """Copy bounded content without creating, linking or renaming the destination."""
    source_fd = os.open(source, _open_flags(os.O_RDONLY))
    try:
        source_stat = os.fstat(source_fd)
        _validate_file(
            source_stat,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            label="source",
        )
        if source_stat.st_size <= 0 or source_stat.st_size > MAX_SOURCE_BYTES:
            raise RuntimeError("source_size_out_of_bounds")
        chunks: list[bytes] = []
        remaining = source_stat.st_size
        while remaining:
            chunk = os.read(source_fd, remaining)
            if not chunk:
                raise RuntimeError("short_source_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
    finally:
        os.close(source_fd)

    destination_fd = os.open(destination, _open_flags(os.O_RDWR))
    try:
        destination_stat = os.fstat(destination_fd)
        _validate_file(
            destination_stat,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            label="destination",
        )
        os.ftruncate(destination_fd, 0)
        written = 0
        while written < len(content):
            count = os.write(destination_fd, content[written:])
            if count <= 0:
                raise RuntimeError("short_destination_write")
            written += count
        os.fsync(destination_fd)
        os.lseek(destination_fd, 0, os.SEEK_SET)
        if os.read(destination_fd, len(content) + 1) != content:
            raise RuntimeError("destination_verification_failed")
    finally:
        os.close(destination_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise PermissionError("root_required")
    replace_existing_file(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
