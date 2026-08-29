import asyncio
from pathlib import Path

from rosetta.cli import demo


def test_complete_local_demo(tmp_path: Path) -> None:
    report = asyncio.run(demo(tmp_path / "demo"))
    assert report["all_matrix_cells_pass"]
    assert report["bundle_verified"]
    assert report["deterministic_roots_equal"]
    assert report["regression_reason"] == "canonical_payload_mismatch"
    assert report["service_card_verified"]
    assert report["discovery_offer_received"]
    assert report["request_acknowledged"]
    assert report["signed_result_received"]
    assert report["service_runner_starts"] == 1
    assert report["public_writes"] == 0
