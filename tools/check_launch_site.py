#!/usr/bin/env python3
"""Fail-closed structural checks for the static launch observatory."""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from rosetta.evidence import verify_bundle

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HTML = SITE / "index.html"
README = ROOT / "README.md"
MANIFEST = SITE / "site.webmanifest"
MARK = SITE / "assets/rosetta-mark.svg"
PREVIEW = SITE / "assets/rosetta-observatory-preview.webp"
SOCIAL_CARD = SITE / "assets/rosetta-social-card.jpg"
PROFILE_AVATAR = SITE / "assets/rosetta-profile-avatar.png"
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
    if len([tag for tag, _ in parser.tags if tag == "h1"]) != 1:
        raise ValueError("launch page must contain exactly one h1")
    if source.count("data-verify-hosted") < 3:
        raise ValueError(
            "instant hosted verification must be available from every primary proof path"
        )
    if source.count("data-hosted-status") != 1:
        raise ValueError("launch page must expose exactly one hosted-verification status indicator")
    if "Verify the live reference. No download." not in source:
        raise ValueError("the launch page must lead with no-download verification")
    html_attributes = next((attrs for tag, attrs in parser.tags if tag == "html"), {})
    if html_attributes.get("lang") != "en":
        raise ValueError("launch page language must be English")

    meta = {
        attrs.get("property") or attrs.get("name"): attrs.get("content", "")
        for tag, attrs in parser.tags
        if tag == "meta" and (attrs.get("property") or attrs.get("name"))
    }
    required_meta = {
        "description",
        "robots",
        "og:title",
        "og:description",
        "og:image",
        "og:image:width",
        "og:image:height",
        "og:image:alt",
        "twitter:card",
        "twitter:title",
        "twitter:description",
        "twitter:image",
        "twitter:image:alt",
    }
    missing_meta = sorted(required_meta - meta.keys())
    if missing_meta:
        raise ValueError(f"launch metadata is incomplete: {missing_meta}")
    if meta["og:image"] != "assets/rosetta-social-card.jpg":
        raise ValueError("unexpected Open Graph image")
    if meta["twitter:image"] != meta["og:image"]:
        raise ValueError("Open Graph and Twitter preview images must match")

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
        "connect-src 'self'",
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
        if tag == "meta" and (
            attrs.get("property") == "og:image" or attrs.get("name") == "twitter:image"
        ):
            _check_local_reference(attrs.get("content", ""))
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
    if script_sources != ["app.js?v=20260901b"]:
        raise ValueError(f"unexpected script set: {script_sources}")
    if re.search(r"<script(?:\s[^>]*)?>\s*[^<\s]", source, flags=re.IGNORECASE):
        raise ValueError("inline script is forbidden")
    if "rosetta-observatory-preview.png" in source:
        raise ValueError("the unoptimized source artwork must not be loaded by the page")

    for required_file in (MANIFEST, MARK, PREVIEW, SOCIAL_CARD, PROFILE_AVATAR):
        if not required_file.is_file():
            raise ValueError(f"missing launch asset: {required_file.relative_to(ROOT)}")
    if PREVIEW.stat().st_size > 100_000:
        raise ValueError("optimized hero artwork exceeds 100 KB")
    if SOCIAL_CARD.stat().st_size > 200_000:
        raise ValueError("social preview artwork exceeds 200 KB")
    if PROFILE_AVATAR.stat().st_size > 1_000_000:
        raise ValueError("profile avatar exceeds 1 MB")
    avatar_header = PROFILE_AVATAR.read_bytes()[:24]
    if avatar_header[:8] != b"\x89PNG\r\n\x1a\n" or avatar_header[12:16] != b"IHDR":
        raise ValueError("profile avatar must be a valid PNG")
    avatar_dimensions = (
        int.from_bytes(avatar_header[16:20], "big"),
        int.from_bytes(avatar_header[20:24], "big"),
    )
    if avatar_dimensions != (800, 800):
        raise ValueError(f"unexpected profile avatar dimensions: {avatar_dimensions}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("name") != "Technocore Rosetta":
        raise ValueError("unexpected web manifest product name")
    if manifest.get("start_url") != "." or manifest.get("scope") != ".":
        raise ValueError("web manifest must remain relocatable")
    icons = manifest.get("icons")
    if not isinstance(icons, list) or not icons or icons[0].get("src") != "assets/rosetta-mark.svg":
        raise ValueError("web manifest must use the reviewed Rosetta mark")

    readme = README.read_text(encoding="utf-8")
    readme_requirements = {
        "site/assets/rosetta-social-card.jpg",
        "## See the proof first",
        "## Why workflow-level evidence",
        "No language model",
        "## Audit and feedback",
    }
    missing_readme = sorted(value for value in readme_requirements if value not in readme)
    if missing_readme:
        raise ValueError(f"README launch narrative is incomplete: {missing_readme}")

    for reference in re.findall(r"!?\[[^]]*\]\(([^)]+)\)", readme):
        parsed = urlsplit(reference)
        if parsed.scheme in {"http", "https"} or not parsed.path:
            continue
        candidate = (ROOT / parsed.path).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            raise ValueError(f"README reference escapes the repository: {reference}")
        if not candidate.exists():
            raise ValueError(f"missing README reference: {reference}")

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
