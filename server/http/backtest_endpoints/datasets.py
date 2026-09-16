"""回测页面使用的持久数据集入口；GET 不联网，POST 才允许准备数据。"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.providers.tdx_runtime import TdxRuntimeConfigurationError
from server.dependencies import get_app_state
from server.services.research_datasets import ResearchDatasetError


class PrepareDatasetRequest(BaseModel):
    symbol: str = Field(pattern=r"^[0-9]{6}$")
    instrument_type: Literal["stock", "etf"] = "stock"
    start_date: date
    end_date: date
    refresh: bool = False


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/backtest/datasets", tags=["backtest"])

    @router.get("")
    async def list_datasets():
        service = get_app_state().research_datasets
        if service is None:
            raise HTTPException(503, "research_dataset_service_unavailable")
        try:
            return await asyncio.to_thread(service.status)
        except Exception:
            raise HTTPException(409, "dataset_catalog_unreadable") from None

    @router.post("")
    async def prepare_dataset(payload: PrepareDatasetRequest):
        state = get_app_state()
        service = state.research_datasets
        if service is None:
            raise HTTPException(503, "research_dataset_service_unavailable")
        try:
            request = DailyBarRequest(
                (
                    InstrumentKey(
                        payload.symbol, InstrumentType(payload.instrument_type)
                    ),
                ),
                payload.start_date,
                payload.end_date,
            )
            return await asyncio.to_thread(
                service.prepare,
                request,
                db=state.require_database(),
                config=state.config,
                refresh=payload.refresh,
            )
        except ResearchDatasetError as exc:
            raise HTTPException(409, str(exc)) from None
        except TdxRuntimeConfigurationError:
            raise HTTPException(422, "tdx_runtime_configuration_invalid") from None
        except ValueError:
            raise HTTPException(422, "dataset_request_invalid") from None
        except Exception:
            raise HTTPException(409, "dataset_preparation_failed") from None

    return router
