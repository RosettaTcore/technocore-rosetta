from pathlib import Path

import pytest

from tools.healthchecks_notify import load_ping_url, signal_url


def test_load_ping_url_accepts_only_one_exact_healthchecks_check(tmp_path: Path) -> None:
    check_id = "12345678-1234-1234-1234-123456789abc"
    path = tmp_path / "healthchecks.url"
    path.write_text(f"https://hc-ping.com/{check_id}\n", encoding="utf-8")
    assert load_ping_url(path) == f"https://hc-ping.com/{check_id}"
    assert signal_url(load_ping_url(path), "success") == f"https://hc-ping.com/{check_id}"
    assert signal_url(load_ping_url(path), "fail") == f"https://hc-ping.com/{check_id}/fail"


@pytest.mark.parametrize(
    "value",
    [
        "http://hc-ping.com/12345678123412341234123456789abc",
        "https://example.com/12345678123412341234123456789abc",
        "https://hc-ping.com/12345678123412341234123456789abc?leak=yes",
        "https://hc-ping.com/not-a-check-id",
        "https://hc-ping.com/12345678123412341234123456789abc/fail",
    ],
)
def test_load_ping_url_rejects_broader_or_ambiguous_destinations(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "healthchecks.url"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(ValueError):
        load_ping_url(path)


def test_load_ping_url_rejects_symlink_and_signal_rejects_unknown_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_text("https://hc-ping.com/12345678123412341234123456789abc", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="url_file_not_regular"):
        load_ping_url(link)
    with pytest.raises(ValueError, match="state_rejected"):
        signal_url("https://hc-ping.com/12345678123412341234123456789abc", "start")
