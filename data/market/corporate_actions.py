"""Immutable observations of stock dividend/bonus announcements, not accounting.

Business dates are source facts. Availability is only when this capture completed;
neither an announcement date nor an ex-date proves historical availability.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, DecimalException
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    ProviderCapture,
    ProviderCaptureError,
    read_provider_capture,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
    ObjectStoreError,
)

FACTS_SCHEMA = "karkinos.corporate_action_facts.v1"
OBSERVATION_SCHEMA = "karkinos.corporate_action_observation.v1"
NORMALIZER_VERSION = "karkinos.stock_dividend_observation.v1"
DATE_FIELDS = (
    "report_period",
    "announcement_date",
    "implementation_announcement_date",
    "record_date",
    "ex_date",
    "pay_date",
    "share_listing_date",
    "base_date",
)
NUMBER_FIELDS = (
    "cash_dividend_before_tax",
    "cash_dividend_after_tax",
    "stock_dividend_ratio",
    "bonus_share_ratio",
    "capitalization_ratio",
    "base_shares",
)
_LIMITATIONS = [
    "Single-source stock dividend/bonus observations; other corporate actions and ETFs are not covered.",
    "An empty response does not prove that no corporate action occurred.",
    "Source business dates do not prove when this revision was historically available.",
    "No adjusted prices, total returns, tax entitlement or portfolio cash flows are calculated.",
]


class CorporateActionObservationError(ValueError):
    """Public failure code, with capture identity when raw evidence was saved."""

    def __init__(self, code: str, *, capture_id: str | None = None) -> None:
        super().__init__(code)
        self.capture_id = capture_id


def publish_corporate_action_observation(
    store: ContentAddressedObjectStore,
    *,
    instrument: InstrumentKey,
    capture: ProviderCapture,
    records: Sequence[Mapping[str, Any]],
) -> ObjectRef:
    """Bind canonical facts and this particular capture without mutating history."""
    if instrument.instrument_type is not InstrumentType.STOCK:
        raise CorporateActionObservationError("corporate_action_instrument_unsupported")
    facts = {
        "schema_version": FACTS_SCHEMA,
        "provider": capture.provider,
        "operation": "dividend",
        "instrument": _instrument_payload(instrument),
        "normalizer_version": NORMALIZER_VERSION,
        "currency": "CNY",
        "cash_unit": "per_share",
        "share_ratio_unit": "shares_per_existing_share",
        "base_shares_unit": "shares",
        "records": _canonical_records(records),
    }
    _validate_capture(capture, facts)
    facts_ref = store.put_bytes(_json_bytes(facts))
    return store.put_bytes(_json_bytes(_observation_payload(capture, facts_ref)))


def read_corporate_action_observation(
    store: ContentAddressedObjectStore, ref: ObjectRef
) -> dict[str, Any]:
    """Read exact frozen identities offline; never consult latest data or a provider."""
    try:
        observation = _read_json(store, ref)
        if observation.get("schema_version") != OBSERVATION_SCHEMA:
            raise CorporateActionObservationError(
                "corporate_action_observation_schema_invalid"
            )
        capture_ref = ObjectRef(**observation["capture_ref"])
        facts_ref = ObjectRef(**observation["facts_ref"])
        capture = read_provider_capture(store, capture_ref)
        store.read_bytes(capture.raw_object_ref)
        facts = _read_json(store, facts_ref)
        if observation != _observation_payload(capture, facts_ref):
            raise CorporateActionObservationError(
                "corporate_action_observation_binding_invalid"
            )
        instrument = InstrumentKey.from_values(**facts["instrument"])
        _validate_facts(facts, instrument)
        _validate_capture(capture, facts)
    except (
        KeyError,
        TypeError,
        ValueError,
        ObjectStoreError,
        ProviderCaptureError,
    ) as exc:
        if isinstance(exc, CorporateActionObservationError):
            raise
        raise CorporateActionObservationError(
            "corporate_action_observation_unreadable"
        ) from exc
    return {
        **facts,
        "observation_id": ref.object_id,
        "facts_revision_id": facts_ref.object_id,
        "capture_id": capture.capture_id,
        "available_at": capture.completed_at.isoformat(),
        "captured_at": capture.completed_at.isoformat(),
        "availability_basis": "capture_completed_at",
        "historical_availability_verified": False,
    }


def summarize_corporate_action_observation(
    observation: Mapping[str, Any], *, start_date: date, end_date: date
) -> dict[str, Any]:
    """Describe dated hits and unresolved records; never infer complete coverage."""
    if start_date > end_date:
        raise CorporateActionObservationError("corporate_action_date_range_invalid")
    relevant_dates = ("record_date", "ex_date", "pay_date", "share_listing_date")
    records = observation["records"]
    events = [
        row
        for row in records
        if any(
            row[field] is not None
            and start_date <= date.fromisoformat(row[field]) <= end_date
            for field in relevant_dates
        )
    ]
    undated = [row for row in records if row["ex_date"] is None]
    return {
        "schema_version": "karkinos.corporate_action_evidence.v1",
        "status": "observed",
        "observation_ids": [observation["observation_id"]],
        "provider": observation["provider"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "available_at": observation["available_at"],
        "captured_at": observation["captured_at"],
        "availability_basis": "capture_completed_at",
        "historical_availability_verified": False,
        "covered_action_types": ["cash_dividend", "bonus_share_distribution"],
        "coverage_status": "provider_reported_only",
        "total_record_count": len(records),
        "matched_event_count": len(events),
        "undated_event_count": len(undated),
        "events": [
            _event_summary(row, observation)
            for row in records
            if row in events or row in undated
        ],
        "returns_modeled": False,
        "limitations": list(_LIMITATIONS),
    }


def _event_summary(
    row: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, Any]:
    names = {
        "implementation_status": "div_proc",
        "report_period": "end_date",
        "announcement_date": "ann_date",
        "implementation_announcement_date": "imp_ann_date",
        "record_date": "record_date",
        "ex_date": "ex_date",
        "pay_date": "pay_date",
        "share_listing_date": "div_listdate",
        "base_date": "base_date",
        "cash_dividend_before_tax": "cash_div_tax",
        "cash_dividend_after_tax": "cash_div",
        "stock_dividend_ratio": "stk_div",
        "bonus_share_ratio": "stk_bo_rate",
        "capitalization_ratio": "stk_co_rate",
        "base_shares": "base_shares",
    }
    return {
        **observation["instrument"],
        **{target: row[source] for source, target in names.items()},
        "base_shares_unit": "shares",
        "available_at": observation["available_at"],
        "captured_at": observation["captured_at"],
        "source_revision_id": observation["facts_revision_id"],
        "observation_id": observation["observation_id"],
    }


def _canonical_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    required = {*DATE_FIELDS, *NUMBER_FIELDS, "source_code", "implementation_status"}
    canonical = []
    seen = set()
    for record in records:
        if set(record) != required:
            raise CorporateActionObservationError(
                "corporate_action_record_fields_invalid"
            )
        row = dict(record)
        for field in ("source_code", "implementation_status"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise CorporateActionObservationError(
                    "corporate_action_record_text_invalid"
                )
        for field in DATE_FIELDS:
            if (
                row[field] is not None
                and date.fromisoformat(row[field]).isoformat() != row[field]
            ):
                raise CorporateActionObservationError(
                    "corporate_action_record_date_invalid"
                )
        for field in NUMBER_FIELDS:
            if row[field] is not None:
                row[field] = _number_text(row[field])
        identity = tuple(
            row[field]
            for field in (
                "source_code",
                "report_period",
                "announcement_date",
                "implementation_announcement_date",
                "ex_date",
                "implementation_status",
            )
        )
        if identity in seen:
            raise CorporateActionObservationError("corporate_action_records_ambiguous")
        seen.add(identity)
        canonical.append(row)
    return sorted(canonical, key=lambda row: _json_bytes(row))


def _number_text(value: Any) -> str:
    try:
        number = Decimal(value)
        if isinstance(value, (bool, float)) or not number.is_finite() or number < 0:
            raise ValueError("invalid_number")
        return format(number.normalize(), "f") if number else "0"
    except (DecimalException, ValueError, TypeError) as exc:
        raise CorporateActionObservationError(
            "corporate_action_record_number_invalid"
        ) from exc


def _validate_facts(facts: dict[str, Any], instrument: InstrumentKey) -> None:
    if (
        facts.get("schema_version") != FACTS_SCHEMA
        or instrument.instrument_type is not InstrumentType.STOCK
        or facts.get("normalizer_version") != NORMALIZER_VERSION
        or facts.get("operation") != "dividend"
        or facts.get("currency") != "CNY"
        or facts.get("cash_unit") != "per_share"
        or facts.get("share_ratio_unit") != "shares_per_existing_share"
        or facts.get("base_shares_unit") != "shares"
        or facts["records"] != _canonical_records(facts["records"])
    ):
        raise CorporateActionObservationError("corporate_action_facts_invalid")


def _validate_capture(capture: ProviderCapture, facts: Mapping[str, Any]) -> None:
    request = json.loads(capture.request_json)
    if (
        capture.operation != "dividend"
        or capture.provider != facts["provider"]
        or request.get("instrument") != facts["instrument"]
        or capture.record_count != len(facts["records"])
        or any(row["source_code"] != request.get("ts_code") for row in facts["records"])
    ):
        raise CorporateActionObservationError(
            "corporate_action_capture_binding_invalid"
        )


def _observation_payload(
    capture: ProviderCapture, facts_ref: ObjectRef
) -> dict[str, Any]:
    return {
        "schema_version": OBSERVATION_SCHEMA,
        "facts_ref": {
            "object_id": facts_ref.object_id,
            "size_bytes": facts_ref.size_bytes,
        },
        "capture_ref": {
            "object_id": capture.capture_ref.object_id,
            "size_bytes": capture.capture_ref.size_bytes,
        },
        "available_at": capture.completed_at.isoformat(),
        "captured_at": capture.completed_at.isoformat(),
        "availability_basis": "capture_completed_at",
        "historical_availability_verified": False,
    }


def _instrument_payload(instrument: InstrumentKey) -> dict[str, str]:
    return {
        "symbol": instrument.symbol,
        "instrument_type": instrument.instrument_type.value,
    }


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_json(store: ContentAddressedObjectStore, ref: ObjectRef) -> dict[str, Any]:
    raw = store.read_bytes(ref)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or _json_bytes(value) != raw:
            raise ValueError("noncanonical")
    except (ValueError, UnicodeDecodeError) as exc:
        raise CorporateActionObservationError(
            "corporate_action_object_invalid"
        ) from exc
    return value


# A date query is genuinely market-wide. Its evidence is different from a
# per-stock full-history response, so it has a distinct, explicitly bounded shape.
MARKET_DAY_SCHEMA = "karkinos.market_dividend_day.v1"
WINDOW_SCHEMA = "karkinos.corporate_action_window.v1"
DIVIDEND_DATE_QUERIES = ("ann_date", "imp_ann_date", "record_date", "ex_date")
_QUERY_RECORD_FIELDS = {
    "ann_date": "announcement_date",
    "imp_ann_date": "implementation_announcement_date",
    "record_date": "record_date",
    "ex_date": "ex_date",
}


def publish_market_dividend_day(
    store: ContentAddressedObjectStore,
    *,
    day: date,
    captures_and_records: Sequence[tuple[ProviderCapture, Sequence[Mapping[str, Any]]]],
) -> ObjectRef:
    """Retain four actual all-market queries, including actual empty responses."""
    queries = []
    for capture, records in captures_and_records:
        queries.append(
            {
                "capture_ref": {
                    "object_id": capture.capture_id,
                    "size_bytes": capture.capture_ref.size_bytes,
                },
                "records": _canonical_records(records),
            }
        )
    payload = {
        "schema_version": MARKET_DAY_SCHEMA,
        "date": day.isoformat(),
        "queries": queries,
    }
    ref = store.put_bytes(_json_bytes(payload))
    read_market_dividend_day(store, ref)
    return ref


def read_market_dividend_day(
    store: ContentAddressedObjectStore, ref: ObjectRef
) -> dict[str, Any]:
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    value = _read_json(store, ref)
    if value.get("schema_version") != MARKET_DAY_SCHEMA:
        raise CorporateActionObservationError("corporate_action_market_day_invalid")
    day = date.fromisoformat(value["date"])
    rows: list[tuple[dict[str, Any], ProviderCapture]] = []
    times, seen = [], set()
    for item in value["queries"]:
        capture = read_provider_capture(store, ObjectRef(**item["capture_ref"]))
        store.read_bytes(capture.raw_object_ref)
        request = json.loads(capture.request_json)
        fields = set(request) - {"fields"}
        field = next(iter(fields)) if len(fields) == 1 else ""
        records = item["records"]
        if (
            field not in DIVIDEND_DATE_QUERIES
            or field in seen
            or request.get(field) != day.strftime("%Y%m%d")
            or not isinstance(request.get("fields"), str)
            or capture.provider != "tushare"
            or capture.operation != "dividend"
            or capture.record_count != len(records)
            or len(records) >= 2000
            or records != _canonical_records(records)
            or any(
                row[_QUERY_RECORD_FIELDS[field]] != day.isoformat() for row in records
            )
            or capture.started_at
            < datetime.combine(day, time(21), ZoneInfo("Asia/Shanghai"))
        ):
            raise CorporateActionObservationError(
                "corporate_action_market_query_invalid"
            )
        seen.add(field)
        times.append(capture.completed_at)
        rows.extend((row, capture) for row in records)
    if seen != set(DIVIDEND_DATE_QUERIES):
        raise CorporateActionObservationError("corporate_action_market_day_incomplete")
    return {
        "date": day,
        "rows": rows,
        "available_at": max(times),
        "oldest_captured_at": min(times),
        "observation_id": ref.object_id,
    }


def publish_corporate_action_window(
    store: ContentAddressedObjectStore,
    *,
    instruments: Sequence[InstrumentKey],
    day_observation_ids: Sequence[str],
) -> ObjectRef:
    """Compose a prospective input; it never certifies the price warmup's past."""
    days = [
        read_market_dividend_day(store, store.resolve_ref(item))
        for item in day_observation_ids
    ]
    if not days:
        raise CorporateActionObservationError("corporate_action_window_empty")
    ordered = sorted(days, key=lambda item: item["date"])
    payload = {
        "schema_version": WINDOW_SCHEMA,
        "instruments": [
            _instrument_payload(key)
            for key in sorted(
                set(instruments), key=lambda k: (k.instrument_type.value, k.symbol)
            )
        ],
        "start_date": ordered[0]["date"].isoformat(),
        "end_date": ordered[-1]["date"].isoformat(),
        "day_observation_ids": [item["observation_id"] for item in ordered],
    }
    ref = store.put_bytes(_json_bytes(payload))
    read_corporate_action_window(store, ref)
    return ref


def read_corporate_action_window(
    store: ContentAddressedObjectStore, ref: ObjectRef
) -> dict[str, Any]:
    from datetime import timedelta

    window = _read_json(store, ref)
    if window.get("schema_version") != WINDOW_SCHEMA:
        raise CorporateActionObservationError("corporate_action_window_invalid")
    keys = tuple(InstrumentKey.from_values(**item) for item in window["instruments"])
    if (
        not keys
        or any(key.instrument_type is not InstrumentType.STOCK for key in keys)
        or keys
        != tuple(sorted(set(keys), key=lambda k: (k.instrument_type.value, k.symbol)))
    ):
        raise CorporateActionObservationError(
            "corporate_action_window_instruments_invalid"
        )
    days = [
        read_market_dividend_day(store, store.resolve_ref(item))
        for item in window["day_observation_ids"]
    ]
    start, end = (
        date.fromisoformat(window["start_date"]),
        date.fromisoformat(window["end_date"]),
    )
    if (
        end < start
        or (end - start).days > 3652
        or [item["date"] for item in days]
        != [start + timedelta(days=index) for index in range((end - start).days + 1)]
    ):
        raise CorporateActionObservationError(
            "corporate_action_window_dates_incomplete"
        )
    symbols = {key.symbol: key for key in keys}
    versions: dict[
        tuple[str, str | None, str | None],
        tuple[bytes, dict[str, Any], ProviderCapture],
    ] = {}
    implemented_periods: set[tuple[str, str | None]] = set()
    # Keep the first actual observation time for unchanged terms. A changed
    # record retains its own capture time; materializing a later window is not
    # the event's first availability time.
    for day in days:
        daily: dict[
            tuple[str, str | None, str | None],
            tuple[bytes, dict[str, Any], ProviderCapture],
        ] = {}
        for row, capture in day["rows"]:
            symbol, _, venue = row["source_code"].partition(".")
            if symbol not in symbols:
                continue
            if (
                venue not in {"SH", "SZ", "BJ"}
                or len(symbol) != 6
                or not symbol.isdigit()
            ):
                raise CorporateActionObservationError(
                    "corporate_action_market_symbol_invalid"
                )
            identity = (symbol, row["report_period"], row["announcement_date"])
            encoded = _json_bytes(row)
            if identity in daily and daily[identity][0] != encoded:
                raise CorporateActionObservationError(
                    "corporate_action_market_revision_ambiguous"
                )
            if (
                identity not in daily
                or capture.completed_at < daily[identity][2].completed_at
            ):
                daily[identity] = (encoded, row, capture)
        for identity, (encoded, row, capture) in daily.items():
            period = (identity[0], row["report_period"])
            if row["implementation_status"] != "实施" and period in implemented_periods:
                # An explicit later cancellation/retraction cannot leave the
                # earlier implementation alive merely because ann_date changed.
                raise CorporateActionObservationError(
                    "corporate_action_market_implementation_retracted_or_ambiguous"
                )
            if row["implementation_status"] == "实施":
                implemented_periods.add(period)
            if identity not in versions or versions[identity][0] != encoded:
                versions[identity] = (encoded, row, capture)
    events = []
    pending_count = 0
    for _, row, capture in versions.values():
        # A proposal is preserved source material, not an implemented cash or
        # share entitlement. Implemented but undated terms remain unresolved.
        if row["implementation_status"] != "实施":
            pending_count += 1
            continue
        # Keep known future implementations too. Their actual capture time is
        # valid information for a later record entitlement; missing terms must
        # remain visible to the financial fail-closed reader.
        symbol = row["source_code"].split(".")[0]
        observed = {
            "instrument": _instrument_payload(symbols[symbol]),
            "available_at": capture.completed_at.isoformat(),
            "captured_at": capture.completed_at.isoformat(),
            "facts_revision_id": capture.capture_id,
            "observation_id": ref.object_id,
        }
        events.append(_event_summary(row, observed))
    return {
        "schema_version": "karkinos.corporate_action_evidence.v1",
        "status": "observed",
        "observation_ids": [ref.object_id],
        "provider": "tushare",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "coverage_start_date": start.isoformat(),
        "coverage_end_date": end.isoformat(),
        "available_at": max(day["available_at"] for day in days).isoformat(),
        "captured_at": max(day["available_at"] for day in days).isoformat(),
        "oldest_captured_at": days[-1]["oldest_captured_at"].isoformat(),
        "availability_basis": "capture_completed_at",
        "historical_availability_verified": False,
        "covered_action_types": ["cash_dividend", "bonus_share_distribution"],
        "coverage_status": "provider_reported_only",
        "total_record_count": len(versions),
        "unimplemented_record_count": pending_count,
        "matched_event_count": len(events),
        "undated_event_count": sum(event["ex_date"] is None for event in events),
        "events": sorted(events, key=_json_bytes),
        "returns_modeled": False,
        "instruments": window["instruments"],
        "day_observation_ids": window["day_observation_ids"],
        "limitations": [
            *_LIMITATIONS,
            "Only prospective daily announcement, implementation, record and ex-date queries are covered; price warmup is not covered.",
            "Unannounced retrospective source changes outside these date queries may remain unobserved.",
        ],
    }
