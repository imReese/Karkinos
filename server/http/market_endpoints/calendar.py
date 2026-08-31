"""Market calendar HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.contracts.http.market_models import (
    MarketCalendarSnapshotResponse,
    MarketCalendarSyncRequest,
    MarketCalendarVerificationRequest,
)
from server.http.market_endpoints.dependencies import CalendarEndpointDependencies


def create_router(dependencies: CalendarEndpointDependencies) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    @r.get("/calendar", response_model=MarketCalendarSnapshotResponse)
    async def get_market_calendar(
        exchange: str = "SSE",
        year: int = 2026,
    ) -> MarketCalendarSnapshotResponse:
        """Read the stored exchange calendar snapshot without network access."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        getter = getattr(db, "get_market_calendar_snapshot_sync", None)
        if not callable(getter):
            raise HTTPException(
                status_code=503, detail="market calendar storage unavailable"
            )
        row = getter(exchange=exchange, year=year)
        return dependencies.market_calendar_snapshot_response(
            row, exchange=exchange, year=year
        )

    @r.post("/calendar/sync", response_model=MarketCalendarSnapshotResponse)
    async def sync_market_calendar(
        request: MarketCalendarSyncRequest,
    ) -> MarketCalendarSnapshotResponse:
        """Synchronize a provider calendar snapshot into local storage."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        upsert = getattr(db, "upsert_market_calendar_snapshot_sync", None)
        if not callable(upsert):
            raise HTTPException(
                status_code=503, detail="market calendar storage unavailable"
            )
        provider_name = str(
            request.provider
            or getattr(state.config, "data_source", "akshare")
            or "akshare"
        ).lower()
        try:
            provider = dependencies.build_market_calendar_provider(
                provider_name,
                tushare_token=getattr(state.config, "tushare_token", ""),
            )
            snapshot = provider.fetch_snapshot(
                exchange=request.exchange.upper(),
                year=request.year,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"market calendar provider failed: {exc}",
            ) from exc

        row = upsert(snapshot)
        return dependencies.market_calendar_snapshot_response(
            row,
            exchange=request.exchange,
            year=request.year,
        )

    @r.put("/calendar/verification", response_model=MarketCalendarSnapshotResponse)
    async def update_market_calendar_verification(
        request: MarketCalendarVerificationRequest,
    ) -> MarketCalendarSnapshotResponse:
        """Record manual official-notice verification for a stored snapshot."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        updater = getattr(db, "update_market_calendar_verification_sync", None)
        if not callable(updater):
            raise HTTPException(
                status_code=503, detail="market calendar storage unavailable"
            )
        try:
            row = updater(
                exchange=request.exchange,
                year=request.year,
                source_fingerprint=request.expected_source_fingerprint,
                verification_status=request.verification_status,
                official_source_url=request.official_source_url,
                official_source_fingerprint=(request.official_source_fingerprint),
                verified_by=request.verified_by,
                review_notes=request.review_notes,
                day_labels=request.day_labels,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(
                status_code=404, detail="market calendar snapshot not found"
            )
        return dependencies.market_calendar_snapshot_response(
            row,
            exchange=request.exchange,
            year=request.year,
        )

    return r
