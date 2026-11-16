"""Data normalization and ingestion for corporate action events.

Converts provider-specific payloads (TuShare, EastMoney, CAS observations) into
canonical, immutable CorporateActionEvent instances with strict validation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException
from typing import Any

from core.types import ZERO, Symbol
from data.corporate_actions.models import CorporateActionEvent, CorporateActionType


def _parse_date(val: Any) -> date | None:
    """Safely parse various date formats (YYYY-MM-DD, YYYYMMDD, date)."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    text = str(val).strip()
    if not text or text.lower() in ("none", "null", "nan"):
        return None
    # Support YYYYMMDD
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    # Support ISO YYYY-MM-DD
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return date.fromisoformat(text)
    # Datetime string prefix
    if len(text) > 10 and text[4] == "-" and text[7] == "-":
        return date.fromisoformat(text[:10])
    raise ValueError(f"unparseable_date_format: {val}")


def _parse_decimal(val: Any, default: Decimal = ZERO) -> Decimal:
    """Safely parse numbers to Decimal."""
    if val is None:
        return default
    text = str(val).strip()
    if not text or text.lower() in ("none", "null", "nan"):
        return default
    try:
        d = Decimal(text)
        if not d.is_finite():
            raise ValueError(f"non_finite_decimal: {val}")
        return d
    except DecimalException as exc:
        raise ValueError(f"invalid_decimal: {val}") from exc


def _parse_datetime(val: Any) -> datetime | None:
    """Safely parse ISO datetime string or datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    text = str(val).strip()
    if not text or text.lower() in ("none", "null", "nan"):
        return None
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def generate_event_id(
    symbol: Symbol | str,
    event_type: str,
    record_date: date,
    ex_date: date,
    terms: Mapping[str, Any],
) -> str:
    """Generate a deterministic sha256 event ID based on key fields."""
    payload = {
        "symbol": str(symbol),
        "type": str(event_type),
        "record_date": record_date.isoformat(),
        "ex_date": ex_date.isoformat(),
        "terms": {k: str(v) for k, v in sorted(terms.items())},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def normalize_facts_record(
    record: Mapping[str, Any],
    symbol: Symbol | str,
    *,
    source: str = "facts",
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
) -> list[CorporateActionEvent]:
    """Convert an internal facts record (e.g. from data.market.corporate_actions)

    into canonical CorporateActionEvent objects.
    A single observation row may yield separate atomic events (cash dividend,
    bonus share, capitalization) or a composite event.
    """
    sym = Symbol(str(symbol))
    record_date = _parse_date(record.get("record_date"))
    ex_date = _parse_date(record.get("ex_date"))

    if record_date is None or ex_date is None:
        # Undated plan or incomplete record cannot produce an effective event
        return []

    ann_date = _parse_date(record.get("announcement_date"))
    imp_ann_date = _parse_date(record.get("implementation_announcement_date"))
    pay_date = _parse_date(record.get("pay_date"))
    listing_date = _parse_date(record.get("share_listing_date"))

    cash_div = _parse_decimal(record.get("cash_dividend_before_tax"))
    bonus_rate = _parse_decimal(record.get("bonus_share_ratio"))
    capital_rate = _parse_decimal(record.get("capitalization_ratio"))
    status = str(record.get("implementation_status") or "实施").strip()

    events: list[CorporateActionEvent] = []

    # If only cash dividend
    if cash_div > ZERO and bonus_rate == ZERO and capital_rate == ZERO:
        eid = generate_event_id(
            sym, "cash_dividend", record_date, ex_date, {"cash": cash_div}
        )
        events.append(
            CorporateActionEvent(
                event_id=eid,
                symbol=sym,
                event_type=CorporateActionType.CASH_DIVIDEND,
                record_date=record_date,
                ex_date=ex_date,
                announcement_date=ann_date,
                implementation_announcement_date=imp_ann_date,
                pay_date=pay_date,
                listing_date=listing_date,
                cash_dividend_per_share=cash_div,
                source=source,
                captured_at=captured_at,
                available_at=available_at,
                div_proc=status,
            )
        )
    # If only stock bonus
    elif cash_div == ZERO and bonus_rate > ZERO and capital_rate == ZERO:
        eid = generate_event_id(
            sym, "stock_dividend", record_date, ex_date, {"bonus": bonus_rate}
        )
        events.append(
            CorporateActionEvent(
                event_id=eid,
                symbol=sym,
                event_type=CorporateActionType.STOCK_DIVIDEND,
                record_date=record_date,
                ex_date=ex_date,
                announcement_date=ann_date,
                implementation_announcement_date=imp_ann_date,
                pay_date=pay_date,
                listing_date=listing_date,
                bonus_ratio=bonus_rate,
                source=source,
                captured_at=captured_at,
                available_at=available_at,
                div_proc=status,
            )
        )
    # If only capitalization
    elif cash_div == ZERO and bonus_rate == ZERO and capital_rate > ZERO:
        eid = generate_event_id(
            sym, "capitalization", record_date, ex_date, {"capital": capital_rate}
        )
        events.append(
            CorporateActionEvent(
                event_id=eid,
                symbol=sym,
                event_type=CorporateActionType.CAPITALIZATION,
                record_date=record_date,
                ex_date=ex_date,
                announcement_date=ann_date,
                implementation_announcement_date=imp_ann_date,
                pay_date=pay_date,
                listing_date=listing_date,
                capitalization_ratio=capital_rate,
                source=source,
                captured_at=captured_at,
                available_at=available_at,
                div_proc=status,
            )
        )
    # If composite (multiple terms non-zero)
    elif cash_div > ZERO or bonus_rate > ZERO or capital_rate > ZERO:
        eid = generate_event_id(
            sym,
            "composite",
            record_date,
            ex_date,
            {"cash": cash_div, "bonus": bonus_rate, "capital": capital_rate},
        )
        events.append(
            CorporateActionEvent(
                event_id=eid,
                symbol=sym,
                event_type=CorporateActionType.COMPOSITE,
                record_date=record_date,
                ex_date=ex_date,
                announcement_date=ann_date,
                implementation_announcement_date=imp_ann_date,
                pay_date=pay_date,
                listing_date=listing_date,
                cash_dividend_per_share=cash_div,
                bonus_ratio=bonus_rate,
                capitalization_ratio=capital_rate,
                source=source,
                captured_at=captured_at,
                available_at=available_at,
                div_proc=status,
            )
        )

    return events


def normalize_observation_evidence(
    evidence: Mapping[str, Any] | None,
) -> list[CorporateActionEvent]:
    """Extract and normalize all implemented events from corporate_action_evidence dict."""
    if not isinstance(evidence, Mapping):
        return []
    available_at = _parse_datetime(evidence.get("available_at"))
    captured_at = _parse_datetime(evidence.get("captured_at"))
    provider = str(evidence.get("provider") or "provider")

    all_events: list[CorporateActionEvent] = []
    for raw_event in evidence.get("events", []):
        sym = raw_event.get("symbol")
        if not sym:
            continue
        # Map fields from summary format
        mapped_record = {
            "record_date": raw_event.get("record_date"),
            "ex_date": raw_event.get("ex_date"),
            "announcement_date": raw_event.get("ann_date"),
            "implementation_announcement_date": raw_event.get("imp_ann_date"),
            "pay_date": raw_event.get("pay_date"),
            "share_listing_date": raw_event.get("div_listdate"),
            "cash_dividend_before_tax": raw_event.get("cash_div_tax"),
            "bonus_share_ratio": raw_event.get("stk_bo_rate"),
            "capitalization_ratio": raw_event.get("stk_co_rate"),
            "implementation_status": raw_event.get("div_proc") or "实施",
        }
        event_available = _parse_datetime(raw_event.get("available_at")) or available_at
        event_captured = _parse_datetime(raw_event.get("captured_at")) or captured_at

        norm_events = normalize_facts_record(
            mapped_record,
            sym,
            source=provider,
            available_at=event_available,
            captured_at=event_captured,
        )
        all_events.extend(norm_events)

    return all_events
