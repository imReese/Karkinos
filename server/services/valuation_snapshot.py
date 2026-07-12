"""Content-addressed valuation snapshots built only from persisted facts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

VALUATION_POLICY_VERSION = "karkinos.persisted_valuation.v2"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MIN_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


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


def load_persisted_quote_rows(db: Any) -> list[dict[str, Any]]:
    """Load persisted quote facts without consulting runtime caches."""
    if db is None:
        return []
    rows: list[dict[str, Any]] = []
    if hasattr(db, "list_latest_quotes_sync"):
        rows.extend(dict(row) for row in (db.list_latest_quotes_sync() or []))
    if hasattr(db, "list_quote_snapshots_sync"):
        rows.extend(dict(row) for row in (db.list_quote_snapshots_sync() or []))
    elif hasattr(db, "get_latest_quotes_sync"):
        rows.extend(dict(row) for row in (db.get_latest_quotes_sync() or []))
    return rows


def _quote_identity(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("symbol") or ""),
        str(row.get("asset_type") or row.get("asset_class") or "stock"),
    )


def _quote_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("quote_timestamp") or row.get("timestamp") or "")


def _parse_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return _MIN_TIMESTAMP
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _MIN_TIMESTAMP
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(timezone.utc)


def _quote_rank(row: dict[str, Any]) -> tuple[datetime, datetime, int]:
    return (
        _parse_timestamp(_quote_timestamp(row)),
        _parse_timestamp(row.get("captured_at") or row.get("created_at")),
        int(row.get("id") or 0),
    )


def select_authoritative_quote_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select one newest persisted observation for each instrument identity."""
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        identity = _quote_identity(row)
        if not identity[0]:
            continue
        existing = selected.get(identity)
        if existing is None or _quote_rank(row) > _quote_rank(existing):
            selected[identity] = dict(row)
    return [selected[key] for key in sorted(selected)]


def _freeze_previous_close_evidence(
    db: Any, quotes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Bind every quote to the exact persisted baseline used for daily PnL."""
    frozen: list[dict[str, Any]] = []
    for raw in quotes:
        quote = dict(raw)
        symbol = str(quote.get("symbol") or "")
        quote_timestamp = _parse_timestamp(_quote_timestamp(quote))
        trade_date = (
            None
            if quote_timestamp == _MIN_TIMESTAMP
            else quote_timestamp.astimezone(_SHANGHAI_TZ).date().isoformat()
        )
        evidence: dict[str, Any] | None = None
        if symbol and trade_date and db is not None:
            if hasattr(db, "get_market_bar_on_date_sync"):
                same_day_bar = db.get_market_bar_on_date_sync(symbol, trade_date)
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
                row = db.get_latest_market_bar_before_date_sync(symbol, trade_date)
                if row and row.get("close", row.get("price")) not in {None, ""}:
                    evidence = {
                        "price": float(row.get("close", row.get("price"))),
                        "trade_date": row.get("trade_date")
                        or str(row.get("timestamp") or "").split("T")[0],
                        "source": "market_bar_close",
                        "observation_source": row.get("source") or "market_bars",
                    }
            if evidence is None and hasattr(db, "get_latest_daily_close_before_sync"):
                row = db.get_latest_daily_close_before_sync(symbol, trade_date)
                if row and row.get("close_price") not in {None, ""}:
                    evidence = {
                        "price": float(row["close_price"]),
                        "trade_date": row.get("trade_date"),
                        "source": "daily_close",
                        "observation_source": row.get("source")
                        or "daily_close_snapshots",
                    }
            if evidence is None and hasattr(db, "get_latest_quote_before_date_sync"):
                row = db.get_latest_quote_before_date_sync(symbol, trade_date)
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
        frozen.append(quote)
    return frozen


def _load_ledger_rows(db: Any, batch_size: int = 500) -> list[dict[str, Any]]:
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
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("id") or 0),
            _parse_timestamp(row.get("timestamp")),
        ),
    )


def _snapshot_status(quotes: list[dict[str, Any]]) -> str:
    if not quotes:
        return "missing"
    statuses = {
        str(row.get("quote_status") or "live").strip().lower() for row in quotes
    }
    if statuses & {"missing", "error"}:
        return "missing"
    if statuses & {"stale", "estimated", "confirmed_nav_missing"}:
        return "degraded"
    return "complete"


def _snapshot_as_of(
    quotes: list[dict[str, Any]], ledger_rows: list[dict[str, Any]]
) -> str:
    candidates = [
        *(_quote_timestamp(row) for row in quotes),
        *(str(row.get("timestamp") or "") for row in ledger_rows),
    ]
    parsed_candidates = [_parse_timestamp(value) for value in candidates if value]
    effective = max(parsed_candidates, default=_parse_timestamp("1970-01-01T00:00:00Z"))
    return effective.astimezone(_SHANGHAI_TZ).isoformat()


def _snapshot_trade_date(quotes: list[dict[str, Any]], as_of: str) -> str:
    quote_timestamps = [
        _parse_timestamp(_quote_timestamp(row))
        for row in quotes
        if _quote_timestamp(row)
    ]
    effective = max(quote_timestamps, default=_parse_timestamp(as_of))
    return effective.astimezone(_SHANGHAI_TZ).date().isoformat()


def build_current_valuation_snapshot(
    db: Any,
    *,
    valuation_policy: str = VALUATION_POLICY_VERSION,
    persist: bool = True,
) -> dict[str, Any]:
    """Build and persist an immutable valuation identity from database facts."""
    quotes = _freeze_previous_close_evidence(
        db,
        select_authoritative_quote_rows(load_persisted_quote_rows(db)),
    )
    ledger_rows = _load_ledger_rows(db)
    quote_set_fingerprint = _fingerprint(quotes)
    ledger_fingerprint = _fingerprint(ledger_rows)
    ledger_ids = [int(row["id"]) for row in ledger_rows if row.get("id") is not None]
    ledger_cutoff_id = max(ledger_ids, default=0)
    as_of = _snapshot_as_of(quotes, ledger_rows)
    trade_date = _snapshot_trade_date(quotes, as_of)
    identity_payload = {
        "valuation_policy": valuation_policy,
        "quote_set_fingerprint": quote_set_fingerprint,
        "ledger_fingerprint": ledger_fingerprint,
        "ledger_cutoff_id": ledger_cutoff_id,
    }
    snapshot_id = f"valuation-{_fingerprint(identity_payload)}"
    payload = {
        "snapshot_id": snapshot_id,
        "as_of": as_of,
        "trade_date": trade_date,
        "valuation_policy": valuation_policy,
        "ledger_cutoff_id": ledger_cutoff_id,
        "ledger_fingerprint": ledger_fingerprint,
        "quote_set_fingerprint": quote_set_fingerprint,
        "status": _snapshot_status(quotes),
        "quotes": quotes,
        "metadata": {
            "quote_count": len(quotes),
            "ledger_entry_count": len(ledger_rows),
            "persisted_facts_only": True,
            "runtime_cache_used": False,
            "provider_fetch_used": False,
            "ingestion_run_ids": sorted(
                {str(row["fetch_run_id"]) for row in quotes if row.get("fetch_run_id")}
            ),
        },
    }
    if persist and db is not None and hasattr(db, "save_valuation_snapshot_sync"):
        db.save_valuation_snapshot_sync(payload)
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
    return {
        "snapshot_id": row["snapshot_id"],
        "as_of": row["as_of"],
        "trade_date": row["trade_date"],
        "valuation_policy": row["valuation_policy"],
        "ledger_cutoff_id": int(row.get("ledger_cutoff_id") or 0),
        "ledger_fingerprint": row["ledger_fingerprint"],
        "quote_set_fingerprint": row["quote_set_fingerprint"],
        "status": row["status"],
        "quotes": json.loads(row.get("quotes_json") or "[]"),
        "metadata": json.loads(row.get("metadata_json") or "{}"),
        "created_at": row["created_at"],
    }
