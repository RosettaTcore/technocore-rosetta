"""Deterministic, narrowly scoped replies to relevant Technocore questions.

Public text is inspected as data only. It never becomes a prompt, URL, command, or
part of the outbound message. False negatives are preferable to unsolicited noise.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from rosetta.local_protocol import ProtocolRecord

POLICY_VERSION = "contextual-replies-v1"


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


def policy_digest(rooms: list[str], per_day: int, cooldown_hours: int, base_url: str) -> str:
    from rosetta_signer.canonical import canonical_json

    policy = {
        "schema": POLICY_VERSION,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rooms": rooms,
        "max_replies_per_day": per_day,
        "room_cooldown_hours": cooldown_hours,
        "max_replies_per_did_per_7_days": 1,
        "service_card_url": base_url + "/service-card.json",
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
