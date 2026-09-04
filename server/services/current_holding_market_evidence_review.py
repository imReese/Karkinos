"""Canonical current-holding market evidence review projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from data.market_data import is_fund_estimate_quote_source
from server.models import (
    CurrentHoldingMarketEvidenceLane,
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
_EVIDENCE_LANE_ASSET_CLASSES = ("stock", "fund")


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

    confirmed_fund_nav_refresh_symbols = sorted(
        {
            item.symbol
            for item in items
            if item.review_reason == "confirmed_nav_missing"
            and _evidence_lane_asset_class(item.asset_class) == "fund"
        }
    )
    confirmed_fund_nav_refresh_symbol_set = set(confirmed_fund_nav_refresh_symbols)
    quote_refresh_symbols = sorted(
        {
            item.symbol
            for item in items
            if item.symbol not in confirmed_fund_nav_refresh_symbol_set
        }
    )
    refreshable_symbols = sorted(
        {*quote_refresh_symbols, *confirmed_fund_nav_refresh_symbols}
    )

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
        "refreshable_symbols": refreshable_symbols,
        "quote_refresh_symbols": quote_refresh_symbols,
        "confirmed_fund_nav_refresh_symbols": confirmed_fund_nav_refresh_symbols,
        "evidence_lanes": [
            lane.model_dump(mode="json")
            for lane in _evidence_lanes(
                current_positions,
                items,
                identity_blockers=source_blockers,
            )
        ],
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

    if is_fund_estimate_quote_source(normalized_source):
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


def _evidence_lane_asset_class(value: Any) -> str:
    asset_class = str(value or "stock").strip().lower()
    return asset_class if asset_class in _EVIDENCE_LANE_ASSET_CLASSES else "other"


def _evidence_lanes(
    current_positions: list[Any],
    items: list[CurrentHoldingMarketEvidenceReviewItem],
    *,
    identity_blockers: list[str],
) -> list[CurrentHoldingMarketEvidenceLane]:
    positions_by_asset_class: dict[str, list[Any]] = {
        asset_class: [] for asset_class in _EVIDENCE_LANE_ASSET_CLASSES
    }
    items_by_asset_class: dict[str, list[CurrentHoldingMarketEvidenceReviewItem]] = {
        asset_class: [] for asset_class in _EVIDENCE_LANE_ASSET_CLASSES
    }
    for position in current_positions:
        asset_class = _evidence_lane_asset_class(getattr(position, "asset_class", None))
        positions_by_asset_class.setdefault(asset_class, []).append(position)
    for item in items:
        asset_class = _evidence_lane_asset_class(item.asset_class)
        items_by_asset_class.setdefault(asset_class, []).append(item)

    ordered_asset_classes = [*_EVIDENCE_LANE_ASSET_CLASSES]
    if positions_by_asset_class.get("other"):
        ordered_asset_classes.append("other")

    lanes: list[CurrentHoldingMarketEvidenceLane] = []
    for asset_class in ordered_asset_classes:
        positions = positions_by_asset_class[asset_class]
        lane_items = items_by_asset_class[asset_class]
        if not positions:
            status = "not_applicable"
        elif identity_blockers:
            status = "blocked_identity"
        elif not lane_items:
            status = "complete"
        elif any(
            item.review_reason
            in {"quote_missing_or_error", "quote_status_not_confirmed"}
            for item in lane_items
        ):
            status = "missing"
        else:
            status = "degraded"
        evidence_blockers = sorted(
            {item.review_reason for item in lane_items},
            key=lambda reason: (_review_priority(reason), reason),
        )
        blocker_statuses = (
            [*identity_blockers, *evidence_blockers]
            if positions and identity_blockers
            else evidence_blockers
        )
        lanes.append(
            CurrentHoldingMarketEvidenceLane(
                asset_class=asset_class,
                status=status,
                current_holding_count=len(positions),
                confirmed_holding_count=len(positions) - len(lane_items),
                review_required_count=len(lane_items),
                blocker_statuses=blocker_statuses,
            )
        )
    return lanes


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
