from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path, PurePosixPath

import yaml

from rosetta.registry import AdapterRegistry

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor/technocore-chat-v0.10.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(path: Path) -> str:
    lines = []
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        lines.append(f"{_sha256(child)}  {child.relative_to(ROOT).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def test_v010_archive_is_exact_safe_and_matches_vendored_source() -> None:
    lock = yaml.safe_load((ROOT / "config/upstream.lock.yaml").read_text())["technocore"]
    archive = (ROOT / lock["source_archive"]).resolve()
    assert ROOT in archive.parents
    assert _sha256(archive) == lock["source_archive_sha256"]
    assert lock["release"] == "v0.10.0"
    assert lock["git_commit"] == "9c7df0e3616cf28d17e7c8ebeb0c05de6adf117c"

    archived: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as source:
        for member in source.getmembers():
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and ".." not in path.parts
            assert path.parts[0] == "technocore-chat-0.10.0"
            assert not member.issym() and not member.islnk()
            if member.isfile():
                stream = source.extractfile(member)
                assert stream is not None
                archived[PurePosixPath(*path.parts[1:]).as_posix()] = stream.read()

    vendored = {
        child.relative_to(VENDOR).as_posix(): child.read_bytes()
        for child in VENDOR.rglob("*")
        if child.is_file()
    }
    required = {"LICENSE", "NOTICE", "src/didkey.py"}
    assert required.issubset(vendored)
    assert any(path.startswith("mcp/src/technocore_mcp/") for path in vendored)
    assert all(archived[path] == content for path, content in vendored.items())
    assert hashlib.sha256(archived["uv.lock"]).hexdigest() == lock["uv_lock_sha256"]


def test_v010_adapter_registry_binds_source_wrapper_and_lock() -> None:
    upstream = yaml.safe_load((ROOT / "config/upstream.lock.yaml").read_text())["technocore"]
    official = AdapterRegistry.load(ROOT / "config/adapters.lock.yaml").require("official-mcp")
    assert official.source_revision == upstream["git_commit"]
    assert official.dependency_lock_sha256 == upstream["uv_lock_sha256"]
    assert official.wrapper_revision_sha256 == _tree_sha256(ROOT / "adapters/official_mcp")
    assert official.transport == "official-mcp-0.10.0+signed-http-boundary"
    assert "/v0.10.0/" in official.source_repository


def test_v010_oci_lock_is_immutable_and_cross_platform() -> None:
    lock = yaml.safe_load((ROOT / "config/upstream.lock.yaml").read_text())["technocore"]
    digests = [lock["oci_index_digest"], *lock["platforms"].values()]
    assert set(lock["platforms"]) == {"linux/amd64", "linux/arm64"}
    assert all(
        digest.startswith("sha256:")
        and len(digest) == 71
        and all(char in "0123456789abcdef" for char in digest.removeprefix("sha256:"))
        for digest in digests
    )
    assert len(set(digests)) == len(digests)
