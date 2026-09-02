#!/usr/bin/env python3
"""Send a bounded success/failure signal to one Healthchecks.io check."""

from __future__ import annotations

import argparse
import http.client
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

MAX_URL_BYTES = 512
CHECK_ID = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def validate_ping_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "hc-ping.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("url_origin_rejected")
    check_id = parsed.path.removeprefix("/")
    if CHECK_ID.fullmatch(check_id) is None:
        raise ValueError("check_id_rejected")
    return urlunsplit(("https", "hc-ping.com", f"/{check_id}", "", ""))


def load_ping_url(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("url_file_not_regular")
    if path.stat().st_size > MAX_URL_BYTES:
        raise ValueError("url_file_oversized")
    return validate_ping_url(path.read_text(encoding="utf-8").strip())


def signal_url(base_url: str, state: str) -> str:
    if state == "success":
        return base_url
    if state == "fail":
        return f"{base_url}/fail"
    raise ValueError("state_rejected")


def send_signal(base_url: str, state: str) -> None:
    target = urlsplit(signal_url(validate_ping_url(base_url), state))
    connection = http.client.HTTPSConnection("hc-ping.com", timeout=10)
    try:
        connection.request("POST", target.path, body=b"")
        response = connection.getresponse()
        response.read(1024)
        if response.status not in {200, 204}:
            raise RuntimeError("unexpected_status")
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-file", type=Path, required=True)
    parser.add_argument("--state", choices=("success", "fail"), default="success")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        base_url = load_ping_url(args.url_file)
        if not args.check_only:
            send_signal(base_url, args.state)
    except (http.client.HTTPException, OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"healthchecks_notification_failed:{type(exc).__name__}")
        return 1
    print("healthchecks_notification=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
