"""Read-only price observations after frozen daily candidates.

The observation starts at the next verified session's open and ends at the
requested session's close. It is a hypothetical, unadjusted price move, never
an account return or an executable trade. Every used bar belongs to an exact
verified daily ingestion receipt from one provider.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.daily_candidate_outcome_store import (
    CandidateOutcomeReceiptReader,
    CandidateOutcomeStoreUnavailable,
    read_candidate_outcome_receipts,
    read_research_candidate_payloads,
    replay_research_dataset_snapshot,
)
from server.persistence.database_identity import optional_database_path
from server.services.market_calendar_evidence import validate_verified_market_calendar

_HORIZONS = (1, 5, 20)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def evaluate_daily_candidate_outcomes(
    db: Any,
    report: Mapping[str, Any],
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Evaluate one report's frozen candidates without writing or fetching data."""
    report_date = _date(report.get("report_date"))
    today = as_of or datetime.now(_SHANGHAI).date()
    if report_date is None:
        raise ValueError("candidate outcome report date invalid")
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError("candidate outcome as_of date invalid")
    if today < report_date:
        raise ValueError("candidate outcome as_of precedes report date")

    path = optional_database_path(db)
    market_path = path.parent / "meta.db" if path is not None else None
    items = [
        item
        for key in ("candidates", "blocked_signals")
        for item in report.get(key, [])
        if isinstance(item, Mapping)
    ]
    items.extend(
        operation
        for preview in report.get("research_previews", [])
        if isinstance(preview, Mapping)
        for operation in preview.get("operations", [])
        if isinstance(operation, Mapping)
    )
    previews = {
        str(item.get("run_id") or ""): item
        for item in report.get("research_previews", [])
        if isinstance(item, Mapping)
    }
    scans = {
        str(item.get("run_id") or ""): item
        for item in report.get("scans", [])
        if isinstance(item, Mapping)
    }
    calendar = _verified_sessions(db, report_date, today)
    if market_path is None or not market_path.is_file():
        evaluated = [
            _unavailable_item(item, "persisted_market_store_missing") for item in items
        ]
    else:
        try:
            with read_candidate_outcome_receipts(market_path) as receipts:
                snapshot_replays: dict[str, bool] = {}
                evaluated = [
                    _evaluate_item(
                        item,
                        scans=scans,
                        previews=previews,
                        app_path=path,
                        market_root=market_path.parent,
                        receipts=receipts,
                        snapshot_replays=snapshot_replays,
                        calendar=calendar,
                        as_of=today,
                    )
                    for item in items
                ]
        except CandidateOutcomeStoreUnavailable:
            evaluated = [
                _unavailable_item(item, "persisted_market_store_unreadable")
                for item in items
            ]
    observed = sum(
        horizon.get("status") == "observed"
        for item in evaluated
        for horizon in item["horizons"].values()
    )
    return {
        "schema_version": "karkinos.decision.candidate_outcomes.v1",
        "report_date": report_date.isoformat(),
        "as_of_date": today.isoformat(),
        "method": "next_verified_session_open_to_horizon_close",
        "horizons": list(_HORIZONS),
        "items": evaluated,
        "observed_horizon_count": observed,
        "formal_authoritative_directional_hits": _formal_directional_hits(evaluated),
        "calendar_evidence_refs": calendar["refs"],
        "limitations": [
            "hypothetical_unadjusted_price_move_only",
            "excludes_fees_dividends_slippage_and_execution",
            "daily_ingestion_receipts_do_not_prove_exact_available_at",
        ],
        "read_only": True,
        "provider_contacted": False,
        "authorizes_execution": False,
    }


def _evaluate_item(
    item: Mapping[str, Any],
    *,
    scans: Mapping[str, Mapping[str, Any]],
    previews: Mapping[str, Mapping[str, Any]],
    app_path: Path | None,
    market_root: Path,
    receipts: CandidateOutcomeReceiptReader,
    snapshot_replays: dict[str, bool],
    calendar: dict[str, Any],
    as_of: date,
) -> dict[str, Any]:
    kind = str(item.get("kind") or "")
    symbol = str(item.get("symbol") or "")
    source_ref = str(item.get("source_ref") or "")
    if not source_ref or not symbol or not symbol.isdigit() or len(symbol) != 6:
        return _unavailable_item(item, "candidate_identity_invalid")
    if calendar["error"]:
        return _unavailable_item(item, calendar["error"])
    if kind == "research_preview":
        preview = previews.get(str(item.get("run_id") or ""))
        anchor, reason = _research_anchor(
            item,
            preview=preview,
            app_path=app_path,
            market_root=market_root,
            receipts=receipts,
            snapshot_replays=snapshot_replays,
        )
        decision_day = _date(item.get("market_date"))
    else:
        scan = scans.get(str(item.get("scan_run_id") or ""))
        anchor, reason = _formal_anchor(item, scan=scan, receipts=receipts)
        decision_day = _date(item.get("decision_date"))
    if reason is not None or anchor is None:
        return _unavailable_item(item, reason or "candidate_anchor_unavailable")
    if decision_day is None:
        return _unavailable_item(item, "candidate_decision_date_invalid")

    future_sessions = [day for day in calendar["sessions"] if day > decision_day]
    entry_date = future_sessions[0] if future_sessions else None
    if entry_date is None:
        return _unavailable_item(item, "next_verified_session_unavailable")
    entry, entry_reason = (
        receipts.bar(entry_date, symbol=symbol, provider=anchor["provider"])
        if entry_date <= as_of
        else (None, "entry_session_not_reached")
    )
    horizons: dict[str, dict[str, Any]] = {}
    for n in _HORIZONS:
        key = f"T+{n}"
        target_date = future_sessions[n - 1] if len(future_sessions) >= n else None
        if target_date is None:
            horizons[key] = _horizon_unavailable("verified_horizon_calendar_missing")
            continue
        if target_date > as_of:
            horizons[key] = {
                **_horizon_unavailable("horizon_session_not_reached"),
                "status": "pending",
                "session_date": target_date.isoformat(),
            }
            continue
        if entry_reason is not None or entry is None:
            horizons[key] = _horizon_unavailable(
                entry_reason or "entry_bar_unavailable"
            )
            continue
        target, target_reason = receipts.bar(
            target_date,
            symbol=symbol,
            provider=anchor["provider"],
        )
        if target_reason is not None or target is None:
            horizons[key] = _horizon_unavailable(
                target_reason or "horizon_bar_unavailable"
            )
            continue
        entry_open = _positive_decimal(entry["open"])
        target_close = _positive_decimal(target["close"])
        if entry_open is None or target_close is None:
            horizons[key] = _horizon_unavailable("horizon_price_invalid")
            continue
        move = (target_close / entry_open - 1) * 100
        horizons[key] = {
            "status": "observed",
            "entry_session_date": entry_date.isoformat(),
            "session_date": target_date.isoformat(),
            "entry_open": str(entry_open),
            "horizon_close": str(target_close),
            "price_move_pct": float(move),
            "provider": anchor["provider"],
            "entry_receipt_fingerprint": entry["receipt_fingerprint"],
            "horizon_receipt_fingerprint": target["receipt_fingerprint"],
            "entry_ingested_at_local": entry["ingested_at_local"],
            "horizon_ingested_at_local": target["ingested_at_local"],
            "available_at": None,
            "available_at_verified": False,
        }
    return {
        "source_ref": source_ref,
        "kind": kind,
        "symbol": symbol,
        "direction": item.get("direction") or item.get("operation"),
        "report_authoritative": item.get("report_authoritative") is True,
        "anchor_status": "verified",
        "anchor": anchor,
        "horizons": horizons,
        "price_move_is_execution_pnl": False,
    }


def _formal_anchor(
    item: Mapping[str, Any],
    *,
    scan: Mapping[str, Any] | None,
    receipts: CandidateOutcomeReceiptReader,
) -> tuple[dict[str, Any] | None, str | None]:
    if (
        scan is None
        or scan.get("integrity_valid") is not True
        or scan.get("status") != "completed"
        or (
            item.get("kind") == "account_blocked_signal"
            and item.get("source_bound") is not True
        )
    ):
        return None, "formal_scan_evidence_unverified"
    market_day = _date(item.get("frozen_market_date"))
    if market_day is None or str(scan.get("market_date")) != market_day.isoformat():
        return None, "formal_anchor_market_date_mismatch"
    fingerprints = scan.get("receipt_fingerprints")
    if not isinstance(fingerprints, list) or not fingerprints:
        return None, "formal_scan_receipt_binding_missing"
    frozen_close = _positive_decimal(item.get("frozen_price"))
    if frozen_close is None:
        return None, "formal_frozen_price_invalid"
    anchor, reason = receipts.anchor(
        market_day,
        symbol=str(item["symbol"]),
        allowed_fingerprints=set(fingerprints),
    )
    if reason is not None or anchor is None:
        return None, reason
    if _positive_decimal(anchor["close"]) != frozen_close:
        return None, "formal_frozen_price_receipt_mismatch"
    return anchor, None


def _research_anchor(
    item: Mapping[str, Any],
    *,
    preview: Mapping[str, Any] | None,
    app_path: Path | None,
    market_root: Path,
    receipts: CandidateOutcomeReceiptReader,
    snapshot_replays: dict[str, bool],
) -> tuple[dict[str, Any] | None, str | None]:
    if preview is None or app_path is None:
        return None, "research_selection_evidence_unavailable"
    if (
        preview.get("status") == "unavailable"
        or preview.get("selection_id") != item.get("selection_id")
        or preview.get("dataset_snapshot_id") != item.get("dataset_snapshot_id")
        or preview.get("formula_fingerprint") != item.get("formula_fingerprint")
    ):
        return None, "research_preview_binding_invalid"
    candidate_id = str(preview.get("research_winner_candidate_id") or "")
    run_id = str(preview.get("run_id") or "")
    if not candidate_id or not run_id:
        return None, "research_candidate_identity_missing"
    try:
        row = read_research_candidate_payloads(
            app_path, run_id=run_id, candidate_id=candidate_id
        )
    except CandidateOutcomeStoreUnavailable:
        return None, "research_backtest_evidence_unreadable"
    if row is None:
        return None, "research_backtest_result_missing"
    try:
        comparison = json.loads(row[0])
        metrics = json.loads(row[1])
    except (TypeError, ValueError):
        return None, "research_backtest_evidence_invalid"
    if not isinstance(comparison, dict) or not isinstance(metrics, dict):
        return None, "research_backtest_evidence_invalid"
    snapshot = metrics.get("dataset_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_id") != item.get(
        "dataset_snapshot_id"
    ):
        return None, "research_snapshot_identity_mismatch"
    original_preview = metrics.get("normalized_research_operation_preview")
    operations = (
        original_preview.get("operations")
        if isinstance(original_preview, dict)
        else None
    )
    if (
        not isinstance(operations, list)
        or not any(
            isinstance(operation, dict)
            and operation.get("symbol") == item.get("symbol")
            and operation.get("operation") == item.get("operation")
            and operation.get("signal_date") == item.get("signal_date")
            for operation in operations
        )
        or comparison.get("normalized_research_operation_preview") != original_preview
    ):
        return None, "research_operation_backtest_mismatch"
    binding = snapshot.get("market_data_binding")
    if not isinstance(binding, dict):
        return None, "research_snapshot_source_unbound"
    refs = binding.get("receipts")
    if not isinstance(refs, list) or not refs:
        return None, "research_snapshot_source_unbound"
    providers = {
        str(ref.get("provider_name") or "") for ref in refs if isinstance(ref, dict)
    }
    if len(providers) != 1 or not next(iter(providers)):
        return None, "research_snapshot_provider_ambiguous"
    snapshot_id = str(snapshot["snapshot_id"])
    if snapshot_id not in snapshot_replays:
        try:
            replay = replay_research_dataset_snapshot(snapshot, market_root=market_root)
        except (OSError, ValueError, CandidateOutcomeStoreUnavailable):
            replay = {"status": "blocked"}
        snapshot_replays[snapshot_id] = replay.get("status") == "pass"
    if not snapshot_replays[snapshot_id]:
        return None, "research_snapshot_replay_failed"
    market_day = _date(item.get("signal_date"))
    if market_day is None or market_day != _date(item.get("market_date")):
        return None, "research_anchor_market_date_mismatch"
    matching_refs = [
        ref
        for ref in refs
        if isinstance(ref, dict) and ref.get("trade_date") == market_day.isoformat()
    ]
    if len(matching_refs) != 1:
        return None, "research_anchor_receipt_binding_missing"
    anchor, reason = receipts.anchor(
        market_day,
        symbol=str(item["symbol"]),
        allowed_fingerprints={str(matching_refs[0].get("receipt_fingerprint") or "")},
    )
    if reason is not None or anchor is None:
        return None, reason
    if anchor["provider"] != next(iter(providers)):
        return None, "research_snapshot_provider_mismatch"
    return {**anchor, "dataset_snapshot_id": snapshot["snapshot_id"]}, None


def _verified_sessions(db: Any, start: date, end: date) -> dict[str, Any]:
    sessions: list[date] = []
    refs: list[str] = []
    for year in range(start.year, end.year + 1):
        reader = getattr(db, "get_market_calendar_snapshot_sync", None)
        row = reader(exchange="SSE", year=year) if callable(reader) else None
        validation = validate_verified_market_calendar(row)
        if not validation.verified:
            return {
                "sessions": [],
                "refs": refs,
                "error": f"verified_calendar_unavailable:{year}",
            }
        raw = row.get("days") or row.get("days_json")
        try:
            days = raw if isinstance(raw, list) else json.loads(str(raw))
        except (TypeError, ValueError):
            days = []
        refs.append(str(validation.evidence_ref))
        sessions.extend(
            day
            for item in days
            if isinstance(item, dict)
            and item.get("is_trading_day") is True
            and (day := _date(item.get("date"))) is not None
            and start < day
        )
    return {"sessions": sorted(sessions), "refs": refs, "error": None}


def _unavailable_item(item: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source_ref": item.get("source_ref"),
        "kind": item.get("kind"),
        "symbol": item.get("symbol"),
        "direction": item.get("direction") or item.get("operation"),
        "report_authoritative": item.get("report_authoritative") is True,
        "anchor_status": "unavailable",
        "anchor": None,
        "reason_code": reason,
        "horizons": {f"T+{n}": _horizon_unavailable(reason) for n in _HORIZONS},
        "price_move_is_execution_pnl": False,
    }


def _horizon_unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason_code": reason}


def _formal_directional_hits(items: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for n in _HORIZONS:
        key = f"T+{n}"
        observed = [
            item
            for item in items
            if item["kind"] == "formal_signal"
            and item["report_authoritative"] is True
            and item["direction"] in {"buy", "sell"}
            and item["horizons"][key]["status"] == "observed"
        ]
        hits = sum(
            (item["horizons"][key]["price_move_pct"] > 0)
            if item["direction"] == "buy"
            else (item["horizons"][key]["price_move_pct"] < 0)
            for item in observed
        )
        result[key] = {
            "observed_count": len(observed),
            "directional_hit_count": hits,
            "directional_hit_rate": hits / len(observed) if observed else None,
        }
    return result


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


__all__ = ["evaluate_daily_candidate_outcomes"]
