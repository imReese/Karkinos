"""Market refresh HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from core.types import AssetClass
from server.contracts.http.market import QuoteRefreshRequest, QuoteRefreshResponse


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _ASSET_CLASS_MAP = dependency("_ASSET_CLASS_MAP")
    _create_manual_quote_fetch_run = dependency("_create_manual_quote_fetch_run")
    _default_refresh_symbols = dependency("_default_refresh_symbols")
    _finish_manual_quote_fetch_run = dependency("_finish_manual_quote_fetch_run")
    _merged_watchlist_assets = dependency("_merged_watchlist_assets")
    _normalize_refresh_symbols = dependency("_normalize_refresh_symbols")
    _quote_fetch_run_asset_type = dependency("_quote_fetch_run_asset_type")
    _refresh_one_quote = dependency("_refresh_one_quote")
    _with_default_market_indices = dependency("_with_default_market_indices")
    asyncio = dependency("asyncio")
    build_current_valuation_snapshot = dependency("build_current_valuation_snapshot")
    datetime = dependency("datetime")
    is_cn_trading_session = dependency("is_cn_trading_session")
    logger = dependency("logger")
    uuid = dependency("uuid")

    @r.post("/quotes/refresh", response_model=QuoteRefreshResponse)
    async def refresh_quotes(request: QuoteRefreshRequest) -> QuoteRefreshResponse:
        """手动刷新行情快照，逐标的返回刷新结果。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        started_at_dt = datetime.now()
        started_at = started_at_dt.isoformat()
        market_open = is_cn_trading_session()
        refresh_policy = "live" if market_open else "cache_only"

        requested_symbols = _normalize_refresh_symbols(request.symbols)
        if not requested_symbols:
            requested_symbols = _default_refresh_symbols(state)
        run_id = f"manual_refresh:{started_at_dt.isoformat()}:{uuid.uuid4().hex}"

        if not requested_symbols:
            completed_at_dt = datetime.now()
            completed_at = completed_at_dt.isoformat()
            _create_manual_quote_fetch_run(
                state,
                run_id=run_id,
                started_at=started_at,
                requested_symbols=[],
                asset_type=None,
            )
            _finish_manual_quote_fetch_run(
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
                valuation_snapshot_id=None,
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

        watchlist_assets = _with_default_market_indices(_merged_watchlist_assets(state))
        asset_class_by_symbol = {
            asset_cfg["symbol"]: _ASSET_CLASS_MAP.get(
                asset_cfg["asset_class"], AssetClass.STOCK
            )
            for asset_cfg in watchlist_assets
        }
        _create_manual_quote_fetch_run(
            state,
            run_id=run_id,
            started_at=started_at,
            requested_symbols=requested_symbols,
            asset_type=_quote_fetch_run_asset_type(
                requested_symbols,
                asset_class_by_symbol,
            ),
        )

        results = await asyncio.gather(
            *[
                _refresh_one_quote(
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
        try:
            valuation_snapshot = build_current_valuation_snapshot(
                getattr(state, "db", None),
                persist=True,
            )
        except Exception as exc:
            logger.exception("Failed to create valuation snapshot after manual refresh")
            db = getattr(state, "db", None)
            if db is not None and hasattr(db, "finish_quote_fetch_run"):
                db.finish_quote_fetch_run(
                    run_id=run_id,
                    finished_at=completed_at,
                    status="failed",
                    success_count=len(refreshed),
                    failure_count=max(len(failed), 1),
                    cache_hit_count=sum(
                        1 for result in results if result.using_persistent_cache
                    ),
                    error_message="valuation_snapshot_persistence_failed",
                    metadata={
                        "requested_symbols": requested_symbols,
                        "error": str(exc),
                        "facts_persisted_but_not_published": True,
                    },
                )
            raise HTTPException(
                status_code=503,
                detail="行情已落库但估值快照生成失败，本批次未发布",
            ) from exc
        _finish_manual_quote_fetch_run(
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
            valuation_snapshot_id=str(valuation_snapshot["snapshot_id"]),
        )
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

    return r
