from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rosetta.contracts import ServiceRequest, SignRequest
from rosetta.pilot import PilotRuntime
from rosetta.pilot_config import PilotConfig
from rosetta.service import service_names, signed_post
from tests.integration.test_pilot_service import PilotFixtureTarget
from tests.unit.test_service_edges import AsyncSigner

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def _config(tmp_path: Path, did: str) -> PilotConfig:
    return PilotConfig.parse_obj(
        {
            "schema": "rosetta.pilot-config.v1",
            "mode": "pilot",
            "technocore": {"discovery_rooms": ["lobby", "meta"]},
            "identity": {"public_did": did},
            "service": {
                "enabled": True,
                "public_base_url": "https://reports.invalid",
                "state_directory": str(tmp_path / "state"),
                "spool_directory": str(tmp_path / "spool"),
                "static_root": str(tmp_path / "public"),
                "kill_switch_file": str(tmp_path / "KILL_SWITCH"),
            },
            "engagement": {"enabled": True, "rooms": ["lobby", "meta"]},
        }
    )


async def _say(target: PilotFixtureTarget, signer: AsyncSigner, room: str, text: str) -> None:
    signed = await signer.sign(
        SignRequest(action="technocore_message", scope="peer", room=room, text=text)
    )
    assert signed.nonce is not None
    target.post_signed("peer", room, signed.did, signed.nonce, text, signed.signature)


def test_relevant_room_question_gets_one_bounded_signed_reply(tmp_path: Path) -> None:
    async def exercise() -> None:
        rosetta = AsyncSigner(tmp_path / "rosetta.sqlite3", "synthetic-engagement-rosetta")
        peer = AsyncSigner(tmp_path / "peer.sqlite3", "synthetic-engagement-peer")
        other = AsyncSigner(tmp_path / "other.sqlite3", "synthetic-engagement-other")
        target = PilotFixtureTarget()
        runtime = PilotRuntime(
            _config(tmp_path, rosetta.did), signer=rosetta, target=target, clock=lambda: NOW
        )
        pilot_preview, pilot_digest = await runtime.prepare(NOW)
        assert (
            pilot_preview["automatic_behavior_after_activation"]["optional_contextual_replies"][
                "requires_separate_approval"
            ]
            is True
        )
        await runtime.activate(pilot_digest, NOW)
        assert "engagement" not in await runtime.poll_once(NOW)
        preview, engagement_digest = runtime.prepare_engagement()
        assert preview["max_replies_per_day"] == 2
        runtime.activate_engagement(engagement_digest)

        await _say(
            target,
            peer,
            "lobby",
            "How can I check if my signed mailbox MCP adapter still works after a restart?",
        )
        assert (await runtime.poll_once(NOW))["engagement"] == 1
        replies = [r for r in target.read_room("lobby") if r.did == rosetta.did]
        assert len(replies) == 1 and replies[0].signed
        assert "Re #" in replies[0].text
        assert "service-card.json" in replies[0].text
        checkpoint = runtime.store.engagement_checkpoint("lobby")
        assert runtime.activate_engagement(engagement_digest)["preview_sha256"] == engagement_digest
        assert runtime.store.engagement_checkpoint("lobby") == checkpoint
        assert (await runtime.poll_once(NOW))["engagement"] == 0

        _, request_mailbox = service_names(rosetta.did)
        request = ServiceRequest(
            schema="rosetta.request.v1",
            request_id="e" * 32,
            scenario="signed-mailbox-roundtrip-v1",
            producer="python-http",
            consumer="official-mcp",
            target_profile="current",
            reply_room="mb-engagement-peer",
            expires_at=NOW + timedelta(hours=1),
        )
        await signed_post(target, peer, "peer", request_mailbox, request.dict())
        assert (await runtime.poll_once(NOW))["requests"] == 1
        assert len(target.read_room("mb-engagement-peer")) == 2

        await _say(target, other, "lobby", "Will Technocore version upgrade break my MCP adapter?")
        assert (await runtime.poll_once(NOW))["engagement"] == 0  # room cooldown
        await _say(target, other, "meta", "Will Technocore version upgrade break my MCP adapter?")
        assert (await runtime.poll_once(NOW))["engagement"] == 1
        await _say(target, peer, "meta", "Will Technocore version upgrade break my MCP adapter?")
        assert (await runtime.poll_once(NOW))["engagement"] == 0  # per-DID cooldown
        third = AsyncSigner(tmp_path / "third.sqlite3", "synthetic-engagement-third")
        await _say(target, third, "meta", "Will Technocore version upgrade break my MCP adapter?")
        assert (await runtime.poll_once(NOW + timedelta(hours=1)))["engagement"] == 0
        assert (
            len(
                [
                    r
                    for room in ("lobby", "meta")
                    for r in target.read_room(room)
                    if r.did == rosetta.did
                ]
            )
            == 2
        )
        runtime.close()
        rosetta.close()
        peer.close()
        other.close()
        third.close()

    asyncio.run(exercise())


def test_engagement_ignores_old_unsigned_irrelevant_and_policy_drift(tmp_path: Path) -> None:
    async def exercise() -> None:
        rosetta = AsyncSigner(tmp_path / "rosetta.sqlite3", "synthetic-engagement-guard")
        peer = AsyncSigner(tmp_path / "peer.sqlite3", "synthetic-engagement-guard-peer")
        target = PilotFixtureTarget()
        runtime = PilotRuntime(
            _config(tmp_path, rosetta.did), signer=rosetta, target=target, clock=lambda: NOW
        )
        _, digest = await runtime.prepare(NOW)
        await runtime.activate(digest, NOW)
        await _say(
            target,
            peer,
            "lobby",
            "How can I check if my signed mailbox MCP adapter still works after a restart?",
        )
        _, engagement_digest = runtime.prepare_engagement()
        runtime.activate_engagement(engagement_digest)
        assert (await runtime.poll_once(NOW))["engagement"] == 0  # no backlog replies
        await _say(target, peer, "lobby", "How is the weather today?")
        assert (await runtime.poll_once(NOW))["engagement"] == 0
        runtime.config.engagement.room_cooldown_hours = 24
        with pytest.raises(RuntimeError, match="engagement_not_approved"):
            await runtime.poll_once(NOW)
        runtime.close()
        rosetta.close()
        peer.close()

    asyncio.run(exercise())


def test_engagement_uncertain_write_restart_and_kill_switch(tmp_path: Path) -> None:
    async def exercise() -> None:
        rosetta = AsyncSigner(tmp_path / "rosetta.sqlite3", "synthetic-engagement-restart")
        peer = AsyncSigner(tmp_path / "peer.sqlite3", "synthetic-engagement-restart-peer")
        target = PilotFixtureTarget()
        config = _config(tmp_path, rosetta.did)
        runtime = PilotRuntime(config, signer=rosetta, target=target, clock=lambda: NOW)
        _, digest = await runtime.prepare(NOW)
        await runtime.activate(digest, NOW)
        _, engagement_digest = runtime.prepare_engagement()
        runtime.activate_engagement(engagement_digest)
        target.inject_uncertain_write_once("rosetta-engagement", "lobby")
        await _say(
            target,
            peer,
            "lobby",
            "How can I check if my signed mailbox MCP adapter still works after a restart?",
        )
        assert (await runtime.poll_once(NOW))["engagement"] == 1
        assert len([r for r in target.read_room("lobby") if r.did == rosetta.did]) == 1
        runtime.close()
        recovered = PilotRuntime(config, signer=rosetta, target=target, clock=lambda: NOW)
        assert (await recovered.poll_once(NOW))["engagement"] == 0
        assert len([r for r in target.read_room("lobby") if r.did == rosetta.did]) == 1
        (tmp_path / "KILL_SWITCH").touch()
        with pytest.raises(RuntimeError, match="kill_switch_active"):
            await recovered.poll_once(NOW)
        recovered.close()
        rosetta.close()
        peer.close()

    asyncio.run(exercise())
