"""Composition helpers for persisted, read-only AI context capture."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from server.ai_runtime.capture import (
    CaptureSelectionError,
    ContextCaptureAuditStore,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.karkinos_source import (
    CaptureProjectionReaders,
    PersistedKarkinosCaptureSource,
)
from server.ai_runtime.store import AiAuditStore
from server.db import AppDatabase
from server.dependencies import AppState
from server.persistence.database_identity import require_database_path


def build_human_context_capture_service(
    state: AppState,
    *,
    projection_readers: CaptureProjectionReaders,
) -> HumanResearchContextCaptureService:
    """Build the audit-only capture service from explicit projection ports."""
    db_path = database_path(state.db)
    evidence_repository = CanonicalEvidenceRepository(db_path)
    context_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    evidence_repository.init()
    context_store.init()
    capture_store.init()
    return HumanResearchContextCaptureService(
        source=PersistedKarkinosCaptureSource(state, projection_readers),
        evidence_repository=evidence_repository,
        context_store=context_store,
        capture_store=capture_store,
        now=utc_now,
    )


def database_path(db: AppDatabase | None) -> Path:
    return require_database_path(
        db,
        CaptureSelectionError("database path is unavailable"),
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
