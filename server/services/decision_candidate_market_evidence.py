"""Exact persisted market evidence for one Decision candidate batch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.types import InstrumentKey
from data.market_data import is_fund_estimate_quote_source
from server.projections.quote_status import quote_status
from server.services.valuation_snapshot import (
    load_persisted_quote_rows,
    select_authoritative_quote_rows,
)


def candidate_market_evidence(
    db: Any,
    tasks: list[dict[str, Any]],
    *,
    state: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve exact persisted quotes without widening account valuation scope."""

    required, invalid_tasks = _required_instruments(tasks)
    ambiguous_symbols = sorted(
        symbol
        for symbol in {key.symbol for key in required}
        if len({key.instrument_type for key in required if key.symbol == symbol}) > 1
    )
    try:
        persisted_rows = load_persisted_quote_rows(db)
        relevant_rows = []
        for raw_row in persisted_rows:
            try:
                if _row_instrument(raw_row) in required:
                    relevant_rows.append(dict(raw_row))
            except (TypeError, ValueError):
                continue
        selected_rows = select_authoritative_quote_rows(relevant_rows)
    except (RuntimeError, ValueError):
        return _result(
            source_status="unavailable",
            required=required,
            quotes={},
            persisted_row_fingerprints={},
            invalid_tasks=invalid_tasks,
            ambiguous_symbols=ambiguous_symbols,
        )

    available: dict[InstrumentKey, dict[str, Any]] = {}
    persisted_row_fingerprints: dict[InstrumentKey, str] = {}
    for raw_row in selected_rows:
        row = dict(raw_row)
        try:
            key = _row_instrument(row)
        except (TypeError, ValueError):
            continue
        if key in required:
            persisted_row_fingerprints[key] = _persisted_row_fingerprint(row)
            row["instrument_type"] = key.instrument_type.value
            row["asset_class"] = (
                "fund"
                if key.instrument_type.value == "open_end_fund"
                else key.instrument_type.value
            )
            _freeze_candidate_freshness(row, key=key, state=state, now=now)
            available[key] = row

    quotes = {
        key.symbol: available[key]
        for key in sorted(required, key=lambda value: value.storage_tuple())
        if key in available and key.symbol not in ambiguous_symbols
    }
    return _result(
        source_status="persisted_current_quotes",
        required=required,
        quotes=quotes,
        persisted_row_fingerprints=persisted_row_fingerprints,
        invalid_tasks=invalid_tasks,
        ambiguous_symbols=ambiguous_symbols,
    )


def bind_candidate_market_evidence(
    portfolio_context: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Bind a separate exact candidate map without changing account valuation."""

    account_quotes = dict(portfolio_context.get("quotes") or {})
    candidate_quotes = dict(evidence.get("quotes") or {})
    conflicts = set(evidence.get("ambiguous_symbols") or [])
    bound_authority: dict[str, str] = {}
    for symbol, candidate in list(candidate_quotes.items()):
        account_quote = account_quotes.get(symbol)
        if account_quote is None:
            bound_authority[symbol] = "persisted_current_quote"
            continue
        try:
            same_identity = _row_instrument(account_quote) == _row_instrument(candidate)
        except (TypeError, ValueError):
            same_identity = False
        if not same_identity:
            conflicts.add(symbol)
            candidate_quotes.pop(symbol, None)
            continue
        bound_authority[symbol] = "persisted_current_quote"

    bound_evidence = {
        **evidence,
        "ambiguous_symbols": sorted(conflicts),
        "context_quote_authority": bound_authority,
        "quotes": candidate_quotes,
    }
    bound_evidence["fingerprint"] = _evidence_fingerprint(bound_evidence)
    return {
        **portfolio_context,
        "candidate_quotes": candidate_quotes,
        "candidate_market_evidence": bound_evidence,
    }


def _required_instruments(
    tasks: list[dict[str, Any]],
) -> tuple[set[InstrumentKey], list[int | str | None]]:
    required: set[InstrumentKey] = set()
    invalid_tasks: list[int | str | None] = []
    for task in tasks:
        try:
            required.add(
                InstrumentKey.from_values(
                    task.get("symbol"),
                    task.get("instrument_type")
                    or task.get("asset_type")
                    or task.get("asset_class"),
                )
            )
        except (TypeError, ValueError):
            invalid_tasks.append(task.get("id"))
    return required, invalid_tasks


def _row_instrument(row: Mapping[str, Any]) -> InstrumentKey:
    return InstrumentKey.from_values(
        row.get("symbol"),
        row.get("instrument_type") or row.get("asset_type") or row.get("asset_class"),
    )


def _freeze_candidate_freshness(
    row: dict[str, Any],
    *,
    key: InstrumentKey,
    state: Any,
    now: datetime | None,
) -> None:
    if not _positive_finite_price(row.get("price")):
        row.setdefault("observed_quote_status", row.get("quote_status"))
        row["quote_status"] = "error"
        row["stale_reason"] = "candidate_quote_price_not_positive_finite"
        return
    source = str(row.get("quote_source") or row.get("source") or "").lower()
    if key.instrument_type.value == "open_end_fund" and is_fund_estimate_quote_source(
        source
    ):
        row.setdefault("observed_quote_status", row.get("quote_status"))
        row["quote_status"] = "confirmed_nav_missing"
        row["stale_reason"] = "confirmed_fund_nav_missing_estimate_only"
        return
    projected = quote_status(
        state,
        {
            **row,
            "timestamp": row.get("quote_timestamp") or row.get("timestamp"),
        },
        now=now,
    )
    if projected == "stale":
        row.setdefault("observed_quote_status", row.get("quote_status"))
        row["quote_status"] = "stale"
        row["stale_reason"] = (
            row.get("stale_reason") or "candidate_quote_outside_freshness_window"
        )


def _positive_finite_price(value: Any) -> bool:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return price.is_finite() and price > 0


def _result(
    *,
    source_status: str,
    required: set[InstrumentKey],
    quotes: dict[str, dict[str, Any]],
    persisted_row_fingerprints: dict[InstrumentKey, str],
    invalid_tasks: list[int | str | None],
    ambiguous_symbols: list[str],
) -> dict[str, Any]:
    bindings = []
    for key in sorted(required, key=lambda value: value.storage_tuple()):
        row = quotes.get(key.symbol)
        bindings.append(
            {
                "symbol": key.symbol,
                "instrument_type": key.instrument_type.value,
                "quote_id": row.get("id") if row else None,
                "persisted_row_fingerprint": (persisted_row_fingerprints.get(key)),
                "price": row.get("price") if row else None,
                "quote_timestamp": (
                    row.get("quote_timestamp") or row.get("timestamp") if row else None
                ),
                "quote_source": row.get("quote_source") if row else None,
                "quote_status": row.get("quote_status") if row else "missing",
                "stale_reason": row.get("stale_reason") if row else None,
                "nav_date": row.get("nav_date") if row else None,
            }
        )
    identity = {
        "schema_version": "karkinos.decision_candidate_market_evidence.v1",
        "source_status": source_status,
        "bindings": bindings,
        "invalid_task_ids": invalid_tasks,
        "ambiguous_symbols": ambiguous_symbols,
    }
    return {
        **identity,
        "fingerprint": _evidence_fingerprint(identity),
        "quotes": quotes,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
    }


def _evidence_fingerprint(evidence: Mapping[str, Any]) -> str:
    identity = {
        key: evidence.get(key)
        for key in (
            "schema_version",
            "source_status",
            "bindings",
            "invalid_task_ids",
            "ambiguous_symbols",
            "context_quote_authority",
        )
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _persisted_row_fingerprint(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(row),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
