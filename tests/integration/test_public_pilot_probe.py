from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from rosetta.cli import _registry, _run_record, _versions
from rosetta.contracts import Acknowledgement, ServiceResult, SignRequest
from rosetta.evidence import build_bundle
from rosetta.public_pilot_probe import PublicPilotProbe, _digest
from rosetta.scenario import run_roundtrip
from rosetta_signer.canonical import canonical_json
from tests.unit.test_pilot_boundaries import _metadata
from tests.unit.test_service_edges import AsyncSigner

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_public_probe_is_digest_gated_and_verifies_the_published_bundle(
    tmp_path: Path,
) -> None:
    async def build_fixtures() -> (
        tuple[AsyncSigner, dict[str, object], dict[str, object], Path, str]
    ):
        from rosetta.service import build_service_card

        registry = _registry()
        signer = AsyncSigner(tmp_path / "service-nonce.sqlite3", "synthetic-public-service")
        card, attestation = await build_service_card(
            signer.did,
            registry,
            signer,
            "https://reports.invalid",
            "v0.13.0",
            NOW,
            tmp_path / "service",
        )
        scenario = await run_roundtrip("python-http", "official-mcp", registry, signer)
        bundle = tmp_path / "bundle"
        root = await build_bundle(
            bundle,
            _run_record(registry, "public-pilot-probe"),
            [scenario],
            _versions(registry),
            signer,
        )
        return signer, card.dict(), attestation, bundle, root

    signer, card, attestation, bundle, root = asyncio.run(build_fixtures())
    posted: list[dict[str, object]] = []
    replies: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.host == "reports.invalid":
            if request.url.path == "/service-card.json":
                return httpx.Response(200, content=canonical_json(card))
            if request.url.path == "/service-card.attestation.json":
                return httpx.Response(200, content=canonical_json(attestation))
            prefix = "/reports/" + root.removeprefix("sha256:") + "/"
            if request.url.path.startswith(prefix):
                relative = request.url.path.removeprefix(prefix)
                path = bundle / relative
                if path.is_file():
                    return httpx.Response(200, content=path.read_bytes())
        if request.url.host == "technocore.chat":
            if request.url.path in {"/healthz", "/.well-known/agent.json", "/openapi.json"}:
                return _metadata(request.url.path)
            if request.method == "POST" and request.url.path == f"/r/{card['request_mailbox']}":
                body = json.loads(request.content)
                posted.append(body)
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "posted": {
                            "seq": 41,
                            "from": body["did"],
                            "nonce": int(body["nonce"]),
                            "text": body["text"],
                            "sig": body["sig"],
                        }
                    },
                )
            if request.method == "GET" and request.url.path.startswith("/r/mb-rosetta-probe-"):
                room = request.url.path.removeprefix("/r/")
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "room": room,
                        "generation": 1,
                        "last_seq": len(replies),
                        "messages": replies,
                    },
                )
        return httpx.Response(404)

    probe = PublicPilotProbe(transport=httpx.MockTransport(upstream))
    preview_path = tmp_path / "preview.json"
    try:
        preview, digest = probe.prepare(
            "https://reports.invalid/service-card.json",
            tmp_path / "peer-state",
            NOW,
        )
        preview_path.write_bytes(canonical_json(preview) + b"\n")
        assert probe.verify(preview_path, digest, NOW) is None
        with pytest.raises(RuntimeError, match="approval digest mismatch"):
            probe.activate(preview_path, "sha256:" + "0" * 64, NOW)

        tampered = deepcopy(preview)
        tampered["expected_automatic_outputs"] = {
            "signed_acknowledgements": 2,
            "signed_results": 1,
            "content_addressed_reports": 1,
        }
        preview_path.write_bytes(canonical_json(tampered) + b"\n")
        with pytest.raises(ValueError, match="scope changed"):
            probe.activate(preview_path, _digest(tampered), NOW)
        preview_path.write_bytes(canonical_json(preview) + b"\n")

        activated = probe.activate(preview_path, digest, NOW)
        assert activated["request_sequence"] == 41
        assert len(posted) == 1
        request_id = str(activated["request_id"])
        reply_room = str(activated["reply_room"])
        job_id = "public-probe-job"
        values = [
            Acknowledgement(request_id=request_id, status="accepted", job_id=job_id, position=1),
            ServiceResult(
                request_id=request_id,
                job_id=job_id,
                outcome="pass",
                bundle_root=root,
                report_url=(
                    "https://reports.invalid/reports/" + root.removeprefix("sha256:") + "/"
                ),
                completed_at=NOW + timedelta(minutes=1),
            ),
        ]
        for sequence, value in enumerate(values, 1):
            text = canonical_json(value.dict()).decode()
            signed = signer.protocol.handle(
                SignRequest(
                    action="technocore_message",
                    scope="public-probe-response",
                    room=reply_room,
                    text=text,
                )
            )
            assert signed.nonce is not None
            replies.append(
                {
                    "seq": sequence,
                    "from": signer.did,
                    "nonce": signed.nonce,
                    "text": text,
                    "sig": signed.signature,
                }
            )

        verified = probe.verify(preview_path, digest, NOW + timedelta(minutes=2))
        assert verified is not None
        assert verified["outcome"] == "pass"
        assert verified["bundle_root"] == root
        assert verified["acknowledgement_sequence"] == 1
        assert verified["result_sequence"] == 2
    finally:
        probe.close()
        signer.close()
