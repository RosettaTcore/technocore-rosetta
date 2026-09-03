import io
import json
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

from tools import release_package

COMMIT = "a" * 40
PREVIOUS = "b" * 40
TREE = "c" * 40


def _run(*parts: str, cwd: Path | None = None) -> None:
    subprocess.run(  # noqa: S603 - test supplies only fixed local commands
        parts, cwd=cwd, check=True, capture_output=True
    )


def _archive(path: Path, *, unsafe: bool = False) -> None:
    with tarfile.open(path, "w:gz") as archive:
        files = {
            "deploy/compose.staging.yaml": b"services: {}\n",
            "deploy/rosetta-upgrade-apply.sh": b"#!/bin/sh\nexit 0\n",
        }
        if unsafe:
            files["../escape"] = b"bad"
        for name, body in files.items():
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if name.endswith(".sh") else 0o644
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))


def _manifest(archive: Path) -> dict[str, object]:
    return {
        "schema": release_package.SCHEMA,
        "repository": release_package.REPOSITORY,
        "commit": COMMIT,
        "tree": TREE,
        "previous_commit": PREVIOUS,
        "archive_sha256": release_package.file_sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "created_at": "2026-09-02T12:00:00+00:00",
        "deployment_profile": "read-only-observer",
    }


def _incoming(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    archive = incoming / "release.tar.gz"
    _archive(archive)
    manifest = _manifest(archive)
    (incoming / "release-manifest.json").write_bytes(
        release_package.canonical_json(manifest) + b"\n"
    )
    (incoming / "release-manifest.json.sig").write_bytes(b"synthetic-signature")
    return incoming, manifest


def test_manifest_requires_exact_canonical_closed_schema(tmp_path: Path) -> None:
    incoming, manifest = _incoming(tmp_path)
    path = incoming / "release-manifest.json"
    assert release_package.load_canonical_manifest(path) == manifest

    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest_not_canonical"):
        release_package.load_canonical_manifest(path)

    manifest["unexpected"] = True
    with pytest.raises(ValueError, match="invalid_manifest_fields"):
        release_package.validate_manifest(manifest)


def test_prepare_release_archives_commit_and_signs_manifest(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run("/usr/bin/git", "init", "--quiet", cwd=repository)
    (repository / "deploy").mkdir()
    (repository / "deploy/compose.staging.yaml").write_text("services: {}\n")
    apply_script = repository / "deploy/rosetta-upgrade-apply.sh"
    apply_script.write_text("#!/bin/sh\nexit 0\n")
    apply_script.chmod(0o755)
    _run("/usr/bin/git", "add", ".", cwd=repository)
    _run(
        "/usr/bin/git",
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release@example.invalid",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "--quiet",
        "-m",
        "release",
        cwd=repository,
    )
    key = tmp_path / "release-key"
    _run("/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))

    output = tmp_path / "package"
    manifest = release_package.prepare_release(repository, "HEAD", PREVIOUS, output, key)
    assert manifest["previous_commit"] == PREVIOUS
    assert release_package.load_canonical_manifest(output / "release-manifest.json") == manifest
    assert release_package.validate_archive(output / "release.tar.gz")

    allowed = tmp_path / "allowed-signers"
    allowed.write_text(
        f"{release_package.PRINCIPAL} {key.with_suffix('.pub').read_text().strip()}\n"
    )
    subprocess.run(  # noqa: S603 - fixed local signature verification
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(allowed),
            "-I",
            release_package.PRINCIPAL,
            "-n",
            release_package.NAMESPACE,
            "-s",
            str(output / "release-manifest.json.sig"),
        ],
        input=(output / "release-manifest.json").read_bytes(),
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("schema", "v2", "invalid_manifest_schema"),
        ("repository", "someone/else", "invalid_repository"),
        ("commit", "main", "invalid_commit"),
        ("tree", "z" * 40, "invalid_tree"),
        ("previous_commit", "a" * 39, "invalid_previous_commit"),
        ("archive_sha256", "0" * 63, "invalid_archive_sha256"),
        ("archive_bytes", True, "invalid_archive_bytes"),
        ("archive_bytes", 0, "archive_size_out_of_bounds"),
        ("deployment_profile", "publisher", "invalid_deployment_profile"),
        ("created_at", "not-a-time", "Invalid isoformat"),
    ],
)
def test_manifest_rejects_invalid_authority_fields(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    incoming, manifest = _incoming(tmp_path)
    manifest[field] = value
    with pytest.raises(ValueError, match=reason):
        release_package.validate_manifest(manifest)


def test_archive_rejects_path_escape_and_non_regular_input(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe.tar.gz"
    _archive(unsafe, unsafe=True)
    with pytest.raises(ValueError, match="unsafe_archive_path"):
        release_package.validate_archive(unsafe)

    source = tmp_path / "source"
    source.write_bytes(b"content")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(OSError):
        release_package.copy_regular(link, tmp_path / "copy", 100)


def test_extract_archive_normalizes_runtime_modes_under_restrictive_umask(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "release.tar.gz"
    _archive(archive)
    destination = tmp_path / "release"
    previous_umask = os.umask(0o077)
    try:
        release_package.extract_archive(archive, destination)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o755
    assert stat.S_IMODE((destination / "deploy").stat().st_mode) == 0o755
    assert stat.S_IMODE((destination / "deploy/rosetta-upgrade-apply.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((destination / "deploy/compose.staging.yaml").stat().st_mode) == 0o644


def test_stage_requires_signed_digest_and_exact_previous_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming, manifest = _incoming(tmp_path)
    releases = tmp_path / "releases"
    releases.mkdir()
    previous = releases / PREVIOUS
    previous.mkdir()
    current = tmp_path / "current"
    current.symlink_to(previous)
    allowed = tmp_path / "allowed-signers"
    allowed.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(release_package.os, "geteuid", lambda: 0)
    monkeypatch.setattr(release_package, "verify_signature", lambda *args, **kwargs: None)
    calls: list[list[str]] = []

    def runner(parts: list[str], **_: object) -> object:
        calls.append(parts)
        return object()

    result = release_package.stage_release(
        incoming, allowed, current, releases, tmp_path / "work", runner=runner
    )
    assert result["status"] == "pass"
    assert result["commit"] == COMMIT
    assert calls[0][0].endswith("deploy/rosetta-upgrade-apply.sh")
    assert (releases / COMMIT / ".rosetta-release").is_file()

    manifest["archive_sha256"] = "0" * 64
    (incoming / "release-manifest.json").write_bytes(
        release_package.canonical_json(manifest) + b"\n"
    )
    with pytest.raises(ValueError, match="archive_digest_mismatch"):
        release_package.stage_release(
            incoming, allowed, current, releases, tmp_path / "work-2", runner=runner
        )


def test_stage_fails_closed_on_wrong_current_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming, _ = _incoming(tmp_path)
    releases = tmp_path / "releases"
    releases.mkdir()
    wrong = releases / ("f" * 40)
    wrong.mkdir()
    current = tmp_path / "current"
    current.symlink_to(wrong)
    allowed = tmp_path / "allowed-signers"
    allowed.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(release_package.os, "geteuid", lambda: 0)
    monkeypatch.setattr(release_package, "verify_signature", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="previous_commit_mismatch"):
        release_package.stage_release(
            incoming, allowed, current, releases, tmp_path / "work", runner=lambda *a, **k: object()
        )


def test_failed_apply_removes_inactive_release_for_safe_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming, _ = _incoming(tmp_path)
    releases = tmp_path / "releases"
    releases.mkdir()
    previous = releases / PREVIOUS
    previous.mkdir()
    current = tmp_path / "current"
    current.symlink_to(previous)
    allowed = tmp_path / "allowed-signers"
    allowed.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(release_package.os, "geteuid", lambda: 0)
    monkeypatch.setattr(release_package, "verify_signature", lambda *args, **kwargs: None)

    def fail_apply(*_: object, **__: object) -> object:
        raise subprocess.CalledProcessError(1, "apply")

    with pytest.raises(subprocess.CalledProcessError):
        release_package.stage_release(
            incoming, allowed, current, releases, tmp_path / "work", runner=fail_apply
        )
    assert not (releases / COMMIT).exists()
