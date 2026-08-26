"""Canonical market fetch runs projections."""

from __future__ import annotations

import json

from core.types import AssetClass
from server.contracts.http.market import (
    QuoteRefreshSymbolResult,
)
from server.models import (
    QuoteFetchRunResponse,
)
from server.services.market_views.health_inputs import (
    configured_provider_name,
)


def quote_fetch_run_asset_type(
    requested_symbols: list[str],
    asset_class_by_symbol: dict[str, AssetClass],
) -> str | None:
    asset_types = {
        asset_class_by_symbol.get(symbol, AssetClass.STOCK).value
        for symbol in requested_symbols
    }
    if not asset_types:
        return None
    if len(asset_types) == 1:
        return next(iter(asset_types))
    return "mixed"


def create_manual_quote_fetch_run(
    state,
    *,
    run_id: str,
    started_at: str,
    requested_symbols: list[str],
    asset_type: str | None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "create_quote_fetch_run"):
        return
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at=started_at,
        trigger="manual_refresh",
        provider=configured_provider_name(state),
        asset_type=asset_type,
        symbol_count=len(requested_symbols),
        status="running",
        metadata={
            "requested_symbols": requested_symbols,
        },
    )


def manual_quote_fetch_run_status(
    *,
    quote_status: str,
    success_count: int,
    failure_count: int,
    cache_hit_count: int,
) -> str:
    if quote_status == "live":
        return "success"
    if cache_hit_count > 0 and success_count == 0:
        return "cache_only"
    if success_count > 0 or cache_hit_count > 0:
        return "partial_success"
    if failure_count > 0:
        return "failed"
    return "failed"


def manual_quote_fetch_provider_status(
    state,
    *,
    quote_status: str,
    last_refresh_error: str | None,
) -> str:
    if last_refresh_error:
        return "failed"
    if quote_status == "live":
        return "live"
    if quote_status == "partial":
        return "partial"
    if quote_status == "stale":
        return "cache"
    return "failed"


def finish_manual_quote_fetch_run(
    state,
    *,
    run_id: str,
    finished_at: str,
    requested_symbols: list[str],
    refreshed: list[QuoteRefreshSymbolResult],
    failed: list[QuoteRefreshSymbolResult],
    skipped: list[QuoteRefreshSymbolResult],
    quote_status: str,
    refresh_policy: str,
    market_open: bool,
    last_refresh_error: str | None,
) -> dict | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "finish_quote_fetch_run"):
        return None
    success_count = len(refreshed)
    failure_count = len(failed)
    cache_hit_count = sum(
        1 for result in [*refreshed, *failed, *skipped] if result.using_persistent_cache
    )
    status = manual_quote_fetch_run_status(
        quote_status=quote_status,
        success_count=success_count,
        failure_count=failure_count,
        cache_hit_count=cache_hit_count,
    )
    metadata = {
        "provider": configured_provider_name(state),
        "provider_status": manual_quote_fetch_provider_status(
            state,
            quote_status=quote_status,
            last_refresh_error=last_refresh_error,
        ),
        "quote_status": quote_status,
        "refresh_policy": refresh_policy,
        "market_open": market_open,
        "using_persistent_cache": cache_hit_count > 0,
        "requested_symbols": requested_symbols,
        "refreshed_symbols": [result.symbol for result in refreshed],
        "failed_symbols": [result.symbol for result in failed],
        "skipped_symbols": [result.symbol for result in skipped],
    }
    return db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at=finished_at,
        status=status,
        success_count=success_count,
        failure_count=failure_count,
        cache_hit_count=cache_hit_count,
        error_message=last_refresh_error,
        metadata=metadata,
    )


def quote_fetch_run_metadata(row: dict) -> dict | None:
    metadata_json = row.get("metadata_json")
    if not metadata_json:
        return None
    try:
        parsed = json.loads(str(metadata_json))
    except (TypeError, ValueError):
        return {
            "raw_metadata": str(metadata_json),
            "parse_error": "invalid_json",
        }
    if isinstance(parsed, dict):
        return parsed
    return {
        "raw_metadata": str(metadata_json),
        "parse_error": "metadata_not_object",
    }


def quote_fetch_run_response(row: dict) -> QuoteFetchRunResponse:
    return QuoteFetchRunResponse(
        run_id=str(row["run_id"]),
        trigger=str(row["trigger"]),
        provider=row.get("provider"),
        asset_type=row.get("asset_type"),
        status=str(row["status"]),
        started_at=str(row["started_at"]),
        finished_at=row.get("finished_at"),
        symbol_count=int(row.get("symbol_count") or 0),
        success_count=int(row.get("success_count") or 0),
        failure_count=int(row.get("failure_count") or 0),
        cache_hit_count=int(row.get("cache_hit_count") or 0),
        error_message=row.get("error_message"),
        metadata=quote_fetch_run_metadata(row),
    )


__all__ = (
    "create_manual_quote_fetch_run",
    "finish_manual_quote_fetch_run",
    "manual_quote_fetch_provider_status",
    "manual_quote_fetch_run_status",
    "quote_fetch_run_asset_type",
    "quote_fetch_run_metadata",
    "quote_fetch_run_response",
)
