"""Frozen schema definitions for durable background jobs."""

V13_DURABLE_BACKGROUND_JOBS = (
    """CREATE TABLE job_runs (
        job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
        payload_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
        attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        available_at TEXT NOT NULL, lease_owner TEXT, lease_expires_at TEXT,
        heartbeat_at TEXT, result_ref TEXT, error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(kind, input_fingerprint)
    )""",
    "CREATE INDEX job_claim_idx ON job_runs(kind, status, available_at, lease_expires_at)",
)

__all__ = ["V13_DURABLE_BACKGROUND_JOBS"]
