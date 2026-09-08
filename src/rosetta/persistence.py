"""SQLite WAL scheduler, idempotency, quota, and health state."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS run_triggers (
                idempotency_key TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS service_requests (
                requester_did TEXT NOT NULL,
                request_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                acknowledgement TEXT NOT NULL,
                result TEXT,
                created_day TEXT NOT NULL,
                PRIMARY KEY(requester_did, request_id)
            );
            CREATE TABLE IF NOT EXISTS request_quotas (
                quota_day TEXT NOT NULL,
                requester_did TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                PRIMARY KEY(quota_day, requester_did)
            );
            CREATE TABLE IF NOT EXISTS global_quotas (
                quota_day TEXT PRIMARY KEY,
                accepted INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS health_events (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bundle_roots (
                bundle_root TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operation_usage (
                period TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount INTEGER NOT NULL,
                PRIMARY KEY(period, kind)
            );
            CREATE TABLE IF NOT EXISTS component_health (
                component TEXT PRIMARY KEY,
                consecutive_errors INTEGER NOT NULL,
                quarantined INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS protocol_observations (
                protocol_digest TEXT PRIMARY KEY,
                release TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                observation_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observer_checks (
                checked_at TEXT PRIMARY KEY,
                safety_status TEXT NOT NULL CHECK(safety_status IN ('safe', 'unsafe')),
                compatibility_status TEXT NOT NULL,
                reason TEXT,
                public_writes INTEGER NOT NULL CHECK(public_writes = 0)
            );
            CREATE TABLE IF NOT EXISTS room_cursors (
                room TEXT PRIMARY KEY,
                sequence INTEGER NOT NULL CHECK(sequence >= 0),
                generation INTEGER CHECK(generation >= 0)
            );
            CREATE TABLE IF NOT EXISTS outbound_deliveries (
                delivery_key TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                room TEXT NOT NULL,
                did TEXT NOT NULL,
                nonce INTEGER NOT NULL,
                text TEXT NOT NULL,
                signature TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('prepared', 'confirmed')),
                sequence INTEGER
            );
            CREATE TABLE IF NOT EXISTS service_jobs (
                requester_did TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('accepted', 'running', 'complete', 'failed')),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(requester_did, request_id)
            );
            CREATE TABLE IF NOT EXISTS discovery_offers (
                requester_did TEXT NOT NULL,
                request_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_day TEXT NOT NULL,
                PRIMARY KEY(requester_did, request_id)
            );
            """
        )
        cursor_columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(room_cursors)")
        }
        if "generation" not in cursor_columns:
            self.connection.execute("ALTER TABLE room_cursors ADD COLUMN generation INTEGER")

    def register_trigger(self, key: str, now: datetime) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO run_triggers(idempotency_key, created_at) VALUES (?, ?)",
            (key, now.astimezone(timezone.utc).isoformat()),
        )
        return cursor.rowcount == 1

    def reserve_discovery_offer(
        self,
        requester: str,
        request_id: str,
        content_hash: str,
        now: datetime,
        per_did_limit: int = 1,
    ) -> str:
        """Reserve one bounded discovery reply; exact duplicates stay idempotent."""
        day = now.astimezone(timezone.utc).date().isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT content_hash FROM discovery_offers "
                "WHERE requester_did=? AND request_id=?",
                (requester, request_id),
            ).fetchone()
            if existing:
                self.connection.execute("ROLLBACK")
                return "duplicate" if existing[0] == content_hash else "conflict"
            count = self.connection.execute(
                "SELECT COUNT(*) FROM discovery_offers " "WHERE requester_did=? AND created_day=?",
                (requester, day),
            ).fetchone()
            if int(count[0]) >= per_did_limit:
                self.connection.execute("ROLLBACK")
                return "quota"
            self.connection.execute(
                "INSERT INTO discovery_offers VALUES (?, ?, ?, ?)",
                (requester, request_id, content_hash, day),
            )
            self.connection.execute("COMMIT")
            return "accepted"
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def request_status(self, requester: str, request_id: str) -> tuple[str, str, str | None] | None:
        row = self.connection.execute(
            "SELECT content_hash, acknowledgement, result FROM service_requests "
            "WHERE requester_did=? AND request_id=?",
            (requester, request_id),
        ).fetchone()
        return None if row is None else (str(row[0]), str(row[1]), row[2])

    def reserve_request(
        self,
        requester: str,
        request_id: str,
        content_hash: str,
        acknowledgement: str,
        now: datetime,
        per_did_limit: int,
        global_limit: int,
        request_json: str | None = None,
        max_queue_depth: int | None = None,
    ) -> str:
        day = now.astimezone(timezone.utc).date().isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT content_hash FROM service_requests WHERE requester_did=? AND request_id=?",
                (requester, request_id),
            ).fetchone()
            if existing:
                result = "duplicate" if existing[0] == content_hash else "conflict"
                self.connection.execute("ROLLBACK")
                return result
            did_row = self.connection.execute(
                "SELECT accepted FROM request_quotas WHERE quota_day=? AND requester_did=?",
                (day, requester),
            ).fetchone()
            global_row = self.connection.execute(
                "SELECT accepted FROM global_quotas WHERE quota_day=?", (day,)
            ).fetchone()
            did_count = int(did_row[0]) if did_row else 0
            global_count = int(global_row[0]) if global_row else 0
            if did_count >= per_did_limit or global_count >= global_limit:
                self.connection.execute("ROLLBACK")
                return "quota"
            if max_queue_depth is not None:
                queued = self.connection.execute(
                    "SELECT COUNT(*) FROM service_jobs WHERE status IN ('accepted', 'running')"
                ).fetchone()
                if int(queued[0]) >= max_queue_depth:
                    self.connection.execute("ROLLBACK")
                    return "busy"
            self.connection.execute(
                "INSERT INTO service_requests VALUES (?, ?, ?, ?, NULL, ?)",
                (requester, request_id, content_hash, acknowledgement, day),
            )
            if request_json is not None:
                self.connection.execute(
                    "INSERT INTO service_jobs VALUES (?, ?, ?, 'accepted', ?)",
                    (
                        requester,
                        request_id,
                        request_json,
                        now.astimezone(timezone.utc).isoformat(),
                    ),
                )
            self.connection.execute(
                "INSERT INTO request_quotas VALUES (?, ?, 1) "
                "ON CONFLICT(quota_day, requester_did) DO UPDATE SET accepted=accepted+1",
                (day, requester),
            )
            self.connection.execute(
                "INSERT INTO global_quotas VALUES (?, 1) "
                "ON CONFLICT(quota_day) DO UPDATE SET accepted=accepted+1",
                (day,),
            )
            self.connection.execute("COMMIT")
            return "accepted"
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def store_result(self, requester: str, request_id: str, result: str) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "UPDATE service_requests SET result=? WHERE requester_did=? AND request_id=?",
                (result, requester, request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("unknown service request")
            self.connection.execute(
                "UPDATE service_jobs SET status='complete', updated_at=? "
                "WHERE requester_did=? AND request_id=?",
                (datetime.now(timezone.utc).isoformat(), requester, request_id),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def mark_job(self, requester: str, request_id: str, status: str, now: datetime) -> None:
        if status not in {"accepted", "running", "complete", "failed"}:
            raise ValueError("invalid service job state")
        cursor = self.connection.execute(
            "UPDATE service_jobs SET status=?, updated_at=? "
            "WHERE requester_did=? AND request_id=?",
            (status, now.astimezone(timezone.utc).isoformat(), requester, request_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("unknown service job")

    def pending_jobs(self) -> list[tuple[str, str, str, str]]:
        rows = self.connection.execute(
            "SELECT requester_did, request_id, request_json, status FROM service_jobs "
            "WHERE status IN ('accepted', 'running') ORDER BY updated_at, requester_did, request_id"
        ).fetchall()
        return [(str(a), str(b), str(c), str(d)) for a, b, c, d in rows]

    def room_cursor(self, room: str) -> int:
        row = self.connection.execute(
            "SELECT sequence FROM room_cursors WHERE room=?", (room,)
        ).fetchone()
        return int(row[0]) if row else 0

    def room_checkpoint(self, room: str) -> tuple[int, int | None]:
        row = self.connection.execute(
            "SELECT sequence, generation FROM room_cursors WHERE room=?", (room,)
        ).fetchone()
        return (0, None) if row is None else (int(row[0]), None if row[1] is None else int(row[1]))

    def set_room_generation(self, room: str, generation: int, *, reset: bool = False) -> None:
        if generation < 0:
            raise ValueError("room generation cannot be negative")
        sequence = 0 if reset else self.room_cursor(room)
        self.connection.execute(
            "INSERT INTO room_cursors(room, sequence, generation) VALUES (?, ?, ?) "
            "ON CONFLICT(room) DO UPDATE SET sequence=excluded.sequence, "
            "generation=excluded.generation",
            (room, sequence, generation),
        )

    def advance_room_cursor(self, room: str, sequence: int) -> None:
        if sequence < self.room_cursor(room):
            raise ValueError("room cursor cannot move backwards")
        self.connection.execute(
            "INSERT INTO room_cursors(room, sequence) VALUES (?, ?) "
            "ON CONFLICT(room) DO UPDATE SET sequence=MAX(sequence, excluded.sequence)",
            (room, sequence),
        )

    def delivery(
        self, delivery_key: str
    ) -> tuple[str, str, str, int, str, str, str, int | None] | None:
        row = self.connection.execute(
            "SELECT actor, room, did, nonce, text, signature, status, sequence "
            "FROM outbound_deliveries WHERE delivery_key=?",
            (delivery_key,),
        ).fetchone()
        if row is None:
            return None
        return (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            int(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            int(row[7]) if row[7] is not None else None,
        )

    def prepare_delivery(
        self,
        delivery_key: str,
        actor: str,
        room: str,
        did: str,
        nonce: int,
        text: str,
        signature: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO outbound_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', NULL)",
            (delivery_key, actor, room, did, nonce, text, signature),
        )

    def confirm_delivery(self, delivery_key: str, sequence: int) -> None:
        cursor = self.connection.execute(
            "UPDATE outbound_deliveries SET status='confirmed', sequence=? WHERE delivery_key=?",
            (sequence, delivery_key),
        )
        if cursor.rowcount != 1:
            raise ValueError("unknown outbound delivery")

    def record_infrastructure_error(self, category: str, now: datetime) -> None:
        self.connection.execute(
            "INSERT INTO health_events(category, created_at) VALUES (?, ?)",
            (category, now.astimezone(timezone.utc).isoformat()),
        )

    def consecutive_errors(self, category: str) -> int:
        rows = self.connection.execute(
            "SELECT category FROM health_events ORDER BY id DESC LIMIT 100"
        ).fetchall()
        count = 0
        for row in rows:
            if row[0] != category:
                break
            count += 1
        return count

    def register_bundle(self, root: str, path: Path, now: datetime) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO bundle_roots VALUES (?, ?, ?)",
            (root, str(path), now.astimezone(timezone.utc).isoformat()),
        )
        return cursor.rowcount == 1

    def reserve_usage(self, period: str, kind: str, amount: int, limit: int) -> bool:
        if amount < 0 or limit < 0:
            raise ValueError("usage and limit must be non-negative")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT amount FROM operation_usage WHERE period=? AND kind=?", (period, kind)
            ).fetchone()
            current = int(row[0]) if row else 0
            if current + amount > limit:
                self.connection.execute("ROLLBACK")
                return False
            self.connection.execute(
                "INSERT INTO operation_usage VALUES (?, ?, ?) "
                "ON CONFLICT(period, kind) DO UPDATE SET amount=amount+excluded.amount",
                (period, kind, amount),
            )
            self.connection.execute("COMMIT")
            return True
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def usage(self, period: str, kind: str) -> int:
        row = self.connection.execute(
            "SELECT amount FROM operation_usage WHERE period=? AND kind=?", (period, kind)
        ).fetchone()
        return int(row[0]) if row else 0

    def record_component_result(
        self, component: str, success: bool, threshold: int, now: datetime
    ) -> tuple[int, bool]:
        if threshold < 1:
            raise ValueError("quarantine threshold must be positive")
        row = self.connection.execute(
            "SELECT consecutive_errors FROM component_health WHERE component=?", (component,)
        ).fetchone()
        errors = 0 if success else (int(row[0]) if row else 0) + 1
        quarantined = errors >= threshold
        self.connection.execute(
            "INSERT INTO component_health VALUES (?, ?, ?, ?) "
            "ON CONFLICT(component) DO UPDATE SET consecutive_errors=excluded.consecutive_errors, "
            "quarantined=excluded.quarantined, updated_at=excluded.updated_at",
            (component, errors, int(quarantined), now.astimezone(timezone.utc).isoformat()),
        )
        return errors, quarantined

    def component_quarantined(self, component: str) -> bool:
        row = self.connection.execute(
            "SELECT quarantined FROM component_health WHERE component=?", (component,)
        ).fetchone()
        return bool(row and row[0])

    def record_protocol_observation(
        self, protocol_digest: str, release: str, now: datetime
    ) -> bool:
        """Persist a protocol view and return True only when the digest is new."""
        observed_at = now.astimezone(timezone.utc).isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT 1 FROM protocol_observations WHERE protocol_digest=?",
                (protocol_digest,),
            ).fetchone()
            if row:
                self.connection.execute(
                    "UPDATE protocol_observations SET last_seen_at=?, "
                    "observation_count=observation_count+1 WHERE protocol_digest=?",
                    (observed_at, protocol_digest),
                )
                self.connection.execute("COMMIT")
                return False
            self.connection.execute(
                "INSERT INTO protocol_observations VALUES (?, ?, ?, ?, 1)",
                (protocol_digest, release, observed_at, observed_at),
            )
            self.connection.execute("COMMIT")
            return True
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def latest_protocol_observation(self) -> tuple[str, str, str, int] | None:
        row = self.connection.execute(
            "SELECT protocol_digest, release, last_seen_at, observation_count "
            "FROM protocol_observations ORDER BY last_seen_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]), str(row[2]), int(row[3])

    def record_observer_check(
        self,
        now: datetime,
        safety_status: str,
        compatibility_status: str,
        reason: str | None = None,
    ) -> None:
        if safety_status not in {"safe", "unsafe"}:
            raise ValueError("invalid safety status")
        self.connection.execute(
            "INSERT OR REPLACE INTO observer_checks VALUES (?, ?, ?, ?, 0)",
            (
                now.astimezone(timezone.utc).isoformat(),
                safety_status,
                compatibility_status,
                reason,
            ),
        )

    def close(self) -> None:
        self.connection.close()


def trigger_key(protocol_digest: str, registry_digest: str, scenario: str, trigger: str) -> str:
    body = "|".join((protocol_digest, registry_digest, scenario, trigger))
    return hashlib.sha256(body.encode()).hexdigest()
