#!/usr/bin/env python3
"""Prepare and verify signed, immutable Rosetta release packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCHEMA = "rosetta.release-package.v1"
NAMESPACE = "rosetta-release-v1"
PRINCIPAL = "rosetta-release"
REPOSITORY = "RosettaTcore/technocore-rosetta"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 10_000
OID = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FIELDS = {
    "schema",
    "repository",
    "commit",
    "tree",
    "previous_commit",
    "archive_sha256",
    "archive_bytes",
    "created_at",
    "deployment_profile",
}
Runner = Callable[..., subprocess.CompletedProcess[str]]


def canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("invalid_manifest_fields")
    manifest = dict(value)
    if manifest["schema"] != SCHEMA:
        raise ValueError("invalid_manifest_schema")
    if manifest["repository"] != REPOSITORY:
        raise ValueError("invalid_repository")
    for field in ("commit", "tree", "previous_commit"):
        if not isinstance(manifest[field], str) or OID.fullmatch(manifest[field]) is None:
            raise ValueError(f"invalid_{field}")
    archive_digest = manifest["archive_sha256"]
    if not isinstance(archive_digest, str) or DIGEST.fullmatch(archive_digest) is None:
        raise ValueError("invalid_archive_sha256")
    archive_bytes = manifest["archive_bytes"]
    if not isinstance(archive_bytes, int) or isinstance(archive_bytes, bool):
        raise ValueError("invalid_archive_bytes")
    if archive_bytes <= 0 or archive_bytes > MAX_ARCHIVE_BYTES:
        raise ValueError("archive_size_out_of_bounds")
    if manifest["deployment_profile"] != "read-only-observer":
        raise ValueError("invalid_deployment_profile")
    created_at = manifest["created_at"]
    if not isinstance(created_at, str):
        raise ValueError("invalid_created_at")
    timestamp = datetime.fromisoformat(created_at)
    if timestamp.tzinfo is None:
        raise ValueError("created_at_not_aware")
    return manifest


def load_canonical_manifest(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) > 16 * 1024:
        raise ValueError("manifest_too_large")
    value = json.loads(raw)
    manifest = validate_manifest(value)
    if raw != canonical_json(manifest) + b"\n":
        raise ValueError("manifest_not_canonical")
    return manifest


def validate_archive(path: Path) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    names: set[str] = set()
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if len(members) >= MAX_MEMBERS:
                raise ValueError("too_many_archive_members")
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or not pure.parts or ".." in pure.parts:
                raise ValueError("unsafe_archive_path")
            normalized = str(pure)
            if normalized in names:
                raise ValueError("duplicate_archive_path")
            if not (member.isdir() or member.isfile()):
                raise ValueError("unsupported_archive_member")
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise ValueError("archive_member_size_out_of_bounds")
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError("archive_expansion_out_of_bounds")
            names.add(normalized)
            members.append(member)
    required = {"deploy/compose.staging.yaml", "deploy/rosetta-upgrade-apply.sh"}
    if not required.issubset(names):
        raise ValueError("required_release_file_missing")
    return members


def extract_archive(path: Path, destination: Path) -> None:
    members = validate_archive(path)
    destination.mkdir(mode=0o755)
    with tarfile.open(path, "r:gz") as archive:
        for member in members:
            pure = PurePosixPath(member.name)
            target = destination.joinpath(*pure.parts)
            if member.isdir():
                target.mkdir(mode=member.mode & 0o755, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("archive_member_unreadable")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o755)


def verify_signature(
    manifest: Path,
    signature: Path,
    allowed_signers: Path,
    *,
    runner: Runner = subprocess.run,
) -> None:
    signer_stat = allowed_signers.lstat()
    if not stat.S_ISREG(signer_stat.st_mode) or signer_stat.st_uid != 0:
        raise ValueError("unsafe_allowed_signers_file")
    if signer_stat.st_mode & 0o022:
        raise ValueError("writable_allowed_signers_file")
    with manifest.open("rb") as stream:
        runner(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(allowed_signers),
                "-I",
                PRINCIPAL,
                "-n",
                NAMESPACE,
                "-s",
                str(signature),
            ],
            stdin=stream,
            check=True,
            text=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )


def copy_regular(source: Path, destination: Path, limit: int) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("nofollow_open_unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptor = os.open(source, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("unsafe_incoming_file")
        if metadata.st_size <= 0 or metadata.st_size > limit:
            raise ValueError("incoming_file_size_out_of_bounds")
        with os.fdopen(descriptor, "rb", closefd=False) as input_stream:
            with destination.open("xb") as output:
                shutil.copyfileobj(input_stream, output)
                output.flush()
                os.fsync(output.fileno())
        destination.chmod(0o400)
    finally:
        os.close(descriptor)


def _git(repository: Path, *arguments: str) -> str:
    # Arguments are generated by the release tool, never by a public request.
    return subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def prepare_release(
    repository: Path,
    ref: str,
    previous_commit: str,
    output: Path,
    signing_key: Path,
) -> dict[str, object]:
    if OID.fullmatch(previous_commit) is None:
        raise ValueError("invalid_previous_commit")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("output_directory_not_empty")
    output.mkdir(parents=True, exist_ok=True)
    commit = _git(repository, "rev-parse", f"{ref}^{{commit}}")
    tree = _git(repository, "rev-parse", f"{commit}^{{tree}}")
    if OID.fullmatch(commit) is None or OID.fullmatch(tree) is None:
        raise ValueError("invalid_git_object")
    archive = output / "release.tar.gz"
    subprocess.run(  # noqa: S603 - fixed Git archive operation on an operator-selected ref
        [
            "/usr/bin/git",
            "-C",
            str(repository),
            "archive",
            "--format=tar.gz",
            "--output",
            str(archive),
            commit,
        ],
        check=True,
    )
    validate_archive(archive)
    manifest: dict[str, object] = {
        "schema": SCHEMA,
        "repository": REPOSITORY,
        "commit": commit,
        "tree": tree,
        "previous_commit": previous_commit,
        "archive_sha256": file_sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deployment_profile": "read-only-observer",
    }
    manifest_path = output / "release-manifest.json"
    manifest_path.write_bytes(canonical_json(manifest) + b"\n")
    subprocess.run(  # noqa: S603 - fixed ssh-keygen signing operation
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(signing_key),
            "-n",
            NAMESPACE,
            str(manifest_path),
        ],
        check=True,
    )
    return manifest


def stage_release(
    incoming: Path,
    allowed_signers: Path,
    current_link: Path,
    release_root: Path,
    work_root: Path,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    if os.geteuid() != 0:
        raise PermissionError("upgrade_gate_requires_root")
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="release-", dir=work_root))
    try:
        archive = work / "release.tar.gz"
        manifest_path = work / "release-manifest.json"
        signature = work / "release-manifest.json.sig"
        copy_regular(incoming / archive.name, archive, MAX_ARCHIVE_BYTES)
        copy_regular(incoming / manifest_path.name, manifest_path, 16 * 1024)
        copy_regular(incoming / signature.name, signature, 64 * 1024)
        manifest = load_canonical_manifest(manifest_path)
        verify_signature(manifest_path, signature, allowed_signers, runner=runner)
        if archive.stat().st_size != manifest["archive_bytes"]:
            raise ValueError("archive_size_mismatch")
        if file_sha256(archive) != manifest["archive_sha256"]:
            raise ValueError("archive_digest_mismatch")
        current = current_link.resolve(strict=True)
        expected_current = release_root / str(manifest["previous_commit"])
        if current != expected_current:
            raise ValueError("previous_commit_mismatch")
        commit = str(manifest["commit"])
        destination = release_root / commit
        temporary = release_root / f".{commit}.incoming"
        if destination.exists() or temporary.exists():
            raise FileExistsError("release_already_staged")
        extract_archive(archive, temporary)
        (temporary / ".rosetta-release").write_bytes(canonical_json(manifest) + b"\n")
        temporary.rename(destination)
        apply_script = destination / "deploy/rosetta-upgrade-apply.sh"
        try:
            runner(
                [str(apply_script), str(destination), commit, str(manifest["previous_commit"])],
                check=True,
            )
        except Exception:
            # A clean rollback makes the exact signed package safely retryable. Preserve a release
            # that is still active so a partial rollback can never delete running code.
            if current_link.resolve(strict=False) != destination:
                shutil.rmtree(destination, ignore_errors=True)
            raise
        return {
            "schema": "rosetta.release-stage-result.v1",
            "status": "pass",
            "commit": commit,
            "previous_commit": manifest["previous_commit"],
            "archive_sha256": manifest["archive_sha256"],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release_package")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--repository", type=Path, required=True)
    prepare.add_argument("--ref", required=True)
    prepare.add_argument("--previous-commit", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--signing-key", type=Path, required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--incoming", type=Path, required=True)
    stage.add_argument("--allowed-signers", type=Path, required=True)
    stage.add_argument("--current-link", type=Path, required=True)
    stage.add_argument("--release-root", type=Path, required=True)
    stage.add_argument("--work-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare_release(
            args.repository, args.ref, args.previous_commit, args.output, args.signing_key
        )
    else:
        result = stage_release(
            args.incoming,
            args.allowed_signers,
            args.current_link,
            args.release_root,
            args.work_root,
        )
    print(canonical_json(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
