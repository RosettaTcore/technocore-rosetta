"""Atomically activate the operator kill switch at a configured explicit path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    path = args.path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text("stopped by operator\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    print(path)


if __name__ == "__main__":
    main()
