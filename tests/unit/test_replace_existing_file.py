import os
from pathlib import Path

import pytest

from tools.replace_existing_file import MAX_SOURCE_BYTES, main, replace_existing_file


def _private_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    path.chmod(0o600)


def _replace(source: Path, destination: Path) -> None:
    replace_existing_file(
        source,
        destination,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def test_replaces_contents_without_replacing_destination_inode(tmp_path: Path) -> None:
    source = tmp_path / "new.env"
    destination = tmp_path / "staging.env"
    _private_file(source, b"ROSETTA_IMAGE=sha256:new\n")
    _private_file(destination, b"ROSETTA_IMAGE=sha256:old\n")
    inode = destination.stat().st_ino

    _replace(source, destination)

    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_ino == inode
    assert destination.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("content", [b"", b"x" * (MAX_SOURCE_BYTES + 1)])
def test_rejects_unbounded_source(tmp_path: Path, content: bytes) -> None:
    source = tmp_path / "new.env"
    destination = tmp_path / "staging.env"
    _private_file(source, content)
    _private_file(destination, b"old\n")

    with pytest.raises(RuntimeError, match="source_size_out_of_bounds"):
        _replace(source, destination)

    assert destination.read_bytes() == b"old\n"


def test_rejects_linked_or_overexposed_files(tmp_path: Path) -> None:
    source = tmp_path / "new.env"
    destination = tmp_path / "staging.env"
    second_link = tmp_path / "second-link.env"
    _private_file(source, b"new\n")
    _private_file(destination, b"old\n")
    os.link(destination, second_link)

    with pytest.raises(RuntimeError, match="unsafe_destination"):
        _replace(source, destination)

    second_link.unlink()
    source.chmod(0o640)
    with pytest.raises(RuntimeError, match="unsafe_source"):
        _replace(source, destination)


def test_rejects_symlink_destination(tmp_path: Path) -> None:
    source = tmp_path / "new.env"
    target = tmp_path / "target.env"
    destination = tmp_path / "staging.env"
    _private_file(source, b"new\n")
    _private_file(target, b"old\n")
    destination.symlink_to(target)

    with pytest.raises(OSError):
        _replace(source, destination)

    assert target.read_bytes() == b"old\n"


def test_cli_requires_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError, match="root_required"):
        main([str(tmp_path / "source"), str(tmp_path / "destination")])
