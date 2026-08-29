"""Fixed-origin client for the containerized local Technocore fixture."""

from __future__ import annotations

from urllib.parse import quote, urlparse

import httpx

from rosetta.local_protocol import ProtocolRecord, RateLimited, UncertainWrite


class HttpTechnocore:
    release = "v0.7.0"

    def __init__(self, base_url: str, image_digest: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "technocore-local",
        }:
            raise ValueError("container fixture must use an approved local-only HTTP origin")
        if (
            parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("target must be a fixed origin")
        if not image_digest.startswith("sha256:") or len(image_digest) != 71:
            raise ValueError("target image must be an immutable sha256 digest")
        self.base_url = base_url.rstrip("/")
        self.image_digest = image_digest
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(2),
            follow_redirects=False,
            trust_env=False,
        )
        health = self.client.get("/health")
        health.raise_for_status()
        if health.json() != {"release": self.release, "status": "ok"}:
            raise ValueError("unexpected local target identity")

    def _post_fixture(self, path: str, body: dict[str, object]) -> None:
        response = self.client.post(path, json=body)
        response.raise_for_status()

    def inject_rate_limit_once(self, actor: str, room: str) -> None:
        self._post_fixture("/_fixture/rate-limit", {"actor": actor, "room": room})

    def inject_uncertain_write_once(self, actor: str, room: str) -> None:
        self._post_fixture("/_fixture/uncertain-write", {"actor": actor, "room": room})

    def capabilities(self) -> dict[str, object]:
        response = self.client.get("/capabilities")
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("invalid capability response")
        return result

    def create_room(self, room: str) -> None:
        self._post_fixture("/_fixture/rooms", {"room": room})

    def read_room(self, room: str, *, since: int = 0, limit: int = 100) -> list[ProtocolRecord]:
        response = self.client.get(
            f"/rooms/{quote(room, safe='')}", params={"since": since, "limit": limit}
        )
        response.raise_for_status()
        records = response.json().get("records")
        if not isinstance(records, list):
            raise ValueError("invalid record response")
        return [ProtocolRecord(**item) for item in records]

    def post_signed(
        self,
        actor: str,
        room: str,
        did: str,
        nonce: int,
        text: str,
        signature: str,
    ) -> ProtocolRecord:
        response = self.client.post(
            f"/rooms/{quote(room, safe='')}/signed",
            json={
                "actor": actor,
                "did": did,
                "nonce": nonce,
                "text": text,
                "signature": signature,
            },
        )
        if response.status_code == 429:
            raise RateLimited(int(response.headers.get("Retry-After", "1")))
        if response.status_code == 599:
            raise UncertainWrite("container target committed before simulated disconnect")
        response.raise_for_status()
        return ProtocolRecord(**response.json())

    def close(self) -> None:
        self.client.close()
