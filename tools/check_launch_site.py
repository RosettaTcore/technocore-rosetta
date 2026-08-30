#!/usr/bin/env python3
"""Fail-closed structural checks for the static launch observatory."""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from rosetta.evidence import verify_bundle

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HTML = SITE / "index.html"
REFERENCE_ROOT = "sha256:0b3435df9b0f6eb8b1ac2eaab22120a0b14730764fceaa9d1a701860f43c1b9f"


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {key: value or "" for key, value in attrs}))


def _check_local_reference(reference: str) -> None:
    parsed = urlsplit(reference)
    if parsed.scheme in {"http", "https"}:
        return
    if parsed.scheme or parsed.netloc or reference.startswith("//"):
        raise ValueError(f"unsupported resource reference: {reference}")
    if not parsed.path:
        return
    candidate = (SITE / parsed.path).resolve()
    if ROOT not in candidate.parents and candidate != ROOT:
        raise ValueError(f"local reference escapes the repository: {reference}")
    if not candidate.is_file():
        raise ValueError(f"missing local site reference: {reference}")


def main() -> int:
    source = HTML.read_text(encoding="utf-8")
    parser = SiteParser()
    parser.feed(source)

    forbidden_tags = {"form", "iframe", "object", "embed"}
    present_forbidden = sorted({tag for tag, _ in parser.tags} & forbidden_tags)
    if present_forbidden:
        raise ValueError(f"forbidden active site elements: {present_forbidden}")
    if "proton.me" in source.lower() or "mailto:" in source.lower():
        raise ValueError("operator contact details must not be published")
    if REFERENCE_ROOT.removeprefix("sha256:") not in source:
        raise ValueError("the reviewed reference root is absent from the page")

    csp = next(
        (
            attrs.get("content", "")
            for tag, attrs in parser.tags
            if tag == "meta" and attrs.get("http-equiv", "").lower() == "content-security-policy"
        ),
        "",
    )
    required_csp = {
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    }
    missing_csp = sorted(directive for directive in required_csp if directive not in csp)
    if missing_csp:
        raise ValueError(f"launch site CSP is incomplete: {missing_csp}")

    for tag, attrs in parser.tags:
        attribute = "src" if tag in {"script", "img"} else "href" if tag == "link" else None
        if attribute and attrs.get(attribute):
            reference = attrs[attribute]
            if urlsplit(reference).scheme in {"http", "https"}:
                raise ValueError(f"external executable or visual dependency: {reference}")
            _check_local_reference(reference)
        if tag == "a" and attrs.get("href"):
            reference = attrs["href"]
            parsed = urlsplit(reference)
            if parsed.scheme in {"http", "https"} and not (
                parsed.scheme == "https"
                and parsed.netloc == "github.com"
                and parsed.path.startswith("/RosettaTcore/technocore-rosetta")
            ):
                raise ValueError(
                    f"external navigation is outside the reviewed repository: {reference}"
                )
            _check_local_reference(reference)

    script_sources = [attrs.get("src") for tag, attrs in parser.tags if tag == "script"]
    if script_sources != ["app.js"]:
        raise ValueError(f"unexpected script set: {script_sources}")
    if re.search(r"<script(?:\s[^>]*)?>\s*[^<\s]", source, flags=re.IGNORECASE):
        raise ValueError("inline script is forbidden")

    actual_root = verify_bundle(SITE / "evidence/latest")
    if actual_root != REFERENCE_ROOT:
        raise ValueError(f"reference evidence root changed: {actual_root}")
    print(f"launch site structure and evidence verified: {actual_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as error:
        print(f"launch site check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
