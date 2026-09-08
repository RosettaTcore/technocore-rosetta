from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rosetta.contracts import ServiceRequest
from rosetta.evidence import verify_bundle
from rosetta.local_protocol import LocalTechnocore
from rosetta.pilot import PilotRuntime
from rosetta.pilot_config import PilotConfig
from rosetta.service import service_names, signed_post
from rosetta_signer.canonical import signed_note_payload
from rosetta_signer.did import verify_signature
from tests.unit.test_service_edges import AsyncSigner

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class PilotFixtureTarget(LocalTechnocore):
    release = "v0.13.0"

    def __init__(self) -> None:
        super().__init__()
        self.notes: dict[tuple[str, str], str] = {}

    def close(self) -> None:
        return None

    def post_signed_note(
        self,
        namespace: str,
        key: str,
        did: str,
        nonce: int,
        value: str,
        signature: str,
        *,
        if_absent: bool = False,
    ) -> dict[str, bool]:
        assert verify_signature(did, signed_note_payload(namespace, key, nonce, value), signature)
        location = (namespace, key)
        if if_absent and location in self.notes:
            raise RuntimeError("already claimed")
        self.notes[location] = value
        return {"stored": True}

    def read_note(self, namespace: str, key: str) -> str | None:
        return self.notes.get((namespace, key))


def test_complete_active_pilot_request_to_signed_published_result(tmp_path: Path) -> None:
    async def exercise() -> None:
        rosetta = AsyncSigner(tmp_path / "rosetta-nonce.sqlite3", "synthetic-live-pilot")
        peer = AsyncSigner(tmp_path / "peer-nonce.sqlite3", "synthetic-live-peer")
        service_room, request_mailbox = service_names(rosetta.did)
        config = PilotConfig.parse_obj(
            {
                "schema": "rosetta.pilot-config.v1",
                "mode": "pilot",
                "technocore": {
                    "authority_origin": "https://technocore.chat",
                    "fetch_origin": "https://fetch.invalid",
                    "discovery_rooms": ["lobby"],
                },
                "identity": {
                    "public_did": rosetta.did,
                    "signer_socket": str(tmp_path / "signer.sock"),
                },
                "service": {
                    "enabled": True,
                    "public_base_url": "https://reports.invalid",
                    "state_directory": str(tmp_path / "state"),
                    "spool_directory": str(tmp_path / "spool"),
                    "static_root": str(tmp_path / "public"),
                    "kill_switch_file": str(tmp_path / "KILL_SWITCH"),
                },
            }
        )
        target = PilotFixtureTarget()
        runtime = PilotRuntime(config, signer=rosetta, target=target, clock=lambda: NOW)
        preview, digest = await runtime.prepare(NOW)
        assert preview["service_room"] == service_room
        assert len(preview["writes"]) == 2
        activated = await runtime.activate(digest, NOW)
        assert activated["request_mailbox"] == request_mailbox
        reply = "mb-synthetic-peer"
        target.create_room(reply)
        request = ServiceRequest(
            schema="rosetta.request.v1",
            request_id="a" * 32,
            scenario="signed-mailbox-roundtrip-v1",
            producer="python-http",
            consumer="official-mcp",
            target_profile="current",
            reply_room=reply,
            expires_at=NOW + timedelta(hours=1),
        )
        await signed_post(target, peer, "peer", request_mailbox, request.dict())
        counts = await runtime.poll_once(NOW)
        assert counts == {"discovery": 0, "requests": 1, "rejected": 0}
        messages = target.read_room(reply)
        assert len(messages) == 2 and all(message.signed for message in messages)
        result = json.loads(messages[-1].text)
        root = result["bundle_root"]
        published = tmp_path / "public/reports" / root.removeprefix("sha256:")
        assert verify_bundle(published) == root
        assert json.loads((tmp_path / "state/health.json").read_bytes())["status"] == "healthy"
        runtime.close()
        rosetta.close()
        peer.close()

    asyncio.run(exercise())
