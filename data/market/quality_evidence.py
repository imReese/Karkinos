"""Immutable, content-addressed evidence for Market Data quality decisions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from core.types import InstrumentKey, InstrumentType
from data.market.quality import (
    MarketDataQualityReport,
    MarketQualityDiagnostic,
    MarketQualityDiagnosticKind,
    MarketQualitySeverity,
    MarketQualityStatus,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
    ObjectStoreError,
)

MARKET_QUALITY_EVIDENCE_SCHEMA_VERSION = "karkinos.market_quality_evidence.v1"
_CONTENT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class MarketQualityEvidenceError(RuntimeError):
    """Base error for immutable quality evidence."""


class MarketQualityEvidenceIntegrityError(MarketQualityEvidenceError):
    """Persisted quality evidence is unreadable or semantically invalid."""


@dataclass(frozen=True, slots=True)
class MarketQualityEvidence:
    """One exact quality decision bound to immutable market lineage."""

    ref: ObjectRef
    report: MarketDataQualityReport

    @property
    def quality_id(self) -> str:
        return self.ref.object_id


def publish_market_quality_evidence(
    store: ContentAddressedObjectStore,
    report: MarketDataQualityReport,
) -> MarketQualityEvidence:
    """Persist a quality report as canonical immutable evidence."""
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("market_quality_evidence_store_invalid")
    if not isinstance(report, MarketDataQualityReport):
        raise TypeError("market_quality_evidence_report_invalid")
    _require_content_id(report.revision_id, field="revision_id")
    _require_content_id(report.materialization_id, field="materialization_id")
    payload = _serialize_report(report)
    ref = store.put_bytes(payload)
    return MarketQualityEvidence(ref=ref, report=report)


def read_market_quality_evidence(
    store: ContentAddressedObjectStore,
    ref: ObjectRef,
) -> MarketQualityEvidence:
    """Read, validate, and canonicalize one persisted quality decision."""
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("market_quality_evidence_store_invalid")
    if not isinstance(ref, ObjectRef):
        raise TypeError("market_quality_evidence_ref_invalid")
    try:
        payload = store.read_bytes(ref)
    except ObjectStoreError as exc:
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_object_unreadable"
        ) from exc
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_json_invalid"
        ) from exc
    try:
        report = _report_from_payload(value)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MarketQualityEvidenceIntegrityError):
            raise
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_semantics_invalid"
        ) from exc
    if _serialize_report(report) != payload:
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_not_canonical"
        )
    return MarketQualityEvidence(ref=ref, report=report)


def _serialize_report(report: MarketDataQualityReport) -> bytes:
    payload = {
        "schema_version": MARKET_QUALITY_EVIDENCE_SCHEMA_VERSION,
        "revision_id": _require_content_id(report.revision_id, field="revision_id"),
        "materialization_id": _require_content_id(
            report.materialization_id, field="materialization_id"
        ),
        "policy_id": _require_text(report.policy_id, field="policy_id"),
        "status": report.status.value,
        "checked_at": _format_utc(report.checked_at),
        "observed_instrument_count": _non_negative_int(
            report.observed_instrument_count, field="observed_instrument_count"
        ),
        "expected_instrument_count": (
            None
            if report.expected_instrument_count is None
            else _non_negative_int(
                report.expected_instrument_count,
                field="expected_instrument_count",
            )
        ),
        "diagnostics": [_diagnostic_payload(item) for item in report.diagnostics],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _report_from_payload(value: object) -> MarketDataQualityReport:
    payload = _object(value, field="root")
    _exact_keys(
        payload,
        {
            "schema_version",
            "revision_id",
            "materialization_id",
            "policy_id",
            "status",
            "checked_at",
            "observed_instrument_count",
            "expected_instrument_count",
            "diagnostics",
        },
        field="root",
    )
    if payload["schema_version"] != MARKET_QUALITY_EVIDENCE_SCHEMA_VERSION:
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_schema_unsupported"
        )
    expected = payload["expected_instrument_count"]
    diagnostics = payload["diagnostics"]
    if not isinstance(diagnostics, list):
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_diagnostics_invalid"
        )
    return MarketDataQualityReport(
        revision_id=_require_content_id(payload["revision_id"], field="revision_id"),
        materialization_id=_require_content_id(
            payload["materialization_id"], field="materialization_id"
        ),
        policy_id=_require_text(payload["policy_id"], field="policy_id"),
        status=MarketQualityStatus(_require_text(payload["status"], field="status")),
        checked_at=_parse_utc(payload["checked_at"], field="checked_at"),
        observed_instrument_count=_non_negative_int(
            payload["observed_instrument_count"], field="observed_instrument_count"
        ),
        expected_instrument_count=(
            None
            if expected is None
            else _non_negative_int(expected, field="expected_instrument_count")
        ),
        diagnostics=tuple(_diagnostic_from_payload(item) for item in diagnostics),
    )


def _diagnostic_payload(item: MarketQualityDiagnostic) -> dict[str, object]:
    if not isinstance(item, MarketQualityDiagnostic):
        raise TypeError("market_quality_evidence_diagnostic_invalid")
    return {
        "kind": item.kind.value,
        "severity": item.severity.value,
        "instrument": (
            None
            if item.instrument is None
            else {
                "symbol": item.instrument.symbol,
                "instrument_type": item.instrument.instrument_type.value,
            }
        ),
        "details": [[key, value] for key, value in item.details],
    }


def _diagnostic_from_payload(value: object) -> MarketQualityDiagnostic:
    payload = _object(value, field="diagnostic")
    _exact_keys(
        payload, {"kind", "severity", "instrument", "details"}, field="diagnostic"
    )
    instrument_payload = payload["instrument"]
    instrument = None
    if instrument_payload is not None:
        raw = _object(instrument_payload, field="instrument")
        _exact_keys(raw, {"symbol", "instrument_type"}, field="instrument")
        instrument = InstrumentKey(
            _require_text(raw["symbol"], field="instrument_symbol"),
            InstrumentType(
                _require_text(raw["instrument_type"], field="instrument_type")
            ),
        )
    details = payload["details"]
    if not isinstance(details, list):
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_details_invalid"
        )
    normalized_details: list[tuple[str, str]] = []
    for item in details:
        if not isinstance(item, list) or len(item) != 2:
            raise MarketQualityEvidenceIntegrityError(
                "market_quality_evidence_detail_invalid"
            )
        normalized_details.append(
            (
                _require_text(item[0], field="detail_key"),
                _require_text(item[1], field="detail_value"),
            )
        )
    if tuple(sorted(normalized_details)) != tuple(normalized_details):
        raise MarketQualityEvidenceIntegrityError(
            "market_quality_evidence_details_not_canonical"
        )
    return MarketQualityDiagnostic(
        kind=MarketQualityDiagnosticKind(
            _require_text(payload["kind"], field="diagnostic_kind")
        ),
        severity=MarketQualitySeverity(
            _require_text(payload["severity"], field="diagnostic_severity")
        ),
        instrument=instrument,
        details=tuple(normalized_details),
    )


def _format_utc(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("market_quality_evidence_datetime_invalid")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market_quality_evidence_datetime_naive")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: object, *, field: str) -> datetime:
    text = _require_text(value, field=field)
    if not text.endswith("Z"):
        raise MarketQualityEvidenceIntegrityError(
            f"market_quality_evidence_{field}_invalid"
        )
    try:
        result = datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise MarketQualityEvidenceIntegrityError(
            f"market_quality_evidence_{field}_invalid"
        ) from exc
    if _format_utc(result) != text:
        raise MarketQualityEvidenceIntegrityError(
            f"market_quality_evidence_{field}_not_canonical"
        )
    return result


def _require_content_id(value: object, *, field: str) -> str:
    text = _require_text(value, field=field)
    if _CONTENT_ID.fullmatch(text) is None:
        raise ValueError(f"market_quality_evidence_{field}_invalid")
    return text


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"market_quality_evidence_{field}_must_be_text")
    text = value.strip()
    if not text:
        raise ValueError(f"market_quality_evidence_{field}_missing")
    return text


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"market_quality_evidence_{field}_invalid")
    return value


def _object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MarketQualityEvidenceIntegrityError(
            f"market_quality_evidence_{field}_must_be_object"
        )
    return value


def _exact_keys(value: dict[str, object], expected: set[str], *, field: str) -> None:
    if set(value) != expected:
        raise MarketQualityEvidenceIntegrityError(
            f"market_quality_evidence_{field}_fields_invalid"
        )
