"""Fixed quality gate baked into the immutable evolution evaluator image."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

CANDIDATE = Path("/candidate")
MAX_TAIL = 2_000
TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".env", ""}
PRIVATE_MARKERS = [
    "BEGIN " + "OPENSSH PRIVATE KEY",
    "BEGIN " + "PRIVATE KEY",
    "BEGIN " + "EC PRIVATE KEY",
    "BEGIN " + "RSA PRIVATE KEY",
]
ASSIGNMENT = re.compile(r"^(?:MODEL_API_KEY|PUBLISHER_CREDENTIAL|.*TOKEN|.*SECRET)=(.+)$")


def _result(name: str, exit_code: int, output: str) -> dict[str, object]:
    normalized = output.replace(str(CANDIDATE), "<candidate>")
    return {
        "name": name,
        "passed": exit_code == 0,
        "exit_code": exit_code,
        "output_sha256": "sha256:" + hashlib.sha256(normalized.encode()).hexdigest(),
        "output_tail": normalized[-MAX_TAIL:],
    }


def _run(name: str, command: list[str]) -> dict[str, object]:
    env = {
        "HOME": "/tmp/home",  # noqa: S108 - evaluator has an isolated tmpfs
        "COVERAGE_FILE": "/tmp/coverage-data",  # noqa: S108 - isolated tmpfs
        "LANG": "C.UTF-8",
        "MYPY_CACHE_DIR": "/tmp/mypy",  # noqa: S108 - evaluator has an isolated tmpfs
        "RUFF_CACHE_DIR": "/tmp/ruff",  # noqa: S108 - evaluator has an isolated tmpfs
        "PYTHONPATH": str(CANDIDATE / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ["PATH"],
    }
    completed = subprocess.run(  # noqa: S603 - commands are constants baked into the image
        command,
        cwd=CANDIDATE,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return _result(name, completed.returncode, completed.stdout + completed.stderr)


def _secret_gate() -> dict[str, object]:
    findings: list[str] = []
    for path in sorted(CANDIDATE.rglob("*")):
        relative = path.relative_to(CANDIDATE)
        if relative.parts and relative.parts[0] == "local":
            continue
        if path.is_symlink():
            findings.append(f"{relative}: symbolic link forbidden")
            continue
        if not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in PRIVATE_MARKERS:
            if marker in text:
                findings.append(f"{relative}: private key marker")
        for number, line in enumerate(text.splitlines(), 1):
            match = ASSIGNMENT.match(line.strip())
            if match and match.group(1).strip() not in {"", "disabled", "UNCONFIGURED"}:
                findings.append(f"{relative}:{number}: populated credential-like variable")
    output = "\n".join(findings) if findings else "fixed secret and symlink scan passed"
    return _result("secrets", 1 if findings else 0, output)


def main() -> None:
    source_roots = [
        "src",
        "tests",
        "tools",
        "adapters/python_http",
        "adapters/official_mcp",
    ]
    gates = [
        _run("format", ["ruff", "format", "--check", *source_roots]),
        _run("lint", ["ruff", "check", *source_roots]),
        _run("types", ["mypy", "--config-file", "pyproject.toml", "src"]),
        _run(
            "tests",
            [
                "python",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp=/candidate/local/evaluator-pytest",
                "--cov=rosetta",
                "--cov=rosetta_signer",
                "--cov-report=term",
                "--cov-fail-under=90",
                "tests",
            ],
        ),
        _run(
            "typescript",
            [
                "/opt/evaluator/node_modules/.bin/tsc",
                "--noEmit",
                "--project",
                "adapters/tsconfig.json",
                "--typeRoots",
                "/opt/evaluator/node_modules/@types",
            ],
        ),
        _secret_gate(),
    ]
    print(json.dumps({"schema": "rosetta.evolution-gates.v1", "gates": gates}, sort_keys=True))
    raise SystemExit(0 if all(bool(item["passed"]) for item in gates) else 1)


if __name__ == "__main__":
    main()
