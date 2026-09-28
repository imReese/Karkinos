"""回测页面使用的持久数据集入口；GET 不联网，POST 才允许准备数据。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.providers.tdx_runtime import TdxRuntimeConfigurationError
from server.dependencies import get_app_state
from server.persistence.jobs import JobIdentityConflictError, SQLiteJobStore
from server.services.research_datasets import (
    ResearchDatasetError,
    publish_verified_interval_dataset,
)
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketDataRequestError,
    VerifiedDailyMarketJobRequest,
)
from server.services.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    VerifiedDailyMarketJobPlanningError,
    enqueue_verified_daily_market_jobs_for_range,
)


class PrepareDatasetRequest(BaseModel):
    symbol: str = Field(pattern=r"^[0-9]{6}$")
    instrument_type: Literal["stock", "etf"] = "stock"
    start_date: date
    end_date: date
    refresh: bool = False


class PrepareVerifiedJobsRequest(BaseModel):
    symbol: str = Field(pattern=r"^[0-9]{6}$")
    instrument_type: Literal["stock", "etf"]
    start_date: date
    end_date: date


class PublishVerifiedIntervalRequest(PrepareVerifiedJobsRequest):
    job_ids: list[str] = Field(min_length=1, max_length=366)


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

    @router.post("/verified-jobs")
    async def prepare_verified_jobs(payload: PrepareVerifiedJobsRequest):
        state = get_app_state()
        if state.db is None or state.config is None:
            raise HTTPException(503, "verified_market_jobs_unavailable")
        try:
            jobs = await asyncio.to_thread(
                enqueue_verified_daily_market_jobs_for_range,
                state.db,
                state.config,
                SQLiteJobStore(state.db.path),
                instrument=InstrumentKey(
                    payload.symbol, InstrumentType(payload.instrument_type)
                ),
                start_date=payload.start_date,
                end_date=payload.end_date,
                now=datetime.now(timezone.utc),
            )
        except VerifiedDailyMarketJobPlanningError as exc:
            raise HTTPException(409, str(exc)) from None
        except JobIdentityConflictError:
            raise HTTPException(409, "verified_market_job_identity_conflict") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(503, "verified_market_jobs_unavailable") from None
        return {
            "jobs": [
                {
                    "trade_date": job.payload["trade_date"],
                    "job_id": job.job_id,
                    "source_policy_id": job.payload["source_policy_id"],
                    "status": job.status,
                    "result_ref": job.result_ref,
                }
                for job in jobs
            ]
        }

    @router.post("/verified-interval")
    async def publish_verified_interval(payload: PublishVerifiedIntervalRequest):
        state = get_app_state()
        if state.db is None:
            raise HTTPException(503, "verified_interval_database_unavailable")
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
        except ValueError:
            raise HTTPException(422, "verified_interval_request_invalid") from None
        try:
            return await asyncio.to_thread(
                publish_verified_interval_dataset,
                state.db.path.resolve().parent / "research",
                request,
                db=state.db,
                job_ids=tuple(payload.job_ids),
            )
        except ResearchDatasetError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "verified_interval_storage_unavailable") from None

    @router.get("/verified-jobs/{job_id}")
    async def get_verified_job(job_id: str):
        state = get_app_state()
        if state.db is None:
            raise HTTPException(503, "verified_market_jobs_unavailable")
        try:
            job = await asyncio.to_thread(SQLiteJobStore(state.db.path).get, job_id)
        except JobIdentityConflictError:
            raise HTTPException(409, "verified_market_job_identity_conflict") from None
        except ValueError:
            raise HTTPException(422, "verified_market_job_id_invalid") from None
        except OSError:
            raise HTTPException(503, "verified_market_jobs_unavailable") from None
        if job is None or job.kind != VERIFIED_DAILY_MARKET_JOB:
            raise HTTPException(404, "verified_market_job_not_found")
        try:
            request = VerifiedDailyMarketJobRequest.from_payload(job.payload)
        except (TypeError, ValueError, VerifiedDailyMarketDataRequestError):
            raise HTTPException(409, "verified_market_job_payload_invalid") from None
        return {
            "trade_date": request.trade_date.isoformat(),
            "job_id": job.job_id,
            "source_policy_id": request.source_policy_id,
            "status": job.status,
            "attempt": job.attempt,
            "result_ref": job.result_ref,
            "error": job.error,
        }

    return router
