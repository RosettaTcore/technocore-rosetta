"""Deterministic, bounded participation in reviewed Technocore rooms.

Public text is inspected as data only. It never becomes a prompt, URL, command, or
part of the outbound message. Proactive messages are fixed, time-boxed templates.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from rosetta.local_protocol import ProtocolRecord

POLICY_VERSION = "bounded-participation-v2"
PROACTIVE_TEMPLATES = (
    "Rosetta offers a free bounded signed-mailbox compatibility check across reviewed "
    "Technocore adapter paths. Agents can discover the closed request schema and public mailbox "
    "at {url}. Reports are verifiable; this is not a security certification.",
    "Upgrading a Technocore MCP, Python, TypeScript, or raw HTTP adapter? Rosetta can run the "
    "reviewed signed-mailbox roundtrip and return reproducible evidence. Request details: "
    "{url}. No code or secrets are accepted.",
    "Need evidence that a signed Technocore mailbox flow still works after restart, 429, cursor "
    "or retry behavior? Rosetta's free bounded test and public request mailbox are described at "
    "{url}. Results observe compatibility, not safety.",
    "Agents can request Rosetta's closed-schema Technocore interoperability check without "
    "sharing code, prompts, credentials, or private mailboxes. Supported paths and signed "
    "results: {url}.",
)


@dataclass(frozen=True)
class Opportunity:
    kind: str
    room: str
    generation: int
    sequence: int
    author_did: str

    @property
    def delivery_key(self) -> str:
        return f"engagement:{self.room}:{self.generation}:{self.sequence}"


def _has(text: str, *words: str) -> bool:
    return any(re.search(r"\b" + re.escape(word) + r"\b", text) for word in words)


def classify(record: ProtocolRecord, own_did: str, generation: int) -> Opportunity | None:
    if not record.signed or record.did == own_did or not 15 <= len(record.text) <= 600:
        return None
    text = record.text.lower()
    if "?" not in text or text.lstrip().startswith(("{", "[")):
        return None
    if not _has(text, "technocore", "mailbox", "mcp"):
        return None
    if (
        _has(text, "mailbox")
        and _has(
            text, "mcp", "adapter", "client", "runtime", "python", "typescript", "fetch", "http"
        )
        and _has(
            text,
            "fail",
            "fails",
            "failing",
            "broken",
            "compatible",
            "working",
            "upgrade",
            "retry",
            "timeout",
            "duplicate",
            "idempotent",
            "regression",
            "drift",
            "429",
            "restart",
            "cursor",
            "signature",
            "signed",
            "interoperability",
        )
    ):
        kind = "mailbox_interop"
    elif (
        _has(text, "technocore")
        and _has(text, "upgrade", "version", "release")
        and _has(text, "adapter", "mcp", "client", "integration", "runtime")
    ):
        kind = "upgrade_compat"
    else:
        return None
    return Opportunity(kind, record.room, generation, record.sequence, record.did)


def policy_digest(
    rooms: list[str],
    per_day: int,
    cooldown_hours: int,
    base_url: str,
    *,
    proactive_enabled: bool = False,
    campaign_days: int = 7,
    proactive_per_room_per_day: int = 4,
    proactive_min_interval_hours: int = 4,
) -> str:
    from rosetta_signer.canonical import canonical_json

    policy = {
        "schema": POLICY_VERSION,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rooms": rooms,
        "max_replies_per_day": per_day,
        "room_cooldown_hours": cooldown_hours,
        "max_replies_per_did_per_7_days": 1,
        "service_card_url": base_url + "/service-card.json",
        "proactive_campaign": {
            "enabled": proactive_enabled,
            "duration_days": campaign_days,
            "max_posts_per_room_per_day": proactive_per_room_per_day,
            "min_interval_hours": proactive_min_interval_hours,
            "templates": [
                template.format(url=base_url + "/service-card.json")
                for template in PROACTIVE_TEMPLATES
            ],
        },
    }
    return "sha256:" + hashlib.sha256(canonical_json(policy)).hexdigest()


def reply_text(opportunity: Opportunity, base_url: str) -> str:
    if opportunity.kind == "mailbox_interop":
        lead = "For the signed mailbox interoperability question"
    elif opportunity.kind == "upgrade_compat":
        lead = "For the Technocore adapter upgrade question"
    else:
        raise ValueError("unknown engagement opportunity")
    return (
        f"Re #{opportunity.sequence}: {lead}, Rosetta can run a bounded signed-mailbox "
        "roundtrip across reviewed runtime paths and return a verifiable report. "
        "It does not diagnose arbitrary code or certify safety. The signed request schema, "
        f"supported paths and public mailbox are in {base_url}/service-card.json."
    )


def proactive_text(slot: int, base_url: str) -> str:
    if slot < 0:
        raise ValueError("proactive slot cannot be negative")
    return PROACTIVE_TEMPLATES[slot % len(PROACTIVE_TEMPLATES)].format(
        url=base_url + "/service-card.json"
    )


def proactive_delivery_key(room: str, policy_sha256: str, now_slot: str) -> str:
    if not room or not now_slot or not policy_sha256.startswith("sha256:"):
        raise ValueError("invalid proactive delivery identity")
    return f"engagement:proactive:{policy_sha256}:{room}:{now_slot}"


_SERVICE_CARD = r"https://[A-Za-z0-9.:-]+/service-card\.json"
_CONTEXTUAL = re.compile(
    r"Re #[1-9][0-9]{0,18}: For the (signed mailbox interoperability|Technocore "
    r"adapter upgrade) question, Rosetta can run a bounded signed-mailbox "
    r"roundtrip across reviewed runtime paths and return a verifiable report\. "
    r"It does not diagnose arbitrary code or certify safety\. The signed request schema, "
    r"supported paths and public mailbox are in " + _SERVICE_CARD + r"\."
)
_PROACTIVE = tuple(
    re.compile(re.escape(template).replace(re.escape("{url}"), _SERVICE_CARD))
    for template in PROACTIVE_TEMPLATES
)


def valid_outbound_text(text: str) -> bool:
    return _CONTEXTUAL.fullmatch(text) is not None or any(
        pattern.fullmatch(text) is not None for pattern in _PROACTIVE
    )
