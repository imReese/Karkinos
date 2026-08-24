"""Explicit operator-triggered external AI provider connectivity route."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.provider_connectivity import (
    ConnectivityCheckRequest,
    ConnectivityConfigurationError,
    ConnectivityStatus,
)
from server.ai_runtime.store import IdempotencyConflict
from server.composition.ai_application_services import (
    build_provider_connectivity_service,
)


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
        from server.dependencies import get_app_state

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
