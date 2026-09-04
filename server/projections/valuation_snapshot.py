"""Content-addressed valuation projections built only from persisted facts."""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from data.market_data import is_fund_estimate_quote_source
from server.contracts.quote_ingestion import (
    quote_authority_conflict_fields,
    quote_timestamp_instant,
)
from server.ledger.models import LedgerEntry
from server.projections.quote_status import (
    expected_quote_date,
    parse_quote_timestamp,
    quote_is_stale,
    quote_valuation_status,
)
from server.projections.service import build_portfolio_projection
from server.services.market_hours import get_shanghai_now
from server.services.position_presence import is_economically_zero_quantity
from server.valuation_snapshot_contract import validate_valuation_snapshot

VALUATION_POLICY_VERSION = "karkinos.persisted_valuation.v5"
_VALUATION_SCOPE_POLICY = "current_nonzero_positions.v1"
_VALUATION_FRESHNESS_POLICY = "expected_session_and_live_ttl.v1"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MIN_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)
_UNCONFIRMED_FUND_ESTIMATE_REASON = "confirmed_fund_nav_missing_estimate_only"
_VALUATION_LANE_ASSET_CLASSES = ("stock", "fund")
_MISSING_QUOTE_STATUSES = {"missing", "error"}
_DEGRADED_QUOTE_STATUSES = {"stale", "estimated", "confirmed_nav_missing"}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _valuation_snapshot_identity_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return the complete v5 content-addressed identity payload."""

    return {
        "valuation_policy": payload["valuation_policy"],
        "as_of": payload["as_of"],
        "trade_date": payload["trade_date"],
        "status": payload["status"],
        "ledger_cutoff_id": int(payload.get("ledger_cutoff_id") or 0),
        "ledger_fingerprint": payload["ledger_fingerprint"],
        "quote_set_fingerprint": payload["quote_set_fingerprint"],
        "metadata": payload["metadata"],
    }


def load_persisted_quote_rows(db: Any) -> list[dict[str, Any]]:
    """Load only the persisted current-quote materialization."""
    if db is None:
        return []
    candidate_reader = getattr(db, "list_quote_selection_candidates_sync", None)
    if callable(candidate_reader):
        return [dict(row) for row in (candidate_reader() or [])]
    current_reader = getattr(db, "list_latest_quotes_sync", None)
    if callable(current_reader):
        return [dict(row) for row in (current_reader() or [])]
    raise RuntimeError("persisted current quote materialization is unavailable")


def _quote_identity(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("symbol") or ""),
        _normalized_instrument_type(
            row.get("instrument_type")
            or row.get("asset_type")
            or row.get("asset_class")
            or "stock"
        ),
    )


def _quote_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("quote_timestamp") or row.get("timestamp") or "")


def _parse_timestamp(value: Any) -> datetime:
    return quote_timestamp_instant(value)


def _quote_rank(row: dict[str, Any]) -> tuple[datetime, int, datetime, int, str]:
    is_latest_projection = int(
        "asset_type" in row and "quote_timestamp" in row and "updated_at" in row
    )
    return (
        _parse_timestamp(_quote_timestamp(row)),
        is_latest_projection,
        _parse_timestamp(
            row.get("captured_at") or row.get("updated_at") or row.get("created_at")
        ),
        int(row.get("id") or 0),
        _canonical_json(row),
    )


def select_authoritative_quote_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select one newest persisted observation for each instrument identity."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        identity = _quote_identity(row)
        if not identity[0]:
            continue
        grouped.setdefault(identity, []).append(dict(row))

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for identity, observations in grouped.items():
        by_instant: dict[datetime, list[dict[str, Any]]] = {}
        for observation in observations:
            by_instant.setdefault(
                _parse_timestamp(_quote_timestamp(observation)), []
            ).append(observation)
        newest_instant = max(by_instant)
        newest_observations = by_instant[newest_instant]
        for left, right in itertools.combinations(newest_observations, 2):
            conflict_fields = quote_authority_conflict_fields(left, right)
            if conflict_fields:
                raise ValueError(
                    "quote authority facts conflict at the same timestamp "
                    f"for {identity[0]}/{identity[1]} at "
                    f"{newest_instant.isoformat()}: " + ",".join(conflict_fields)
                )
        selected[identity] = max(newest_observations, key=_quote_rank)
    return [selected[key] for key in sorted(selected)]


def _account_valuation_quote_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Exclude non-investable market context from account valuation facts."""
    return [
        row
        for row in rows
        if str(row.get("asset_type") or row.get("asset_class") or "stock")
        .strip()
        .lower()
        != "index"
    ]


def _freeze_previous_close_evidence(
    db: Any,
    quotes: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Bind every quote to the exact persisted baseline used for daily PnL."""
    frozen: list[dict[str, Any]] = []
    for raw in quotes:
        quote = dict(raw)
        symbol = str(quote.get("symbol") or "")
        quote_timestamp = _parse_timestamp(_quote_timestamp(quote))
        if quote_timestamp == _MIN_TIMESTAMP:
            quote["quote_status"] = "error"
            quote["stale_reason"] = "invalid_quote_timestamp"
            quote["valuation_evidence_status"] = "invalid_timestamp"
        trade_date = (
            None
            if quote_timestamp == _MIN_TIMESTAMP
            else quote_timestamp.astimezone(_SHANGHAI_TZ).date().isoformat()
        )
        asset_class = (
            str(quote.get("asset_type") or quote.get("asset_class") or "")
            .strip()
            .lower()
        )
        instrument_type = _normalized_instrument_type(
            quote.get("instrument_type") or asset_class
        )
        evidence: dict[str, Any] | None = None
        if symbol and trade_date and db is not None:
            same_day_close_available = trade_date < now.date().isoformat() or (
                trade_date == now.date().isoformat()
                and now.weekday() < 5
                and now.time() >= time(15, 0)
            )
            if (
                instrument_type != "open_end_fund"
                and same_day_close_available
                and hasattr(db, "get_market_bar_on_date_sync")
            ):
                same_day_bar = db.get_market_bar_on_date_sync(
                    symbol,
                    trade_date,
                    instrument_type=instrument_type,
                )
                if same_day_bar and same_day_bar.get(
                    "close", same_day_bar.get("price")
                ) not in {None, ""}:
                    quote["observed_price"] = quote.get("price")
                    quote["observed_timestamp"] = _quote_timestamp(quote)
                    quote["observed_quote_source"] = quote.get(
                        "quote_source"
                    ) or quote.get("source")
                    quote["observed_quote_status"] = quote.get("quote_status")
                    quote["price"] = float(
                        same_day_bar.get("close", same_day_bar.get("price"))
                    )
                    valuation_timestamp = f"{trade_date}T15:00:00+08:00"
                    quote["timestamp"] = valuation_timestamp
                    quote["quote_timestamp"] = valuation_timestamp
                    quote["quote_source"] = "market_bar_close"
                    quote["source"] = "market_bar_close"
                    quote["quote_status"] = "confirmed"
                    quote["valuation_price_source"] = "market_bar_close"
                    quote["valuation_price_date"] = trade_date
                    quote["valuation_price_timestamp"] = valuation_timestamp
            if hasattr(db, "get_latest_market_bar_before_date_sync"):
                row = db.get_latest_market_bar_before_date_sync(
                    symbol,
                    trade_date,
                    instrument_type=instrument_type,
                )
                if row and row.get("close", row.get("price")) not in {None, ""}:
                    evidence = {
                        "price": float(row.get("close", row.get("price"))),
                        "trade_date": row.get("trade_date")
                        or str(row.get("timestamp") or "").split("T")[0],
                        "source": "market_bar_close",
                        "observation_source": row.get("source") or "market_bars",
                    }
            if evidence is None and hasattr(db, "get_latest_daily_close_before_sync"):
                row = db.get_latest_daily_close_before_sync(
                    symbol,
                    trade_date,
                    instrument_type=instrument_type,
                )
                if row and row.get("close_price") not in {None, ""}:
                    evidence = {
                        "price": float(row["close_price"]),
                        "trade_date": row.get("trade_date"),
                        "source": "daily_close",
                        "observation_source": row.get("source")
                        or "daily_close_snapshots",
                    }
            if evidence is None and hasattr(db, "get_latest_quote_before_date_sync"):
                row = db.get_latest_quote_before_date_sync(
                    symbol,
                    trade_date,
                    instrument_type=instrument_type,
                )
                if row and row.get("price") not in {None, ""}:
                    evidence = {
                        "price": float(row["price"]),
                        "trade_date": str(
                            row.get("trade_date") or row.get("timestamp") or ""
                        ).split("T")[0],
                        "source": "fallback_close",
                        "observation_source": row.get("source")
                        or row.get("quote_source")
                        or "quote_snapshots",
                    }

        if evidence is not None:
            quote["previous_close"] = evidence["price"]
            quote["previous_close_date"] = evidence["trade_date"]
            quote["previous_close_source"] = evidence["source"]
            quote["previous_close_observation_source"] = evidence["observation_source"]
            quote["valuation_baseline_status"] = "complete"
        elif quote.get("previous_close") not in {None, ""}:
            quote["previous_close_source"] = (
                quote.get("previous_close_source") or "previous_close"
            )
            quote["valuation_baseline_status"] = "observed_without_close_row"
        else:
            quote["valuation_baseline_status"] = "missing"
        _mark_unconfirmed_fund_estimate(quote)
        frozen.append(quote)
    return frozen


def _mark_unconfirmed_fund_estimate(quote: dict[str, Any]) -> None:
    """Keep an estimate visible while preventing it from becoming authoritative."""
    asset_class = (
        str(quote.get("asset_type") or quote.get("asset_class") or "").strip().lower()
    )
    source = str(quote.get("quote_source") or quote.get("source") or "").strip().lower()
    if (
        asset_class != "fund"
        or not is_fund_estimate_quote_source(source)
        or quote.get("price") in {None, ""}
    ):
        return

    quote.setdefault("observed_quote_status", quote.get("quote_status"))
    quote["quote_status"] = "confirmed_nav_missing"
    quote["stale_reason"] = _UNCONFIRMED_FUND_ESTIMATE_REASON
    quote["valuation_price_source"] = source
    quote["valuation_evidence_status"] = "unconfirmed_estimate"


def _freeze_current_quote_freshness(
    quotes: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Freeze one wall-clock decision into otherwise persisted quote facts."""

    expected_date = expected_quote_date(now)
    frozen: list[dict[str, Any]] = []
    for raw in quotes:
        quote = dict(raw)
        if quote_valuation_status(quote) != "complete":
            frozen.append(quote)
            continue
        timestamp = parse_quote_timestamp(
            quote.get("quote_timestamp") or quote.get("timestamp")
        )
        stale_reason: str | None = None
        if timestamp is None:
            stale_reason = "invalid_quote_timestamp"
        elif timestamp > now + timedelta(minutes=1):
            stale_reason = "quote_timestamp_after_valuation_clock"
        elif quote_is_stale(
            {**quote, "timestamp": timestamp.isoformat()},
            now=now,
        ):
            stale_reason = (
                "quote_older_than_expected_session"
                if timestamp.date() < expected_date
                else "quote_older_than_live_ttl"
            )
        if stale_reason is not None:
            quote.setdefault("observed_quote_status", quote.get("quote_status"))
            quote["quote_status"] = "stale"
            quote["stale_reason"] = stale_reason
            quote["valuation_evidence_status"] = "stale"
        frozen.append(quote)
    return frozen


def _load_ledger_rows(
    db: Any,
    batch_size: int = 500,
    *,
    candidate_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return []
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = list(db.get_ledger_entries_sync(limit=batch_size, offset=offset) or [])
        rows.extend(dict(row) for row in batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    if candidate_rows:
        identified = {
            int(row["id"]): dict(row) for row in rows if row.get("id") is not None
        }
        unidentified = [dict(row) for row in rows if row.get("id") is None]
        for candidate in candidate_rows:
            row = dict(candidate)
            if row.get("id") is None:
                unidentified.append(row)
            else:
                identified[int(row["id"])] = row
        rows = [*identified.values(), *unidentified]
    return ledger_identity_from_rows(rows)["rows"]


def ledger_identity_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the canonical ledger cutoff/fingerprint from persisted rows."""

    normalized_rows = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            int(row.get("id") or 0),
            _parse_timestamp(row.get("timestamp")),
        ),
    )
    ledger_ids = [
        int(row["id"]) for row in normalized_rows if row.get("id") is not None
    ]
    return {
        "rows": normalized_rows,
        "ledger_cutoff_id": max(ledger_ids, default=0),
        "ledger_fingerprint": _fingerprint(normalized_rows),
    }


def _snapshot_status(quotes: list[dict[str, Any]]) -> str:
    if not quotes:
        return "complete"
    statuses = {quote_valuation_status(row) for row in quotes}
    if "missing" in statuses:
        return "missing"
    if "degraded" in statuses:
        return "degraded"
    return "complete"


def _valuation_lane_asset_class(quote: dict[str, Any]) -> str:
    asset_class = (
        str(quote.get("asset_type") or quote.get("asset_class") or "stock")
        .strip()
        .lower()
    )
    if asset_class in {*_VALUATION_LANE_ASSET_CLASSES, "etf"}:
        return asset_class
    return "other"


def _valuation_lane_blockers(quotes: list[dict[str, Any]]) -> list[str]:
    blockers: set[str] = set()
    for quote in quotes:
        quote_status = str(quote.get("quote_status") or "live").strip().lower()
        if quote_status in _MISSING_QUOTE_STATUSES | _DEGRADED_QUOTE_STATUSES:
            blockers.add(quote_status)
        if quote.get("valuation_baseline_status") == "missing":
            blockers.add("valuation_baseline_missing")
    return sorted(blockers)


def valuation_lanes_from_quotes(
    quotes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Summarize quote completeness by asset class under one snapshot identity."""

    grouped: dict[str, list[dict[str, Any]]] = {
        asset_class: [] for asset_class in _VALUATION_LANE_ASSET_CLASSES
    }
    for quote in quotes:
        grouped.setdefault(_valuation_lane_asset_class(quote), []).append(quote)

    ordered_asset_classes = [*_VALUATION_LANE_ASSET_CLASSES]
    if grouped.get("etf"):
        ordered_asset_classes.append("etf")
    if grouped.get("other"):
        ordered_asset_classes.append("other")

    lanes: list[dict[str, Any]] = []
    for asset_class in ordered_asset_classes:
        lane_quotes = grouped[asset_class]
        review_required_count = sum(
            quote_valuation_status(quote) != "complete" for quote in lane_quotes
        )
        lanes.append(
            {
                "asset_class": asset_class,
                "status": (
                    _snapshot_status(lane_quotes) if lane_quotes else "not_applicable"
                ),
                "quote_count": len(lane_quotes),
                "complete_quote_count": len(lane_quotes) - review_required_count,
                "review_required_quote_count": review_required_count,
                "blocker_statuses": _valuation_lane_blockers(lane_quotes),
            }
        )
    return lanes


def _normalized_instrument_type(value: Any) -> str:
    normalized = str(value or "stock").strip().lower().replace("-", "_")
    if normalized in {"fund", "openend_fund"}:
        return "open_end_fund"
    return normalized


def _current_position_scope(
    ledger_rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Resolve canonical non-zero holdings from the same ledger rows we hash."""

    entries = [LedgerEntry.from_row(row) for row in ledger_rows]
    projection = build_portfolio_projection(entries, latest_quotes={})
    evidence: dict[str, list[str]] = {}
    for row in ledger_rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        evidence.setdefault(symbol, []).append(
            _normalized_instrument_type(row.get("asset_class"))
        )
    return {
        symbol: _resolve_position_instrument_type(symbol, evidence.get(symbol, ()))
        for symbol, position in projection.positions.items()
        if not is_economically_zero_quantity(position.quantity)
    }


def _resolve_position_instrument_type(
    symbol: str,
    values: list[str] | tuple[str, ...],
) -> str:
    explicit = {value for value in values if value != "fund"}
    has_legacy_fund = "fund" in values
    if len(explicit) > 1:
        kinds = ",".join(sorted(explicit))
        raise ValueError(
            f"authoritative instrument identity conflicts for {symbol}: {kinds}"
        )
    if explicit:
        resolved = next(iter(explicit))
        if has_legacy_fund and resolved not in {"etf", "open_end_fund"}:
            raise ValueError(
                f"authoritative instrument identity conflicts for {symbol}: "
                f"{resolved},fund"
            )
        return resolved
    if has_legacy_fund:
        return "open_end_fund"
    return "stock"


def _valuation_asset_type(instrument_type: str) -> str:
    return "fund" if instrument_type == "open_end_fund" else instrument_type


def _quotes_for_current_positions(
    quotes: list[dict[str, Any]],
    position_scope: dict[str, str],
) -> list[dict[str, Any]]:
    """Keep exactly one matching observation or an explicit missing row per holding."""

    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for quote in quotes:
        identity = (
            str(quote.get("symbol") or "").strip(),
            _normalized_instrument_type(
                quote.get("instrument_type")
                or quote.get("asset_type")
                or quote.get("asset_class")
            ),
        )
        candidates[identity] = quote

    scoped: list[dict[str, Any]] = []
    for symbol, instrument_type in sorted(position_scope.items()):
        quote = candidates.get((symbol, instrument_type))
        # Legacy rows used ``fund`` for open-end funds.  An ETF must retain an
        # explicit ETF identity; otherwise a same-symbol fund observation could
        # silently satisfy the wrong valuation lane.
        if quote is None and instrument_type == "open_end_fund":
            quote = candidates.get((symbol, "fund"))
        if quote is None:
            scoped.append(
                {
                    "symbol": symbol,
                    "asset_type": _valuation_asset_type(instrument_type),
                    "quote_status": "missing",
                    "stale_reason": "holding_quote_missing",
                    "valuation_baseline_status": "missing",
                    "valuation_evidence_status": "missing",
                }
            )
            continue
        scoped.append(
            {
                **quote,
                "observation_instrument_type": _normalized_instrument_type(
                    quote.get("instrument_type")
                    or quote.get("asset_type")
                    or quote.get("asset_class")
                ),
                "asset_type": _valuation_asset_type(instrument_type),
            }
        )
    return scoped


def _snapshot_as_of(
    quotes: list[dict[str, Any]], ledger_rows: list[dict[str, Any]]
) -> str:
    candidates = [
        *(_quote_timestamp(row) for row in quotes),
        *(str(row.get("timestamp") or "") for row in ledger_rows),
    ]
    parsed_candidates = [
        parsed
        for value in candidates
        if value and (parsed := _parse_timestamp(value)) != _MIN_TIMESTAMP
    ]
    effective = max(parsed_candidates, default=_parse_timestamp("1970-01-01T00:00:00Z"))
    return effective.astimezone(_SHANGHAI_TZ).isoformat()


def _snapshot_trade_date(quotes: list[dict[str, Any]], as_of: str) -> str:
    quote_timestamps = [
        parsed
        for row in quotes
        if _quote_timestamp(row)
        and (parsed := _parse_timestamp(_quote_timestamp(row))) != _MIN_TIMESTAMP
    ]
    effective = max(quote_timestamps, default=_parse_timestamp(as_of))
    return effective.astimezone(_SHANGHAI_TZ).date().isoformat()


def build_current_valuation_snapshot(
    db: Any,
    *,
    valuation_policy: str = VALUATION_POLICY_VERSION,
    persist: bool = False,
    candidate_ledger_rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an immutable valuation identity, persisting only when requested."""
    frozen_now = get_shanghai_now(now)
    valuation_expected_date = expected_quote_date(frozen_now).isoformat()
    ledger_identity = ledger_identity_from_rows(
        _load_ledger_rows(db, candidate_rows=candidate_ledger_rows)
    )
    ledger_rows = ledger_identity["rows"]
    persisted_quote_rows = load_persisted_quote_rows(db)
    selected_quotes = select_authoritative_quote_rows(
        _account_valuation_quote_rows(persisted_quote_rows)
    )
    position_scope = _current_position_scope(ledger_rows)
    position_scope_fingerprint = _fingerprint(position_scope)
    scoped_quotes = _quotes_for_current_positions(selected_quotes, position_scope)
    observed_quotes = [
        quote for quote in scoped_quotes if quote.get("quote_status") != "missing"
    ]
    missing_quotes = [
        quote for quote in scoped_quotes if quote.get("quote_status") == "missing"
    ]
    quotes = _freeze_current_quote_freshness(
        [
            *_freeze_previous_close_evidence(db, observed_quotes, now=frozen_now),
            *missing_quotes,
        ],
        now=frozen_now,
    )
    quote_set_fingerprint = _fingerprint(quotes)
    ledger_fingerprint = ledger_identity["ledger_fingerprint"]
    ledger_cutoff_id = ledger_identity["ledger_cutoff_id"]
    as_of = _snapshot_as_of(quotes, ledger_rows)
    trade_date = _snapshot_trade_date(quotes, as_of)
    metadata = {
        "quote_count": len(quotes),
        "current_position_count": len(position_scope),
        "valuation_scope_policy": _VALUATION_SCOPE_POLICY,
        "valuation_freshness_policy": _VALUATION_FRESHNESS_POLICY,
        "valuation_expected_date": valuation_expected_date,
        "current_position_scope_fingerprint": position_scope_fingerprint,
        "ledger_entry_count": len(ledger_rows),
        "persisted_facts_only": True,
        "runtime_cache_used": False,
        "provider_fetch_used": False,
        "ingestion_run_ids": sorted(
            {str(row["fetch_run_id"]) for row in quotes if row.get("fetch_run_id")}
        ),
    }
    payload = {
        "as_of": as_of,
        "trade_date": trade_date,
        "valuation_policy": valuation_policy,
        "ledger_cutoff_id": ledger_cutoff_id,
        "ledger_fingerprint": ledger_fingerprint,
        "quote_set_fingerprint": quote_set_fingerprint,
        "status": _snapshot_status(quotes),
        "valuation_lanes": valuation_lanes_from_quotes(quotes),
        "quotes": quotes,
        "metadata": metadata,
    }
    payload["snapshot_id"] = (
        f"valuation-{_fingerprint(_valuation_snapshot_identity_payload(payload))}"
    )
    if persist:
        raise RuntimeError(
            "valuation projections are read-only; publish through the service boundary"
        )
    return payload


def valuation_identity_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the shared identity fields embedded in financial projections."""
    return {
        "valuation_snapshot_id": payload["snapshot_id"],
        "valuation_as_of": payload["as_of"],
        "valuation_trade_date": payload["trade_date"],
        "valuation_policy": payload["valuation_policy"],
        "valuation_status": payload["status"],
        "ledger_cutoff_id": int(payload.get("ledger_cutoff_id") or 0),
        "ledger_fingerprint": payload["ledger_fingerprint"],
        "quote_set_fingerprint": payload["quote_set_fingerprint"],
    }


def valuation_snapshot_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialize one persisted valuation snapshot row for API use."""
    quotes = json.loads(row.get("quotes_json") or "[]")
    payload = {
        "snapshot_id": row["snapshot_id"],
        "as_of": row["as_of"],
        "trade_date": row["trade_date"],
        "valuation_policy": row["valuation_policy"],
        "ledger_cutoff_id": int(row.get("ledger_cutoff_id") or 0),
        "ledger_fingerprint": row["ledger_fingerprint"],
        "quote_set_fingerprint": row["quote_set_fingerprint"],
        "status": row["status"],
        "valuation_lanes": valuation_lanes_from_quotes(quotes),
        "quotes": quotes,
        "metadata": json.loads(row.get("metadata_json") or "{}"),
        "created_at": row["created_at"],
    }
    validate_valuation_snapshot(payload)
    return payload


__all__ = [
    "VALUATION_POLICY_VERSION",
    "build_current_valuation_snapshot",
    "ledger_identity_from_rows",
    "load_persisted_quote_rows",
    "quote_valuation_status",
    "select_authoritative_quote_rows",
    "valuation_identity_fields",
    "valuation_lanes_from_quotes",
    "valuation_snapshot_from_row",
    "validate_valuation_snapshot",
]
