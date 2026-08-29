"""Separate monotonic signer state."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class NonceStore:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS nonce_scopes (
                scope TEXT PRIMARY KEY,
                nonce INTEGER NOT NULL CHECK (nonce > 0)
            );
            CREATE TABLE IF NOT EXISTS sign_events (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                scope_hash TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                nonce INTEGER
            );
            """
        )

    def next(self, scope: str, requested: int | None = None) -> int:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT nonce FROM nonce_scopes WHERE scope = ?", (scope,)
            ).fetchone()
            current = int(row[0]) if row else 0
            candidate = current + 1 if requested is None else requested
            if candidate <= current or candidate < 1 or candidate > 9_999_999_999_999_999_999:
                raise ValueError("nonce is not strictly increasing")
            self.connection.execute(
                "INSERT INTO nonce_scopes(scope, nonce) VALUES (?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET nonce=excluded.nonce",
                (scope, candidate),
            )
            self.connection.execute("COMMIT")
            return candidate
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def record(self, action: str, scope_hash: str, payload_hash: str, nonce: int | None) -> None:
        self.connection.execute(
            "INSERT INTO sign_events(action, scope_hash, payload_hash, nonce) VALUES (?, ?, ?, ?)",
            (action, scope_hash, payload_hash, nonce),
        )

    def close(self) -> None:
        self.connection.close()
