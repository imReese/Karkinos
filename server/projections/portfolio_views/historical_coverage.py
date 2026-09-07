"""Pure diagnostic over a fixed ledger snapshot and explicit source evidence."""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from core.types import InstrumentKey
from data.market_data import is_fund_estimate_quote_source
from server.contracts.http.historical_coverage_models import (
    HistoricalCoverageItem,
    HistoricalCoverageReport,
)
from server.ledger.models import LedgerEntry
from server.persistence.database_normalization import stable_json_fingerprint
from server.persistence.valuation_publication_recovery import (
    publication_affects_instruments,
)
from server.projections.portfolio_read_snapshot import (
    PortfolioReadSnapshot,
    PortfolioReadSnapshotIdentity,
    PortfolioReadSnapshotRejected,
)
from server.projections.portfolio_views.historical_ledger_series import (
    ledger_entry_timestamp,
    quote_valuation_date,
)
from server.projections.portfolio_views.historical_series import (
    historical_correction_performance_blockers,
)
from server.projections.quote_status import parse_quote_timestamp
from server.projections.service import PortfolioReplayAccumulator
from server.services.market_calendar_dates import POST_CLOSE_INGESTION_TIME
from server.services.market_calendar_evidence import validate_verified_market_calendar

_SH = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class HistoricalCoverageEvidence:
    snapshot_identity: PortfolioReadSnapshotIdentity
    observations: tuple[dict[str, Any], ...]
    metadata: tuple[dict[str, Any], ...]
    calendars: tuple[dict[str, Any], ...]
    incidents: tuple[dict[str, Any], ...]


def build_historical_coverage(
    snapshot: PortfolioReadSnapshot, evidence: HistoricalCoverageEvidence
) -> HistoricalCoverageReport:
    if snapshot.identity != evidence.snapshot_identity:
        raise PortfolioReadSnapshotRejected("coverage evidence identity mismatch")
    try:
        return _build(snapshot, evidence)
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise PortfolioReadSnapshotRejected(
            "historical coverage inputs invalid"
        ) from exc


def _build(
    snapshot: PortfolioReadSnapshot, evidence: HistoricalCoverageEvidence
) -> HistoricalCoverageReport:
    end = date.fromisoformat(str(snapshot.published_valuation["trade_date"]))
    as_of = parse_quote_timestamp(snapshot.published_valuation.get("as_of"))
    if as_of is None:
        raise PortfolioReadSnapshotRejected("coverage valuation time unavailable")
    as_of = as_of.astimezone(_SH)
    entries = [LedgerEntry.from_row(dict(row)) for row in snapshot.ledger_rows]
    dated = [(ledger_entry_timestamp(entry), entry) for entry in entries]
    if any(stamp is None or stamp > as_of for stamp, _ in dated):
        raise PortfolioReadSnapshotRejected("coverage ledger time unavailable")
    dated.sort(key=lambda pair: (pair[0], pair[1].id or 0))
    keys = {}
    for row, entry in zip(snapshot.ledger_rows, entries, strict=True):
        if not entry.symbol:
            continue
        key = InstrumentKey.from_values(
            entry.symbol,
            row.get("instrument_type") or row.get("asset_type") or entry.asset_class,
        )
        if key != InstrumentKey.from_values(entry.symbol, entry.asset_class):
            raise PortfolioReadSnapshotRejected(
                "ledger replay instrument identity mismatch"
            )
        if key.symbol in keys and keys[key.symbol] != key:
            raise PortfolioReadSnapshotRejected("ambiguous ledger instrument namespace")
        keys[key.symbol] = key
    metadata = defaultdict(list)
    for row in evidence.metadata:
        key = InstrumentKey.from_values(row["symbol"], row["asset_type"])
        metadata[key].append(row)
    calendars = {}
    for row in evidence.calendars:
        try:
            calendar_key = (
                str(row.get("exchange", "")).upper(),
                int(row.get("year", 0)),
            )
        except (TypeError, ValueError):
            continue
        if calendar_key in calendars:
            raise PortfolioReadSnapshotRejected("duplicate coverage calendar identity")
        try:
            validation = validate_verified_market_calendar(row)
        except (TypeError, ValueError, OverflowError):
            validation = validate_verified_market_calendar(None)
        days = {}
        if validation.verified:
            raw_days = row.get("days") or json.loads(row["days_json"])
            days = {item["date"]: item["is_trading_day"] for item in raw_days}
        calendars[calendar_key] = (validation, days)
    observations = defaultdict(list)
    for row in evidence.observations:
        key = InstrumentKey.from_values(row["symbol"], row["instrument_type"])
        nav_day = (
            quote_valuation_date({"trade_date": row.get("nav_date")})
            if key.instrument_type.value == "open_end_fund"
            else None
        )
        day = nav_day or quote_valuation_date(row)
        if day is None:
            raise PortfolioReadSnapshotRejected("coverage observation date unavailable")
        observations[(key, day.isoformat())].append(row)
    items = []
    replay = PortfolioReplayAccumulator(initial_cash=0)
    index = 0
    start = dated[0][0].date() if dated else None
    day = start or end
    while start is not None and day <= end:
        cutoff = min(datetime.combine(day, time.max, tzinfo=_SH), as_of)
        while index < len(dated) and dated[index][0] <= cutoff:
            replay.apply(dated[index][1])
            index += 1
        for symbol in replay.active_symbols:
            key = keys[symbol]
            requirement, reason, calendar_ref = _requirement(
                key, day, as_of, metadata[key], calendars
            )
            status, reasons, refs = _evidence_status(
                key, observations[(key, day.isoformat())], evidence.incidents
            )
            items.append(
                HistoricalCoverageItem(
                    symbol=key.symbol,
                    instrument_type=key.instrument_type.value,
                    valuation_date=day.isoformat(),
                    requirement=requirement,
                    requirement_reason=reason,
                    calendar_evidence_ref=calendar_ref,
                    evidence_status=status,
                    evidence_reasons=reasons,
                    evidence_refs=refs,
                )
            )
        day += timedelta(days=1)
    items.sort(
        key=lambda item: (item.symbol, item.instrument_type, item.valuation_date)
    )
    gaps = [
        item
        for item in items
        if item.requirement == "required" and item.evidence_status == "missing"
    ]
    available = defaultdict(list)
    for item in items:
        if item.evidence_status == "available":
            available[(item.symbol, item.instrument_type)].append(item.valuation_date)
    for item in gaps:
        dates = available[(item.symbol, item.instrument_type)]
        if dates:
            item.gap_position = (
                "leading"
                if item.valuation_date < min(dates)
                else "trailing" if item.valuation_date > max(dates) else "internal"
            )
    unknown = sum(item.requirement == "unknown" for item in items)
    unavailable = sum(
        item.requirement == "required" and item.evidence_status != "available"
        for item in items
    )
    return HistoricalCoverageReport(
        identity=asdict(snapshot.identity),
        evidence_fingerprint=stable_json_fingerprint(asdict(evidence)),
        calendar_evidence_refs=sorted(
            {item.calendar_evidence_ref for item in items if item.calendar_evidence_ref}
        ),
        start_date=start.isoformat() if start else None,
        end_date=end.isoformat(),
        status=(
            "empty"
            if not entries
            else "unknown" if unknown else "incomplete" if unavailable else "complete"
        ),
        confirmed_gap_dates=len({item.valuation_date for item in gaps}),
        confirmed_gap_instrument_dates=len(gaps),
        unknown_requirement_instrument_dates=unknown,
        unavailable_required_instrument_dates=unavailable,
        performance_blockers=historical_correction_performance_blockers(entries),
        items=items,
    )


def _requirement(key, day, as_of, metadata, calendars):
    if key.instrument_type.value == "open_end_fund":
        return "unknown", "fund_nav_rule_unavailable", None
    if key.instrument_type.value not in {"stock", "etf"}:
        return "unknown", "instrument_price_rule_unavailable", None
    exchanges = {str(row.get("exchange") or "").upper() for row in metadata}
    if len(exchanges) != 1 or not exchanges.issubset({"SSE", "SZSE", "BSE"}):
        return "unknown", "instrument_exchange_unavailable", None
    calendar = calendars.get((next(iter(exchanges)), day.year))
    if calendar is None or not calendar[0].verified:
        return "unknown", "verified_calendar_unavailable", None
    validation, days = calendar
    if not days[day.isoformat()]:
        return "not_required", "verified_exchange_closed", validation.evidence_ref
    if datetime.combine(day, POST_CLOSE_INGESTION_TIME, tzinfo=_SH) > as_of:
        return "unknown", "session_evidence_not_due", validation.evidence_ref
    return "required", "held_on_verified_trading_day", validation.evidence_ref


def _evidence_status(key, rows, incidents):
    reasons, refs, values = set(), set(), set()
    invalid = False
    affected = [
        incident
        for incident in incidents
        if publication_affects_instruments(
            incident, {(key.instrument_type.value, key.symbol)}
        )
    ]
    for row in rows:
        refs.add(str(row["evidence_ref"]))
        try:
            price = Decimal(str(row["price"]))
            valid = price.is_finite() and price > 0
        except (InvalidOperation, TypeError, ValueError):
            valid = False
        if not valid:
            invalid = True
            reasons.add("invalid_price")
            continue
        if key.instrument_type.value == "open_end_fund":
            if (
                row["kind"] != "quote"
                or quote_valuation_date({"trade_date": row.get("nav_date")}) is None
                or row.get("quote_status") != "confirmed"
                or is_fund_estimate_quote_source(str(row.get("source", "")))
            ):
                reasons.add("confirmed_nav_evidence_unavailable")
                continue
        elif row["kind"] == "quote":
            stamp = parse_quote_timestamp(row.get("timestamp"))
            if (
                stamp is None
                or stamp.astimezone(_SH).time() != time(15)
                or row.get("quote_status") != "confirmed"
            ):
                reasons.add("daily_close_evidence_unverified")
                continue
        values.add(price)
    if len(values) > 1:
        reasons.add("observed_price_conflict")
    if affected:
        reasons.add("unresolved_publication")
        refs.update(
            str(item["incident_ref"]) for item in affected if item.get("incident_ref")
        )
    status = (
        "unverified"
        if affected or len(values) > 1
        else (
            "available"
            if values
            else "invalid" if invalid else "unverified" if rows else "missing"
        )
    )
    return status, sorted(reasons), sorted(refs)
