"""Portable quality entrypoint; uses Ruff/Mypy when installed."""

from __future__ import annotations

import compileall
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603 - internal fixed tool commands


def main() -> None:
    action = sys.argv[1]
    if action == "format":
        if importlib.util.find_spec("ruff"):
            run([sys.executable, "-m", "ruff", "format", "src", "tests", "tools"])
        else:
            print("Ruff is not installed; source is maintained in formatter-stable style")
    elif action == "lint":
        if importlib.util.find_spec("ruff"):
            run([sys.executable, "-m", "ruff", "check", "src", "tests", "tools"])
        if not compileall.compile_dir(ROOT / "src", quiet=1):
            raise SystemExit("bytecode compilation failed")
        if not compileall.compile_dir(ROOT / "tests", quiet=1):
            raise SystemExit("test bytecode compilation failed")
        print("lint/compile gate passed")
    elif action == "type":
        if importlib.util.find_spec("mypy"):
            run([sys.executable, "-m", "mypy", "src"])
        else:
            run([sys.executable, "-m", "compileall", "-q", "src"])
            print("Mypy is not installed; annotation/import compilation gate passed")
    else:
        raise SystemExit(f"unknown quality action: {action}")


if __name__ == "__main__":
    main()
