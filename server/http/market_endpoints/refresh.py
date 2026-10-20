"""Market refresh HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.types import AssetClass
from server.contracts.http.market import (
    MarketSyncApiRequest,
    MarketSyncApiResponse,
    QuoteRefreshRequest,
    QuoteRefreshResponse,
)
from server.http.market_endpoints.dependencies import RefreshEndpointDependencies


def create_router(dependencies: RefreshEndpointDependencies) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    @r.post("/quotes/refresh", response_model=QuoteRefreshResponse)
    async def refresh_quotes(request: QuoteRefreshRequest) -> QuoteRefreshResponse:
        """手动刷新行情快照，逐标的返回刷新结果。"""
        from server.dependencies import get_app_state

        asyncio = dependencies.asyncio_provider()
        datetime = dependencies.datetime_provider()
        uuid = dependencies.uuid_provider()
        state = get_app_state()
        started_at_dt = datetime.now()
        started_at = started_at_dt.isoformat()
        market_open = dependencies.is_cn_trading_session()
        refresh_policy = "live" if market_open else "cache_only"

        requested_symbols = dependencies.normalize_refresh_symbols(request.symbols)
        if not requested_symbols:
            requested_symbols = dependencies.default_refresh_symbols(state)
        run_id = f"manual_refresh:{started_at_dt.isoformat()}:{uuid.uuid4().hex}"

        if not requested_symbols:
            completed_at_dt = datetime.now()
            completed_at = completed_at_dt.isoformat()
            dependencies.create_manual_quote_fetch_run(
                state,
                run_id=run_id,
                started_at=started_at,
                requested_symbols=[],
                asset_type=None,
            )
            dependencies.finish_manual_quote_fetch_run(
                state,
                run_id=run_id,
                finished_at=completed_at,
                requested_symbols=[],
                refreshed=[],
                failed=[],
                skipped=[],
                quote_status="error",
                refresh_policy=refresh_policy,
                market_open=market_open,
                last_refresh_error="no_refresh_symbols",
            )
            return QuoteRefreshResponse(
                requested_symbols=[],
                refresh_policy=refresh_policy,
                market_open=market_open,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=int(
                    (completed_at_dt - started_at_dt).total_seconds() * 1000
                ),
                quote_status="error",
                last_refresh_attempt=started_at,
                last_refresh_error="no_refresh_symbols",
                message="没有可刷新的行情标的",
            )

        watchlist_assets = dependencies.with_default_market_indices(
            dependencies.merged_watchlist_assets(state)
        )
        asset_class_by_symbol: dict[str, AssetClass] = {}
        for asset_cfg in watchlist_assets:
            # User/config/ledger assets precede built-in market indices. A
            # symbol-only public request keeps that stable preference here;
            # refresh_one_quote still resolves and validates exact identity
            # before any quote is persisted.
            asset_class_by_symbol.setdefault(
                asset_cfg["symbol"],
                dependencies.asset_class_map.get(
                    asset_cfg["asset_class"],
                    AssetClass.STOCK,
                ),
            )
        dependencies.create_manual_quote_fetch_run(
            state,
            run_id=run_id,
            started_at=started_at,
            requested_symbols=requested_symbols,
            asset_type=dependencies.quote_fetch_run_asset_type(
                requested_symbols,
                asset_class_by_symbol,
            ),
            asset_class_by_symbol=asset_class_by_symbol,
        )

        results = await asyncio.gather(
            *[
                dependencies.refresh_one_quote(
                    state,
                    symbol,
                    asset_class_by_symbol.get(symbol, AssetClass.STOCK),
                    fetch_run_id=run_id,
                )
                for symbol in requested_symbols
            ]
        )

        refreshed = [result for result in results if result.status == "refreshed"]
        failed = [result for result in results if result.status == "failed"]
        skipped = [
            result for result in results if result.status not in {"refreshed", "failed"}
        ]

        if refreshed and not failed and not skipped:
            quote_status = "live"
            message = "行情刷新完成"
        elif refreshed:
            quote_status = "partial"
            message = "部分行情刷新完成"
        elif failed and not skipped:
            quote_status = "error"
            message = "行情刷新失败"
        else:
            quote_status = "stale"
            message = "行情源返回缓存行情"

        completed_at_dt = datetime.now()
        last_refresh_error = next(
            (
                result.last_refresh_error or result.error
                for result in results
                if result.error
            ),
            None,
        )
        has_persistent_cache = any(result.using_persistent_cache for result in results)
        completed_at = completed_at_dt.isoformat()
        finished = dependencies.finish_manual_quote_fetch_run(
            state,
            run_id=run_id,
            finished_at=completed_at,
            requested_symbols=requested_symbols,
            refreshed=refreshed,
            failed=failed,
            skipped=skipped,
            quote_status=quote_status,
            refresh_policy=refresh_policy,
            market_open=market_open,
            last_refresh_error=last_refresh_error,
        )
        run_metadata = (
            dependencies.quote_fetch_run_metadata(finished)
            if isinstance(finished, dict)
            else None
        )
        if refreshed and (
            not isinstance(finished, dict)
            or finished.get("status") not in {"success", "partial_success"}
            or not isinstance(run_metadata, dict)
            or not run_metadata.get("valuation_snapshot_id")
        ):
            raise HTTPException(
                status_code=503,
                detail="行情批次未能原子发布，已拒绝暴露本批数据",
            )
        if refreshed:
            dependencies.publish_committed_runtime_quotes(state, refreshed)
        return QuoteRefreshResponse(
            requested_symbols=requested_symbols,
            refreshed=refreshed,
            failed=failed,
            skipped=skipped,
            refresh_policy=refresh_policy,
            market_open=market_open,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=int((completed_at_dt - started_at_dt).total_seconds() * 1000),
            quote_status=quote_status,
            last_refresh_attempt=started_at,
            last_refresh_error=last_refresh_error,
            message=message,
            real_data_available=bool(refreshed) or has_persistent_cache,
            has_persistent_cache=has_persistent_cache,
        )

    @r.post("/sync", response_model=MarketSyncApiResponse)
    async def sync_market(request: MarketSyncApiRequest) -> MarketSyncApiResponse:
        """Trigger comprehensive multi-asset market synchronization."""
        from server.dependencies import get_app_state
        from server.services.market.sync import (
            MarketSyncRequest,
            get_market_sync_service,
        )

        state = get_app_state()
        service = get_market_sync_service(
            data_dir=getattr(state, "data_dir", None),
            db=getattr(state, "db", None),
            config=getattr(state, "config", None),
        )
        sync_req = MarketSyncRequest(
            universe=request.universe,
            symbols=request.symbols,
            start_date=request.start,
            end_date=request.end,
            skip_calendar=request.skip_calendar,
            skip_quotes=request.skip_quotes,
            force=request.force,
            exchanges=tuple(request.exchanges),
            universe_snapshot_id=request.universe_snapshot_id,
        )
        asyncio_mod = dependencies.asyncio_provider()
        summary = await asyncio_mod.to_thread(service.sync, sync_req)
        return MarketSyncApiResponse(
            status=summary.status,
            started_at=summary.started_at,
            completed_at=summary.completed_at,
            duration_seconds=summary.duration_seconds,
            calendar_years=summary.calendar_years,
            total_targets=summary.total_targets,
            successful_targets=summary.successful_targets,
            failed_targets=summary.failed_targets,
            quotes_updated=summary.quotes_updated,
            items=[
                {
                    "symbol": item.symbol,
                    "asset_class": item.asset_class,
                    "instrument_type": item.instrument_type,
                    "bars_count": item.bars_count,
                    "status": item.status,
                    "error": item.error,
                }
                for item in summary.items
            ],
            jobs=summary.jobs,
            scope=summary.scope,
            error=summary.error,
            message=f"Market sync {summary.status}: {summary.successful_targets}/{summary.total_targets} succeeded",
        )

    @r.get("/sync/status", response_model=MarketSyncApiResponse | None)
    async def get_sync_status() -> MarketSyncApiResponse | None:
        """Query the latest market synchronization outcome."""
        from server.dependencies import get_app_state
        from server.services.market.sync import get_market_sync_service

        state = get_app_state()
        service = get_market_sync_service(
            data_dir=getattr(state, "data_dir", None),
            db=getattr(state, "db", None),
            config=getattr(state, "config", None),
        )
        summary = service.get_last_summary()
        if summary is None:
            return None
        return MarketSyncApiResponse(
            status=summary.status,
            started_at=summary.started_at,
            completed_at=summary.completed_at,
            duration_seconds=summary.duration_seconds,
            calendar_years=summary.calendar_years,
            total_targets=summary.total_targets,
            successful_targets=summary.successful_targets,
            failed_targets=summary.failed_targets,
            quotes_updated=summary.quotes_updated,
            items=[
                {
                    "symbol": item.symbol,
                    "asset_class": item.asset_class,
                    "instrument_type": item.instrument_type,
                    "bars_count": item.bars_count,
                    "status": item.status,
                    "error": item.error,
                }
                for item in summary.items
            ],
            jobs=summary.jobs,
            scope=summary.scope,
            error=summary.error,
            message=f"Latest sync {summary.status}: {summary.successful_targets}/{summary.total_targets} succeeded",
        )

    return r


__all__ = ["create_router"]
