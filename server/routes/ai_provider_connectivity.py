"""Explicit operator-triggered external AI provider connectivity route."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.provider_connectivity import (
    ConnectivityCheckRequest,
    ConnectivityConfigurationError,
    ConnectivityStatus,
    ProviderConnectivityAuditStore,
    ProviderConnectivityService,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.bootstrap import resolve_config_path


class HumanProviderConnectivityCheckPayload(BaseModel):
    """One human-authorized, non-financial external model probe."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=128)
    confirmation: Literal[
        "run_external_ai_connectivity_check_without_financial_context"
    ]


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/ai/provider-connectivity", tags=["ai-research"])

    @router.post("/checks")
    async def run_provider_connectivity_check(
        payload: HumanProviderConnectivityCheckPayload,
    ) -> JSONResponse:
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        try:
            service = build_provider_connectivity_service(state)
            result = await asyncio.to_thread(
                service.run,
                ConnectivityCheckRequest(
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    confirmation=payload.confirmation,
                ),
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ConnectivityConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        status_code = {
            ConnectivityStatus.PASSED: 200,
            ConnectivityStatus.RUNNING: 202,
            ConnectivityStatus.FAILED: 502,
        }[result.status]
        return JSONResponse(status_code=status_code, content=result.to_dict())

    return router


def build_provider_connectivity_service(state) -> ProviderConnectivityService:
    """Build the explicit network probe on AI-only audit tables."""
    db_path = _database_path(state.db)
    settings = load_provider_connectivity_settings(resolve_config_path())
    ai_store = AiAuditStore(db_path)
    audit_store = ProviderConnectivityAuditStore(db_path)
    ai_store.init()
    audit_store.init()
    return ProviderConnectivityService(
        settings=settings,
        audit_store=audit_store,
        ai_store=ai_store,
    )


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ConnectivityConfigurationError("database path is unavailable")
    return Path(path)
