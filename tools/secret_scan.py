"""Fail on committed private-key material or populated credential templates."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".env", ""}
PRIVATE_MARKERS = [
    "BEGIN " + "OPENSSH PRIVATE KEY",
    "BEGIN " + "PRIVATE KEY",
    "BEGIN " + "EC PRIVATE KEY",
    "BEGIN " + "RSA PRIVATE KEY",
]
ASSIGNMENT = re.compile(r"^(?:MODEL_API_KEY|PUBLISHER_CREDENTIAL|.*TOKEN|.*SECRET)=(.+)$")


def tracked_and_untracked_files() -> list[Path]:
    output = subprocess.check_output(  # noqa: S603 - fixed read-only Git invocation
        ["/usr/bin/git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    )
    return [ROOT / line for line in output.splitlines() if line]


def main() -> None:
    findings: list[str] = []
    for path in tracked_and_untracked_files():
        if not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT)
        for marker in PRIVATE_MARKERS:
            if marker in text:
                findings.append(f"{relative}: private key marker")
        for line_number, line in enumerate(text.splitlines(), 1):
            match = ASSIGNMENT.match(line.strip())
            if match and match.group(1).strip() not in {"", "disabled", "UNCONFIGURED"}:
                findings.append(f"{relative}:{line_number}: populated credential-like variable")
    if findings:
        raise SystemExit("\n".join(findings))
    print(f"secret scan passed ({len(tracked_and_untracked_files())} files)")


if __name__ == "__main__":
    main()
