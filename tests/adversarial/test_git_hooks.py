import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRE_PUSH_HOOK = PROJECT_ROOT / ".githooks" / "pre-push"


def _invoke_pre_push(remote_ref: str) -> subprocess.CompletedProcess[str]:
    update = f"refs/heads/topic {'1' * 40} {remote_ref} {'2' * 40}\n"
    return subprocess.run(  # noqa: S603 - fixed repository-owned hook under test
        [str(PRE_PUSH_HOOK), "origin", "git@example.invalid:owner/repository.git"],
        input=update,
        text=True,
        capture_output=True,
        check=False,
    )


def test_pre_push_hook_blocks_direct_main_updates() -> None:
    result = _invoke_pre_push("refs/heads/main")

    assert result.returncode == 1
    assert "Direct pushes to main are blocked" in result.stderr


def test_pre_push_hook_allows_feature_branches() -> None:
    result = _invoke_pre_push("refs/heads/ci-guard-test")

    assert result.returncode == 0
    assert result.stderr == ""
