import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import verify_staging_live


def _result(status: str, *, reasons: list[str] | None = None) -> str:
    return json.dumps(
        {
            "schema": "rosetta.staging-status.v2",
            "status": status,
            "reasons": reasons or [],
            "warnings": [],
        }
    )


def test_runtime_status_drops_directly_to_numeric_runtime_identity() -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def runner(parts: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((parts, kwargs))
        return subprocess.CompletedProcess(parts, 0, stdout=_result("pass"), stderr="")

    script = Path("/opt/rosetta/releases/reviewed/tools/staging_status.py")
    status = verify_staging_live.runtime_status(script, runner=runner)

    assert status["status"] == "pass"
    parts, kwargs = calls[0]
    assert parts[0] == "/usr/bin/python3"
    assert parts[1] == str(script)
    assert kwargs["user"] == 65532
    assert kwargs["group"] == 65532
    assert kwargs["extra_groups"] == ()
    assert kwargs["check"] is False
    assert "setpriv" not in parts


def test_runtime_status_surfaces_bounded_stable_failure_reasons() -> None:
    def runner(parts: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        reasons = ["health_stale", "unsafe_check_recorded", *[f"extra_{i}" for i in range(10)]]
        return subprocess.CompletedProcess(
            parts, 1, stdout=_result("fail", reasons=reasons), stderr="ignored"
        )

    with pytest.raises(
        verify_staging_live.VerificationError,
        match=(
            "offline_status_failed:health_stale,unsafe_check_recorded,extra_0,extra_1,"
            "extra_2,extra_3,extra_4,extra_5"
        ),
    ):
        verify_staging_live.runtime_status(Path("status.py"), runner=runner)


@pytest.mark.parametrize(
    ("stdout", "reason"),
    [
        ("not-json", "offline_status_output_invalid"),
        (json.dumps({"schema": "unknown"}), "offline_status_output_invalid"),
        (
            "x" * (verify_staging_live.MAX_STATUS_OUTPUT_BYTES + 1),
            "offline_status_output_oversized",
        ),
    ],
)
def test_runtime_status_rejects_untrusted_output(stdout: str, reason: str) -> None:
    def runner(parts: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(parts, 0, stdout=stdout, stderr="")

    with pytest.raises(verify_staging_live.VerificationError, match=reason):
        verify_staging_live.runtime_status(Path("status.py"), runner=runner)


def test_runtime_status_reports_child_failure_without_trusting_stderr() -> None:
    def runner(parts: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(parts, 1, stdout="", stderr="untrusted detail")

    with pytest.raises(verify_staging_live.VerificationError, match="offline_status_child_failed"):
        verify_staging_live.runtime_status(Path("status.py"), runner=runner)


@pytest.mark.parametrize("error", [PermissionError("blocked"), subprocess.SubprocessError("bad")])
def test_runtime_status_fails_closed_when_child_cannot_start(error: Exception) -> None:
    def runner(*_: Any, **__: Any) -> subprocess.CompletedProcess[str]:
        raise error

    with pytest.raises(verify_staging_live.VerificationError, match="offline_status_unavailable"):
        verify_staging_live.runtime_status(Path("status.py"), runner=runner)
