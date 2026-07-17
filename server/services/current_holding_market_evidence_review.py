"""Canonical current-holding market evidence review projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from server.models import (
    CurrentHoldingMarketEvidenceReviewItem,
    CurrentHoldingMarketEvidenceReviewResponse,
    PortfolioSnapshot,
)
from server.services.position_presence import is_economically_zero_quantity

CURRENT_HOLDING_MARKET_EVIDENCE_REVIEW_SCHEMA_VERSION = (
    "karkinos.current_holding_market_evidence_review.v1"
)

_CONFIRMED_STATUSES = {"confirmed", "fresh", "healthy", "live"}
_STALE_OR_CACHED_STATUSES = {
    "cache",
    "cache_only",
    "cached",
    "market_closed_cache_only",
    "stale",
}
_MISSING_OR_ERROR_STATUSES = {"", "error", "missing", "unknown"}
_FUND_ESTIMATE_SOURCE = "eastmoney_fund_estimate"


def build_current_holding_market_evidence_review(
    snapshot: PortfolioSnapshot,
) -> CurrentHoldingMarketEvidenceReviewResponse:
    """Project exact persisted quote blockers without refreshing or mutating facts."""

    current_positions = [
        position
        for position in snapshot.positions
        if not is_economically_zero_quantity(position.quantity)
    ]
    items = [
        item
        for position in current_positions
        if (item := _review_item(position)) is not None
    ]
    items.sort(key=lambda item: (_review_priority(item.review_reason), item.symbol))

    source_blockers = _identity_blockers(snapshot)
    if source_blockers:
        status = "blocked_identity"
        next_manual_action = "restore_valuation_identity_before_review"
    elif not current_positions:
        status = "no_current_holdings"
        next_manual_action = "none"
    elif items:
        status = "review_required"
        next_manual_action = "review_current_holding_market_evidence"
    else:
        status = "complete"
        next_manual_action = "none"

    core = {
        "schema_version": CURRENT_HOLDING_MARKET_EVIDENCE_REVIEW_SCHEMA_VERSION,
        "status": status,
        "next_manual_action": next_manual_action,
        "current_holding_count": len(current_positions),
        "confirmed_holding_count": len(current_positions) - len(items),
        "review_required_count": len(items),
        "fund_nav_review_count": _count_reason(items, "confirmed_nav_missing"),
        "estimated_review_count": _count_reason(
            items, "estimated_quote_not_authoritative"
        ),
        "stale_or_cached_review_count": _count_reason(items, "quote_stale_or_cached"),
        "missing_or_error_review_count": _count_reason(items, "quote_missing_or_error"),
        "unknown_status_review_count": _count_reason(
            items, "quote_status_not_confirmed"
        ),
        "refreshable_symbols": sorted({item.symbol for item in items}),
        "items": [item.model_dump(mode="json") for item in items],
        "source_blockers": source_blockers,
        "valuation_snapshot_id": snapshot.valuation_snapshot_id,
        "valuation_as_of": snapshot.valuation_as_of,
        "valuation_trade_date": snapshot.valuation_trade_date,
        "valuation_policy": snapshot.valuation_policy,
        "valuation_status": snapshot.valuation_status,
        "ledger_cutoff_id": snapshot.ledger_cutoff_id,
        "ledger_fingerprint": snapshot.ledger_fingerprint,
        "quote_set_fingerprint": snapshot.quote_set_fingerprint,
    }
    return CurrentHoldingMarketEvidenceReviewResponse(
        **core,
        review_fingerprint=_fingerprint(core),
    )


def _review_item(position: Any) -> CurrentHoldingMarketEvidenceReviewItem | None:
    raw_status = _normalize_status(getattr(position, "quote_status", None))
    quote_source = str(getattr(position, "quote_source", None) or "").strip()
    normalized_source = quote_source.lower()
    asset_class = str(getattr(position, "asset_class", None) or "stock").strip()

    if normalized_source == _FUND_ESTIMATE_SOURCE:
        quote_status = "confirmed_nav_missing"
        review_reason = "confirmed_nav_missing"
        next_action = "wait_for_confirmed_nav_then_run_explicit_refresh"
    elif raw_status in _CONFIRMED_STATUSES:
        return None
    elif raw_status == "confirmed_nav_missing":
        quote_status = raw_status
        review_reason = "confirmed_nav_missing"
        next_action = "wait_for_confirmed_nav_then_run_explicit_refresh"
    elif raw_status == "estimated":
        quote_status = raw_status
        review_reason = "estimated_quote_not_authoritative"
        next_action = "wait_for_confirmed_data_then_run_explicit_refresh"
    elif raw_status in _STALE_OR_CACHED_STATUSES:
        quote_status = raw_status
        review_reason = "quote_stale_or_cached"
        next_action = "run_explicit_quote_refresh"
    elif raw_status in _MISSING_OR_ERROR_STATUSES:
        quote_status = raw_status or "missing"
        review_reason = "quote_missing_or_error"
        next_action = "inspect_data_source_then_run_explicit_refresh"
    else:
        quote_status = raw_status
        review_reason = "quote_status_not_confirmed"
        next_action = "review_unknown_quote_status_before_refresh"

    return CurrentHoldingMarketEvidenceReviewItem(
        symbol=str(position.symbol),
        name=str(position.display_name or position.name or position.symbol),
        asset_class=asset_class,
        quantity=float(position.quantity),
        quote_status=quote_status,
        quote_source=quote_source or None,
        quote_timestamp=getattr(position, "quote_timestamp", None),
        stale_reason=getattr(position, "stale_reason", None),
        nav_date=getattr(position, "nav_date", None),
        review_reason=review_reason,
        next_manual_action=next_action,
    )


def _identity_blockers(snapshot: PortfolioSnapshot) -> list[str]:
    blockers: list[str] = []
    if not str(snapshot.valuation_snapshot_id or "").strip():
        blockers.append("valuation_snapshot_id_missing")
    if not str(snapshot.quote_set_fingerprint or "").strip():
        blockers.append("quote_set_fingerprint_missing")
    if not str(snapshot.ledger_fingerprint or "").strip():
        blockers.append("ledger_fingerprint_missing")
    if isinstance(snapshot.ledger_cutoff_id, bool) or snapshot.ledger_cutoff_id < 0:
        blockers.append("ledger_cutoff_id_invalid")
    return blockers


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", " ").replace(" ", "_")


def _review_priority(reason: str) -> int:
    return {
        "quote_missing_or_error": 0,
        "quote_status_not_confirmed": 1,
        "quote_stale_or_cached": 2,
        "estimated_quote_not_authoritative": 3,
        "confirmed_nav_missing": 4,
    }.get(reason, 5)


def _count_reason(
    items: list[CurrentHoldingMarketEvidenceReviewItem], reason: str
) -> int:
    return sum(item.review_reason == reason for item in items)


def _fingerprint(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
