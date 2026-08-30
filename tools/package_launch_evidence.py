#!/usr/bin/env python3
"""Build or verify the deterministic public reference-evidence archive."""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site/evidence/latest"
TARGET = ROOT / "site/evidence/rosetta-v0.10.0-reference.zip"
FIXED_TIME = (2026, 8, 31, 0, 0, 0)


def _archive_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(SOURCE.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"reference evidence must not contain symlinks: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(SOURCE).as_posix()
            info = zipfile.ZipInfo(f"rosetta-v0.10.0-reference/{relative}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if the checked-in archive differs"
    )
    args = parser.parse_args()
    expected = _archive_bytes()
    if args.check:
        if not TARGET.is_file() or TARGET.read_bytes() != expected:
            raise SystemExit("launch evidence archive is missing or non-deterministic")
        print(f"launch evidence archive verified: {TARGET.relative_to(ROOT)}")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(expected)
    print(f"wrote deterministic launch evidence archive: {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
