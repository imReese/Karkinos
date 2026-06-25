"""Acceptance audit routes — /api/acceptance-audits/*"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from analytics.acceptance_audit_report import (
    AUDIT_REGISTRY,
    build_acceptance_audit_export,
)


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/acceptance-audits", tags=["acceptance-audits"])

    @r.get("/{audit_key}")
    async def get_acceptance_audit(audit_key: str) -> dict:
        """Return one read-only acceptance audit manifest for Web/CI review."""
        if audit_key not in AUDIT_REGISTRY:
            raise HTTPException(status_code=404, detail="unknown_acceptance_audit")
        return build_acceptance_audit_export(selected_audit=audit_key)

    return r
