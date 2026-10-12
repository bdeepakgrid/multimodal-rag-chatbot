"""Durable feedback state and lightweight retrieval feedback signals."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class FeedbackStore:
    def __init__(self, db_path: str | Path = "./data/feedback.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    session_id TEXT,
                    query_text TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('confirmed', 'rejected', 'partial')),
                    chunk_id TEXT NOT NULL,
                    incident_id TEXT,
                    source_file TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_feedback (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    incident_id TEXT,
                    source_file TEXT,
                    state TEXT NOT NULL CHECK (state IN ('awaiting_outcome', 'awaiting_detail')),
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_chunk ON feedback_events (tenant_id, chunk_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_incident ON feedback_events (tenant_id, incident_id)"
            )

    def save_pending(
        self,
        session_id: str,
        tenant_id: str,
        query_text: str,
        chunk_id: str,
        incident_id: str | None,
        source_file: str | None,
        state: str = "awaiting_outcome",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_feedback
                    (session_id, tenant_id, query_text, chunk_id, incident_id, source_file, state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    query_text=excluded.query_text,
                    chunk_id=excluded.chunk_id,
                    incident_id=excluded.incident_id,
                    source_file=excluded.source_file,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (session_id, tenant_id, query_text, chunk_id, incident_id, source_file, state, now),
            )

    def get_pending(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_feedback WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_pending(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_feedback WHERE session_id = ?", (session_id,))

    def record_event(
        self,
        tenant_id: str,
        session_id: str | None,
        query_text: str,
        outcome: str,
        chunk_id: str,
        incident_id: str | None,
        source_file: str | None,
    ) -> None:
        if outcome not in {"confirmed", "rejected", "partial"}:
            raise ValueError(f"Unsupported feedback outcome: {outcome}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_events
                    (tenant_id, session_id, query_text, outcome, chunk_id, incident_id, source_file, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, session_id, query_text, outcome, chunk_id, incident_id, source_file, now),
            )

    def get_chunk_scores(self, tenant_ids: set[str]) -> dict[tuple[str, str], float]:
        """Return durable positive/negative signals for retrieval ranking."""
        if not tenant_ids:
            return {}
        placeholders = ",".join("?" for _ in tenant_ids)
        params = list(tenant_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT tenant_id, chunk_id,
                       SUM(CASE WHEN outcome = 'confirmed' THEN 1.0
                                WHEN outcome = 'rejected' THEN -1.0
                                ELSE 0.0 END) AS score
                FROM feedback_events
                WHERE tenant_id IN ({placeholders})
                GROUP BY tenant_id, chunk_id
                """,
                params,
            ).fetchall()
        return {(row["tenant_id"], row["chunk_id"]): float(row["score"] or 0.0) for row in rows}

