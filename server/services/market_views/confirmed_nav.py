"""Canonical market confirmed nav projections."""

from __future__ import annotations

from functools import partial

from fastapi import HTTPException

from core.types import AssetClass, Symbol
from server.contracts.http.market import (
    ConfirmedFundNavRefreshRequest,
    ConfirmedFundNavRefreshResponse,
)
from server.services.market_refresh import run_blocking_fetch as _run_blocking_fetch
from server.services.market_refresh import shanghai_now as _shanghai_now
from server.services.market_views.fetch_runs import (
    quote_fetch_run_response,
)
from server.services.market_views.health_inputs import (
    extract_runtime_portfolio,
    merged_watchlist_assets,
    normalize_refresh_symbols,
)

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
    "index": AssetClass.INDEX,
}


async def refresh_confirmed_fund_nav(
    state,
    request: ConfirmedFundNavRefreshRequest,
) -> ConfirmedFundNavRefreshResponse:
    """Run an explicit, audited, confirmation-only fund NAV ingestion batch."""
    from server.services.fund_nav_sync import (
        FundNavSyncIdempotencyConflict,
        refresh_fund_nav_quotes,
    )

    db = getattr(state, "db", None)
    required_audit_methods = (
        "create_quote_fetch_run",
        "finish_quote_fetch_run",
        "get_quote_fetch_run",
    )
    if db is None or any(
        not callable(getattr(db, method_name, None))
        for method_name in required_audit_methods
    ):
        raise HTTPException(
            status_code=503,
            detail="confirmed fund NAV audit storage unavailable",
        )

    requested_symbols = normalize_refresh_symbols(request.symbols)
    if not requested_symbols:
        raise HTTPException(status_code=422, detail="at least one symbol is required")

    assets_by_symbol = {
        asset["symbol"]: asset for asset in merged_watchlist_assets(state)
    }
    invalid_symbols = [
        symbol
        for symbol in requested_symbols
        if symbol not in assets_by_symbol
        or _ASSET_CLASS_MAP.get(assets_by_symbol[symbol]["asset_class"])
        is not AssetClass.FUND
    ]
    if invalid_symbols:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "confirmed_fund_nav_requires_known_fund_symbols",
                "symbols": invalid_symbols,
            },
        )

    _, _, _, latest_quotes = extract_runtime_portfolio(state)
    watchlist = [(Symbol(symbol), AssetClass.FUND) for symbol in requested_symbols]
    try:
        result = await _run_blocking_fetch(
            partial(
                refresh_fund_nav_quotes,
                state.config,
                db,
                watchlist,
                latest_quotes,
                now=_shanghai_now(),
                ttl_seconds=0,
                confirmation_only=True,
                request_id=request.request_id,
            )
        )
    except FundNavSyncIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="confirmed fund NAV request id payload conflict",
        ) from exc
    if not result.run_id:
        raise HTTPException(
            status_code=503,
            detail="confirmed fund NAV ingestion did not create an audit run",
        )
    run_row = db.get_quote_fetch_run(result.run_id)
    if run_row is None:
        raise HTTPException(
            status_code=503,
            detail="confirmed fund NAV audit run is unavailable",
        )

    run = quote_fetch_run_response(run_row)
    metadata = run.metadata or {}
    valuation_snapshot_id = metadata.get("valuation_snapshot_id")
    if run.status == "success":
        next_manual_action = "review_refreshed_current_holding_evidence"
    elif run.status in {"partial", "partial_success"}:
        next_manual_action = "review_partial_confirmed_fund_nav_refresh"
    elif run.status == "running":
        next_manual_action = "wait_for_existing_confirmed_fund_nav_run"
    else:
        next_manual_action = "wait_for_confirmed_nav_then_retry"

    return ConfirmedFundNavRefreshResponse(
        request_id=request.request_id,
        idempotent_replay=result.idempotent_replay,
        status=run.status,
        next_manual_action=next_manual_action,
        requested_symbols=requested_symbols,
        refreshed_symbols=list(result.refreshed),
        skipped_symbols=list(result.skipped),
        failed_symbols=dict(result.failed),
        run=run,
        valuation_snapshot_id=(
            str(valuation_snapshot_id) if valuation_snapshot_id else None
        ),
        provider_contact_performed=not result.idempotent_replay,
    )


__all__ = ("refresh_confirmed_fund_nav",)
