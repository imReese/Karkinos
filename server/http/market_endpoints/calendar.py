"""Market calendar HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    HTTPException = dependency("HTTPException")
    MarketCalendarSnapshotResponse = dependency("MarketCalendarSnapshotResponse")
    MarketCalendarSyncRequest = dependency("MarketCalendarSyncRequest")
    MarketCalendarVerificationRequest = dependency("MarketCalendarVerificationRequest")
    _market_calendar_snapshot_response = dependency(
        "_market_calendar_snapshot_response"
    )
    build_market_calendar_provider = dependency("build_market_calendar_provider")

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
        return _market_calendar_snapshot_response(row, exchange=exchange, year=year)

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
            provider = build_market_calendar_provider(
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
        return _market_calendar_snapshot_response(
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
        row = updater(
            exchange=request.exchange,
            year=request.year,
            verification_status=request.verification_status,
            official_source_url=request.official_source_url,
            verified_by=request.verified_by,
            review_notes=request.review_notes,
            day_labels=request.day_labels,
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail="market calendar snapshot not found"
            )
        return _market_calendar_snapshot_response(
            row,
            exchange=request.exchange,
            year=request.year,
        )

    return r
