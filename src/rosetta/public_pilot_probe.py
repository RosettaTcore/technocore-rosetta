"""Operator-gated synthetic peer probe for the public Rosetta pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from rosetta.contracts import (
    Acknowledgement,
    ServiceCard,
    ServiceRequest,
    ServiceResult,
    SignRequest,
)
from rosetta.evidence import verify_bundle
from rosetta.service import verify_service_card
from rosetta.technocore_client import TechnocoreHttpClient
from rosetta_signer.canonical import canonical_json, signed_room_payload
from rosetta_signer.did import SyntheticIdentity, did_fingerprint, verify_signature
from rosetta_signer.nonce_store import NonceStore
from rosetta_signer.protocol import SignerProtocol

TECHNOCORE_ORIGIN = "https://technocore.chat"
SYNTHETIC_PEER_ID = "synthetic-public-pilot-peer-v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPORT_PATH = re.compile(
    r"^(run\.json|matrix\.json|summary\.md|evidence/[a-z0-9._-]+\.json|"
    r"reproduce/[a-z0-9._-]+\.(json|txt))$"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


class PublicPilotProbe:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport
        self.web = httpx.Client(
            timeout=20,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"User-Agent": "technocore-rosetta-public-pilot-probe/0.2"},
        )

    def close(self) -> None:
        self.web.close()

    def _json(self, url: str) -> dict[str, Any]:
        response = self.web.get(url)
        if response.is_redirect or response.status_code != 200:
            raise RuntimeError("public_probe_unexpected_status")
        if len(response.content) > 1_048_576:
            raise RuntimeError("public_probe_response_too_large")
        try:
            value = response.json()
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("public_probe_invalid_json") from exc
        if not isinstance(value, dict):
            raise RuntimeError("public_probe_invalid_json_shape")
        return value

    def _load_card(
        self, service_card_url: str, now: datetime
    ) -> tuple[ServiceCard, dict[str, Any], str]:
        parsed = urlparse(service_card_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path != "/service-card.json"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("probe requires an exact HTTPS service-card URL")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        card_raw = self._json(service_card_url)
        attestation = self._json(origin + "/service-card.attestation.json")
        card = ServiceCard.parse_obj(card_raw)
        if not verify_service_card(card, attestation, now):
            raise RuntimeError("public_probe_invalid_service_card")
        if card.status != "available" or card.protocol_baseline != "v0.13.0":
            raise RuntimeError("public_probe_service_unavailable")
        if str(card.request_schema_url) != origin + "/schemas/rosetta-request-v1.json":
            raise RuntimeError("public_probe_request_schema_origin_mismatch")
        if str(card.report_base_url).rstrip("/") != origin + "/reports":
            raise RuntimeError("public_probe_report_origin_mismatch")
        return card, attestation, origin

    def prepare(
        self,
        service_card_url: str,
        state_directory: Path,
        now: datetime | None = None,
    ) -> tuple[dict[str, object], str]:
        current = (now or _now()).astimezone(timezone.utc)
        card, attestation, _origin = self._load_card(service_card_url, current)
        peer = SyntheticIdentity(SYNTHETIC_PEER_ID)
        reply_room = "mb-rosetta-probe-" + did_fingerprint(peer.did)
        expires_at = current + timedelta(minutes=30)
        request_id = hashlib.sha256(
            (
                "rosetta.public-pilot-probe.v1|"
                + peer.did
                + "|"
                + str(attestation["service_card_sha256"])
                + "|"
                + expires_at.isoformat()
            ).encode()
        ).hexdigest()[:32]
        request = ServiceRequest.parse_obj(
            {
                "schema": "rosetta.request.v1",
                "request_id": request_id,
                "scenario": "signed-mailbox-roundtrip-v1",
                "producer": "python-http",
                "consumer": "official-mcp",
                "target_profile": "current",
                "reply_room": reply_room,
                "expires_at": expires_at,
            }
        )
        text = canonical_json(request.dict()).decode()
        state_directory.mkdir(parents=True, exist_ok=True)
        nonce_store = NonceStore(state_directory / "peer-nonce.sqlite3")
        try:
            signed = SignerProtocol(peer, nonce_store).handle(
                SignRequest(
                    action="technocore_message",
                    scope="public-pilot-probe",
                    room=card.request_mailbox,
                    text=text,
                )
            )
        finally:
            nonce_store.close()
        if signed.nonce is None:
            raise RuntimeError("public probe signer omitted nonce")
        preview: dict[str, object] = {
            "schema": "rosetta.public-pilot-probe-preview.v1",
            "technocore_origin": TECHNOCORE_ORIGIN,
            "service_card_url": service_card_url,
            "service_card_sha256": attestation["service_card_sha256"],
            "service_did": card.did,
            "request_mailbox": card.request_mailbox,
            "peer_did": peer.did,
            "reply_room": reply_room,
            "request": request.dict(),
            "write": {
                "method": "POST",
                "path": f"/r/{card.request_mailbox}?format=json",
                "body": {
                    "did": peer.did,
                    "sig": signed.signature,
                    "nonce": str(signed.nonce),
                    "text": text,
                },
            },
            "expected_automatic_outputs": {
                "signed_acknowledgements": 1,
                "signed_results": 1,
                "content_addressed_reports": 1,
            },
        }
        return preview, _digest(preview)

    def _validated_preview(
        self, preview_path: Path, approved_digest: str
    ) -> tuple[dict[str, Any], ServiceRequest, dict[str, Any]]:
        preview = json.loads(preview_path.read_bytes())
        if not isinstance(preview, dict) or preview.get("schema") != (
            "rosetta.public-pilot-probe-preview.v1"
        ):
            raise ValueError("invalid public pilot probe preview")
        if not _DIGEST.fullmatch(approved_digest) or _digest(preview) != approved_digest:
            raise RuntimeError("public pilot probe approval digest mismatch")
        expected = {
            "schema",
            "technocore_origin",
            "service_card_url",
            "service_card_sha256",
            "service_did",
            "request_mailbox",
            "peer_did",
            "reply_room",
            "request",
            "write",
            "expected_automatic_outputs",
        }
        if set(preview) != expected or preview["technocore_origin"] != TECHNOCORE_ORIGIN:
            raise ValueError("public pilot probe preview fields changed")
        request = ServiceRequest.parse_obj(preview["request"])
        peer = SyntheticIdentity(SYNTHETIC_PEER_ID)
        expected_reply_room = "mb-rosetta-probe-" + did_fingerprint(peer.did)
        expected_outputs = {
            "signed_acknowledgements": 1,
            "signed_results": 1,
            "content_addressed_reports": 1,
        }
        if (
            not isinstance(preview["service_card_url"], str)
            or not isinstance(preview["service_did"], str)
            or not isinstance(preview["request_mailbox"], str)
            or preview["peer_did"] != peer.did
            or preview["reply_room"] != expected_reply_room
            or request.reply_room != expected_reply_room
            or request.scenario != "signed-mailbox-roundtrip-v1"
            or request.producer != "python-http"
            or request.consumer != "official-mcp"
            or request.target_profile != "current"
            or preview["expected_automatic_outputs"] != expected_outputs
            or not isinstance(preview["service_card_sha256"], str)
            or not _DIGEST.fullmatch(preview["service_card_sha256"])
        ):
            raise ValueError("public pilot probe scope changed")
        write = preview["write"]
        if not isinstance(write, dict) or set(write) != {"method", "path", "body"}:
            raise ValueError("invalid public pilot probe write")
        body = write["body"]
        if not isinstance(body, dict) or set(body) != {"did", "sig", "nonce", "text"}:
            raise ValueError("invalid public pilot probe body")
        if (
            write["method"] != "POST"
            or write["path"] != f"/r/{preview['request_mailbox']}?format=json"
            or body["did"] != preview["peer_did"]
            or body["text"] != canonical_json(request.dict()).decode()
            or not isinstance(body["nonce"], str)
            or not body["nonce"].isdigit()
            or not verify_signature(
                str(body["did"]),
                signed_room_payload(
                    str(preview["request_mailbox"]), int(body["nonce"]), str(body["text"])
                ),
                str(body["sig"]),
            )
        ):
            raise ValueError("public pilot probe signed bytes changed")
        return preview, request, body

    def activate(
        self,
        preview_path: Path,
        approved_digest: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current = (now or _now()).astimezone(timezone.utc)
        preview, request, body = self._validated_preview(preview_path, approved_digest)
        request.validate_expiry(current)
        card, attestation, _origin = self._load_card(str(preview["service_card_url"]), current)
        if (
            card.did != preview["service_did"]
            or card.request_mailbox != preview["request_mailbox"]
            or attestation["service_card_sha256"] != preview["service_card_sha256"]
        ):
            raise RuntimeError("public pilot probe service metadata changed")
        target = TechnocoreHttpClient(
            TECHNOCORE_ORIGIN,
            TECHNOCORE_ORIGIN,
            "v0.13.0",
            transport=self.transport,
        )
        try:
            target.capabilities()
            record = target.post_signed(
                "public-pilot-probe",
                card.request_mailbox,
                str(body["did"]),
                int(body["nonce"]),
                str(body["text"]),
                str(body["sig"]),
            )
        finally:
            target.close()
        return {
            "schema": "rosetta.public-pilot-probe-activation.v1",
            "request_id": request.request_id,
            "peer_did": preview["peer_did"],
            "reply_room": request.reply_room,
            "request_sequence": record.sequence,
        }

    def _verify_report(self, result: ServiceResult, origin: str) -> str:
        expected_prefix = origin + "/reports/" + result.bundle_root.removeprefix("sha256:") + "/"
        if str(result.report_url) != expected_prefix:
            raise RuntimeError("public_probe_result_url_mismatch")
        checksums_response = self.web.get(expected_prefix + "checksums.txt")
        if checksums_response.status_code != 200 or len(checksums_response.content) > 64_000:
            raise RuntimeError("public_probe_checksums_unavailable")
        lines = checksums_response.text.splitlines()
        paths: list[str] = []
        for line in lines:
            if line.count("  ") != 1:
                raise RuntimeError("public_probe_invalid_checksum_manifest")
            digest, path = line.split("  ", 1)
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or not _REPORT_PATH.fullmatch(path):
                raise RuntimeError("public_probe_invalid_checksum_manifest")
            paths.append(path)
        if not paths or len(paths) != len(set(paths)):
            raise RuntimeError("public_probe_invalid_checksum_manifest")
        with tempfile.TemporaryDirectory(prefix="rosetta-public-probe-") as temporary:
            bundle = Path(temporary)
            (bundle / "checksums.txt").write_bytes(checksums_response.content)
            for path in [*paths, "attestation.json"]:
                response = self.web.get(expected_prefix + path)
                if response.status_code != 200 or len(response.content) > 1_048_576:
                    raise RuntimeError("public_probe_report_file_unavailable")
                destination = bundle / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.content)
            return verify_bundle(bundle)

    def verify(
        self,
        preview_path: Path,
        approved_digest: str,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        current = (now or _now()).astimezone(timezone.utc)
        preview, request, _body = self._validated_preview(preview_path, approved_digest)
        card, attestation, origin = self._load_card(str(preview["service_card_url"]), current)
        if (
            card.did != preview["service_did"]
            or attestation["service_card_sha256"] != preview["service_card_sha256"]
        ):
            raise RuntimeError("public pilot probe service metadata changed")
        target = TechnocoreHttpClient(
            TECHNOCORE_ORIGIN,
            TECHNOCORE_ORIGIN,
            "v0.13.0",
            transport=self.transport,
        )
        try:
            target.capabilities()
            records = target.read_room(request.reply_room, since=0, limit=200)
        finally:
            target.close()
        acknowledgement: tuple[int, Acknowledgement] | None = None
        result: tuple[int, ServiceResult] | None = None
        for record in records:
            if record.did != card.did or not record.signed:
                continue
            try:
                value = json.loads(record.text)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict) or value.get("request_id") != request.request_id:
                continue
            if value.get("schema") == "rosetta.ack.v1":
                acknowledgement = record.sequence, Acknowledgement.parse_obj(value)
            elif value.get("schema") == "rosetta.result.v1":
                result = record.sequence, ServiceResult.parse_obj(value)
        if acknowledgement is None or result is None:
            return None
        ack_sequence, ack = acknowledgement
        result_sequence, service_result = result
        if (
            ack.status != "accepted"
            or ack.job_id is None
            or ack.job_id != service_result.job_id
            or service_result.outcome.value != "pass"
        ):
            raise RuntimeError("public_probe_unsuccessful_service_result")
        verified_root = self._verify_report(service_result, origin)
        return {
            "schema": "rosetta.public-pilot-probe-verification.v1",
            "request_id": request.request_id,
            "peer_did": preview["peer_did"],
            "service_did": card.did,
            "acknowledgement_sequence": ack_sequence,
            "result_sequence": result_sequence,
            "bundle_root": verified_root,
            "outcome": service_result.outcome.value,
            "verified_at": current,
        }


def main() -> None:
    parser = argparse.ArgumentParser(prog="rosetta-public-pilot-probe")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--service-card-url", required=True)
    prepare.add_argument("--state-directory", type=Path, required=True)
    prepare.add_argument("--preview", type=Path, required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--preview", type=Path, required=True)
    activate.add_argument("--approved-digest", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--preview", type=Path, required=True)
    verify.add_argument("--approved-digest", required=True)
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probe = PublicPilotProbe()
    try:
        if args.command == "prepare":
            preview_value, digest = probe.prepare(args.service_card_url, args.state_directory)
            _write_json(args.preview, preview_value)
            print(json.dumps({"preview": str(args.preview), "digest": digest}, sort_keys=True))
        elif args.command == "activate":
            activation_result = probe.activate(args.preview, args.approved_digest)
            print(json.dumps(activation_result, sort_keys=True))
        else:
            verification_result = probe.verify(args.preview, args.approved_digest)
            if verification_result is None:
                print(json.dumps({"status": "pending"}, sort_keys=True))
            else:
                _write_json(args.output, verification_result)
                print(json.dumps(verification_result, sort_keys=True, default=str))
    finally:
        probe.close()


if __name__ == "__main__":
    main()
